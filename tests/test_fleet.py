"""Unit tests for home/bin/fleet. Standard library only, so they run anywhere the
CLI runs (Linux, macOS and Windows, Python 3.9+):

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import fnmatch
import http.client
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "home" / "bin" / "fleet"
POSIX = os.name != "nt"


def load_cli():
    loader = importlib.machinery.SourceFileLoader("fleet_cli", str(CLI))
    spec = importlib.util.spec_from_loader("fleet_cli", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fleet_cli"] = module  # dataclasses look the module up while it loads
    loader.exec_module(module)
    return module


fleet = load_cli()


def make_cfg(tmp: Path, *names, **node_kw) -> fleet.Config:
    nodes = {n: fleet.Node(name=n, host=n, **node_kw) for n in (names or ("vps1", "vps2", "vps3"))}
    return fleet.Config(path=tmp / "fleet.ini", remote_root=str(tmp / "nodes" / "{node}"),
                        results_dir=tmp / "results", secrets_dir=tmp / "secrets", ssh_key=tmp / "key",
                        connect_timeout=10, transport="local", nodes=nodes)


def healthy(**over) -> dict:
    st = {"reachable": True, "service": "active", "heartbeat_age_s": 3, "paused": False, "low_disk": False,
          "disk_free_gb": 80, "disk_free_pct": 70, "max_parallel": 1, "reboot_required": False,
          "queue": {"inbox": 0, "running": 0, "done": 0, "failed": 0, "unpulled": 0},
          "providers": [{"provider": "claude", "installed": True, "ok": True, "auth": "api-key",
                         "credential_age_days": 10}]}
    st.update(over)
    return st


def quietly(fn, *args, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(*args, **kw)
    return rc, out.getvalue(), err.getvalue()


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()


# --------------------------------------------------------------------------- jobs

class ValidateJobTest(unittest.TestCase):
    def ok(self, **job):
        return fleet.validate_job(dict({"prompt": "make a video"}, **job))

    def bad(self, pattern, **job):
        with self.assertRaisesRegex(fleet.FleetError, pattern):
            fleet.validate_job(dict({"prompt": "make a video"}, **job))

    def test_defaults(self):
        job = self.ok()
        self.assertEqual(job["provider"], "claude")
        self.assertEqual(job["channel"], "general")

    def test_prompt_required(self):
        for job in ({}, {"prompt": "   "}, {"prompt": 5}):
            with self.assertRaisesRegex(fleet.FleetError, "prompt"):
                fleet.validate_job(job)
        with self.assertRaisesRegex(fleet.FleetError, "JSON object"):
            fleet.validate_job(["not", "a", "dict"])

    def test_ids(self):
        self.ok(id="20261118-090000-space-a1b2c")
        for bad_id in ("../x", "a/b", " x", "-x", "x" * 129, "a b"):
            self.bad("invalid id", id=bad_id)

    def test_whole_number_ranges(self):
        self.ok(max_turns=1, timeout_minutes=1440, max_retries=0)
        self.ok(max_turns=10000, max_retries=5)
        for key, value in (("max_turns", 0), ("max_turns", 10001), ("max_turns", True), ("max_turns", "5"),
                           ("max_turns", 2.5), ("timeout_minutes", 0), ("timeout_minutes", 1441),
                           ("max_retries", -1), ("max_retries", 6)):
            self.bad(key, **{key: value})

    def test_budget(self):
        self.ok(max_budget_usd=2.5)
        self.ok(max_budget_usd=3)
        for v in (0, -1, "2"):
            self.bad("max_budget_usd", max_budget_usd=v)

    def test_model_effort_and_permission_mode(self):
        self.ok(model="claude-opus-5-5[1m]", effort="ultracode", permission_mode="acceptEdits")
        self.ok(model="sonnet", effort="low", permission_mode="dontAsk")
        self.bad("invalid model", model="x; rm -rf /")
        self.bad('"effort" must be one of high, low, max, medium, ultracode, xhigh', effort="turbo")
        self.bad("permission_mode", permission_mode="yolo")

    def test_text_fields(self):
        self.ok(title="t" * 200)
        self.bad("title", title="t" * 201)
        self.bad("title", title=7)
        self.bad("channel", channel="")
        self.bad("channel", channel="c" * 201)
        self.bad("invalid provider", provider="Claude Code")

    def test_template_and_tools(self):
        self.ok(template="space-facts", allowed_tools=["Bash", "Read"])
        self.ok(allowed_tools="Bash Read")
        self.bad("invalid template", template="../x")
        self.bad("allowed_tools", allowed_tools=["Bash", 3])

    def test_files(self):
        self.ok(files=[{"path": "brief/notes.md", "content": "hi"},
                       {"path": "img/a.png", "content": "aGk=", "encoding": "base64"}])
        for path in ("../evil", "a/../../b", "/etc/passwd", "\\\\server\\share", "C:/x", "c:x", ""):
            self.bad("unsafe or missing file path", files=[{"path": path, "content": "x"}])
        self.bad("unsafe or missing file path", files=["just a string"])
        self.bad("needs string", files=[{"path": "a.txt"}])
        self.bad("encoding", files=[{"path": "a.txt", "content": "x", "encoding": "hex"}])
        self.bad('"files" must be a list', files={"path": "a"})


class JobIdTest(unittest.TestCase):
    def test_readable_and_valid(self):
        jid = fleet.make_job_id("Space Facts!")
        self.assertRegex(jid, r"^\d{8}-\d{6}-space-facts-[a-z0-9]{5}$")
        self.assertTrue(fleet.ID_RE.match(jid))

    def test_odd_channels(self):
        self.assertRegex(fleet.make_job_id(""), r"-job-[a-z0-9]{5}$")
        self.assertRegex(fleet.make_job_id("!!!"), r"-job-[a-z0-9]{5}$")
        long_id = fleet.make_job_id("x" * 300)
        self.assertTrue(fleet.ID_RE.match(long_id))
        self.assertLessEqual(len(long_id), 64)

    def test_unique(self):
        self.assertEqual(len({fleet.make_job_id("c") for _ in range(200)}), 200)


class LoadJobsTest(TempDirTest):
    def args(self, *files, prompt=None, channel=None, provider=None):
        return argparse.Namespace(job_files=[str(f) for f in files], prompt=prompt, channel=channel, provider=provider)

    def test_prompt_file_and_bom(self):
        (self.tmp / "brief.md").write_text("Write episode 4", encoding="utf-8")
        job = self.tmp / "job.json"
        job.write_bytes(b"\xef\xbb\xbf" + json.dumps({"prompt_file": "brief.md", "channel": "Space"}).encode())
        (loaded,) = fleet.load_jobs(self.args(job))
        self.assertEqual(loaded["prompt"], "Write episode 4")
        self.assertNotIn("prompt_file", loaded)

    def test_wildcards_are_expanded(self):
        for name in ("b.json", "a.json"):
            (self.tmp / name).write_text(json.dumps({"prompt": name}), encoding="utf-8")
        loaded = fleet.load_jobs(self.args(self.tmp / "*.json"))
        self.assertEqual([j["prompt"] for j in loaded], ["a.json", "b.json"])
        with self.assertRaisesRegex(fleet.FleetError, "no file matches"):
            fleet.load_jobs(self.args(self.tmp / "none-*.json"))
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp), "USERPROFILE": str(self.tmp)}):
            self.assertEqual(len(fleet.load_jobs(self.args("~/*.json"))), 2)

    def test_overrides_and_errors(self):
        (loaded,) = fleet.load_jobs(self.args(prompt="hi", channel="History"))
        self.assertEqual(loaded["channel"], "History")
        broken = self.tmp / "broken.json"
        broken.write_text("{nope", encoding="utf-8")
        with self.assertRaisesRegex(fleet.FleetError, "broken.json"):
            fleet.load_jobs(self.args(broken))
        with self.assertRaisesRegex(fleet.FleetError, "job files"):
            fleet.load_jobs(self.args())


# --------------------------------------------------------------------------- config

class ConfigTest(TempDirTest):
    def write(self, body: str) -> Path:
        p = self.tmp / "fleet.ini"
        p.write_text(body, encoding="utf-8")
        return p

    def test_load(self):
        cfg = fleet.load_config(self.write(
            "[defaults]\nresults_dir = ~/fleet-results ; comment\nconnect_timeout = 7\n"
            "[vps1]\nhost = vps1\npublic_ip = 203.0.113.10\nhostinger_account = account 1\n"
            "[vps2]\nproviders = claude, other\nsessions = 0\nenabled = no\n"))
        self.assertEqual(list(cfg.nodes), ["vps1", "vps2"])
        v1, v2 = cfg.nodes["vps1"], cfg.nodes["vps2"]
        self.assertEqual((v1.public_ip, v1.user, v1.port, v1.providers), ("203.0.113.10", "fleet", 22, ["claude"]))
        self.assertEqual((v2.host, v2.providers, v2.sessions, v2.enabled), ("vps2", ["claude", "other"], 1, False))
        self.assertEqual(cfg.results_dir, Path.home() / "fleet-results")
        self.assertEqual(cfg.connect_timeout, 7)
        self.assertEqual(cfg.remote_root, "/home/fleet/fleet")

    def test_example_inventory_loads(self):
        cfg = fleet.load_config(REPO / "home" / "fleet.ini.example")
        self.assertEqual(list(cfg.nodes), ["vps1", "vps2", "vps3", "vps4", "vps5"])
        self.assertTrue(all(n.providers == ["claude"] and n.enabled for n in cfg.nodes.values()))

    def test_errors(self):
        with self.assertRaisesRegex(fleet.FleetError, "fleet init"):
            fleet.load_config(self.tmp / "missing.ini")
        with self.assertRaisesRegex(fleet.FleetError, "lowercase hostname"):
            fleet.load_config(self.write("[VPS_1]\n"))
        with self.assertRaisesRegex(fleet.FleetError, r"bad value in \[vps1\]"):
            fleet.load_config(self.write("[vps1]\nport = twenty-two\n"))

    def test_transport_override(self):
        with mock.patch.dict(os.environ, {"FLEET_TRANSPORT": "local"}):
            self.assertEqual(fleet.load_config(self.write("[vps1]\n")).transport, "local")

    def test_resolve_targets(self):
        cfg = fleet.load_config(self.write("[vps1]\n[vps2]\nenabled = false\n[vps3]\n"))
        self.assertEqual([n.name for n in fleet.resolve_targets(cfg, None)], ["vps1", "vps3"])
        self.assertEqual([n.name for n in fleet.resolve_targets(cfg, "all", include_disabled=True)],
                         ["vps1", "vps2", "vps3"])
        self.assertEqual([n.name for n in fleet.resolve_targets(cfg, "vps3, vps2")], ["vps3", "vps2"])
        with self.assertRaisesRegex(fleet.FleetError, "unknown node 'vps9'"):
            fleet.resolve_targets(cfg, "vps9")
        empty = fleet.load_config(self.write("[vps1]\nenabled = false\n"))
        with self.assertRaisesRegex(fleet.FleetError, "no enabled nodes"):
            fleet.resolve_targets(empty, "all")


# --------------------------------------------------------------------------- transport

class TransportTest(TempDirTest):
    def test_wrap_remote_uses_safe_characters(self):
        wrapped = fleet.wrap_remote("echo \"it's\" $HOME `id` \\ %PATH% ^& 'x'\nprintf 'é'\n")
        payload = re.search(r"printf %s (\S+) \|", wrapped).group(1)
        self.assertRegex(payload, r"^[A-Za-z0-9+/=]+$")
        self.assertNotRegex(wrapped.replace("printf %s", ""), r"['\"`\\%^]")

    @unittest.skipUnless(POSIX and shutil.which("bash") and shutil.which("base64"), "needs bash and base64")
    def test_wrap_remote_round_trip(self):
        script = "set -e\nx='a \"quoted\" $value'\necho \"$x\"\necho 'unicode: é ✓'\nexit 3\n"
        r = subprocess.run(["bash", "-c", fleet.wrap_remote(script)], capture_output=True)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout.decode("utf-8"), 'a "quoted" $value\nunicode: é ✓\n')

    def test_ssh_options(self):
        cfg = make_cfg(self.tmp, "vps1", port=2222)
        n = cfg.nodes["vps1"]
        with mock.patch.object(fleet, "HOME", self.tmp), mock.patch.object(fleet, "IS_WINDOWS", False):
            opts = fleet.ssh_options(cfg, n)
            self.assertIn("BatchMode=yes", opts)
            self.assertIn("StrictHostKeyChecking=accept-new", opts)
            self.assertEqual(opts[opts.index("-p") + 1], "2222")
            self.assertIn("ControlMaster=auto", opts)
            self.assertNotIn("-i", opts)
            cfg.ssh_key.write_text("key", encoding="utf-8")
            self.assertEqual(fleet.ssh_options(cfg, n)[-4:], ["-i", str(cfg.ssh_key), "-o", "IdentitiesOnly=yes"])
        with mock.patch.object(fleet, "HOME", self.tmp), mock.patch.object(fleet, "IS_WINDOWS", True):
            self.assertFalse(any("ControlMaster" in o for o in fleet.ssh_options(cfg, n)))

    def test_ssh_config_text(self):
        cfg = make_cfg(self.tmp, "vps1", "vps2")
        txt = fleet.ssh_config_text(cfg)
        self.assertIn("Host vps1\n  HostName vps1\n  User fleet\n  Port 22\n", txt)
        self.assertIn(f"IdentityFile {cfg.ssh_key.as_posix()}", txt)
        self.assertNotIn("\\", txt)

    def test_root_and_worker_paths(self):
        cfg = make_cfg(self.tmp, "vps1")
        self.assertEqual(fleet.root_of(cfg, cfg.nodes["vps1"]), str(self.tmp / "nodes" / "{node}").replace("{node}", "vps1"))
        cfg.remote_root = "/home/fleet/my fleet"
        self.assertEqual(fleet.worker(cfg, cfg.nodes["vps1"]), "'/home/fleet/my fleet/app/worker/fleet-worker'")


class TarDirTest(TempDirTest):
    def members(self) -> dict:
        with tarfile.open(fileobj=io.BytesIO(fleet.tar_dir(self.tmp)), mode="r:gz") as tf:
            return {m.name: (m, tf.extractfile(m).read() if m.isfile() else None) for m in tf.getmembers()}

    def test_packing_rules(self):
        (self.tmp / "worker").mkdir()
        (self.tmp / "worker" / "fleet-worker").write_bytes(b"#!/usr/bin/env bash\r\necho hi\r\n")
        (self.tmp / "install.sh").write_bytes(b"echo one\r\necho two\r\n")
        (self.tmp / "README.md").write_bytes(b"line\r\n")
        (self.tmp / "logo.bin").write_bytes(b"\x00\x01\r\n\x02")
        (self.tmp / "claude.env").write_text("ANTHROPIC_API_KEY=secret", encoding="utf-8")
        (self.tmp / "claude.env.example").write_text("ANTHROPIC_API_KEY=", encoding="utf-8")
        (self.tmp / "__pycache__").mkdir()
        (self.tmp / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        (self.tmp / ".DS_Store").write_bytes(b"\x00")
        m = self.members()
        self.assertEqual(set(m), {"worker", "worker/fleet-worker", "install.sh", "README.md", "logo.bin",
                                  "claude.env.example"})
        self.assertTrue(m["worker"][0].isdir())
        self.assertEqual(m["worker/fleet-worker"][1], b"#!/usr/bin/env bash\necho hi\n")
        self.assertEqual(m["worker/fleet-worker"][0].mode, 0o755)
        self.assertEqual(m["install.sh"][0].mode, 0o755)
        self.assertEqual(m["README.md"][0].mode, 0o644)
        self.assertEqual(m["README.md"][1], b"line\n")
        self.assertEqual(m["logo.bin"][1], b"\x00\x01\r\n\x02")
        self.assertEqual(m["worker/fleet-worker"][0].uid, 0)

    def test_repo_vps_bundle(self):
        with tarfile.open(fileobj=io.BytesIO(fleet.tar_dir(REPO / "vps")), mode="r:gz") as tf:
            names = {m.name: m for m in tf.getmembers()}
        for must in ("bootstrap.sh", "lockdown.sh", "worker/fleet-worker", "providers/claude/run.sh",
                     "providers/claude/check.sh", "providers/claude/install.sh", "systemd/fleet-worker.service"):
            self.assertIn(must, names)
        self.assertEqual(names["worker/fleet-worker"].mode, 0o755)
        self.assertFalse([n for n in names if n.endswith(".env")])


# --------------------------------------------------------------------------- status & health

class LastJsonTest(unittest.TestCase):
    def test_parsing(self):
        self.assertEqual(fleet.last_json(b"Welcome to Ubuntu\n{\"a\": 1}\n\n"), {"a": 1})
        self.assertEqual(fleet.last_json(b"[1, 2]"), [1, 2])
        self.assertEqual(fleet.last_json(b"", []), [])
        self.assertEqual(fleet.last_json(b"{\"a\": 1}\ntrailing words", "dflt"), "dflt")
        with self.assertRaises(ValueError):
            fleet.last_json(b"no json here")

    def test_number(self):
        self.assertEqual(fleet.number("7", 0), 7.0)
        self.assertEqual(fleet.number(None, 5), 5)
        self.assertEqual(fleet.number("?", 2), 2)
        self.assertEqual(fleet.number(True, 1), 1)


class HealthTest(TempDirTest):
    args = argparse.Namespace(min_disk_pct=15, max_backlog=25)

    def problems(self, statuses: dict, **node_kw) -> dict:
        cfg = make_cfg(self.tmp, *statuses, **node_kw)

        def fake(_cfg, n):
            st = statuses[n.name]
            if isinstance(st, Exception):
                raise st
            return dict(st, node=n.name)
        with mock.patch.object(fleet, "fetch_status", side_effect=fake):
            return fleet.health_problems(cfg, self.args)

    def test_healthy_fleet(self):
        self.assertEqual(self.problems({"vps1": healthy(), "vps2": healthy(service="unknown")}), {})

    def test_each_problem(self):
        claude = healthy()["providers"][0]
        p = self.problems({
            "vps1": {"reachable": False, "error": "ssh: connect to host vps1 port 22: Connection timed out"},
            "vps2": healthy(service="failed"),
            "vps3": healthy(heartbeat_age_s=900, paused=True),
            "vps4": healthy(heartbeat_age_s=-1, low_disk=True, disk_free_gb=2, disk_free_pct=2),
            "vps5": healthy(disk_free_pct=9, reboot_required=True,
                            queue=dict(healthy()["queue"], inbox=30)),
            "vps6": healthy(providers=[]),
            "vps7": healthy(providers=[dict(claude, ok=False, error="no credentials")]),
            "vps8": healthy(providers=[dict(claude, auth="oauth-token", credential_age_days=340)]),
            "vps9": healthy(providers=[dict(claude, auth="api-key", credential_age_days=400)]),
            "vps10": RuntimeError("boom"),
        })
        self.assertIn("unreachable (ssh: connect", p["vps1:unreachable"])
        self.assertEqual(p["vps2:service"], "vps2: fleet-worker service is failed (fleet restart vps2)")
        self.assertIn("no heartbeat for 900s", p["vps3:heartbeat"])
        self.assertIn("fleet resume vps3", p["vps3:paused"])
        self.assertIn("no heartbeat yet", p["vps4:heartbeat"])
        self.assertIn("new jobs are on hold", p["vps4:disk"])
        self.assertIn("disk-full runbook", p["vps5:disk"])
        self.assertNotIn("on hold", p["vps5:disk"])
        self.assertIn("30 jobs waiting", p["vps5:backlog"])
        self.assertIn("fleet reboot vps5", p["vps5:reboot"])
        self.assertIn("fleet provider install claude vps6", p["vps6:provider:claude"])
        self.assertEqual(p["vps7:provider:claude"], "vps7: claude not ok: no credentials")
        self.assertIn("340 days ago", p["vps8:token-age:claude"])
        self.assertIn("rotate-credentials runbook", p["vps8:token-age:claude"])
        self.assertIn("health check crashed: boom", p["vps10:check"])
        self.assertFalse([k for k in p if k.startswith("vps9:")])
        self.assertFalse([k for k in p if k.startswith("vps1:") and k != "vps1:unreachable"])

    def test_odd_numbers_do_not_crash(self):
        p = self.problems({"vps1": healthy(disk_free_pct=None, heartbeat_age_s="soon",
                                           queue=dict(healthy()["queue"], inbox="?"))})
        self.assertEqual(p, {})

    def test_changes_only(self):
        cfg = make_cfg(self.tmp, "vps1")
        a = argparse.Namespace(changes_only=True, quiet=False, remind_hours=6.0, min_disk_pct=15, max_backlog=25)
        state = {"st": healthy(paused=True)}
        with mock.patch.object(fleet, "fetch_status", side_effect=lambda c, n: dict(state["st"], node=n.name)), \
                mock.patch.object(fleet, "STATE_DIR", self.tmp / "state"):
            rc, out, _ = quietly(fleet.cmd_health, cfg, a)
            self.assertEqual(rc, 0)
            self.assertIn("NEW  vps1: paused", out)
            self.assertEqual(quietly(fleet.cmd_health, cfg, a)[1], "")
            state["st"] = healthy()
            self.assertIn("OK   vps1: paused", quietly(fleet.cmd_health, cfg, a)[1])
            self.assertEqual(quietly(fleet.cmd_health, cfg, a)[1], "")
            a.changes_only = False
            self.assertEqual(quietly(fleet.cmd_health, cfg, a)[:2], (0, "Fleet health: all 1 nodes OK\n"))
            state["st"] = healthy(service="failed")
            rc, out, _ = quietly(fleet.cmd_health, cfg, a)
            self.assertEqual(rc, 2)
            self.assertIn("1 problem(s)", out)


class ReadinessAndDispatchTest(TempDirTest):
    def test_node_readiness(self):
        claude = healthy()["providers"][0]
        cases = [
            ({"reachable": False}, "unreachable"),
            (healthy(service="inactive"), "its worker service is inactive"),
            (healthy(paused=True), "paused"),
            (healthy(low_disk=True), "low on disk"),
            (healthy(providers=[]), "claude is not installed"),
            (healthy(providers=[dict(claude, ok=False, error="no credentials")]), "claude is not ok (no credentials)"),
            (healthy(), None),
            (healthy(service="unknown"), None),
        ]
        for st, want in cases:
            self.assertEqual(fleet.node_readiness(st, "claude"), want)
        self.assertEqual(fleet.node_readiness(None, "claude"), "unreachable")

    def dispatch(self, statuses: dict, jobs: list, spec: str = "auto", dry_run: bool = False):
        cfg = make_cfg(self.tmp, *statuses)
        uploaded = []
        fake_status = mock.patch.object(fleet, "fetch_status",
                                        side_effect=lambda c, n: dict(statuses[n.name], node=n.name))
        fake_upload = mock.patch.object(fleet, "upload_job", side_effect=lambda c, n, j: uploaded.append((n.name, j)))
        with fake_status as fs, fake_upload:
            rc, out, err = quietly(fleet.dispatch_jobs, cfg, [fleet.validate_job(j) for j in jobs], spec, dry_run, False)
            if dry_run:
                fs.assert_not_called()
        return rc, uploaded, out, err

    def test_auto_picks_least_busy_ready_node(self):
        busy = dict(healthy()["queue"], inbox=3)
        rc, up, out, _ = self.dispatch({"vps1": healthy(queue=busy), "vps2": healthy(paused=True),
                                        "vps3": healthy(max_parallel=2, queue=dict(busy, inbox=1))},
                                       [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}])
        self.assertEqual(rc, 0)
        self.assertEqual([n for n, _ in up], ["vps3", "vps3", "vps3"])
        self.assertIn("queued ", out)
        self.assertTrue(all(j["node"] == "vps3" and j["submitted_at"] for _, j in up))

    def test_auto_refuses_when_nothing_is_ready(self):
        rc, up, _, err = self.dispatch({"vps1": healthy(low_disk=True), "vps2": {"reachable": False}},
                                       [{"prompt": "a", "channel": "Space"}])
        self.assertEqual((rc, up), (1, []))
        self.assertIn("no VPS can take a claude job right now (vps1 low on disk; vps2 unreachable)", err)

    def test_explicit_node_queues_with_a_warning(self):
        rc, up, _, err = self.dispatch({"vps1": healthy(paused=True), "vps2": healthy()},
                                       [{"prompt": "a", "id": "fixed-id"}], spec="vps1")
        self.assertEqual(rc, 0)
        self.assertEqual([(n, j["id"]) for n, j in up], [("vps1", "fixed-id")])
        self.assertIn("warning: vps1: paused; fixed-id waits in its queue", err)

    def test_all_makes_one_copy_per_reachable_node(self):
        rc, up, _, err = self.dispatch({"vps1": healthy(), "vps2": healthy(), "vps3": {"reachable": False}},
                                       [{"prompt": "a", "id": "batch"}], spec="all")
        self.assertEqual(rc, 1)
        self.assertEqual(sorted(j["id"] for _, j in up), ["batch-vps1", "batch-vps2"])
        self.assertIn("vps3 is unreachable", err)

    def test_unknown_provider_and_dry_run(self):
        rc, up, _, err = self.dispatch({"vps1": healthy()}, [{"prompt": "a", "provider": "other"}])
        self.assertEqual((rc, up), (1, []))
        self.assertIn("offers provider 'other'", err)
        rc, up, out, _ = self.dispatch({"vps1": healthy(), "vps2": healthy()}, [{"prompt": "a"}], dry_run=True)
        self.assertEqual((rc, up), (0, []))
        self.assertEqual(json.loads(out)["node"], "vps1")


class UsageLimitTest(TempDirTest):
    """A VPS whose account hit its usage limit reports a `limit` hold in its status."""

    @staticmethod
    def limited(hours_left: float, hours_total: float = None, **over) -> dict:
        now = __import__("time").time()
        total = hours_left if hours_total is None else hours_total
        lim = {"provider": "claude", "kind": "five_hour", "message": "You've hit your session limit",
               "since": int(now - (total - hours_left) * 3600), "until": int(now + hours_left * 3600)}
        return healthy(limit=lim, on_hold="usage limit (claude) until later", **over)

    def test_active_limit_and_time(self):
        self.assertTrue(fleet.active_limit(self.limited(1)))
        self.assertEqual(fleet.active_limit(self.limited(-1)), {})
        self.assertEqual(fleet.active_limit(healthy()), {})
        self.assertEqual(fleet.active_limit(healthy(limit=None)), {})
        self.assertEqual(fleet.active_limit(None), {})
        now = __import__("time").time()
        self.assertRegex(fleet.short_time(now + 60), r"^\d\d:\d\d$")
        self.assertRegex(fleet.short_time(now + 3 * 86400), r"^[A-Z][a-z]{2} \d\d [A-Z][a-z]{2} \d\d:\d\d$")

    def test_readiness(self):
        self.assertRegex(fleet.node_readiness(self.limited(2), "claude"), r"^at its usage limit until ")
        self.assertIsNone(fleet.node_readiness(self.limited(-0.1), "claude"))
        # a paused node reports the pause first
        self.assertEqual(fleet.node_readiness(self.limited(2, paused=True), "claude"), "paused")

    def test_only_long_holds_are_health_problems(self):
        cfg = make_cfg(self.tmp, "vps1", "vps2")
        statuses = {"vps1": self.limited(4), "vps2": self.limited(3, hours_total=7 * 24)}
        with mock.patch.object(fleet, "fetch_status", side_effect=lambda c, n: dict(statuses[n.name], node=n.name)):
            p = fleet.health_problems(cfg, argparse.Namespace(min_disk_pct=15, max_backlog=25))
        self.assertEqual(list(p), ["vps2:limit"])
        self.assertIn("vps2: claude usage limit reached (You've hit your session limit)", p["vps2:limit"])
        self.assertIn("continues by itself", p["vps2:limit"])

    def dispatch(self, statuses):
        cfg = make_cfg(self.tmp, *statuses)
        uploaded = []
        with mock.patch.object(fleet, "fetch_status", side_effect=lambda c, n: dict(statuses[n.name], node=n.name)), \
                mock.patch.object(fleet, "upload_job", side_effect=lambda c, n, j: uploaded.append(n.name)):
            rc, _, err = quietly(fleet.dispatch_jobs, cfg, [fleet.validate_job({"prompt": "x"})], "auto", False, False)
        return rc, uploaded, err

    def test_dispatch_prefers_ready_nodes(self):
        rc, up, _ = self.dispatch({"vps1": self.limited(2), "vps2": healthy(queue=dict(healthy()["queue"], inbox=9))})
        self.assertEqual((rc, up), (0, ["vps2"]))

    def test_dispatch_when_every_account_is_limited(self):
        rc, up, err = self.dispatch({"vps1": self.limited(3), "vps2": self.limited(1), "vps3": healthy(paused=True)})
        self.assertEqual((rc, up), (0, ["vps2"]))
        self.assertIn("warning: vps2: at its usage limit until", err)


# --------------------------------------------------------------------------- channels and handover

class ChannelTest(TempDirTest):
    """Each VPS makes videos for its own channels (`channels` in fleet.ini)."""

    def cfg(self, **channels):
        cfg = make_cfg(self.tmp, *channels)
        for name, ch in channels.items():
            cfg.nodes[name].channels = ch
        return cfg

    def dispatch(self, cfg, statuses, jobs, spec="auto"):
        uploaded = []
        with mock.patch.object(fleet, "fetch_status", side_effect=lambda c, n: dict(statuses[n.name], node=n.name)), \
                mock.patch.object(fleet, "upload_job",
                                  side_effect=lambda c, n, j: uploaded.append((n.name, j["channel"]))):
            rc, _, err = quietly(fleet.dispatch_jobs, cfg, [fleet.validate_job(j) for j in jobs], spec, False, False)
        return rc, uploaded, err

    def test_names_match_loosely(self):
        key = fleet.channel_key
        self.assertEqual({key("Space Facts"), key("space-facts"), key(" SPACE_FACTS "), key("space  facts!")},
                         {"space-facts"})
        self.assertEqual(key("قناة الفضاء"), "قناة-الفضاء")
        self.assertNotEqual(key("Space Facts"), key("Space Fact"))
        self.assertEqual(key("!!!"), "!!!")

    def test_channel_home(self):
        cfg = self.cfg(vps1="Space Facts", vps2="History, all", vps3="")
        pool = list(cfg.nodes.values())

        def home(nodes, ch):
            found, dedicated = fleet.channel_home(nodes, ch)
            return [n.name for n in found], dedicated
        self.assertEqual(home(pool, "space-facts"), (["vps1"], True))
        self.assertEqual(home(pool, "HISTORY"), (["vps2"], True))
        self.assertEqual(home(pool, "Cooking"), (["vps2"], False))
        self.assertEqual(home(pool[:1], "Cooking"), ([], False))
        self.assertTrue(fleet.serves(cfg.nodes["vps2"], "Cooking"))
        self.assertFalse(fleet.serves(cfg.nodes["vps3"], "Cooking"))
        self.assertEqual(fleet.dedicated_channels(cfg.nodes["vps2"]), ["History"])

    def test_inventory(self):
        p = self.tmp / "fleet.ini"
        p.write_text("[vps1]\nchannels = Space Facts, History ; two\n[vps2]\nchannels =\n[vps3]\n", encoding="utf-8")
        cfg = fleet.load_config(p)
        self.assertEqual(fleet.channel_names(cfg.nodes["vps1"]), ["Space Facts", "History"])
        self.assertEqual(fleet.channel_names(cfg.nodes["vps2"]), [])
        self.assertEqual(fleet.channel_names(cfg.nodes["vps3"]), ["all"])  # inventories from before channels
        example = fleet.load_config(REPO / "home" / "fleet.ini.example")
        self.assertTrue(all(n.channels == "" for n in example.nodes.values()))

    def test_jobs_stay_on_their_channels_vps(self):
        cfg = self.cfg(vps1="Space Facts", vps2="History", vps3="all")
        statuses = {"vps1": UsageLimitTest.limited(30), "vps2": healthy(paused=True), "vps3": healthy()}
        rc, up, err = self.dispatch(cfg, statuses, [{"prompt": "a", "channel": "Space Facts"},
                                                    {"prompt": "b", "channel": "history"},
                                                    {"prompt": "c", "channel": "Cooking"}])
        self.assertEqual(rc, 0)
        self.assertEqual(up, [("vps1", "Space Facts"), ("vps2", "history"), ("vps3", "Cooking")])
        self.assertIn("warning: vps1: at its usage limit until", err)
        self.assertIn("waits in its queue until the limit resets", err)
        self.assertIn("warning: vps2: paused", err)

    def test_several_vps_for_one_channel(self):
        cfg = self.cfg(vps1="Space Facts", vps2="space facts", vps3="all")
        busy = dict(healthy()["queue"], inbox=2)
        jobs = [{"prompt": p, "channel": "Space Facts"} for p in "abc"]
        rc, up, _ = self.dispatch(cfg, {"vps1": healthy(queue=busy), "vps2": healthy(), "vps3": healthy()}, jobs)
        self.assertEqual((rc, [n for n, _ in up]), (0, ["vps2", "vps2", "vps1"]))
        limited = {"vps1": UsageLimitTest.limited(1), "vps2": UsageLimitTest.limited(2), "vps3": healthy()}
        rc, up, _ = self.dispatch(cfg, limited, jobs[:1])
        self.assertEqual((rc, up), (0, [("vps1", "Space Facts")]))  # never the idle vps3

    def test_no_vps_for_the_channel(self):
        cfg = self.cfg(vps1="Space Facts", vps2="")
        rc, up, err = self.dispatch(cfg, {"vps1": healthy(), "vps2": healthy()}, [{"prompt": "a", "channel": "Cooking"}])
        self.assertEqual((rc, up), (1, []))
        self.assertIn("no VPS makes videos for channel 'Cooking'", err)
        self.assertIn("--to", err)

    def test_unreachable_channel_vps_is_an_error(self):
        cfg = self.cfg(vps1="Space Facts", vps2="all")
        rc, up, err = self.dispatch(cfg, {"vps1": {"reachable": False}, "vps2": healthy()},
                                    [{"prompt": "a", "channel": "Space Facts"}])
        self.assertEqual((rc, up), (1, []))
        self.assertIn("channel 'Space Facts' is made on vps1, and no VPS can take", err)

    def test_broken_provider_on_the_channels_vps(self):
        # Such a job would fail rather than wait, so auto dispatch refuses it.
        cfg = self.cfg(vps1="Space Facts", vps2="all")
        broken = healthy(providers=[{"provider": "claude", "installed": True, "ok": False,
                                     "error": "no credentials"}])
        statuses = {"vps1": broken, "vps2": healthy()}
        job = [{"prompt": "a", "channel": "Space Facts"}]
        rc, up, err = self.dispatch(cfg, statuses, job)
        self.assertEqual((rc, up), (1, []))
        self.assertIn("channel 'Space Facts' is made on vps1, and no VPS can take a claude job right now "
                      "(vps1 claude is not ok (no credentials))", err)
        rc, up, err = self.dispatch(cfg, statuses, job, spec="vps1")  # named: it goes, with a warning
        self.assertEqual((rc, up), (0, [("vps1", "Space Facts")]))
        self.assertIn("fails if that is not fixed before it starts", err)

    def test_named_vps_gets_a_note(self):
        cfg = self.cfg(vps1="Space Facts", vps2="History")
        statuses = {"vps1": healthy(), "vps2": healthy()}
        rc, up, err = self.dispatch(cfg, statuses, [{"prompt": "a", "channel": "Space Facts"}], spec="vps2")
        self.assertEqual((rc, up), (0, [("vps2", "Space Facts")]))
        self.assertIn("note: vps2 does not make videos for channel 'Space Facts'", err)
        rc, up, err = self.dispatch(cfg, statuses, [{"prompt": "a", "channel": "Space Facts"}], spec="vps1")
        self.assertNotIn("note:", err)

    def test_provider_on_the_channels_vps(self):
        cfg = self.cfg(vps1="Space Facts", vps2="all")
        cfg.nodes["vps2"].providers = ["claude", "other"]
        rc, up, err = self.dispatch(cfg, {"vps1": healthy(), "vps2": healthy()},
                                    [{"prompt": "a", "channel": "Space Facts", "provider": "other"}])
        self.assertEqual((rc, up), (1, []))
        self.assertIn("channel 'Space Facts' is made on vps1, which does not offer provider 'other'", err)

    def test_health_points_to_handover_for_a_channels_vps(self):
        cfg = self.cfg(vps1="Space Facts", vps2="all")
        week = 7 * 24
        statuses = {"vps1": UsageLimitTest.limited(3, hours_total=week),
                    "vps2": UsageLimitTest.limited(3, hours_total=week, stuck_handovers=2)}
        with mock.patch.object(fleet, "fetch_status", side_effect=lambda c, n: dict(statuses[n.name], node=n.name)):
            p = fleet.health_problems(cfg, argparse.Namespace(min_disk_pct=15, max_backlog=25))
        self.assertIn("(new Space Facts jobs wait there too, unless you move them with fleet handover)",
                      p["vps1:limit"])
        self.assertFalse([m for m in p.values() if re.search(r"[<>`]", m)])  # plain text for every chat app
        self.assertIn("fleet dispatch sends new jobs to other VPSs meanwhile", p["vps2:limit"])
        self.assertIn("2 job(s) stopped halfway through a handover", p["vps2:handover"])
        self.assertNotIn("vps1:handover", p)


class HandoverTest(TempDirTest):
    listing = [{"id": "q1", "state": "inbox", "channel": "Space Facts", "provider": "claude"},
               {"id": "q2", "state": "outgoing", "channel": "Space Facts", "provider": "claude"},
               {"id": "r1", "state": "running", "channel": "Space Facts"},
               {"id": "d1", "state": "done", "channel": "Space Facts"},
               {"id": "o1", "state": "inbox", "channel": "Space Facts", "provider": "other"}]

    def handover(self, listing, ids=(), dry_run=False, to_status=None, fail=()):
        cfg = make_cfg(self.tmp, "vps1", "vps2")
        cfg.nodes["vps1"].channels, cfg.nodes["vps2"].channels = "Space Facts", "History"
        moved = []

        def fake_remote(c, n, command, **kw):
            self.assertEqual((n.name, command.split()[-2:]), ("vps1", ["jobs", "--json"]))
            return subprocess.CompletedProcess([], 0, json.dumps(listing).encode(), b"")

        def fake_hand_over(c, frm, to, jid):
            if jid in fail:
                raise fleet.FleetError(f"{jid} stays on {frm.name}: boom")
            moved.append(jid)
            return f"moved {jid}"
        a = argparse.Namespace(from_node="vps1", to_node="vps2", job_ids=list(ids), dry_run=dry_run)
        with mock.patch.object(fleet, "remote", side_effect=fake_remote), \
                mock.patch.object(fleet, "fetch_status", return_value=to_status or healthy()), \
                mock.patch.object(fleet, "hand_over", side_effect=fake_hand_over):
            rc, out, err = quietly(fleet.cmd_handover, cfg, a)
        return rc, moved, out, err

    def test_moves_every_queued_job_by_default(self):
        rc, moved, out, err = self.handover(self.listing)
        self.assertEqual((rc, moved), (1, ["q1", "q2"]))  # o1 stays: vps2 does not offer its provider
        self.assertIn("vps2 does not offer provider 'other'", err)
        self.assertIn("running jobs stay on vps1: r1", err)
        self.assertIn("note: only these jobs moved. New Space Facts jobs still go to the VPS", out)

    def test_named_jobs(self):
        rc, moved, _, err = self.handover(self.listing, ids=["q2", "r1", "d1", "zz"])
        self.assertEqual((rc, moved), (1, ["q2"]))
        self.assertIn("fleet cancel vps1 r1, then fleet retry vps1 r1 --to vps2", err)
        self.assertIn("d1 is not queued on vps1 (it is done)", err)
        self.assertIn("vps1 has no job zz", err)

    def test_dry_run_and_nothing_to_move(self):
        rc, moved, out, _ = self.handover(self.listing[:2], dry_run=True)
        self.assertEqual((rc, moved), (0, []))
        self.assertIn("would move q1 (channel Space Facts) from vps1 to vps2", out)
        rc, moved, out, _ = self.handover([{"id": "d1", "state": "done"}])
        self.assertEqual((rc, moved), (0, []))
        self.assertIn("nothing to hand over", out)

    def test_target_checks(self):
        rc, moved, _, err = self.handover(self.listing[:1], to_status=UsageLimitTest.limited(2))
        self.assertEqual((rc, moved), (0, ["q1"]))
        self.assertIn("warning: vps2: at its usage limit", err)
        broken = healthy(providers=[{"provider": "claude", "installed": True, "ok": False, "error": "no credentials"}])
        rc, moved, _, err = self.handover(self.listing[:1], to_status=broken)
        self.assertEqual((rc, moved), (1, []))  # it would only fail there
        self.assertIn("q1 stays on vps1: on vps2, claude is not ok (no credentials), so it would fail there", err)
        with self.assertRaisesRegex(fleet.FleetError, "unreachable, so nothing was moved"):
            self.handover(self.listing[:1], to_status={"reachable": False, "error": "timed out"})
        a = argparse.Namespace(from_node="vps1", to_node="vps1", job_ids=[], dry_run=False)
        with self.assertRaisesRegex(fleet.FleetError, "same VPS"):
            fleet.cmd_handover(make_cfg(self.tmp, "vps1"), a)
        a = argparse.Namespace(from_node="vps1", to_node="vps2", job_ids=["../x"], dry_run=False)
        with self.assertRaisesRegex(fleet.FleetError, "invalid job id"):
            fleet.cmd_handover(make_cfg(self.tmp, "vps1", "vps2"), a)

    def test_failures_are_reported(self):
        rc, moved, _, err = self.handover(self.listing[:2], fail=("q1",))
        self.assertEqual((rc, moved), (1, ["q2"]))
        self.assertIn("q1 stays on vps1: boom", err)


# --------------------------------------------------------------------------- secrets

class SecretsTest(TempDirTest):
    def test_read_env_file(self):
        p = self.tmp / "claude.env"
        p.write_bytes(b"\xef\xbb\xbf# comment\n\nANTHROPIC_API_KEY = \"sk-ant-1\"\nexport CLAUDE_MAX_TURNS='40'\n"
                      b"CLAUDE_CODE_OAUTH_TOKEN=\nnot a pair\n")
        self.assertEqual(fleet.read_env_file(p), {"ANTHROPIC_API_KEY": "sk-ant-1", "CLAUDE_MAX_TURNS": "40",
                                                  "CLAUDE_CODE_OAUTH_TOKEN": ""})

    def test_shipped_templates_have_no_values(self):
        for name in ("claude.env.example", "tailscale.env.example"):
            values = fleet.read_env_file(REPO / "home" / "secrets.example" / name)
            self.assertTrue(values, name)
            self.assertFalse({k: v for k, v in values.items() if v and k.endswith(("KEY", "TOKEN"))}, name)
            self.assertTrue(all(fleet.ENV_KEY_RE.match(k) for k in values), name)

    @unittest.skipUnless(POSIX, "file modes are POSIX only")
    def test_secret_file_lookup_and_permissions(self):
        cfg = make_cfg(self.tmp, "vps1", "vps2")
        (self.tmp / "secrets" / "vps1").mkdir(parents=True)
        shared, own = self.tmp / "secrets" / "claude.env", self.tmp / "secrets" / "vps1" / "claude.env"
        shared.write_text("A=1\n", encoding="utf-8")
        own.write_text("A=2\n", encoding="utf-8")
        os.chmod(shared, 0o600)
        os.chmod(own, 0o600)
        self.assertEqual(fleet.secret_file(cfg, cfg.nodes["vps1"], "claude"), own)
        self.assertEqual(fleet.secret_file(cfg, cfg.nodes["vps2"], "claude"), shared)
        self.assertIsNone(fleet.secret_file(cfg, cfg.nodes["vps2"], "tailscale"))
        os.chmod(own, 0o644)
        with self.assertRaisesRegex(fleet.FleetError, "chmod 600"):
            fleet.secret_file(cfg, cfg.nodes["vps1"], "claude")

    @unittest.skipUnless(POSIX, "file modes are POSIX only")
    def test_push_refuses_bad_names(self):
        cfg = make_cfg(self.tmp, "vps1")
        (self.tmp / "secrets").mkdir()
        f = self.tmp / "secrets" / "claude.env"
        f.write_text("GOOD=1\nBAD-NAME=2\n", encoding="utf-8")
        os.chmod(f, 0o600)
        a = argparse.Namespace(name="claude", targets="vps1")
        with mock.patch.object(fleet, "remote") as remote:
            with self.assertRaisesRegex(fleet.FleetError, "BAD-NAME"):
                fleet.cmd_secrets(cfg, a)
            remote.assert_not_called()


# --------------------------------------------------------------------------- home setup

class CronScriptTest(TempDirTest):
    def render(self, config, cli, args=("health", "--changes-only")):
        return fleet.CRON_SCRIPT.format(config=str(config), args=list(args), cli=str(cli))

    def test_windows_paths_survive(self):
        cfg = r"C:\Users\Owner Name\.config\fleet\fleet.ini"
        cli = r"C:\Users\Owner Name\hermes-fleet\home\bin\fleet"
        src = self.render(cfg, cli)
        tree = ast.parse(src)
        literals = [ast.literal_eval(node) for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertIn(cfg, literals)
        self.assertIn(cli, literals)

    def test_exit_codes(self):
        fake = self.tmp / "fake-fleet"
        fake.write_text("import os, sys\nprint(os.environ['FLEET_CONFIG'], *sys.argv[1:])\n"
                        "rc = os.environ.get('RC')\nif rc: sys.exit(int(rc))\n", encoding="utf-8")
        script = self.tmp / "fleet_health.py"
        script.write_text(self.render(self.tmp / "fleet.ini", fake), encoding="utf-8")
        for rc, want in (("", 0), ("0", 0), ("2", 0), ("1", 1), ("3", 3)):
            env = {k: v for k, v in os.environ.items() if k != "FLEET_CONFIG"}
            env["RC"] = rc
            r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, want, (rc, r.stderr))
            self.assertEqual(r.stdout.split(), [str(self.tmp / "fleet.ini"), "health", "--changes-only"])


class FakeHermes:
    """Stands in for `hermes config get/set`, storing values in a dict."""

    def __init__(self, store=None):
        self.store, self.sets = dict(store or {}), []

    def __call__(self, exe, *args, profile=None, timeout=120):
        if args[:2] == ("config", "get"):
            out = json.dumps(self.store[args[2]]) if args[2] in self.store else "null"
            return subprocess.CompletedProcess(args, 0, out.encode(), b"")
        if args[:2] == ("config", "set"):
            try:
                value = json.loads(args[3])
            except ValueError:
                value = args[3]
            self.store[args[2]] = value
            self.sets.append(args[2])
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return subprocess.CompletedProcess(args, 1, b"", b"unsupported")


class ProfileHermes(FakeHermes):
    """FakeHermes with profiles: `profile create` makes the profile's folder under root."""

    def __init__(self, root, store=None):
        super().__init__(store)
        self.root, self.calls, self.cron = Path(root), [], []

    def __call__(self, exe, *args, profile=fleet.HERMES_PROFILE, timeout=120):
        self.calls.append((profile, args))
        if args[:2] == ("profile", "show"):
            home = self.root / "profiles" / args[2]
            if not home.is_dir():
                return subprocess.CompletedProcess(args, 1, b"", b"no such profile")
            return subprocess.CompletedProcess(args, 0, f"Profile: {args[2]}\nPath:    {home}\n".encode(), b"")
        if args[:2] == ("profile", "create"):
            (self.root / "profiles" / args[2]).mkdir(parents=True)
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if args[:2] == ("cron", "list"):
            return subprocess.CompletedProcess(args, 0, "\n".join(self.cron).encode(), b"")
        if args[:2] == ("cron", "create"):
            self.cron.append(args[args.index("--name") + 1])
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if args[:2] == ("cron", "remove") and args[2] in self.cron:
            self.cron.remove(args[2])
            return subprocess.CompletedProcess(args, 0, b"", b"")
        return super().__call__(exe, *args, timeout=timeout)


