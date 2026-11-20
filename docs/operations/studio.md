# The studio

The studio is a page in your browser that shows the whole fleet at a glance, like a film
lot seen from above. Your PC is the director's office at the top, the private road is
Tailscale, and every VPS is a sound stage with its channel's name on the roof. You see
which VPSs are making a video, what each Claude session is doing right now, what waits,
and what finished today.

![The studio with an example fleet](../assets/studio.png)

It only watches. Nothing on the page changes the fleet: to act, ask the director or use
the `fleet` commands.

## Open it

In a terminal on your PC (PowerShell on Windows):

```
fleet studio
```

```
Fleet studio: http://127.0.0.1:8740/
It looks at the VPSs every 20 seconds and only watches: it changes nothing.
Press Ctrl+C to stop it.
```

Your browser opens the page. Leave the terminal window open: the studio runs as long as
it does, and the page updates by itself. To stop it, press Ctrl+C in that window, or
close it. The VPSs keep working either way.

The director does not open the studio for you, because it keeps running until you stop
it. Ask the director for a status instead when you are away from your PC, or open the
studio on your phone as described below.

## What you see

**The office** at the top counts the stages by lamp, the jobs that wait, the jobs that
finished today and the jobs that wait to be collected. It also says when the studio last
looked at the VPSs.

**Each stage** is one VPS:

- The **roof** carries the stage number and the channels the VPS makes.
- A **slate** for each running job: its title (or id), its channel, the take (the
  attempt, with the usage-limit waits it went through) and how long it has been rolling.
  Under **Now** is the session's latest step, such as *Running: Render the video* or a
  line of what it just wrote, and how long ago that was. The `fleet logs` command
  under it follows that job in a terminal; **Copy** puts it on your clipboard.
- **Waiting at the door**: the jobs queued on this VPS.
- The **lamp** over the door, and the **meters**: jobs done and failed today, finished
  jobs not collected yet, sessions in use, free disk, and whether Claude is ready.

| Lamp | Sign | It means |
| --- | --- | --- |
| Red | **Rolling** | A Claude session is making a video. |
| Green | **Standing by** | Ready. The next job for its channel starts at once. |
| Amber | **On hold** | Its Claude account reached a usage limit. The queue continues by itself after the reset, at the time shown. See [Usage limits](usage-limits.md). |
| Off | **Dark** | The VPS is paused. `fleet resume` starts it again. |
| Off | **No contact** | Your PC cannot reach the VPS. See [VPS unreachable](../runbooks/vps-unreachable.md). |
| Yellow and black tape | **Needs a look** | Something needs a fix: the worker stopped, Claude is not ready, or the disk is low. The stage says what. Ask the director, or run `fleet health`. |

**The call board** at the bottom lists every job on the lot: what runs now, what waits,
and what finished in the last 24 hours, with the reason a job waits or failed and
whether a finished job was collected. Times are in the local time of the device you
watch on.

## Watch from your phone

Start the studio on your PC's Tailscale address instead:

```
fleet studio --tailnet
```

```
Fleet studio: http://my-pc.tailnet-name.ts.net:8740/
It looks at the VPSs every 20 seconds and only watches: it changes nothing.
Press Ctrl+C to stop it.
```

Open that address on your phone, with the Tailscale app connected. It works on your other
devices on your tailnet too. With the fleet's
[Tailscale policy](../tailscale.md), only your own devices can open it.

The first time, Windows may ask whether Python may communicate on networks. Allow it on
private networks: Tailscale marks its own network as private on Windows. If you
declined, open **Windows Security**, then **Firewall & network protection**, then
**Allow an app through firewall**, and tick **Private** for Python. On a Mac with the
firewall on, allow Python to accept incoming connections when macOS asks.

Your PC must be on and the studio running for the phone to see it. The page says
*Lost contact* when the studio stops.

## Options

| Option | Meaning |
| --- | --- |
| `--tailnet` | Open it on your PC's Tailscale address, for your phone and your other devices. |
| `--port PORT` | Another port, when something else uses 8740: `fleet studio --port 8750`. |
| `--every SECONDS` | How often it looks at the VPSs. Default 20, at least 5. |
| `--no-browser` | Do not open the browser. |
| `--json` | Look once, print what it saw as JSON, and exit. |

## How it works

`fleet studio` runs a small web server on your PC, the same way the other `fleet`
commands run: nothing is installed and nothing runs on the VPSs. Every 20 seconds it
makes one short SSH connection to each VPS, like `fleet status`, and asks for the
worker's status, the job list and the last step of each running session (from the end
of its `logs/transcript.jsonl`). The page asks your PC for that every few seconds.

- Without `--tailnet`, only your PC can open the page (`127.0.0.1`). With it, only
  devices on your tailnet can.
- The server answers only requests addressed to your PC by its own name or address, so
  a web page from somewhere else cannot read the studio through your browser.
- The page loads its fonts from Google Fonts; everything else comes from your PC.

To see the page without a fleet, open `home/studio/studio.html` from the repository in
your browser. It shows an example lot with made-up jobs.

## If something looks wrong

| You see | Do this |
| --- | --- |
| A stage says **No contact** | Your PC cannot reach that VPS: [VPS unreachable](../runbooks/vps-unreachable.md). |
| *worker returned no status (run fleet sync)* | The worker on that VPS is missing or did not answer: run `fleet sync`. A VPS that was never set up needs [Provision a VPS](../vps/provisioning.md) first. |
| `cannot open the studio on 127.0.0.1:8740` | Another program uses the port: `fleet studio --port 8750`. |
| *Lost contact with fleet studio on your PC* | The studio stopped. Run `fleet studio` again. |
| `Tailscale is not connected on this computer` | Open Tailscale on your PC and sign in, then run `fleet studio --tailnet` again. |
