#!/usr/bin/env bash
# Renders the chart with monitoring, existing-secret and bridge values, checks the objects
# and runs the promtool unit tests of the alert rules. Needs helm, promtool and python3
# with PyYAML on PATH. Run from anywhere: tests/chart/run.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$here/../.."
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

render() { out="$1"; shift; helm template miloagent "$repo/deploy" -n miloagent "$@" > "$work/$out"; }
render off.yaml
render on.yaml --set monitoring.enabled=true
render labels.yaml --set monitoring.enabled=true --set monitoring.rules.labels.team=ops
render existing.yaml --set env.MILO_WEB_PASS= --set existingSecrets.env=creds \
  --set existingSecrets.files=files --set 'existingSecrets.fileKeys={llm}' \
  --set secrets.llm=plain --set secrets.reddit_api=plain \
  --set 'extraObjects[0].apiVersion=v1' --set 'extraObjects[0].kind=ConfigMap' \
  --set 'extraObjects[0].metadata.name=extra'
render nobridge.yaml --set bridge.enabled=false
render nobridge-on.yaml --set bridge.enabled=false --set monitoring.enabled=true
render gateway.yaml --set bridge.server.mcp.targetName=miloagent \
  --set bridge.server.mcp.appProtocol=agentgateway.dev/mcp \
  --set bridge.server.networkPolicy.egress.enabled=true \
  --set 'bridge.server.networkPolicy.ingressNamespaces[0].matchLabels.team=gateway' \
  --set bridge.server.passwordSecret.name=web --set bridge.server.env.MILOAGENT_CACHE_SECONDS=30

# a hand-made exporter next to the chart's exporter is refused
if helm template miloagent "$repo/deploy" --set monitoring.enabled=true \
  --set 'extraContainers[0].name=exporter' --set 'extraContainers[0].image=x' > /dev/null 2>&1; then
  echo "extraContainers exporter with bridge.exporter rendered" >&2; exit 1
fi
helm template miloagent "$repo/deploy" --set monitoring.enabled=true --set bridge.exporter.enabled=false \
  --set 'extraContainers[0].name=exporter' --set 'extraContainers[0].image=x' > /dev/null
# no password source for the bridge is an error
if helm template miloagent "$repo/deploy" --set env.MILO_WEB_PASS= > /dev/null 2>&1; then
  echo "bridge rendered without a password source" >&2; exit 1
fi

python3 - "$work" "$repo/docs/alerts.md" <<'PY'
import sys, yaml
work = sys.argv[1]
headings = {l[4:].strip() for l in open(sys.argv[2]) if l.startswith("### ")}
def docs(name):
    return [d for d in yaml.safe_load_all(open(f"{work}/{name}")) if d]
def one(name, kind, obj=None):
    hits = [d for d in docs(name) if d["kind"] == kind and (obj is None or d["metadata"]["name"] == obj)]
    assert len(hits) == 1, f"{name}: {len(hits)} {kind} {obj or ''}"
    return hits[0]
def containers(name):
    return one(name, "Deployment", "miloagent")["spec"]["template"]["spec"]["containers"]
def container(name):
    return containers(name)[0]
def bridge(d):
    return d["metadata"].get("labels", {}).get("app.kubernetes.io/component") == "bridge"

# monitoring off by default, on with monitoring.enabled
for kind in ("ServiceMonitor", "PrometheusRule"):
    assert not [d for d in docs("off.yaml") if d["kind"] == kind], f"{kind} rendered by default"
metrics = one("on.yaml", "Service", "miloagent-metrics")
for k, v in one("on.yaml", "ServiceMonitor")["spec"]["selector"]["matchLabels"].items():
    assert metrics["metadata"]["labels"].get(k) == v, f"ServiceMonitor selector {k} misses the Service"
rule = one("on.yaml", "PrometheusRule")
for group in rule["spec"]["groups"]:
    for r in group["rules"]:
        name = r["alert"]
        assert r["labels"]["severity"] in ("critical", "warning", "info"), name
        assert r["annotations"]["runbook_url"].endswith("#" + name.lower()), name
        assert name in headings, f"docs/alerts.md has no section {name}"
for group in one("labels.yaml", "PrometheusRule")["spec"]["groups"]:
    for r in group["rules"]:
        assert r["labels"].get("team") == "ops", r["alert"]
yaml.safe_dump(rule["spec"], open(f"{work}/rules.yaml", "w"))

# plain values keep working: one envFrom, the password in the chart's Secret
c = container("off.yaml")
assert [e["secretRef"]["name"] for e in c["envFrom"]] == ["miloagent-env"]
assert "MILO_WEB_PASS" in one("off.yaml", "Secret", "miloagent-env")["stringData"]

# existing secrets: env Secret last, llm.yaml from it once, reddit_api still from values
c = container("existing.yaml")
assert [e["secretRef"]["name"] for e in c["envFrom"]] == ["miloagent-env", "creds"]
assert "MILO_WEB_PASS" not in one("existing.yaml", "Secret", "miloagent-env")["stringData"]
mounts = {m["mountPath"]: m["name"] for m in c["volumeMounts"]}
paths = [m["mountPath"] for m in c["volumeMounts"]]
assert len(paths) == len(set(paths)), "duplicate mountPath"
assert mounts["/app/config/llm.yaml"] == "existing-secret-files"
assert mounts["/app/config/reddit_api.yaml"] == "secret-files"
vols = {v["name"]: v for v in one("existing.yaml", "Deployment", "miloagent")["spec"]["template"]["spec"]["volumes"]}
assert vols["existing-secret-files"]["secret"]["secretName"] == "files"
one("existing.yaml", "ConfigMap", "extra")