class DirectorProfileTest(TempDirTest):
    """Hermes directs the fleet from its own profile, `director`."""

    def test_hermes_commands_target_the_director(self):
        seen = []
        with mock.patch.object(fleet.subprocess, "run", side_effect=lambda argv, **kw: seen.append(argv)):
            fleet.hermes_cmd("hermes", "cron", "list")
            fleet.hermes_cmd("hermes", "profile", "list", profile="")
        self.assertEqual(seen, [["hermes", "-p", "director", "cron", "list"], ["hermes", "profile", "list"]])

    def test_profile_is_created_once(self):
        fake = ProfileHermes(self.tmp)
        with mock.patch.object(fleet, "hermes_cmd", fake):
            home, lines = fleet.ensure_director("hermes")
            self.assertEqual(home, self.tmp / "profiles" / "director")
            self.assertIn("+ profile director", lines[0])
            again, lines = fleet.ensure_director("hermes")
        self.assertEqual(again, home)
        self.assertIn("= profile director", lines[0])
        creates = [args for _, args in fake.calls if args[:2] == ("profile", "create")]
        self.assertEqual(len(creates), 1)
        self.assertIn("--no-skills", creates[0])
        self.assertEqual({p for p, _ in fake.calls}, {""})  # profile commands run without -p

    def test_hermes_without_profiles(self):
        with mock.patch.object(fleet, "hermes_cmd", FakeHermes()):
            home, lines = fleet.ensure_director("hermes")
        self.assertIsNone(home)
        self.assertIn("could not create the Hermes profile 'director': unsupported", lines[0])
        self.assertIn("hermes update", lines[1])

    def test_init_sets_up_the_director(self):
        (self.tmp / "key").write_text("private", encoding="utf-8")
        (self.tmp / "key.pub").write_text("ssh-ed25519 AAAA test", encoding="utf-8")
        ini = self.tmp / "fleet.ini"
        ini.write_text(f"[defaults]\nssh_key = {(self.tmp / 'key').as_posix()}\n"
                       f"secrets_dir = {(self.tmp / 'secrets').as_posix()}\n[vps1]\n", encoding="utf-8")
        fake = ProfileHermes(self.tmp / "hermes", {"model.provider": "openrouter", "model.default": "some/model"})
        with mock.patch.object(fleet, "HOME", self.tmp), mock.patch.object(fleet, "STATE_DIR", self.tmp / "state"), \
                mock.patch.object(fleet, "find_hermes", return_value="hermes"), \
                mock.patch.object(fleet, "hermes_cmd", fake):
            rc, out, _ = quietly(fleet.cmd_init, ini, argparse.Namespace(no_hermes=False))
        self.assertEqual(rc, 0)
        home = self.tmp / "hermes" / "profiles" / "director"
        self.assertEqual((home / "SOUL.md").read_bytes(), (REPO / "home" / "hermes" / "SOUL.md").read_bytes())
        for script in ("fleet_health.py", "fleet_pull.py", "fleet_report.py", "fleet_plan.py"):
            self.assertTrue((home / "scripts" / script).is_file(), script)
        self.assertEqual(fake.store["terminal.cwd"], fleet.REPO_ROOT.as_posix())
        self.assertEqual({p for p, args in fake.calls if args[0] == "config"}, {"director"})
        self.assertIn("model: openrouter / some/model", out)
        self.assertIn("hermes -p director model", out)

    def test_cron_jobs_belong_to_the_director(self):
        fake, cfg, a = ProfileHermes(self.tmp), make_cfg(self.tmp, "vps1"), argparse.Namespace(deliver="telegram")
        with mock.patch.object(fleet, "find_hermes", return_value="hermes"), mock.patch.object(fleet, "hermes_cmd", fake):
            with self.assertRaisesRegex(fleet.FleetError, "run `fleet init` first"):
                fleet.cmd_hermes_cron(cfg, a)
            (self.tmp / "profiles" / "director").mkdir(parents=True)
            fake.cron = ["fleet-health", "fleet-daily-report"]  # made by an older fleet
            rc, out, _ = quietly(fleet.cmd_hermes_cron, cfg, a)
            self.assertEqual(rc, 0)
            self.assertIn("- fleet-daily-report (replaced by fleet-report)", out)
            self.assertEqual(fake.cron, ["fleet-health", "fleet-pull", "fleet-report", "fleet-plan", "fleet-week-plan"])
            self.assertIn("= fleet-health already exists", quietly(fleet.cmd_hermes_cron, cfg, a)[1])
        self.assertEqual({p for p, args in fake.calls if args[0] == "cron"}, {"director"})
        creates = {args[args.index("--name") + 1]: args for _, args in fake.calls if args[:2] == ("cron", "create")}
        self.assertEqual(creates["fleet-report"][2:6], ("0 9 * * *", "--no-agent", "--script", "fleet_report.py"))
        self.assertEqual(creates["fleet-plan"][2:6], ("every 1h", "--no-agent", "--script", "fleet_plan.py"))
        week = creates["fleet-week-plan"]
        self.assertEqual(week[2], "0 10 * * 0")
        self.assertIn("fleet plan import", week[3])
        self.assertIn("Do not approve anything yourself", week[3])
        self.assertIn("fleet-ops", week)
        scripts = self.tmp / "profiles" / "director" / "scripts"
        self.assertIn("'plan', 'run', '--quiet'", (scripts / "fleet_plan.py").read_text(encoding="utf-8"))
        self.assertIn("['report']", (scripts / "fleet_report.py").read_text(encoding="utf-8"))


