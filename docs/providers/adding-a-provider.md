# Add another provider

Today every VPS runs one provider, `claude` (Claude Code). The fleet is built so that
another tool can be added next to it later without touching the worker, the queue, the
pulls or the Hermes skills. A provider is a folder with three small scripts.

```
vps/providers/<name>/
  install.sh   install or update the tool for the fleet user (never as root)
  run.sh       run ONE job:  run.sh <job.json> <workspace>
  check.sh     health check: --json prints one JSON object, --smoke makes a real call
```

The full contract, with every environment variable and exit code, is in
[`vps/providers/README.md`](https://github.com/CoffeeTimeGX/hermes-fleet/blob/main/vps/providers/README.md).
The short version:

- `run.sh` works inside the job's workspace, puts every deliverable in `output/`, and
  writes `result.json` (with `is_error`) and `output/SUMMARY.txt`.
- It exits `0` on success, `78` when credentials are missing, `75` when the account hit
  a usage limit (after writing `logs/limit.json` with the reset time), and anything else
  on failure.
- It reads credentials only from `~/.config/fleet/providers/<name>.env` on the VPS, which
  `fleet secrets push <name> <vps>` writes. It never prints them.
- `check.sh --json` is fast and spends nothing: `fleet status` calls it on every check.

## Steps

1. Copy `vps/providers/claude/` to `vps/providers/<name>/` and adapt the three scripts.
   The Claude adapter is the reference for result files, usage limits and resuming.
2. Add `home/secrets.example/<name>.env.example` describing the variables it needs, and
   create `~/.config/fleet/secrets/<vps>/<name>.env` on your PC.
3. In `~/.config/fleet/fleet.ini`, add the provider to the nodes that should run it:
   `providers = claude, <name>`.
4. Install, push credentials and test:

    ```
    fleet provider install <name> vps3
    fleet secrets push <name> vps3
    fleet provider check <name> vps3 --smoke
    ```

5. Queue jobs with `"provider": "<name>"`. `fleet dispatch` only sends a job to VPSs
   that list its provider, and `fleet status` and `fleet health` start reporting it.

Add a test for it to `tests/e2e-local.sh` with a stub, the way `tests/lib/claude-stub`
stands in for Claude Code.