# bridge off: exactly the default objects without the bridge, MiloAgent's pod unchanged
for plain, without in (("off.yaml", "nobridge.yaml"), ("on.yaml", "nobridge-on.yaml")):
    assert not [d for d in docs(without) if bridge(d)], f"{without}: bridge object rendered"
    assert [c["name"] for c in containers(without)] == ["miloagent"], without
    expected = [d for d in docs(plain) if not bridge(d)]
    for d in expected:
        if d["kind"] == "Deployment":
            spec = d["spec"]["template"]["spec"]
            spec["containers"] = [c for c in spec["containers"] if c["name"] != "exporter"]
    assert expected == docs(without), f"{without} differs from {plain} beyond the bridge"

# bridge on by default: Deployment, Service and NetworkPolicy <release>-bridge
dep = one("off.yaml", "Deployment", "miloagent-bridge")
svc = one("off.yaml", "Service", "miloagent-bridge")
np = one("off.yaml", "NetworkPolicy", "miloagent-bridge")
pod = dep["spec"]["template"]
milo_selector = one("off.yaml", "Service", "miloagent")["spec"]["selector"]
assert not all(pod["metadata"]["labels"].get(k) == v for k, v in milo_selector.items()), \
    "bridge pods match the MiloAgent Service"
assert all(pod["metadata"]["labels"].get(k) == v for k, v in svc["spec"]["selector"].items())
assert dep["spec"]["selector"]["matchLabels"] == svc["spec"]["selector"] == np["spec"]["podSelector"]["matchLabels"]
assert svc["spec"]["ports"] == [{"name": "mcp", "port": 8000, "targetPort": "mcp", "protocol": "TCP"}]
assert "annotations" not in svc["metadata"]
assert pod["spec"]["automountServiceAccountToken"] is False
(server,) = pod["spec"]["containers"]
assert server["image"] == "ghcr.io/hoolia/miloagent-bridge:latest"
env = {e["name"]: e for e in server["env"]}
assert env["MILOAGENT_URL"]["value"] == "http://miloagent:8420"
assert env["MILOAGENT_PASSWORD"]["valueFrom"]["secretKeyRef"] == {"name": "miloagent-env", "key": "MILO_WEB_PASS"}
assert server["securityContext"]["runAsNonRoot"] is True
assert server["readinessProbe"]["httpGet"]["path"] == "/healthz"
assert np["spec"]["policyTypes"] == ["Ingress"]
assert np["spec"]["ingress"][0]["from"] == [{"podSelector": {}}]
# the exporter only with monitoring: the default MiloAgent pod has one container
assert [c["name"] for c in containers("off.yaml")] == ["miloagent"]
exp = [c for c in containers("on.yaml") if c["name"] == "exporter"]
assert len(exp) == 1 and exp[0]["image"] == server["image"]
assert exp[0]["ports"] == [{"name": "metrics", "containerPort": 9420}]
assert {m["mountPath"]: m.get("readOnly", False) for m in exp[0]["volumeMounts"]} == {"/volume": False, "/app/logs": True}
assert exp[0]["securityContext"]["capabilities"]["drop"] == ["ALL"]

# the password from existingSecrets.env when the values hold none
env = {e["name"]: e for e in one("existing.yaml", "Deployment", "miloagent-bridge")["spec"]["template"]["spec"]["containers"][0]["env"]}
assert env["MILOAGENT_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "creds"

# gateway values: MCP target annotations, appProtocol, egress to DNS and MiloAgent only
svc = one("gateway.yaml", "Service", "miloagent-bridge")
assert svc["metadata"]["annotations"] == {"agentgateway.dev/mcp-path": "/mcp", "agentgateway.dev/mcp-target-name": "miloagent"}
assert svc["spec"]["ports"][0]["appProtocol"] == "agentgateway.dev/mcp"
np = one("gateway.yaml", "NetworkPolicy", "miloagent-bridge")
assert np["spec"]["policyTypes"] == ["Ingress", "Egress"]
assert np["spec"]["ingress"][0]["from"][1] == {"namespaceSelector": {"matchLabels": {"team": "gateway"}}}
assert np["spec"]["egress"][1]["to"] == [{"podSelector": {"matchLabels": milo_selector}}]
assert np["spec"]["egress"][1]["ports"] == [{"protocol": "TCP", "port": 8420}]
env = {e["name"]: e for e in one("gateway.yaml", "Deployment", "miloagent-bridge")["spec"]["template"]["spec"]["containers"][0]["env"]}
assert env["MILOAGENT_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "web"
assert env["MILOAGENT_CACHE_SECONDS"]["value"] == "30"
print("render checks passed")
PY

cp "$here/prometheusrule_test.yaml" "$work/"
promtool check rules "$work/rules.yaml"
cd "$work" && promtool test rules prometheusrule_test.yaml