class HermesSettingsTest(unittest.TestCase):
    def test_merge_and_idempotence(self):
        skills = (REPO / "home" / "hermes" / "skills").as_posix()
        fake = FakeHermes({"skills.external_dirs": ["/mine"], "terminal.timeout": 1800,
                           "approvals.deny": ["my rule"], "model.default": "something-else"})
        with mock.patch.object(fleet, "hermes_cmd", fake):
            report = fleet.apply_hermes_settings("hermes", "/repo")
            self.assertEqual(fake.store["skills.external_dirs"], ["/mine", skills])
            self.assertEqual(fake.store["terminal.timeout"], 1800)
            self.assertEqual(fake.store["terminal.cwd"], "/repo")
            deny = fake.store["approvals.deny"]
            self.assertEqual((deny[0], len(deny)), ("my rule", 5))
            for secret in ("cat ~/.hermes/.env", "cat ~/.hermes/profiles/director/.env",
                           r"type %LOCALAPPDATA%\hermes\profiles\director\.env", "cat ~/.config/fleet/secrets/vps1/claude.env"):
                self.assertTrue(any(fnmatch.fnmatchcase(secret, d) for d in deny), secret)
            self.assertFalse(any(fnmatch.fnmatchcase("fleet status", d) for d in deny))
            self.assertEqual(fake.store["skills.auto_load"], ["fleet-ops"])
            self.assertTrue(any("terminal.cwd" in line for line in report))
            fake.sets.clear()
            fleet.apply_hermes_settings("hermes", "/repo")
            self.assertEqual(fake.sets, [])

    def test_model_is_left_to_the_owner(self):
        fake = FakeHermes({"terminal.timeout": 60, "model.provider": "openrouter", "model.default": "some/model"})
        with mock.patch.object(fleet, "hermes_cmd", fake):
            fleet.apply_hermes_settings("hermes", "/repo")
        self.assertEqual(fake.store["terminal.timeout"], 900)
        self.assertEqual((fake.store["model.provider"], fake.store["model.default"]), ("openrouter", "some/model"))
        self.assertFalse([k for k in fake.sets if k.startswith("model.")])

    def test_hermes_model(self):
        for store, want in (({}, ""), ({"model.default": "some/model"}, "some/model"),
                            ({"model.provider": "nous", "model.default": "hermes-x"}, "nous / hermes-x")):
            with mock.patch.object(fleet, "hermes_cmd", FakeHermes(store)):
                self.assertEqual(fleet.hermes_model("hermes"), want)


