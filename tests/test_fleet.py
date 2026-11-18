"""Unit tests for home/bin/fleet. Standard library only, so they run anywhere the
CLI runs (Linux, macOS and Windows, Python 3.9+):

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
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

    def __call__(self, exe, *args, timeout=120):
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


class HermesSettingsTest(unittest.TestCase):
    def test_merge_and_idempotence(self):
        skills = (REPO / "home" / "hermes" / "skills").as_posix()
        fake = FakeHermes({"skills.external_dirs": ["/mine"], "terminal.timeout": 1800,
                           "approvals.deny": ["my rule"], "model.default": "something-else"})
        with mock.patch.object(fleet, "hermes_cmd", fake):
            report = fleet.apply_hermes_settings("hermes", "/repo", keep_model=False)
            self.assertEqual(fake.store["skills.external_dirs"], ["/mine", skills])
            self.assertEqual(fake.store["terminal.timeout"], 1800)
            self.assertEqual(fake.store["terminal.cwd"], "/repo")
            self.assertEqual(fake.store["approvals.deny"][0], "my rule")
            self.assertEqual(len(fake.store["approvals.deny"]), 4)
            self.assertEqual(fake.store["skills.auto_load"], ["fleet-ops"])
            self.assertEqual((fake.store["model.provider"], fake.store["model.default"]),
                             ("anthropic", fleet.DIRECTOR_MODEL))
            self.assertTrue(any("was \"something-else\"" in line for line in report))
            fake.sets.clear()
            fleet.apply_hermes_settings("hermes", "/repo", keep_model=False)
            self.assertEqual(fake.sets, [])

    def test_keep_model_and_low_timeout(self):
        fake = FakeHermes({"terminal.timeout": 60})
        with mock.patch.object(fleet, "hermes_cmd", fake):
            fleet.apply_hermes_settings("hermes", "/repo", keep_model=True)
        self.assertNotIn("model.default", fake.store)
        self.assertEqual(fake.store["terminal.timeout"], 900)


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


# --------------------------------------------------------------------------- command line

class CommandLineTest(TempDirTest):
    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True,
                              env=dict(os.environ, **(env or {})))

    def test_version_and_help(self):
        self.assertEqual(self.run_cli("--version").stdout.strip(), f"fleet {fleet.VERSION}")
        r = self.run_cli("--help")
        self.assertEqual(r.returncode, 0)
        for cmd in ("dispatch", "pause", "resume", "retry", "hermes-cron", "doctor"):
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
