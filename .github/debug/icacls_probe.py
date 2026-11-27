"""Temporary probe: why can a file not be read after restrict_dir's icacls on the Windows runner?"""
import os
import pathlib
import subprocess
import sys
import tempfile


def run(*a):
    r = subprocess.run(list(a), capture_output=True, text=True)
    print(">", " ".join(a), "-> rc", r.returncode)
    for s in (r.stdout.strip(), r.stderr.strip()):
        if s:
            print("   " + s.replace("\n", "\n   "))
    return r


print(sys.version)
for k in ("USERNAME", "USERDOMAIN", "COMPUTERNAME", "TEMP", "USERPROFILE"):
    print(k, "=", os.environ.get(k))
run("whoami")
sid = run("whoami", "/user", "/fo", "csv", "/nh").stdout.strip().split(",")[-1].strip('"')
print("SID", sid)
for variant in ("env-name", "sid", "env-name-in-plain-dir"):
    base = pathlib.Path(tempfile.mkdtemp()) if variant != "env-name-in-plain-dir" else pathlib.Path(os.environ["RUNNER_TEMP"]) / "plain"
    d = base / "secrets" / "publish"
    d.mkdir(parents=True)
    f = d / "k.json"
    f.write_text('{"key": "x"}', encoding="utf-8")
    print("\n=====", variant, d)
    run("icacls", str(base))
    who = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}" if variant != "sid" else "*" + sid
    run("icacls", str(d), "/inheritance:r", "/grant:r", f"{who}:(OI)(CI)F", "/grant:r", "SYSTEM:(OI)(CI)F", "/T")
    run("icacls", str(d))
    run("icacls", str(f))
    try:
        print(variant, "READ OK", f.read_text(encoding="utf-8"))
    except Exception as e:
        print(variant, "READ FAILED", repr(e))
    try:
        (d / "new.json").write_text("{}", encoding="utf-8")
        print(variant, "NEW FILE OK", (d / "new.json").read_text(encoding="utf-8"))
    except Exception as e:
        print(variant, "NEW FILE FAILED", repr(e))