class ShimTest(TempDirTest):
    def test_windows_shims(self):
        with mock.patch.object(fleet, "IS_WINDOWS", True):
            made = fleet.install_shims(self.tmp / "bin")
        self.assertEqual(len(made), 2)
        sh = (self.tmp / "bin" / "fleet").read_bytes()
        cmd = (self.tmp / "bin" / "fleet.cmd").read_bytes()
        self.assertTrue(sh.startswith(b"#!/bin/sh\nexec "))
        self.assertNotIn(b"\r\n", sh)
        self.assertTrue(cmd.startswith(b"@echo off\r\n"))
        self.assertIn(b"%*", cmd)

    @unittest.skipUnless(POSIX, "symlinks need extra rights on Windows")
    def test_posix_symlink(self):
        fleet.install_shims(self.tmp / "bin")
        fleet.install_shims(self.tmp / "bin")  # a second run replaces the link
        link = self.tmp / "bin" / "fleet"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), CLI.resolve())


# --------------------------------------------------------------------------- studio

def ran(code: int = 0, out: bytes = b"", err: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=out, stderr=err)


def step(*content) -> str:
    """One assistant message of a Claude Code transcript."""
    return json.dumps({"type": "assistant", "message": {"content": list(content)}})


class FakeStudioServer:
    def __init__(self, host, port, handler, looked):
        self.server_address = (host, port)
        self.handler, self.looked, self.closed = handler, looked, False

    def serve_forever(self, poll_interval=0.5):
        self.looked.wait(5)  # the first look at the VPSs has happened
        raise KeyboardInterrupt

    def server_close(self):
        self.closed = True


class FakeTimer:
    def __init__(self, delay, fn):
        self.fn, self.daemon = fn, False

    def start(self):
        self.fn()


