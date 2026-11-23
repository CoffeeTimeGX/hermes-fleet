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
        self.assertTrue((home / "scripts" / "fleet_health.py").is_file())
        self.assertTrue((home / "scripts" / "fleet_pull.py").is_file())
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
            self.assertEqual(quietly(fleet.cmd_hermes_cron, cfg, a)[0], 0)
            self.assertEqual(fake.cron, ["fleet-health", "fleet-pull", "fleet-daily-report"])
            self.assertIn("= fleet-health already exists", quietly(fleet.cmd_hermes_cron, cfg, a)[1])
        self.assertEqual({p for p, args in fake.calls if args[0] == "cron"}, {"director"})


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

    def serve(self, snapshot) -> int:
        files = {"/": (b"<p>page</p>", "text/html; charset=utf-8"), "/app.js": (b"go()", "text/javascript; charset=utf-8")}
        handler = fleet.studio_handler(files, {"snapshot": snapshot}, threading.Lock(), fleet.LOOPBACK_NAMES)
        srv = fleet.studio_server("127.0.0.1", 0, handler)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return srv.server_address[1]

    def get(self, port, path, method="GET", host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            c.request(method, path, headers={"Host": host} if host else {})
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
