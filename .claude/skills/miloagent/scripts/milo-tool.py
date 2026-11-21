#!/usr/bin/env python3
"""CLI for the MiloAgent dashboard API - projects, prompts, and personas.

Reads MILO_BASE (default http://localhost:8420), MILO_WEB_USER (default admin),
and MILO_WEB_PASS from the environment. Read MILO_WEB_PASS from your secret store.
Stdlib only - no pip install needed.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("MILO_BASE", "http://localhost:8420").rstrip("/")
USER = os.environ.get("MILO_WEB_USER", "admin")


def _die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _token_cache_path():
    key = hashlib.sha256(f"{BASE}|{USER}".encode()).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), f".milo-token-{key}.json")


def _err_detail(e):
    try:
        return json.loads(e.read()).get("detail", "")
    except Exception:
        return getattr(e, "reason", str(e))


def _login():
    pw = os.environ.get("MILO_WEB_PASS")
    if not pw:
        _die("MILO_WEB_PASS is not set - source it from Vaultwarden")
    data = json.dumps({"username": USER, "password": pw}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/auth/login", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        _die(f"login failed ({e.code}): {_err_detail(e)}")
    except urllib.error.URLError as e:
        _die(f"cannot reach {BASE}: {e.reason}")
    token = body.get("token")
    if not token:
        _die(f"login response had no token: {body}")
    try:
        path = _token_cache_path()
        with open(path, "w") as f:
            json.dump({"token": token, "ts": time.time()}, f)
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def _cached_token():
    try:
        with open(_token_cache_path()) as f:
            c = json.load(f)
        if time.time() - c.get("ts", 0) < 23 * 3600:
            return c.get("token")
    except (OSError, ValueError):
        pass
    return None


def _request(method, path, body=None, _retry=True):
    token = _cached_token() or _login()
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry:
            try:
                os.remove(_token_cache_path())
            except OSError:
                pass
            _login()
            return _request(method, path, body, _retry=False)
        _die(f"{method} {path} -> {e.code}: {_err_detail(e)}")
    except urllib.error.URLError as e:
        _die(f"cannot reach {BASE}: {e.reason}")


def _q(project):
    return "?project=" + urllib.parse.quote(project) if project else ""


def _enc(name):
    return urllib.parse.quote(name, safe="")


def _pp(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _read_content(args):
    if getattr(args, "file", None):
        with open(args.file) as f:
            return f.read()
    if getattr(args, "content", None) is not None:
        return args.content
    _die("provide --content or --file")


# --- command handlers ---

def cmd_health(args):
    try:
        with urllib.request.urlopen(f"{BASE}/health", timeout=15) as r:
            print(r.read().decode().strip() or "ok")
    except Exception as e:
        _die(f"health check failed: {e}")


def cmd_projects(args):
    _pp(_request("GET", "/api/projects"))


def cmd_project_schema(args):
    _pp(_request("GET", "/api/projects/schema"))


def cmd_project_get(args):
    _pp(_request("GET", f"/api/projects/{_enc(args.name)}"))


def cmd_project_set(args):
    raw = args.json if args.json is not None else _read_content(args)
    try:
        patch = json.loads(raw)
    except ValueError as e:
        _die(f"--json/--file must be a JSON object: {e}")
    if not isinstance(patch, dict):
        _die("patch must be a JSON object")
    _pp(_request("PUT", f"/api/projects/{_enc(args.name)}", patch))


def cmd_project_create(args):
    body = {"name": args.name, "url": args.url, "description": args.description,
            "project_type": args.type, "weight": args.weight, "tagline": args.tagline}
    _pp(_request("POST", "/api/projects", body))


def cmd_project_delete(args):
    _pp(_request("DELETE", f"/api/projects/{_enc(args.name)}"))


def cmd_prompts(args):
    _pp(_request("GET", "/api/prompts" + _q(args.project)))


def cmd_prompt_get(args):
    d = _request("GET", f"/api/prompts/{_enc(args.name)}" + _q(args.project))
    ph = " ".join("{" + p + "}" for p in d.get("placeholders", [])) or "(none)"
    state = "OVERRIDE" if d.get("override") else "default"
    print(f"# {d.get('name')} [{state}] placeholders: {ph}", file=sys.stderr)
    print(d.get("effective", ""))


def cmd_prompt_set(args):
    body = {"project": args.project, "content": _read_content(args)}
    _pp(_request("PUT", f"/api/prompts/{_enc(args.name)}", body))


def cmd_prompt_revert(args):
    _pp(_request("DELETE", f"/api/prompts/{_enc(args.name)}" + _q(args.project)))


def cmd_personas(args):
    _pp(_request("GET", "/api/personas" + _q(args.project)))


def cmd_persona_get(args):
    d = _request("GET", f"/api/personas/{_enc(args.name)}" + _q(args.project))
    state = "OVERRIDE" if d.get("override") else "default"
    print(f"# {d.get('name')} [{state}]", file=sys.stderr)
    print(d.get("effective", ""))


def cmd_persona_set(args):
    body = {"project": args.project, "content": _read_content(args)}
    _pp(_request("PUT", f"/api/personas/{_enc(args.name)}", body))


def cmd_persona_revert(args):
    _pp(_request("DELETE", f"/api/personas/{_enc(args.name)}" + _q(args.project)))


def build_parser():
    p = argparse.ArgumentParser(description="MiloAgent dashboard CLI")
    sub = p.add_subparsers(dest="group", required=True)

    sub.add_parser("health", help="unauthenticated liveness check").set_defaults(fn=cmd_health)
    sub.add_parser("projects", help="list projects").set_defaults(fn=cmd_projects)
    sub.add_parser("project-schema", help="print the project field schema").set_defaults(fn=cmd_project_schema)
    sub.add_parser("prompts", help="list prompt templates").add_argument("--project", default="")
    sub.choices["prompts"].set_defaults(fn=cmd_prompts)
    sub.add_parser("personas", help="list personas").add_argument("--project", default="")
    sub.choices["personas"].set_defaults(fn=cmd_personas)

    proj = sub.add_parser("project", help="get/set/create/delete a project").add_subparsers(dest="action", required=True)
    proj.add_parser("get").add_argument("name")
    proj.choices["get"].set_defaults(fn=cmd_project_get)
    ps = proj.add_parser("set")
    ps.add_argument("name")
    ps.add_argument("--json", help="deep-merge patch as a JSON object string")
    ps.add_argument("--file", help="read the JSON patch from a file")
    ps.set_defaults(fn=cmd_project_set)
    pc = proj.add_parser("create")
    pc.add_argument("--name", required=True)
    pc.add_argument("--url", required=True)
    pc.add_argument("--description", required=True)
    pc.add_argument("--type", default="SaaS")
    pc.add_argument("--weight", type=float, default=1.0)
    pc.add_argument("--tagline", default="")
    pc.set_defaults(fn=cmd_project_create)
    proj.add_parser("delete").add_argument("name")
    proj.choices["delete"].set_defaults(fn=cmd_project_delete)

    pr = sub.add_parser("prompt", help="get/set/revert a prompt template").add_subparsers(dest="action", required=True)
    prg = pr.add_parser("get")
    prg.add_argument("name")
    prg.add_argument("--project", required=True)
    prg.set_defaults(fn=cmd_prompt_get)
    prs = pr.add_parser("set")
    prs.add_argument("name")
    prs.add_argument("--project", required=True)
    prs.add_argument("--content")
    prs.add_argument("--file")
    prs.set_defaults(fn=cmd_prompt_set)
    prr = pr.add_parser("revert")
    prr.add_argument("name")
    prr.add_argument("--project", required=True)
    prr.set_defaults(fn=cmd_prompt_revert)

    pe = sub.add_parser("persona", help="get/set/revert a persona").add_subparsers(dest="action", required=True)
    peg = pe.add_parser("get")
    peg.add_argument("name")
    peg.add_argument("--project", required=True)
    peg.set_defaults(fn=cmd_persona_get)
    pes = pe.add_parser("set")
    pes.add_argument("name")
    pes.add_argument("--project", required=True)
    pes.add_argument("--content")
    pes.add_argument("--file")
    pes.set_defaults(fn=cmd_persona_set)
    per = pe.add_parser("revert")
    per.add_argument("name")
    per.add_argument("--project", required=True)
    per.set_defaults(fn=cmd_persona_revert)

    return p


def main():
    args = build_parser().parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
