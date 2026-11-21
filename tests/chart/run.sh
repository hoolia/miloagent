#!/usr/bin/env bash
# Renders the chart with monitoring and existing-secret values, checks the objects and
# runs the promtool unit tests of the alert rules. Needs helm, promtool and python3 with
# PyYAML on PATH. Run from anywhere: tests/chart/run.sh
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
def container(name):
    return one(name, "Deployment")["spec"]["template"]["spec"]["containers"][0]

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
vols = {v["name"]: v for v in one("existing.yaml", "Deployment")["spec"]["template"]["spec"]["volumes"]}
assert vols["existing-secret-files"]["secret"]["secretName"] == "files"
one("existing.yaml", "ConfigMap", "extra")
print("render checks passed")
PY

cp "$here/prometheusrule_test.yaml" "$work/"
promtool check rules "$work/rules.yaml"
cd "$work" && promtool test rules prometheusrule_test.yaml