class StudioTest(TempDirTest):
    def worker_output(self) -> bytes:
        jobs = [{"id": "job-a", "state": "running", "channel": "Space Facts"}, {"id": "job-b", "state": "inbox"}]
        return "\n".join([
            "Welcome to Ubuntu 24.04 LTS",
            json.dumps(healthy()),
            json.dumps(jobs),
            '{"cut": ',
            json.dumps({"kind": "tool", "name": "Bash", "detail": "Render the video", "id": "job-a", "mtime": 1}),
            json.dumps({"kind": "text", "text": "Writing the script", "id": "job-c", "mtime": 2}),
            json.dumps({"kind": "other", "id": "job-d"}),
        ]).encode("utf-8") + b"\n"

    def test_parse_studio_keeps_the_json_and_skips_the_rest(self):
        status, jobs, activity = fleet.parse_studio(self.worker_output())
        self.assertEqual(status["queue"]["inbox"], 0)
        self.assertEqual([j["id"] for j in jobs], ["job-a", "job-b"])
        self.assertEqual(sorted(activity), ["job-a", "job-c"])
        self.assertEqual(activity["job-a"]["detail"], "Render the video")
        self.assertEqual(fleet.parse_studio(b""), (None, [], {}))

    def test_studio_node(self):
        cfg = make_cfg(self.tmp, "vps1", channels="Space Facts, History")
        n = cfg.nodes["vps1"]
        with mock.patch.object(fleet, "remote", return_value=ran(0, self.worker_output())):
            got = fleet.studio_node(cfg, n)
        self.assertEqual((got["name"], got["channels"], got["sessions"]), ("vps1", ["Space Facts", "History"], 1))
        self.assertTrue(got["reachable"] and got["status"]["reachable"])
        self.assertEqual((len(got["jobs"]), sorted(got["activity"])), (2, ["job-a", "job-c"]))
        timeout = ran(255, err=b"ssh: connect to host vps1 port 22: Connection timed out\n")
        with mock.patch.object(fleet, "remote", return_value=timeout):
            got = fleet.studio_node(cfg, n)
        self.assertFalse(got["reachable"])
        self.assertIn("Connection timed out", got["error"])
        with mock.patch.object(fleet, "remote", return_value=ran(0, b"[]\n")):
            self.assertEqual(fleet.studio_node(cfg, n)["error"], "worker returned no status (run fleet sync)")

    def test_snapshot_lists_every_enabled_vps_in_order(self):
        cfg = make_cfg(self.tmp, "vps1", "vps2", "vps3")
        cfg.nodes["vps3"].enabled = False

        def look(cfg_, n):
            if n.name == "vps2":
                raise RuntimeError("no route to vps2")
            return dict(fleet.studio_base(n), reachable=True, status=healthy(), jobs=[], activity={})

        with mock.patch.object(fleet, "studio_node", side_effect=look):
            snap = fleet.studio_snapshot(cfg, 20)
        self.assertEqual([x["name"] for x in snap["nodes"]], ["vps1", "vps2"])
        self.assertEqual((snap["every"], snap["fleet_version"]), (20, fleet.VERSION))
        self.assertEqual(snap["nodes"][1], dict(fleet.studio_base(cfg.nodes["vps2"]), reachable=False,
                                                error="no route to vps2"))
        self.assertEqual(snap["screenings"], [])  # nothing collected yet
        self.assertEqual((snap["ideas"][0]["title"], snap["ideas_starter"]), ("Trend looker", True))
        json.dumps(snap)

    @unittest.skipUnless(POSIX and shutil.which("jq"), "the VPS side runs on Linux, with jq")
    def test_activity_is_the_last_step_of_the_transcript(self):
        def last(*lines):
            r = subprocess.run(["jq", "-cR", fleet.STUDIO_ACTIVITY_JQ], input=("\n".join(lines) + "\n").encode(),
                               capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            got = [json.loads(x) for x in r.stdout.decode("utf-8").splitlines() if x.strip()]
            return got[-1] if got else None

        render = {"type": "tool_use", "name": "Bash",
                  "input": {"command": "ffmpeg -i a.mp4 b.mp4", "description": "Render the video"}}
        self.assertEqual(last('of a line cut in half"}', json.dumps({"type": "system", "subtype": "init"}),
                              step({"type": "text", "text": "Planning"}),
                              step({"type": "text", "text": "Rendering"}, render),
                              json.dumps({"type": "user", "message": {"content": [{"type": "tool_result"}]}}),
                              json.dumps({"type": "result", "subtype": "success"})),
                         {"kind": "tool", "name": "Bash", "detail": "Render the video"})
        self.assertEqual(last(step({"type": "text", "text": "x" * 1000})), {"kind": "text", "text": "x" * 300})
        write = {"type": "tool_use", "name": "Write", "input": {"file_path": "/w/script.md", "content": "..."}}
        self.assertEqual(last(step(write))["detail"], "/w/script.md")
        self.assertIsNone(last(json.dumps({"type": "result"}), step({"type": "thinking", "thinking": "hm"})))

    @unittest.skipUnless(POSIX and shutil.which("bash") and shutil.which("jq"), "needs bash and jq")
    def test_studio_script_over_the_local_transport(self):
        cfg = make_cfg(self.tmp, "vps1")
        n = cfg.nodes["vps1"]
        root = Path(fleet.root_of(cfg, n))
        worker = root / "app" / "worker" / "fleet-worker"
        worker.parent.mkdir(parents=True)
        worker.write_text("#!/bin/bash\ncase \"$1\" in\n"
                          f"  status) echo '{json.dumps(healthy())}' ;;\n"
                          "  jobs) echo '[{\"id\": \"job-a\", \"state\": \"running\"}]' ;;\nesac\n", encoding="utf-8")
        worker.chmod(0o755)
        (root / "jobs" / "running").mkdir(parents=True)
        for job in ("job-a", "job-b"):  # job-b has no transcript yet
            (root / "jobs" / "running" / f"{job}.json").write_text("{}", encoding="utf-8")
        logs = root / "work" / "job-a" / "logs"
        logs.mkdir(parents=True)
        render = {"type": "tool_use", "name": "Bash", "input": {"command": "ffmpeg", "description": "Render the video"}}
        (logs / "transcript.jsonl").write_text(json.dumps({"type": "system"}) + "\n" + step(render) + "\n",
                                               encoding="utf-8")
        got = fleet.studio_node(cfg, n)
        self.assertTrue(got["reachable"], got)
        self.assertEqual(got["jobs"], [{"id": "job-a", "state": "running"}])
        self.assertEqual(list(got["activity"]), ["job-a"])
        act = got["activity"]["job-a"]
        self.assertEqual((act["kind"], act["name"], act["detail"]), ("tool", "Bash", "Render the video"))
        self.assertIsInstance(act["mtime"], int)

    def test_host_check(self):
        for host in ("127.0.0.1:8740", "127.0.0.1", "localhost:8740", "LOCALHOST", "[::1]:8740", "::1"):
            self.assertTrue(fleet.studio_host_ok(host, fleet.LOOPBACK_NAMES), host)
        for host in ("", "evil.example", "evil.example:8740", "127.0.0.1.evil.example", "[::1", "my-pc:8740"):
            self.assertFalse(fleet.studio_host_ok(host, fleet.LOOPBACK_NAMES), host)
        tailnet = {"100.101.102.103", "my-pc.tailnet-name.ts.net", "my-pc"}
        for host in ("my-pc:8740", "My-PC.tailnet-name.ts.net:8740", "100.101.102.103:8740"):
            self.assertTrue(fleet.studio_host_ok(host, tailnet), host)
        self.assertFalse(fleet.studio_host_ok("127.0.0.1:8740", tailnet))

    def serve(self, snapshot, media_root=None) -> int:
        files = {"/": (b"<p>page</p>", "text/html; charset=utf-8"), "/app.js": (b"go()", "text/javascript; charset=utf-8")}
        handler = fleet.studio_handler(files, {"snapshot": snapshot}, threading.Lock(), fleet.LOOPBACK_NAMES, media_root)
        srv = fleet.studio_server("127.0.0.1", 0, handler)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def get(self, port, path, method="GET", host=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            c.request(method, path, headers=dict({"Host": host} if host else {}, **(headers or {})))
            r = c.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
        finally:
            c.close()

    def test_server_answers_only_to_this_computer(self):
        snap = {"generated_at": "2026-01-01T00:00:00Z", "every": 20, "fleet_version": fleet.VERSION, "nodes": []}
        port = self.serve(snap)
        code, headers, body = self.get(port, "/")
        self.assertEqual((code, body), (200, b"<p>page</p>"))
        self.assertTrue(headers["content-type"].startswith("text/html"))
        self.assertEqual((headers["cache-control"], headers["x-content-type-options"]), ("no-store", "nosniff"))
        code, headers, body = self.get(port, "/api/studio?t=1")
        self.assertEqual((code, headers["content-type"], json.loads(body)), (200, "application/json", snap))
        self.assertEqual(self.get(port, "/", method="HEAD")[::2], (200, b""))
        code, headers, body = self.get(port, "/app.js")
        self.assertEqual((code, headers["content-type"], body), (200, "text/javascript; charset=utf-8", b"go()"))
        self.assertEqual(self.get(port, "/nope")[0], 404)
        self.assertEqual(self.get(port, "/", host=f"localhost:{port}")[0], 200)
        for host in ("evil.example", f"evil.example:{port}", f"127.0.0.1.evil.example:{port}"):
            code, _, body = self.get(port, "/api/studio", host=host)
            self.assertEqual(code, 403, host)
            self.assertNotIn(b"generated_at", body)

    def screening_lot(self):
        """A results folder as fleet pull leaves it: an index, and each job's output folder."""
        cfg = make_cfg(self.tmp, "vps1", "vps2")
        lines = []

        def job(node, jid, files, **kw):
            for name, data in files.items():
                p = cfg.results_dir / node / jid / "output" / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            lines.append(json.dumps(dict({"node": node, "id": jid, "state": "done", "channel": "Space Facts",
                                          "title": "Title of " + jid, "finished_at": "2026-01-01T00:00:00Z"}, **kw)))

        job("vps1", "job-a", {"final.mp4": b"0123456789", "thumb.png": b"png"})
        job("vps1", "job-b", {"raw take.mp4": b"x" * 50, "renders/video.mp4": b"small", "frames/f001.png": b"f"})
        job("vps2", "job-c", {"script.md": b"# no video"})
        job("vps2", "job-d", {"final.mp4": b"v"}, state="failed")
        job("vps2", "job-e", {"final.mp4": b"v"}, pull_error="timed out")
        job("vps2", "job-f", {"a.mp4": b"a", "b.webm": b"bbbb", "Cover Art.jpg": b"j", ".hidden.mp4": b"h" * 99})
        lines.insert(1, "not json")
        lines.append(lines[0])  # pulled twice: listed once
        (cfg.results_dir / "index.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return cfg

    def test_screenings_are_the_newest_videos_collected(self):
        cfg = self.screening_lot()
        got = fleet.studio_screenings(cfg)
        self.assertEqual([(s["node"], s["id"]) for s in got], [("vps1", "job-a"), ("vps2", "job-f"), ("vps1", "job-b")])
        a, f, b = got
        self.assertEqual((a["video"], a["poster"], a["bytes"], a["title"], a["channel"]),
                         ("media/vps1/job-a/final.mp4", "media/vps1/job-a/thumb.png", 10, "Title of job-a", "Space Facts"))
        self.assertEqual((f["video"], f["poster"]), ("media/vps2/job-f/b.webm", "media/vps2/job-f/Cover%20Art.jpg"))
        self.assertEqual((b["video"], b["poster"]), ("media/vps1/job-b/renders/video.mp4", None))
        self.assertEqual(len(fleet.studio_screenings(cfg, limit=1)), 1)
        self.assertEqual(fleet.studio_screenings(make_cfg(self.tmp / "none")), [])

    def test_media_serves_collected_videos_and_nothing_else(self):
        cfg = self.screening_lot()
        outside = cfg.results_dir / "secret.mp4"
        outside.write_bytes(b"secret")
        if POSIX:  # a link out of the job's folder is not followed
            (cfg.results_dir / "vps1" / "job-a" / "output" / "link.mp4").symlink_to(outside)
        port = self.serve({"nodes": []}, media_root=cfg.results_dir)
        url = "/media/vps1/job-a/final.mp4"
        code, headers, body = self.get(port, url)
        self.assertEqual((code, body, headers["content-type"], headers["accept-ranges"]), (200, b"0123456789", "video/mp4", "bytes"))
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        code, headers, body = self.get(port, url, headers={"Range": "bytes=2-5"})
        self.assertEqual((code, body, headers["content-range"]), (206, b"2345", "bytes 2-5/10"))
        self.assertEqual(self.get(port, url, headers={"Range": "bytes=7-"})[2], b"789")
        self.assertEqual(self.get(port, url, headers={"Range": "bytes=-3"})[2], b"789")
        code, headers, _ = self.get(port, url, headers={"Range": "bytes=10-"})
        self.assertEqual((code, headers["content-range"]), (416, "bytes */10"))
        self.assertEqual(self.get(port, url, headers={"Range": "lines=1-2"})[0], 416)
        self.assertEqual(self.get(port, url, method="HEAD")[::2], (200, b""))
        self.assertEqual(self.get(port, "/media/vps1/job-b/renders/video.mp4")[2], b"small")
        self.assertEqual(self.get(port, "/media/vps2/job-f/Cover%20Art.jpg")[1]["content-type"], "image/jpeg")
        for bad in ("/media/vps1/job-a/../../secret.mp4", "/media/vps1/job-a/..%2F..%2Fsecret.mp4",
                    "/media/vps1/job-a/%2e%2e/%2e%2e/secret.mp4", "/media/../secret.mp4", "/media/vps2/job-c/script.md",
                    "/media/vps1/job-a/link.mp4", "/media/vps1/job-a/missing.mp4", "/media/vps1/job-b/frames",
                    "/media/vps1/job-a/thumb.png/x.mp4", "/media/VPS1/job-a/final.mp4", "/media/vps1/.job-a/final.mp4",
                    "/media/vps2/job-f/.hidden.mp4", "/media/vps1/job-a"):
            code, _, body = self.get(port, bad)
            self.assertEqual(code, 404, bad)
            self.assertNotIn(b"secret", body)
        self.assertEqual(self.get(port, url, host="evil.example")[0], 403)
        self.assertEqual(self.get(self.serve({"nodes": []}), url)[0], 404)  # no results folder, no media

    def test_a_busy_port_is_refused(self):
        handler = fleet.studio_handler({}, {"snapshot": {}}, threading.Lock(), fleet.LOOPBACK_NAMES)
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            with self.assertRaises(OSError):
                fleet.studio_server("127.0.0.1", busy.getsockname()[1], handler).server_close()
        cfg = make_cfg(self.tmp, "vps1")
        with mock.patch.object(fleet, "studio_server", side_effect=OSError(98, "Address already in use")):
            with self.assertRaisesRegex(fleet.FleetError, "pick another with --port"):
                fleet.cmd_studio(cfg, self.args())

    def test_pages(self):
        board = fleet.STUDIO_PAGE.read_text(encoding="utf-8")
        self.assertTrue(board.startswith("<title>Hermes Fleet Studio</title>"))
        self.assertNotRegex(board, r"(?i)<!doctype|<(html|head|body)[\s>]")  # a fragment, for the preview too
        pixel = (fleet.STUDIO_DIR / "pixel.html").read_text(encoding="utf-8")
        self.assertTrue(pixel.lower().startswith("<!doctype html>"))
        shared = (fleet.STUDIO_DIR / "studio-data.js").read_text(encoding="utf-8")
        for page in (board, pixel):  # the shared script comes first, and the views link to each other
            self.assertLess(page.index('<script src="studio-data.js"></script>'), page.index("FleetStudio"))
        self.assertIn('href="pixel.html"', board)
        self.assertIn('href="index.html"', pixel)
        for control in ('id="t-auto"', 'id="t-slider"', 'id="t-lapse"', 'id="t-full"', "requestFullscreen", "wakeLock", 'id="z-in"',
                        'id="z-out"', 'id="w-season"', 'id="w-pick"', 'id="s-sound"', 'id="r-open"', 'id="r-strip"', 'id="d-watch"'):
            self.assertIn(control, pixel)  # time all day, zoom, full screen, weather, sound, replay, the screen
        for control in ('id="day-strip"', 'id="day-play"', 'id="replay-banner"', 'id="reels"'):
            self.assertIn(control, board)  # the board replays the day and has a screening room
        for part in ("function at(", "function spans(", "function strip(", "function play("):
            self.assertIn(part, shared)
        self.assertIn('fetch("api/studio"', shared)
        for text in (board, pixel, shared):
            self.assertLessEqual(set(re.findall(r"https?://([^/\"'\s?)]+)", text)),
                                 {"fonts.googleapis.com", "fonts.gstatic.com"})
        files = fleet.studio_files()
        self.assertEqual(set(files), {"/", "/index.html", "/pixel.html", "/studio-data.js"})
        page = files["/"][0].decode("utf-8")
        self.assertTrue(page.startswith("<!doctype html>") and page.rstrip().endswith("</html>"))
        self.assertNotIn("FLEET_STUDIO_LIVE = true", page)
        js, ctype = files["/studio-data.js"]
        self.assertTrue(js.startswith(b"window.FLEET_STUDIO_LIVE = true;\n") and ctype.startswith("text/javascript"))
        self.assertEqual(files["/pixel.html"][0], pixel.encode("utf-8"))

    def args(self, **kw):
        return argparse.Namespace(**dict(dict(port=8740, tailnet=False, every=20, no_browser=True, json=False), **kw))

    def test_every_has_a_floor_and_json_prints_one_look(self):
        cfg = make_cfg(self.tmp, "vps1")
        with self.assertRaisesRegex(fleet.FleetError, "at least 5"):
            fleet.cmd_studio(cfg, self.args(every=4))
        snap = {"generated_at": "x", "every": 30, "fleet_version": fleet.VERSION, "nodes": []}
        with mock.patch.object(fleet, "studio_snapshot", return_value=snap) as look:
            rc, out, _ = quietly(fleet.cmd_studio, cfg, self.args(every=30, json=True))
        self.assertEqual((rc, json.loads(out)), (0, snap))
        look.assert_called_once_with(cfg, 30)

    def run_studio(self, cfg, **kw):
        looked, made, browser = threading.Event(), [], mock.Mock()

        def server(host, port, handler):
            made.append(FakeStudioServer(host, port, handler, looked))
            return made[-1]

        def snapshot(cfg_, every):
            looked.set()
            return {"generated_at": "x", "every": every, "fleet_version": fleet.VERSION, "nodes": []}

        with mock.patch.object(fleet, "studio_server", side_effect=server), \
                mock.patch.object(fleet, "studio_snapshot", side_effect=snapshot), \
                mock.patch.object(fleet, "studio_handler", wraps=fleet.studio_handler) as handler, \
                mock.patch.object(fleet.threading, "Timer", FakeTimer), mock.patch("webbrowser.open", browser):
            rc, out, _ = quietly(fleet.cmd_studio, cfg, self.args(**kw))
        self.assertTrue(looked.is_set())
        return rc, out, made[0], handler.call_args.args[3], browser

    def test_serves_this_computer_only_by_default(self):
        rc, out, srv, allowed, browser = self.run_studio(make_cfg(self.tmp, "vps1", "vps2"))
        self.assertEqual((rc, srv.server_address, allowed), (0, ("127.0.0.1", 8740), fleet.LOOPBACK_NAMES))
        self.assertIn("Fleet studio: http://127.0.0.1:8740/  (pixel lot: http://127.0.0.1:8740/pixel.html)", out)
        self.assertIn("only watches", out)
        self.assertIn("Fleet studio stopped.", out)
        self.assertTrue(srv.closed)
        browser.assert_not_called()

    def test_tailnet_serves_the_tailscale_address(self):
        me = ("100.101.102.103", "my-pc.tailnet-name.ts.net")
        with mock.patch.object(fleet, "tailscale_self", return_value=me):
            rc, out, srv, allowed, browser = self.run_studio(make_cfg(self.tmp, "vps1"), tailnet=True, port=9000,
                                                             no_browser=False)
        self.assertEqual((rc, srv.server_address), (0, ("100.101.102.103", 9000)))
        self.assertEqual(allowed, {"100.101.102.103", "my-pc.tailnet-name.ts.net", "my-pc"})
        self.assertIn("Fleet studio: http://my-pc.tailnet-name.ts.net:9000/", out)
        browser.assert_called_once_with("http://my-pc.tailnet-name.ts.net:9000/")

    def test_tailscale_self(self):
        status = {"Self": {"TailscaleIPs": ["fd7a:115c:a1e0::1", "100.101.102.103"],
                           "DNSName": "My-PC.tailnet-name.ts.net."}}
        with mock.patch.object(fleet, "tailscale_binary", return_value="tailscale"):
            with mock.patch.object(fleet.subprocess, "run", return_value=ran(0, json.dumps(status).encode())):
                self.assertEqual(fleet.tailscale_self(), ("100.101.102.103", "my-pc.tailnet-name.ts.net"))
            with mock.patch.object(fleet.subprocess, "run", return_value=ran(0, b'{"Self": {"TailscaleIPs": []}}')):
                with self.assertRaisesRegex(fleet.FleetError, "not connected"):
                    fleet.tailscale_self()
        with mock.patch.object(fleet, "tailscale_binary", return_value=None):
            with self.assertRaisesRegex(fleet.FleetError, "not installed"):
                fleet.tailscale_self()


# --------------------------------------------------------------------------- video check and report

def load_checker():
    path = REPO / "vps" / "worker" / "fleet-check"
    loader = importlib.machinery.SourceFileLoader("fleet_check", str(path))
    spec = importlib.util.spec_from_loader("fleet_check", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


checker = load_checker()


class VideoCheckTest(TempDirTest):
    """vps/worker/fleet-check, the check each VPS runs on a finished job's video."""

    def workspace(self, job=None, files=()):
        ws = self.tmp / f"ws{len(list(self.tmp.iterdir()))}"
        (ws / "output").mkdir(parents=True)
        (ws / "job.json").write_text(json.dumps(job or {}), encoding="utf-8")
        for name in files:
            (ws / "output" / name).parent.mkdir(parents=True, exist_ok=True)
            (ws / "output" / name).write_bytes(b"x" * 10)
        return ws

    def test_tags_are_counted_the_way_youtube_does(self):
        self.assertEqual(checker.tags_length(["a", "b c"]), 1 + 5 + 1)
        self.assertEqual(checker.tags_length([]), 0)

    def test_metadata(self):
        out = self.workspace() / "output"
        self.assertIn("missing", checker.metadata_problems(out)[1][0])
        (out / "metadata.json").write_text("{not json", encoding="utf-8")
        self.assertIn("not valid JSON", checker.metadata_problems(out)[1][0])
        (out / "metadata.json").write_text(json.dumps({"title": "x" * 101, "description": "a <b>", "tags": "a,b"}),
                                           encoding="utf-8")
        probs = " | ".join(checker.metadata_problems(out)[1])
        for words in ("101 characters", "description has a <", "list of words"):
            self.assertIn(words, probs)
        (out / "metadata.json").write_text(json.dumps({"title": "Fine", "tags": ["t"] * 300}), encoding="utf-8")
        self.assertIn("tags add up to 599", checker.metadata_problems(out)[1][0])
        (out / "metadata.json").write_text(json.dumps({"title": "Fine", "description": "ok", "tags": ["a"]}),
                                           encoding="utf-8")
        self.assertEqual(checker.metadata_problems(out)[1], [])

    def test_which_video(self):
        ws = self.workspace(files=("clip.mp4", "parts/part1.mp4", "final cut.mov"))
        (ws / "output" / "parts" / "part1.mp4").write_bytes(b"x" * 1000)
        self.assertEqual(checker.find_video(ws, None).name, "final cut.mov")  # named final beats bigger
        (ws / "output" / "video.mp4").write_bytes(b"x")
        self.assertEqual(checker.find_video(ws, None).name, "video.mp4")
        self.assertEqual(checker.find_video(ws, "output/clip.mp4").name, "clip.mp4")
        self.assertIsNone(checker.find_video(ws, "../outside.mp4"))
        self.assertEqual(checker.find_video(ws, 5).name, "video.mp4")  # not a name: chosen as usual
        self.assertIsNone(checker.find_video(ws / "nothing", None))

    def test_without_ffprobe_the_check_is_skipped(self):
        ws = self.workspace(files=("video.mp4",))
        with mock.patch.object(checker, "run", return_value=(127, "", "[Errno 2] No such file or directory")):
            v = checker.check(ws)
        self.assertIsNone(v["ok"])
        self.assertIn("ffprobe is not installed", v["skipped"])

    def test_turned_off_and_settings(self):
        self.assertEqual(checker.check(self.workspace({"checks": False}))["skipped"], "this job turns the check off")
        info = {"format": {"duration": "30.5", "size": "48000000"},
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30000/1001",
                             "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "aac"}]}
        ws = self.workspace({"checks": {"min_seconds": "45", "width": 1080, "height": "1920", "max_megabytes": 40,
                                        "thumbnail": False, "metadata": False}}, files=("video.mp4",))
        with mock.patch.object(checker, "probe", return_value=(info, None)), \
                mock.patch.object(checker, "black_keyframes", return_value=(0, 10)), \
                mock.patch.object(checker, "loudest_db", return_value=-3.0):
            v = checker.check(ws)
        self.assertFalse(v["ok"])
        self.assertEqual(v["facts"]["fps"], 29.97)
        self.assertEqual(v["problems"], ["it is 30 seconds long; this job wants at least 45",
                                         "the file is 48 MB; this job wants at most 40 MB",
                                         "it is 1920x1080; this job wants 1080x1920"])

    def test_a_phone_video_on_its_side_counts_as_upright(self):
        info = {"format": {"duration": "10"}, "streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                                                            "side_data_list": [{"rotation": -90}]}]}
        self.assertEqual(checker.picture(info)[2]["width"], 1080)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg")
    def test_real_videos(self):
        ws = self.workspace({"checks": {"vertical": True}})
        out = ws / "output"

        def ff(*args):
            subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, stdin=subprocess.DEVNULL)
        ff("-f", "lavfi", "-i", "testsrc2=s=180x320:r=10:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2",
           "-shortest", "-pix_fmt", "yuv420p", str(out / "video.mp4"))
        ff("-f", "lavfi", "-i", "testsrc2=s=1280x720:d=1", "-frames:v", "1", str(out / "thumbnail.png"))
        (out / "metadata.json").write_text(json.dumps({"title": "A test"}), encoding="utf-8")
        v = checker.check(ws)
        self.assertTrue(v["ok"], v)
        self.assertEqual((v["facts"]["width"], v["facts"]["height"]), (180, 320))
        ff("-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=2", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
           "-t", "2", "-pix_fmt", "yuv420p", str(out / "video.mp4"))
        probs = " | ".join(checker.check(ws)["problems"])
        for words in ("not vertical", "picture is black", "sound is silent"):
            self.assertIn(words, probs)
        r = subprocess.run([sys.executable, str(REPO / "vps" / "worker" / "fleet-check"), str(ws)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(json.loads(r.stdout)["ok"])


class ReportTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.cfg = make_cfg(self.tmp, "vps1", "vps2")
        self.cfg.nodes["vps1"].channels = "Space Facts"
        self.cfg.path.write_text("", encoding="utf-8")

    def test_check_words(self):
        self.assertEqual(fleet.check_line(None), "")
        self.assertEqual(fleet.check_line({"ok": True}), "video ok")
        self.assertEqual(fleet.check_line({"ok": False, "problems": ["a", "b"]}), "CHECK: a (+1 more)")
        self.assertEqual(fleet.check_line({"ok": None, "skipped": "off"}), "not checked: off")
        lines = fleet.describe_check({"ok": False, "problems": ["no sound"], "video": "output/video.mp4",
                                      "facts": {"seconds": 52.4, "width": 1080, "height": 1920, "fps": 30.0,
                                                "megabytes": 21.5, "video_codec": "h264", "title": "T"}})
        self.assertEqual(lines[:2], ["1 problem(s):", "  - no sound"])
        self.assertIn("output/video.mp4: 52 s, 1080x1920, 30 fps, 21.5 MB, h264", lines[2])
        self.assertIn("  title: T", lines)

    def report(self, jobs, statuses=None, silent=()):
        st = statuses or {"vps1": healthy(), "vps2": healthy()}
        with mock.patch.object(fleet, "parallel", return_value=st), \
                mock.patch.object(fleet, "fetch_jobs", return_value=(jobs, list(silent))):
            return fleet.report_data(self.cfg, 24)

    def test_report(self):
        now = fleet.now_iso()
        jobs = [{"node": "vps1", "id": "a", "state": "done", "finished_at": now, "title": "Saturn",
                 "check": {"ok": False, "problems": ["the sound is silent"]}},
                {"node": "vps1", "id": "b", "state": "done", "finished_at": now, "check": {"ok": True}},
                {"node": "vps1", "id": "old", "state": "failed", "finished_at": "2020-01-01T00:00:00Z"},
                {"node": "vps2", "id": "c", "state": "failed", "finished_at": now, "reason": "provider exited 1"},
                {"node": "vps2", "id": "q", "state": "inbox"}]
        d = self.report(jobs, {"vps1": healthy(), "vps2": healthy(paused=True)})
        self.assertEqual([(n["node"], n["made"], n["made_ok"], n["failed"], n["queued"]) for n in d["nodes"]],
                         [("vps1", 2, 1, 0, 0), ("vps2", 0, 0, 1, 1)])
        out = fleet.report_text(d)
        self.assertIn("vps1 (Space Facts): 2 video(s) made", out)
        self.assertIn("vps2 (any channel): 0 video(s) made, 1 failed, 1 queued", out)
        self.assertIn('- vps1 "Saturn" (a): the sound is silent. Again: fleet retry vps1 a', out)
        self.assertIn("- vps2 c: provider exited 1. Again: fleet retry vps2 c", out)
        self.assertIn("Needs you:\n- vps2: paused", out)
        self.assertNotIn("old", out)

    def test_quiet_day_and_a_silent_vps(self):
        out = fleet.report_text(self.report([], silent=["vps2"]))
        self.assertIn("vps2 (any channel): did not answer", out)
        self.assertTrue(out.endswith("Nothing needs you."))


# --------------------------------------------------------------------------- week plan

class PlanTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.cfg = make_cfg(self.tmp, "vps1", "vps2")
        self.cfg.nodes["vps1"].channels = "Space Facts"
        self.cfg.nodes["vps2"].channels = "History"
        self.cfg.path.write_text("", encoding="utf-8")
        self.today = fleet.datetime.now().date()

    def plan(self, *specs, action="show", **kw):
        base = dict(action=action, args=list(specs), week=None, status=None, channel=None, day=None, time=None,
                    title=None, brief=None, quiet=False, dry_run=False, json=False)
        base.update(kw)
        return quietly(fleet.cmd_plan, self.cfg, argparse.Namespace(**base))

    def items(self):
        return fleet.load_plan(self.cfg)["items"]

    def day(self, n):
        return (self.today + fleet.timedelta(days=n)).isoformat()

    def test_numbers(self):
        plan = {"items": [{"id": 3, "status": "draft"}, {"id": 4, "status": "approved"}, {"id": 5, "status": "draft"}]}
        self.assertEqual(fleet.plan_ids(["1-3", "#7,9", "all"], plan), [1, 2, 3, 7, 9, 5])
        with self.assertRaisesRegex(fleet.FleetError, "not a plan number"):
            fleet.plan_ids(["three"], plan)
        self.assertEqual(fleet.compact_ids([{"id": k} for k in (7, 3, 4, 5, 9, 10)]), "3-5,7,9-10")

    def test_week_range(self):
        lo, hi = fleet.week_range("next")
        self.assertEqual((lo.weekday(), (hi - lo).days), (0, 6))
        self.assertGreater(lo, self.today)
        lo, hi = fleet.week_range("this")
        self.assertEqual((lo, hi.weekday()), (self.today, 6))

    def test_slots_follow_each_channels_days(self):
        chans = self.tmp / "channels"
        chans.mkdir()
        (chans / "history.json").write_text(json.dumps({"channel": "History", "prompt": "x",
                                                         "plan": {"days": ["mon", "Thursday"], "time": "07:30"}}),
                                            encoding="utf-8")
        rc, out, _ = self.plan(action="slots", week="next", json=True)
        slots = json.loads(out)
        self.assertEqual(len([s for s in slots if s["channel"] == "Space Facts"]), 7)
        self.assertEqual([(s["weekday"], s["time"]) for s in slots if s["channel"] == "History"],
                         [("Mon", "07:30"), ("Thu", "07:30")])

    def test_import_approve_and_run(self):
        src = self.tmp / "next.json"
        src.write_text(json.dumps([
            {"channel": "space facts", "day": self.day(0), "time": "00:00", "title": "Saturn", "brief": "rings"},
            {"channel": "History", "day": self.day(1), "title": "Printing", "brief": "Gutenberg"}]), encoding="utf-8")
        rc, out, _ = self.plan(str(src), action="import")
        self.assertEqual(rc, 0)
        self.assertIn("2 topic(s) wait for the owner's yes: fleet plan approve 1-2", out)
        self.assertEqual([(i["id"], i["channel"], i["status"], i["time"]) for i in self.items()],
                         [(1, "Space Facts", "draft", "00:00"), (2, "History", "draft", "09:00")])
        self.assertIn("already planned as #1", self.plan(str(src), action="import")[1])  # importing again adds nothing
        self.assertEqual(len(self.items()), 2)
        sent = []

        def dispatch(cfg, jobs, spec, dry_run, as_json):
            sent.extend(jobs)
            print(json.dumps([{"node": "vps1", "id": j["id"], "channel": j["channel"]} for j in jobs]))
            return 0
        with mock.patch.object(fleet, "dispatch_jobs", dispatch):
            self.assertIn("nothing is due yet", self.plan(action="run")[1])  # drafts are never queued
            self.assertIn("approved #1", self.plan("all", action="approve")[1])
            rc, out, _ = self.plan(action="run", quiet=True)
        self.assertEqual(rc, 0)
        self.assertEqual([j["title"] for j in sent], ["Saturn"])  # #2 waits for its day
        job = sent[0]
        self.assertEqual((job["channel"], job["plan_id"]), ("Space Facts", 1))
        self.assertIn('"Saturn"', job["prompt"])
        topic = {f["path"]: f["content"] for f in job["files"]}["topic.md"]
        self.assertIn("# Saturn", topic)
        self.assertIn("rings", topic)
        self.assertIn("queued #1 ", out)
        done = {i["id"]: i for i in self.items()}
        self.assertEqual((done[1]["status"], done[1]["node"], done[1]["job_id"]), ("queued", "vps1", job["id"]))
        self.assertEqual(done[2]["status"], "approved")
        with mock.patch.object(fleet, "dispatch_jobs", dispatch):
            self.assertEqual(self.plan(action="run", quiet=True)[1], "")  # nothing new: a quiet run prints nothing
        self.assertIn("already queued", self.plan("1", action="reject")[1])

    def test_a_run_that_stopped_half_way_does_not_queue_twice(self):
        fleet.save_plan(self.cfg, {"next_id": 2, "items": [
            {"id": 1, "channel": "History", "day": self.day(0), "time": "00:00", "title": "T", "status": "approved",
             "job_id": "20260101-000000-history-abcde"}]})

        def dispatch(cfg, jobs, spec, dry_run, as_json):
            print(f"fleet: vps2: could not queue {jobs[0]['id']}: job id {jobs[0]['id']} already exists on vps2",
                  file=sys.stderr)
            print("[]")
            return 1
        with mock.patch.object(fleet, "dispatch_jobs", dispatch):
            self.plan(action="run")
        self.assertEqual((self.items()[0]["status"], self.items()[0]["node"]), ("queued", "vps2"))

    def test_a_vps_that_cannot_take_it_is_tried_again(self):
        fleet.save_plan(self.cfg, {"next_id": 2, "items": [
            {"id": 1, "channel": "History", "day": self.day(0), "time": "00:00", "title": "T", "status": "approved"}]})

        def dispatch(cfg, jobs, spec, dry_run, as_json):
            print(f"fleet: {jobs[0]['id']}: channel 'History' is made on vps2, and no VPS can take a claude job",
                  file=sys.stderr)
            print("[]")
            return 1
        with mock.patch.object(fleet, "dispatch_jobs", dispatch):
            out = self.plan(action="run", quiet=True)[1]
            self.assertIn("NOT QUEUED #1", out)
            self.assertEqual(self.plan(action="run", quiet=True)[1], "")  # not every hour
        item = self.items()[0]
        self.assertEqual((item["status"], item["tries"]), ("approved", 2))
        self.assertIn("no VPS can take", item["error"])
        d = mock.patch.object(fleet, "parallel", return_value={"vps1": healthy(), "vps2": healthy()})
        with d, mock.patch.object(fleet, "fetch_jobs", return_value=([], [])):
            self.assertIn("Week plan: #1 ", fleet.report_text(fleet.report_data(self.cfg, 24)))

    def test_channel_job_file_and_placeholders(self):
        chans = self.tmp / "channels"
        chans.mkdir()
        (chans / "space-facts.json").write_text(json.dumps({
            "prompt": "Make {title} for {channel} on {day}. {brief}", "checks": {"vertical": True},
            "files": [{"path": "brief.md", "content": "Topic: {title} {unknown}"}],
            "plan": {"days": "weekdays"}, "max_turns": 50}), encoding="utf-8")
        item = {"id": 7, "channel": "Space Facts", "day": "2026-12-01", "title": "Rings {brief}", "brief": "B"}
        job = fleet.plan_job(self.cfg, item)
        self.assertEqual(job["prompt"], "Make Rings {brief} for Space Facts on 2026-12-01. B")  # one pass only
        self.assertEqual(job["checks"], {"vertical": True})
        self.assertEqual(job["max_turns"], 50)
        self.assertNotIn("plan", job)
        files = {f["path"]: f["content"] for f in job["files"]}
        self.assertEqual(files["brief.md"], "Topic: Rings {brief} {unknown}")
        self.assertIn("topic.md", files)
        (chans / "space-facts.json").write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(fleet.FleetError, "space-facts.json"):
            fleet.plan_job(self.cfg, item)
        # a file with only the days and time still gets the full default prompt
        (chans / "space-facts.json").write_text(json.dumps({"plan": {"days": "mon", "time": "07:30"}}), encoding="utf-8")
        job = fleet.plan_job(self.cfg, item)
        self.assertIn("Make one video for the channel \"Space Facts\"", job["prompt"])
        self.assertIn("metadata.json", job["prompt"])
        self.assertEqual(job["timeout_minutes"], 180)

    def test_checks_on_what_hermes_sends(self):
        def bad(raw, words):
            with self.assertRaisesRegex(fleet.FleetError, words):
                fleet.plan_item(self.cfg, raw, "item")
        bad({"channel": "Cooking", "day": self.day(1), "title": "x"}, "no VPS makes videos for channel 'Cooking'")
        bad({"channel": "History", "day": "tomorrow", "title": "x"}, "must be a date")
        bad({"channel": "History", "day": self.day(-1), "title": "x"}, "in the past")
        bad({"channel": "History", "day": self.day(1), "time": "9am", "title": "x"}, "HH:MM")
        bad({"channel": "History", "day": self.day(1), "title": ""}, "title")
        bad(["History"], "an object")
        rc, out, _ = self.plan(action="add", channel="History", day=self.day(2), title="Rome", brief="")
        self.assertIn("added #1", out)
        self.assertIn("changed #1", self.plan("1", action="edit", title="Rome, briefly")[1])
        self.assertEqual(self.items()[0]["title"], "Rome, briefly")
        self.assertIn("removed #1", self.plan("1", action="remove")[1])
        self.assertEqual(self.items(), [])

    def test_the_lock(self):
        lock = self.tmp / "plan.lock"
        with fleet.plan_locked(self.cfg):
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())
        lock.write_text("", encoding="utf-8")
        os.utime(lock, (1, 1))  # left behind long ago by a crash
        with fleet.plan_locked(self.cfg):
            pass
        self.assertFalse(lock.exists())


# --------------------------------------------------------------------------- ideas

class IdeasTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.cfg = make_cfg(self.tmp, "vps1")
        self.cfg.path.write_text("", encoding="utf-8")

    def ideas(self, action="list", *args, **kw):
        base = dict(action=action, args=list(args), note=None, title=None, status=None, at=None, to=None, json=False)
        base.update(kw)
        return quietly(fleet.cmd_ideas, self.cfg, argparse.Namespace(**base))

    def keep(self, *titles):
        fleet.ideas_file(self.cfg).write_text(json.dumps({"version": 1, "ideas": [{"title": t} for t in titles]}),
                                              encoding="utf-8")

    def titles(self):
        return [i["title"] for i in fleet.load_ideas(self.cfg)["ideas"]]

    def test_the_starter_list_until_the_owner_changes_it(self):
        rc, out, _ = self.ideas()
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("1. Trend looker\n   A zeppelin over the lot"), out)
        self.assertIn("These are the starter ideas", out)
        self.assertFalse(fleet.ideas_file(self.cfg).exists())  # looking writes nothing
        rc, out, _ = self.ideas("add", "Weekly", "summary", note=" On Sundays: what was made. ")
        self.assertEqual(out, f"added {len(fleet.STARTER_IDEAS) + 1}. Weekly summary\n")
        d = json.loads(fleet.ideas_file(self.cfg).read_text(encoding="utf-8"))
        self.assertNotIn("starter", d)
        self.assertEqual(d["ideas"][0]["title"], "Trend looker")
        self.assertEqual(d["ideas"][-1], {"title": "Weekly summary", "note": "On Sundays: what was made.", "status": "idea",
                                          "added": fleet.datetime.now().date().isoformat()})
        self.assertNotIn("starter ideas", self.ideas()[1])
        self.assertFalse(fleet.ideas_file(self.cfg).with_name("ideas.lock").exists())

    def test_add_edit_move_and_remove(self):
        self.keep(*"ABCD")
        self.assertEqual(self.ideas("add", "E", at=1)[1], "added 1. E\n")
        self.assertEqual(self.ideas("move", "5", to="2")[1], "moved D from 5 to 2\n")
        self.assertEqual(self.ideas("move", "#1", "3")[1], "moved E from 1 to 3\n")  # `move 1 3` works too
        self.assertEqual(self.titles(), list("DAEBC"))
        self.assertEqual(self.ideas("edit", "1", status="built")[1], "changed 5. D [built]\n")  # built: to the end
        self.assertEqual(self.titles(), list("AEBCD"))
        self.assertEqual(self.ideas("edit", "2", title=" E  two ", note="  why  ", status="next")[1], "changed 2. E two [next]\n")
        i = fleet.load_ideas(self.cfg)["ideas"][1]
        self.assertEqual((i["title"], i["note"], i["status"]), ("E two", "why", "next"))
        self.assertEqual(self.ideas("remove", "1,3", "1")[1], "removed 1. A\nremoved 3. B\n")
        got = json.loads(self.ideas(json=True)[1])
        self.assertEqual([(i["n"], i["title"], i["status"]) for i in got], [(1, "E two", "next"), (2, "C", "idea"), (3, "D", "built")])
        with self.assertRaises(fleet.FleetError):
            self.ideas("remove", "1", "9")  # one wrong number: nothing goes
        self.assertEqual(len(self.titles()), 3)

    def test_mistakes(self):
        self.keep("A")
        for args, kw, msg in [(("add",), {}, "needs a title"), (("add", "x" * 81), {}, "keep the title short"),
                              (("add", "x"), {"note": "y" * 1001}, "1000 at most"), (("add", "x"), {"at": 3}, "--at must be 1 to 2"),
                              (("edit", "1"), {}, "say what changes"), (("edit", "2"), {"title": "x"}, "not an idea number"),
                              (("move", "1"), {}, "usage: fleet ideas move"), (("remove",), {}, "name the idea numbers"),
                              (("remove", "1-3"), {}, "not an idea number")]:
            with self.subTest(args=args), self.assertRaisesRegex(fleet.FleetError, msg):
                self.ideas(*args, **kw)
        self.keep()
        with self.assertRaisesRegex(fleet.FleetError, "the ideas list is empty"):
            self.ideas("remove", "1")
        self.assertEqual(self.ideas()[1], 'no ideas yet: fleet ideas add "Title" --note "what it does"\n')

    def test_a_broken_file_is_named_and_the_studio_says_so(self):
        fleet.ideas_file(self.cfg).write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(fleet.FleetError, "ideas.json cannot be read"):
            fleet.load_ideas(self.cfg)
        got = fleet.studio_ideas(self.cfg)
        self.assertEqual(got["ideas"], [])
        self.assertIn("ideas.json cannot be read", got["ideas_error"])
        fleet.ideas_file(self.cfg).write_text(json.dumps({"ideas": [{"title": "A", "status": "weird"}, {"note": "no title"}, 3]}),
                                              encoding="utf-8")
        self.assertEqual(fleet.studio_ideas(self.cfg), {"ideas": [{"title": "A", "note": "", "status": "idea"}],
                                                       "ideas_starter": False})

    def test_the_example_lot_has_the_same_starter_ideas(self):
        js = (REPO / "home" / "studio" / "studio-data.js").read_text(encoding="utf-8")
        for title, note in fleet.STARTER_IDEAS:
            self.assertIn(f"{{ title: {json.dumps(title)}, note: {json.dumps(note)}, status: \"idea\" }}", js)
        self.assertEqual(js.count('status: "idea" }'), len(fleet.STARTER_IDEAS))

    def test_command_line(self):
        a = fleet.parse_cli(["ideas"])
        self.assertEqual((a.action, a.args), ("list", []))
        a = fleet.parse_cli(["ideas", "add", "Trend", "looker", "--note", "A zeppelin", "--at", "1"])
        self.assertEqual((a.action, a.args, a.note, a.at), ("add", ["Trend", "looker"], "A zeppelin", 1))
        a = fleet.parse_cli(["ideas", "move", "3", "--to", "1"])
        self.assertEqual((a.args, a.to), (["3"], "1"))
        self.assertEqual(fleet.parse_cli(["ideas", "edit", "2", "--status", "built"]).status, "built")


# --------------------------------------------------------------------------- publishing

class FakePlatforms:
    """One local server that answers like Google, YouTube, TikTok and Instagram do
    (the CLI talks to it through FLEET_PUBLISH_FAKE_API)."""

    def __init__(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import parse_qs, urlparse
        self.calls, self.ig_status, self.got = [], ["IN_PROGRESS", "FINISHED"], {"yt": 0, "tt": 0}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, code, obj=None, headers=None):
                body = json.dumps({} if obj is None else obj).encode()
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.route("GET")

            def do_POST(self):
                self.route("POST")

            def do_PUT(self):
                self.route("PUT")

            def route(self, method):
                u = urlparse(self.path)
                size = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(size) if size else b""
                form = {k: v[0] for k, v in parse_qs(data.decode("latin-1")).items()} \
                    if "form-urlencoded" in (self.headers.get("Content-Type") or "") else {}
                fake.calls.append({"method": method, "path": u.path, "query": parse_qs(u.query), "form": form,
                                   "headers": dict(self.headers), "data": data})
                rng = re.match(r"bytes (\d+)-(\d+)/(\d+)", self.headers.get("Content-Range") or "")
                p = u.path
                if p == "/google_token":
                    tok = {"access_token": "g-" + form.get("grant_type", "?"), "expires_in": 3599}
                    if form.get("grant_type") == "authorization_code":
                        tok["refresh_token"] = "google-refresh"
                    return self.answer(200, tok)
                if p == "/youtube_upload/videos":
                    return self.answer(200, headers={"Location": fake.base + "/yt-session"})
                if p == "/yt-session":
                    first, last, total = map(int, rng.groups())
                    fake.got["yt"] += last - first + 1
                    if last + 1 < total:
                        return self.answer(308, headers={"Range": f"bytes=0-{last}"})
                    return self.answer(200, {"id": "vid123"})
                if p == "/youtube_upload/thumbnails/set":
                    return self.answer(200, {"items": []})
                if p == "/tiktok_api/oauth/token/":
                    return self.answer(200, {"access_token": "tt-" + form.get("grant_type", "?"), "expires_in": 86400,
                                             "refresh_token": "tiktok-refresh-2", "refresh_expires_in": 31536000,
                                             "open_id": "open-1", "scope": "user.info.basic,video.upload"})
                if p == "/tiktok_api/post/publish/inbox/video/init/":
                    return self.answer(200, {"data": {"publish_id": "pub-1", "upload_url": fake.base + "/tt-upload"},
                                             "error": {"code": "ok", "message": ""}})
                if p == "/tt-upload":
                    first, last, total = map(int, rng.groups())
                    fake.got["tt"] += len(data)
                    return self.answer(201 if last + 1 == total else 206)
                if p == "/tiktok_api/post/publish/status/fetch/":
                    return self.answer(200, {"data": {"status": "SEND_TO_USER_INBOX"}, "error": {"code": "ok"}})
                if p == "/instagram_api/me":
                    return self.answer(200, {"user_id": "1789", "username": "spacefacts"})
                if p == "/instagram_api/1789/media":
                    return self.answer(200, {"id": "container-1"})
                if p == "/instagram_api/container-1":
                    return self.answer(200, {"status_code": fake.ig_status.pop(0)})
                if p == "/instagram_api/1789/media_publish":
                    return self.answer(200, {"id": "media-1"})
                if p == "/instagram_root/refresh_access_token":
                    return self.answer(200, {"access_token": "ig-renewed", "expires_in": 5184000})
                return self.answer(404, {"error": {"message": f"no route {method} {p}"}})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def paths(self, method=None):
        return [c["path"] for c in self.calls if method in (None, c["method"])]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PublishTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.fake = FakePlatforms()
        self.addCleanup(self.fake.close)
        env = mock.patch.dict(os.environ, {"FLEET_PUBLISH_FAKE_API": self.fake.base, "FLEET_PUBLISH_POLL_SECONDS": "0",
                                           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = make_cfg(self.tmp, "vps1")
        self.cfg.nodes["vps1"].channels = "Space Facts"
        self.cfg.path.write_text("", encoding="utf-8")
        self.pub = self.cfg.secrets_dir / "publish"
        self.pub.mkdir(parents=True)
        self.browser_saw = []

    def args(self, **kw):
        base = dict(node=None, job_id=None, to=None, at=None, now=False, video_url=None, channel=None, anyway=False,
                    dry_run=False, json=False, login=None, made_for_kids=None, no_ai_label=False, ig_user_id=None,
                    port=0, accounts=False)
        base.update(kw)
        return argparse.Namespace(**base)

    def browser(self, url):
        """Stands in for the owner's browser: it signs in and goes back to the CLI."""
        from urllib.parse import parse_qs, urlparse
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.browser_saw.append(q)
        back = f"{q['redirect_uri']}?code=the-code&state={q['state']}"
        threading.Thread(target=lambda: urllib_get(back), daemon=True).start()
        return True

    def login(self, platform, **kw):
        with mock.patch("webbrowser.open", side_effect=self.browser):
            return quietly(fleet.cmd_publish, self.cfg, self.args(login=platform, channel="space facts", **kw))

    def job(self, size=600_000, check=True, jid="20261124-090000-space-facts-abcde"):
        d = self.cfg.results_dir / "vps1" / jid
        (d / "output").mkdir(parents=True)
        (d / "logs").mkdir()
        (d / "output" / "video.mp4").write_bytes(os.urandom(size))
        (d / "output" / "thumbnail.png").write_bytes(b"\x89PNG fake")
        (d / "output" / "metadata.json").write_text(json.dumps({
            "title": "Five facts about Saturn", "description": "Rings.", "tags": ["space", "saturn rings"]}),
            encoding="utf-8")
        (d / "job.json").write_text(json.dumps({"channel": "Space Facts"}), encoding="utf-8")
        verdict = {"ok": True, "problems": [], "video": "output/video.mp4"} if check else \
            {"ok": False, "problems": ["the sound is silent"], "video": "output/video.mp4"}
        (d / "logs" / "check.json").write_text(json.dumps(verdict), encoding="utf-8")
        return jid, d

    def test_youtube_sign_in_and_private_draft(self):
        with self.assertRaisesRegex(fleet.FleetError, "no Google app yet"):
            self.login("youtube", made_for_kids="no")  # the owner's own OAuth client comes first
        (self.pub / "youtube-client.json").write_text(json.dumps(
            {"installed": {"client_id": "cid", "client_secret": "csecret"}}), encoding="utf-8")
        rc, out, err = self.login("youtube", made_for_kids="no")
        self.assertEqual(rc, 0, err)
        q = self.browser_saw[-1]
        self.assertEqual((q["scope"], q["code_challenge_method"], q["access_type"]), (fleet.YOUTUBE_SCOPE, "S256", "offline"))
        self.assertTrue(q["redirect_uri"].startswith("http://127.0.0.1:"))
        token_call = [c for c in self.fake.calls if c["path"] == "/google_token"][-1]["form"]
        self.assertEqual(len(token_call["code_verifier"]), 64)
        acct_file = self.pub / "youtube-space-facts.json"
        acct = json.loads(acct_file.read_text(encoding="utf-8"))
        self.assertEqual((acct["refresh_token"], acct["made_for_kids"], acct["synthetic_media"], acct["channel"]),
                         ("google-refresh", False, True, "Space Facts"))
        if POSIX:
            self.assertEqual(acct_file.stat().st_mode & 0o777, 0o600)
        jid, d = self.job()
        acct["expires_at"] = 0  # an old access token: it is renewed first
        acct_file.write_text(json.dumps(acct), encoding="utf-8")
        with mock.patch.object(fleet, "YOUTUBE_CHUNK", 256 * 1024):
            rc, out, err = quietly(fleet.cmd_publish, self.cfg, self.args(node="vps1", job_id=jid, to="youtube"))
        self.assertEqual(rc, 0, err)
        self.assertIn("uploaded as a private draft, it stays private until you publish it", out)
        self.assertIn("https://studio.youtube.com/video/vid123/edit (thumbnail set)", out)
        insert = next(c for c in self.fake.calls if c["path"] == "/youtube_upload/videos")
        meta = json.loads(insert["data"])
        self.assertEqual(meta["status"], {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                                          "containsSyntheticMedia": True})
        self.assertEqual(meta["snippet"]["tags"], ["space", "saturn rings"])
        self.assertEqual(insert["headers"]["Authorization"], "Bearer g-refresh_token")
        self.assertEqual(self.fake.paths("PUT"), ["/yt-session"] * 3)
        self.assertEqual(self.fake.got["yt"], 600_000)
        self.assertEqual(json.loads((d / "publish.json").read_text(encoding="utf-8"))["youtube"]["video_id"], "vid123")
        log = [json.loads(x) for x in (self.cfg.results_dir / "publish.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((log[-1]["platform"], log[-1]["id"]), ("youtube", jid))
        self.assertEqual(fleet.publish_summary(self.cfg, 0), {"youtube": 1})

    def test_youtube_goes_public_only_at_the_time_asked(self):
        (self.pub / "youtube-client.json").write_text(json.dumps({"installed": {"client_id": "c", "client_secret": "s"}}),
                                                      encoding="utf-8")
        self.login("youtube", made_for_kids="yes")
        jid, _ = self.job()
        when = (fleet.datetime.now() + fleet.timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
        rc, out, err = quietly(fleet.cmd_publish, self.cfg, self.args(node="vps1", job_id=jid, to="youtube", at=when))
        self.assertEqual(rc, 0, err)
        status = json.loads(next(c for c in self.fake.calls if c["path"] == "/youtube_upload/videos")["data"])["status"]
        self.assertEqual((status["privacyStatus"], status["selfDeclaredMadeForKids"]), ("private", True))
        self.assertTrue(status["publishAt"].endswith("Z"))
        self.assertIn("goes public by itself", out)
        with self.assertRaisesRegex(fleet.FleetError, "15 minutes from now"):
            fleet.publish_at("2020-01-01 10:00")

    def test_tiktok_inbox(self):
        with self.assertRaisesRegex(fleet.FleetError, "fill in your TikTok app"):
            self.login("tiktok")
        self.assertEqual(json.loads((self.pub / "tiktok-app.json").read_text(encoding="utf-8")),
                         {"client_key": "", "client_secret": ""})  # a template to fill in
        (self.pub / "tiktok-app.json").write_text(json.dumps({"client_key": "ck", "client_secret": "cs"}),
                                                  encoding="utf-8")
        port = free_port()
        with mock.patch.object(fleet, "TIKTOK_PORT", port):
            rc, out, err = self.login("tiktok")
        self.assertEqual(rc, 0, err)
        q = self.browser_saw[-1]
        self.assertEqual(q["redirect_uri"], f"http://127.0.0.1:{port}/callback/")
        self.assertRegex(q["code_challenge"], r"^[0-9a-f]{64}$")  # hex, as TikTok's desktop kit wants
        self.assertEqual(q["scope"], "user.info.basic,video.upload")
        jid, _ = self.job(size=2_500_000)
        with mock.patch.object(fleet, "TIKTOK_CHUNK", 1_000_000):
            rc, out, err = quietly(fleet.cmd_publish, self.cfg, self.args(node="vps1", job_id=jid, to="tiktok"))
        self.assertEqual(rc, 0, err)
        init = json.loads(next(c for c in self.fake.calls if c["path"].endswith("/inbox/video/init/"))["data"])
        self.assertEqual(init["source_info"], {"source": "FILE_UPLOAD", "video_size": 2_500_000,
                                               "chunk_size": 1_000_000, "total_chunk_count": 2})
        ranges = [c["headers"]["Content-Range"] for c in self.fake.calls if c["path"] == "/tt-upload"]
        self.assertEqual(ranges, ["bytes 0-999999/2500000", "bytes 1000000-2499999/2500000"])  # the last takes the rest
        self.assertEqual(self.fake.got["tt"], 2_500_000)
        self.assertIn("is in your TikTok inbox", out)
        self.assertIn("#space #saturnrings", out)

    def test_instagram_posts_only_with_now(self):
        jid, _ = self.job()
        with self.assertRaisesRegex(fleet.FleetError, "Instagram has no drafts"):
            fleet.cmd_publish(self.cfg, self.args(node="vps1", job_id=jid, to="instagram"))
        with mock.patch("getpass.getpass", return_value=" ig-token "):
            rc, out, err = quietly(fleet.cmd_publish, self.cfg, self.args(login="instagram", channel="Space Facts"))
        self.assertEqual(rc, 0, err)
        acct_file = self.pub / "instagram-space-facts.json"
        acct = json.loads(acct_file.read_text(encoding="utf-8"))
        self.assertEqual((acct["access_token"], acct["user_id"], acct["username"]), ("ig-token", "1789", "spacefacts"))
        acct["refreshed_at"] -= 2 * 86400  # two days old: renewed before it is used
        acct_file.write_text(json.dumps(acct), encoding="utf-8")
        rc, out, err = quietly(fleet.cmd_publish, self.cfg, self.args(
            node="vps1", job_id=jid, to="instagram", now=True, video_url="https://media.example.test/v.mp4"))
        self.assertEqual(rc, 0, err)
        made = next(c for c in self.fake.calls if c["path"] == "/instagram_api/1789/media")["form"]
        self.assertEqual((made["media_type"], made["video_url"], made["access_token"]),
                         ("REELS", "https://media.example.test/v.mp4", "ig-renewed"))
        self.assertTrue(made["caption"].startswith("Five facts about Saturn"))
        self.assertIn("/instagram_api/1789/media_publish", self.fake.paths("POST"))
        self.assertIn("posted as a Reel (media media-1)", out)

    def test_instagram_shares_the_video_with_funnel_and_stops_after(self):
        seen = []
        with mock.patch.object(fleet, "tailscale_binary", return_value="tailscale"), \
                mock.patch.object(fleet, "tailscale_self", return_value=("100.64.0.1", "my-pc.tail-net.ts.net")), \
                mock.patch.object(fleet.subprocess, "run", side_effect=lambda argv, **kw: seen.append(argv) or ran()):
            with contextlib.redirect_stdout(io.StringIO()), fleet.shared_publicly(self.tmp / "v.mp4") as url:
                self.assertRegex(url, r"^https://my-pc\.tail-net\.ts\.net/fleet-[\w-]+\.mp4$")
        on, off = seen
        self.assertEqual(on[:4], ["tailscale", "funnel", "--bg", "--https=443"])
        self.assertEqual(off, ["tailscale", "funnel", "--https=443", on[4], "off"])
        self.assertEqual(on[4], "--set-path=" + url.split(".ts.net", 1)[1])

    def test_refusals(self):
        with self.assertRaisesRegex(fleet.FleetError, "run fleet pull vps1 first"):
            fleet.cmd_publish(self.cfg, self.args(node="vps1", job_id="nothing-here", to="youtube"))
        jid, _ = self.job(check=False)
        with self.assertRaisesRegex(fleet.FleetError, "the sound is silent.*--anyway"):
            fleet.cmd_publish(self.cfg, self.args(node="vps1", job_id=jid, to="youtube"))
        with self.assertRaisesRegex(fleet.FleetError, "no youtube account for Space Facts"):
            fleet.cmd_publish(self.cfg, self.args(node="vps1", job_id=jid, to="youtube", anyway=True))
        with self.assertRaisesRegex(fleet.FleetError, "not vimeo"):
            fleet.cmd_publish(self.cfg, self.args(node="vps1", job_id=jid, to="vimeo"))
        with self.assertRaisesRegex(fleet.FleetError, "--channel"):
            fleet.cmd_publish(self.cfg, self.args(login="youtube"))
        self.assertEqual(self.fake.calls, [])

    def test_dry_run_sends_nothing(self):
        (self.pub / "tiktok-space-facts.json").write_text(json.dumps({"platform": "tiktok", "channel": "Space Facts"}),
                                                          encoding="utf-8")
        jid, _ = self.job()
        rc, out, _ = quietly(fleet.cmd_publish, self.cfg, self.args(node="vps1", job_id=jid, to="tiktok", dry_run=True))
        self.assertEqual(rc, 0)
        self.assertIn("title: Five facts about Saturn", out)
        self.assertIn("an upload to the TikTok inbox", out)
        self.assertEqual(self.fake.calls, [])
        self.assertIn("tiktok", quietly(fleet.cmd_publish, self.cfg, self.args(accounts=True))[1])

    def test_captions(self):
        self.assertEqual(fleet.caption({"caption": " Mine "}), "Mine")
        self.assertEqual(fleet.caption({"title": "T", "description": "D", "tags": ["a b", "c-d"]}), "T\n\nD\n\n#ab #cd")
        self.assertEqual(len(fleet.caption({"title": "x" * 3000})), 2200)


def urllib_get(url: str) -> None:
    import urllib.request
    with urllib.request.urlopen(url, timeout=10) as r:
        r.read()


# --------------------------------------------------------------------------- schedules

def load_scheduler():
    path = REPO / "vps" / "worker" / "fleet-schedule"
    loader = importlib.machinery.SourceFileLoader("fleet_schedule", str(path))
    spec = importlib.util.spec_from_loader("fleet_schedule", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


scheduler = load_scheduler()


def utc(s: str) -> float:
    """A UTC time like "2026-11-24 09:00" (a Tuesday) as an epoch."""
    return fleet.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=fleet.timezone.utc).timestamp()


class ScheduleRulesTest(TempDirTest):
    """vps/worker/fleet-schedule, which each VPS asks before it starts a job."""

    def sched(self, node="vps1", **parts):
        return scheduler.Schedule(scheduler.check(dict({"tz": "UTC", "seed": "abcd"}, **parts), now=utc("2026-11-24 00:00")),
                                  node)

    def state(self, s, when, starts=(), last_end=""):
        return s.state(utc(when), [(utc(e), j) for e, j in starts], utc(last_end) if last_end else 0)

    def test_hours_and_a_night_window(self):
        s = self.sched(hours=[["08:00", "12:00"], ["22:00", "02:00"]])
        self.assertEqual(self.state(s, "2026-11-24 07:00")["reason"], "off duty until 08:00")
        st = self.state(s, "2026-11-24 09:00")
        self.assertEqual((st["open"], st["until"], st["note"]), (True, utc("2026-11-24 12:00"), "working until 12:00"))
        self.assertEqual(self.state(s, "2026-11-24 12:30")["reason"], "off duty until 22:00")
        self.assertTrue(self.state(s, "2026-11-25 01:30")["open"])  # the night that started on Tuesday
        self.assertEqual(self.state(s, "2026-11-25 02:00")["reason"], "off duty until 08:00")

    def test_days_and_days_off(self):
        s = self.sched(hours=[["22:00", "07:00"]], days=["mon", "tue", "wed", "thu", "fri"])
        self.assertTrue(self.state(s, "2026-11-28 06:00")["open"])  # Saturday morning ends Friday's night
        self.assertEqual(self.state(s, "2026-11-28 08:00")["reason"], "day off until Mon 22:00")
        s = self.sched(off=[["2026-11-25", "2026-11-26"], ["2026-01-01", "2026-01-02"]])
        self.assertEqual(s.s["off"], [["2026-11-25", "2026-11-26"]])  # ranges that are over leave the list
        self.assertEqual(self.state(s, "2026-11-25 10:00")["reason"], "day off until Fri 00:00")
        self.assertTrue(self.state(s, "2026-11-24 23:59")["open"])

    def test_work_then_rest(self):
        s = self.sched(hours=[["08:00", "23:00"]], cycle=[180, 60])
        self.assertEqual([(a - utc("2026-11-24 00:00")) / 3600 for a, _ in s.blocks(fleet.datetime(2026, 11, 24).date())],
                         [8, 12, 16, 20])
        self.assertEqual(self.state(s, "2026-11-24 11:30")["reason"], "resting until 12:00")
        self.assertTrue(self.state(s, "2026-11-24 22:59")["open"])

    def test_pause_after_each_video(self):
        s = self.sched(gap=45)
        self.assertEqual(self.state(s, "2026-11-24 10:00", last_end="2026-11-24 09:40")["reason"],
                         "pause after a video until 10:25")
        self.assertTrue(self.state(s, "2026-11-24 10:25", last_end="2026-11-24 09:40")["open"])

    def test_daily_cap_counts_each_job_once(self):
        s = self.sched(hours=[["08:00", "23:00"]], cap=2)
        again = [("2026-11-24 09:00", "a"), ("2026-11-24 11:00", "a")]  # a job back from a usage limit
        self.assertTrue(self.state(s, "2026-11-24 15:00", again)["open"])
        st = self.state(s, "2026-11-24 15:00", again + [("2026-11-24 12:00", "b")])
        self.assertEqual(st["reason"], "done for the day (2 videos) until tomorrow 08:00")
        self.assertTrue(self.state(s, "2026-11-24 15:00", [("2026-11-23 20:00", "x"), ("2026-11-23 21:00", "y")])["open"])

    def test_random_start_times(self):
        s = self.sched(hours=[["08:00", "23:00"]], random=[4, 60])
        day = fleet.datetime(2026, 11, 24).date()
        picks = s.picks(day)
        self.assertEqual(picks, self.sched(hours=[["08:00", "23:00"]], random=[4, 60]).picks(day))  # the same all day
        self.assertNotEqual(picks, self.sched("vps2", hours=[["08:00", "23:00"]], random=[4, 60]).picks(day))
        self.assertEqual(len(picks), 4)
        self.assertTrue(all(utc("2026-11-24 08:00") <= p < utc("2026-11-24 23:00") for p in picks))
        self.assertTrue(all(b - a >= 3600 for a, b in zip(picks, picks[1:])))
        self.assertTrue(all(p % 60 == 0 for p in picks))
        before = s.state(picks[0] - 60, [], 0)
        self.assertEqual(before["until"], picks[0])
        self.assertTrue(before["reason"].startswith(("off duty until", "next random start at")))
        self.assertTrue(s.state(picks[0], [], 0)["open"])
        late = picks[1] - 60  # the first start time is still good until the second one
        self.assertTrue(s.state(late, [], 0)["open"])
        used = [(picks[0] + 120, "a")]
        st = s.state(picks[0] + 180, used, 0)
        self.assertEqual((st["open"], st["until"]), (False, picks[1]))
        self.assertTrue(st["reason"].startswith("next random start at "))
        w = s.workday(picks[1] + 60, used, 0)
        self.assertEqual([p["state"] for p in w["picks"]], ["used", "now", "ahead", "ahead"])
        squeezed = self.sched(hours=[["08:00", "09:00"]], random=[6, 60]).picks(day)  # cannot fit 6 an hour apart
        self.assertEqual(len(squeezed), 6)
        self.assertTrue(all(utc("2026-11-24 08:00") <= p < utc("2026-11-24 09:00") for p in squeezed))

    def test_extra_time_beats_everything(self):
        s = self.sched(hours=[["08:00", "09:00"]], cap=1, open_until=int(utc("2026-11-24 20:00")))
        st = self.state(s, "2026-11-24 19:00", [("2026-11-24 08:10", "a")])
        self.assertEqual((st["open"], st["kind"], st["until"]), (True, "extra", utc("2026-11-24 20:00")))
        self.assertEqual(self.state(s, "2026-11-24 20:00")["reason"], "off duty until tomorrow 08:00")

    def test_odd_schedules_are_refused(self):
        bad = [({"hours": [["08:00", "08:00"]]}, "same time"), ({"hours": [["8:00", "9:00"]]}, "two times"),
               ({"hours": [["08:00", "12:00"], ["11:00", "13:00"]]}, "overlap"),
               ({"hours": [["22:00", "07:00"], ["06:00", "09:00"]]}, "overlap"), ({"tz": "Mars/Base"}, "unknown"),
               ({"tz": "+15:00"}, "out of range"), ({"cycle": [5, 5]}, "10 to 1440"), ({"random": [0, 5]}, "1 to 48"),
               ({"days": []}, "days"), ({"days": ["monday"]}, "days"), ({"off": [["2026-12-02", "2026-12-01"]]}, "before"),
               ({"cap": True}, "cap"), ({"gap": "45"}, "gap"), ([], "object")]
        for s, words in bad:
            with self.assertRaisesRegex(ValueError, words, msg=s):
                scheduler.check(s)

    def test_words(self):
        w = scheduler.summary
        self.assertEqual(w({"tz": "UTC"}), "works 24/7")
        self.assertEqual(w({"hours": [["08:00", "12:00"], ["14:00", "23:00"]], "days": ["mon", "tue", "wed", "thu", "fri"],
                            "gap": 45, "cap": 3}),
                         "works 08:00-12:00 and 14:00-23:00 on weekdays; a 45 min pause after each video; "
                         "at most 3 videos a day")
        self.assertEqual(w({"days": ["mon", "wed"], "cycle": [180, 90], "random": [1, 0], "off": [["2026-12-24", "2026-12-24"]]}),
                         "works around the clock on Mon and Wed; in blocks of 3h with 1h30 of rest between them; "
                         "1 random start time a day; days off: 24 Dec")
        self.assertEqual(scheduler.days_words(["tue", "wed", "thu"]), "from Tue to Thu")

    @unittest.skipUnless(scheduler.ZoneInfo, "no zoneinfo")
    def test_summer_time(self):
        try:
            s = self.sched(tz="Europe/Paris", hours=[["08:00", "09:00"]])
        except ValueError:
            self.skipTest("no time zone data here (pip install tzdata)")
        self.assertEqual(s.windows(fleet.datetime(2026, 3, 28).date()), [(utc("2026-03-28 07:00"), utc("2026-03-28 08:00"))])
        self.assertEqual(s.windows(fleet.datetime(2026, 3, 29).date()), [(utc("2026-03-29 06:00"), utc("2026-03-29 07:00"))])
        self.assertEqual(s.clock(utc("2026-03-29 06:00"), utc("2026-03-29 01:00")), "08:00")


class ScheduleFileTest(TempDirTest):
    """What the worker loop and `fleet-worker schedule` do with fleet-schedule."""

    def setUp(self):
        super().setUp()
        self.now = utc("2026-11-24 10:00")

    def save(self, **changes):
        return scheduler.save(str(self.tmp), changes, now=self.now)

    def test_changes_merge_and_24_7_removes_the_file(self):
        self.save(hours=[["08:00", "23:00"]], tz_default="+01:00")
        self.save(cap=3, tz_default="+02:00")  # a guessed offset follows the PC's clock
        s = json.loads((self.tmp / "schedule.json").read_text(encoding="utf-8"))
        self.assertEqual((s["hours"], s["cap"], s["tz"]), ([["08:00", "23:00"]], 3, "+02:00"))
        seed = s["seed"]
        self.save(tz="UTC", random=[2, 30])
        self.save(cap=None, tz_default="+05:00")  # an explicit zone stays
        s = json.loads((self.tmp / "schedule.json").read_text(encoding="utf-8"))
        self.assertEqual((s.get("cap"), s["tz"], s["seed"]), (None, "UTC", seed))
        self.assertIsNone(self.save(reset=True))
        self.assertFalse((self.tmp / "schedule.json").exists())
        self.assertIsNone(scheduler.status(str(self.tmp), now=self.now))
        with self.assertRaisesRegex(ValueError, "open_for"):
            self.save(open_for=-5)

    def test_open_for_then_close(self):
        self.save(hours=[["01:00", "02:00"]], tz="UTC")
        self.assertEqual(scheduler.gate(str(self.tmp), now=self.now), f"{int(self.now) + 300}\toff duty until tomorrow 01:00")
        self.save(open_for=90)
        st = scheduler.status(str(self.tmp), now=self.now)
        self.assertEqual((st["open"], st["note"]), (True, "extra work time until 11:30"))
        self.assertEqual(scheduler.gate(str(self.tmp), now=self.now), f"{int(self.now) + 300}\t")
        self.save(open_for=0)
        self.assertFalse(scheduler.status(str(self.tmp), now=self.now)["open"])

    def test_the_gate_reads_starts_and_ends(self):
        self.save(gap=30, cap=2, tz="UTC")
        (self.tmp / ".starts").write_text(f"{int(self.now) - 7200} a\n{int(self.now) - 3600} b\nnot a line\n",
                                          encoding="utf-8")
        (self.tmp / ".last-end").write_text(str(int(self.now) - 600), encoding="utf-8")
        until, why = scheduler.gate(str(self.tmp), now=self.now).split("\t")
        self.assertEqual(why, "done for the day (2 videos) until tomorrow 00:00")
        self.assertEqual(int(until), int(self.now) + 300)  # asked again within five minutes
        st = scheduler.status(str(self.tmp), now=self.now)
        self.assertEqual(st["workday"]["started"], 2)
        self.assertIn("now: done for the day", scheduler.text(st))

    def test_an_unreadable_schedule_starts_nothing(self):
        (self.tmp / "schedule.json").write_text("{not json", encoding="utf-8")
        until, why = scheduler.gate(str(self.tmp), now=self.now).split("\t")
        self.assertTrue(why.startswith("the schedule could not be read"))
        self.assertEqual(int(until), int(self.now) + 60)
        st = scheduler.status(str(self.tmp), now=self.now)
        self.assertEqual((st["open"], st["kind"]), (False, "error"))
        self.save(reset=True, hours=[["08:00", "20:00"]])  # setting it again mends it
        self.assertTrue(scheduler.status(str(self.tmp), now=self.now)["open"])


class ScheduleCliTest(TempDirTest):
    def test_parsers(self):
        self.assertEqual([fleet.parse_minutes(v, "x") for v in ("45m", "2h", "1h30", "1.5h", "90", "90min", "off")],
                         [45, 120, 90, 90, 90, 90, 0])
        self.assertEqual(fleet.parse_hours("8-12, 14:30-23"), [["08:00", "12:00"], ["14:30", "23:00"]])
        self.assertEqual(fleet.parse_hours("22:00-07:00"), [["22:00", "07:00"]])
        self.assertEqual(fleet.parse_hours("18:00 to 24:00"), [["18:00", "24:00"]])
        self.assertIsNone(fleet.parse_hours("00:00-24:00"))
        self.assertIsNone(fleet.parse_hours("all"))
        self.assertEqual(fleet.parse_days("mon-fri"), ["mon", "tue", "wed", "thu", "fri"])
        self.assertEqual(fleet.parse_days("fri-mon"), ["mon", "fri", "sat", "sun"])
        self.assertEqual(fleet.parse_days("Saturday, sunday"), ["sat", "sun"])
        self.assertIsNone(fleet.parse_days("every day"))
        self.assertEqual(fleet.parse_off("2026-12-24..2026-12-26,2027-01-01"),
                         [["2026-12-24", "2026-12-26"], ["2027-01-01", "2027-01-01"]])
        self.assertEqual(fleet.parse_cycle("3h/45m"), [180, 45])
        self.assertEqual([fleet.parse_count(v, "x") for v in ("4", "4/day", "4 a day", "none")], [4, 4, 4, 0])
        for fn, v in ((fleet.parse_minutes, "soon"), (fleet.parse_hours, "25-26"), (fleet.parse_hours, "24-02"),
                      (fleet.parse_days, "mon-funday"), (fleet.parse_off, "2026-02-30"), (fleet.parse_cycle, "3h"),
                      (fleet.parse_count, "lots")):
            with self.assertRaises(fleet.FleetError, msg=v):
                fn(v, "x") if fn in (fleet.parse_minutes, fleet.parse_count) else fn(v)

    def test_command_line(self):
        a = fleet.parse_cli(["schedule", "vps1,vps2"])  # no action: show
        self.assertEqual((a.action, a.args), ("show", ["vps1,vps2"]))
        a = fleet.parse_cli(["--config", "x.ini", "schedule", "set", "vps1", "24/7", "--cap", "3"])
        self.assertEqual((a.action, a.args, a.cap), ("set", ["vps1", "24/7"], "3"))
        self.assertEqual(fleet.parse_cli(["schedule"]).action, "show")
        self.assertEqual(fleet.parse_cli(["schedule", "--json"]).action, "show")

    def args(self, action="set", *words, **kw):
        base = dict(action=action, args=list(words), hours=None, days=None, off=None, cycle=None, gap=None, random=None,
                    min_gap=None, cap=None, tz=None, for_=None, json=False)
        base.update(kw)
        return argparse.Namespace(**base)

    def run_schedule(self, a, answer=None, cfg=None):
        cfg = cfg or make_cfg(self.tmp, "vps1", "vps2", channels="Space Facts")
        sent = []

        def fake_remote(c, n, command, stdin=None, **kw):
            sent.append((n.name, command, json.loads(stdin) if stdin else None))
            return ran(out=json.dumps(answer).encode())
        with mock.patch.object(fleet, "remote", side_effect=fake_remote), \
                mock.patch.object(fleet, "pc_zone", return_value="+01:00"):
            rc, out, err = quietly(fleet.cmd_schedule, cfg, a)
        return rc, out, err, sent

    def test_set_sends_the_changes(self):
        a = self.args("set", "vps1", hours="08:00-23:00", days="weekdays", gap="45m", random="4/day", cap="3")
        rc, out, _, sent = self.run_schedule(a, {"summary": "works 08:00-23:00 on weekdays", "tz": "+01:00",
                                                 "config": {"tz": "+01:00", "tz_guess": True},
                                                 "note": "working until 23:00", "open": True, "workday": {}})
        self.assertEqual(rc, 0)
        (node, command, changes), = sent
        self.assertEqual(node, "vps1")
        self.assertTrue(command.endswith("schedule set"))
        self.assertEqual(changes, {"hours": [["08:00", "23:00"]], "days": ["mon", "tue", "wed", "thu", "fri"], "gap": 45,
                                   "random": [4, 30], "cap": 3, "tz_default": "+01:00"})
        self.assertIn("vps1 (Space Facts): works 08:00-23:00 on weekdays. Times in UTC+01:00.", out)
        self.assertIn("To follow summer time, add timezone = Area/City", out)
        _, _, _, sent = self.run_schedule(self.args("set", "all", "24/7", tz="Europe/Paris"))
        self.assertEqual([s[2] for s in sent], [{"reset": True, "tz": "Europe/Paris", "tz_default": "+01:00"}] * 2)
        cfg = make_cfg(self.tmp, "vps1")
        cfg.timezone = "Europe/Paris"  # [defaults] timezone in fleet.ini
        _, _, _, sent = self.run_schedule(self.args("set", "vps1", cap="0"), cfg=cfg)
        self.assertEqual(sent[0][2], {"cap": None, "tz": "Europe/Paris", "tz_default": "+01:00"})

    def test_open_close_and_show(self):
        _, _, _, sent = self.run_schedule(self.args("open", "vps1,vps2", for_="2h"))
        self.assertEqual(sorted((s[0], s[2]["open_for"]) for s in sent), [("vps1", 120), ("vps2", 120)])
        _, _, _, sent = self.run_schedule(self.args("close", "vps2"))
        self.assertEqual(sent[0][2], {"open_for": 0})
        rc, out, _, sent = self.run_schedule(self.args("show"), None)
        self.assertEqual(rc, 0)
        self.assertEqual([s[1].endswith("schedule show --json") for s in sent], [True, True])
        self.assertIn("vps2 (Space Facts): works 24/7", out)

    def test_refusals(self):
        for a, words in ((self.args("set", "vps1"), "say what to change"), (self.args("open"), "name the VPSs"),
                         (self.args("show", "24/7"), "24/7 goes with set"),
                         (self.args("set", "vps1", min_gap="1h"), "--min-gap goes with --random"),
                         (self.args("set", "vps1", tz="Paris time"), "time zone"),
                         (self.args("open", "vps1", for_="200h"), "7 days"), (self.args("set", "vps9", cap="1"), "unknown node")):
            with self.assertRaisesRegex(fleet.FleetError, words):
                self.run_schedule(a)

    def test_a_vps_off_duty_keeps_its_jobs(self):
        off = {"open": False, "kind": "off", "reason": "off duty until 08:00", "until": fleet.time.time() + 3600}
        self.assertEqual(fleet.node_readiness(healthy(schedule=off), "claude"), "held by its schedule (off duty until 08:00)")
        self.assertIsNone(fleet.node_readiness(healthy(schedule={"open": True, "kind": "open"}), "claude"))
        cfg = make_cfg(self.tmp, "vps1", "vps2", channels="all")
        cfg.nodes["vps1"].channels = "Space Facts"
        uploaded = []
        statuses = {"vps1": healthy(schedule=off), "vps2": healthy(schedule=dict(off, until=fleet.time.time() + 60))}
        with mock.patch.object(fleet, "fetch_status", side_effect=lambda c, n: dict(statuses[n.name], node=n.name)), \
                mock.patch.object(fleet, "upload_job", side_effect=lambda c, n, j: uploaded.append(n.name)):
            rc, _, err = quietly(fleet.dispatch_jobs, cfg, [fleet.validate_job({"prompt": "a", "channel": "Space Facts"}),
                                                            fleet.validate_job({"prompt": "b", "channel": "History"})],
                                 "auto", False, False)
        self.assertEqual((rc, uploaded), (0, ["vps1", "vps2"]))  # its own VPS keeps it; the shared one opens first
        self.assertIn("waits in its queue until its schedule lets it start", err)
        bad = {"error": "not JSON", "open": False, "kind": "error", "reason": "the schedule could not be read: not JSON"}
        with mock.patch.object(fleet, "fetch_status", side_effect=lambda c, n: dict(healthy(schedule=bad), node=n.name)):
            problems = fleet.health_problems(make_cfg(self.tmp, "vps1"))
        self.assertIn("vps1: its schedule could not be read (not JSON)", problems["vps1:schedule"])
        never = dict(off, until=None, reason="day off, no work time in the next 60 days")
        st = healthy(schedule=never, queue=dict(healthy()["queue"], inbox=2))
        with mock.patch.object(fleet, "fetch_status", side_effect=lambda c, n: dict(st, node=n.name)):
            self.assertIn("no work time in the next 60 days", fleet.health_problems(make_cfg(self.tmp, "vps1"))["vps1:schedule"])
            rc, out, _ = quietly(fleet.cmd_status, make_cfg(self.tmp, "vps1"), argparse.Namespace(targets=None, json=False))
        self.assertIn("OFF DUTY", out)


# --------------------------------------------------------------------------- command line

class CommandLineTest(TempDirTest):
    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True,
                              env=dict(os.environ, **(env or {})))

    def test_version_and_help(self):
        self.assertEqual(self.run_cli("--version").stdout.strip(), f"fleet {fleet.VERSION}")
        r = self.run_cli("--help")
        self.assertEqual(r.returncode, 0)
        for cmd in ("dispatch", "pause", "resume", "retry", "handover", "studio", "hermes-cron", "doctor"):
            self.assertIn(cmd, r.stdout)

    def test_missing_config_is_a_clear_error(self):
        r = self.run_cli("--config", str(self.tmp / "none.ini"), "status")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Run `fleet init`", r.stderr)

    def test_parser(self):
        p = fleet.build_parser()
        a = p.parse_args(["dispatch", "a.json", "b.json", "--to", "vps1,vps2", "--json"])
        self.assertEqual((a.job_files, a.to, a.json), (["a.json", "b.json"], "vps1,vps2", True))
        a = p.parse_args(["provider", "install", "claude", "vps3", "--version", "2.1.0"])
        self.assertEqual((a.action, a.name, a.targets, a.version), ("install", "claude", "vps3", "2.1.0"))
        self.assertEqual(p.parse_args(["secrets", "push", "claude"]).targets, "all")
        a = p.parse_args(["handover", "vps2", "vps4", "job-a", "job-b", "--dry-run"])
        self.assertEqual((a.from_node, a.to_node, a.job_ids, a.dry_run), ("vps2", "vps4", ["job-a", "job-b"], True))
        self.assertEqual(p.parse_args(["handover", "vps2", "vps4"]).job_ids, [])
        self.assertEqual(p.parse_args(["jobs", "--state", "moved"]).state, "moved")
        a = p.parse_args(["studio", "--tailnet", "--port", "9000", "--no-browser"])
        self.assertEqual((a.tailnet, a.port, a.every, a.no_browser, a.json), (True, 9000, 20, True, False))
        self.assertEqual(p.parse_args(["studio"]).port, fleet.STUDIO_PORT)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            p.parse_args(["jobs", "--state", "weird"])

    def test_exec_options_work_on_either_side_of_the_targets(self):
        for argv in (["exec", "vps1", "--root", "--", "id", "-u"],
                     ["exec", "--root", "vps1", "--", "id", "-u"],
                     ["--config", "x.ini", "exec", "vps1", "--root", "--", "id", "-u"]):
            a = fleet.parse_cli(argv)
            self.assertEqual((a.targets, a.root, a.command), ("vps1", True, ["id", "-u"]), argv)
        a = fleet.parse_cli(["exec", "all", "--timeout", "5", "--", "ls", "--", "-la"])
        self.assertEqual((a.root, a.timeout, a.command), (False, 5, ["ls", "--", "-la"]))
        self.assertEqual(fleet.parse_cli(["exec", "vps2"]).command, [])
        # Only `fleet exec` splits at "--".
        self.assertEqual(fleet.parse_cli(["dispatch", "--", "job.json"]).job_files, ["job.json"])

    @unittest.skipUnless(POSIX and shutil.which("bash"), "the local transport needs bash")
    def test_exec_over_local_transport(self):
        ini = self.tmp / "fleet.ini"
        ini.write_text(f"[defaults]\ntransport = local\nremote_root = {self.tmp}/{{node}}\n[vps1]\n[vps2]\n",
                       encoding="utf-8")
        r = self.run_cli("--config", str(ini), "exec", "all", "--", "echo", "hello from $FLEET_NODE")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--- vps1 (exit 0)\nhello from vps1", r.stdout)
        self.assertIn("--- vps2 (exit 0)\nhello from vps2", r.stdout)
        r = self.run_cli("--config", str(ini), "exec", "vps2", "--", "exit 4")
        self.assertEqual(r.returncode, 4)


if __name__ == "__main__":
    unittest.main()
