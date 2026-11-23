/* Hermes Fleet Studio: what the board (index.html) and the pixel lot (pixel.html) share.
   Served by `fleet studio` on your PC, it reads your fleet live from api/studio. Opened
   anywhere else, it shows an example lot with made-up jobs. It only reads. */
(function () {
  "use strict";
  const LIVE = window.FLEET_STUDIO_LIVE === true;
  const POLL_MS = 5000;
  const DAY_MS = 24 * 3600 * 1000;

  // ---------------------------------------------------------------- time and words
  const when = (iso) => { const t = Date.parse(iso || ""); return Number.isNaN(t) ? null : t; };
  function ago(t) {
    const s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 10) return "just now";
    if (s < 60) return s + " s ago";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 48 * 3600) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " days ago";
  }
  function span(t) {
    const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (s < 60) return s + " s";
    const m = Math.floor(s / 60);
    if (m < 60) return m + " min";
    return Math.floor(m / 60) + " h " + String(m % 60).padStart(2, "0") + " min";
  }
  function timecode(t) {
    const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
    const p = (x) => String(x).padStart(2, "0");
    return p(Math.floor(s / 3600)) + ":" + p(Math.floor(s / 60) % 60) + ":" + p(s % 60);
  }
  function clock(sec) {
    const d = new Date(sec * 1000);
    const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const today = new Date();
    if (d.toDateString() === today.toDateString()) return hm;
    return d.toLocaleDateString([], { weekday: "short" }) + " " + hm;
  }
  // The worker writes times as UTC (2026-01-31T21:42:08Z); show them in this device's time.
  const localTimes = (txt) => String(txt || "").replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z\b/g,
    (iso) => { const t = Date.parse(iso); return Number.isNaN(t) ? iso : clock(t / 1000); });
  const stageNo = (name, i) => { const m = /(\d+)$/.exec(name || ""); return m ? m[1] : String(i + 1); };
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);

  const VERBS = { Bash: "Running", Write: "Writing", Edit: "Editing", MultiEdit: "Editing", Read: "Reading",
    Glob: "Looking for files", Grep: "Searching the files", WebSearch: "Searching the web", WebFetch: "Reading a web page",
    TodoWrite: "Planning", Task: "Handing a part to a helper", Agent: "Handing a part to a helper" };
  // A session's latest step in words: "Running: Render the video", or what it last said.
  function activityText(a) {
    if (!a) return null;
    if (a.kind === "text") return (a.text || "").replace(/\s+/g, " ").trim() || null;
    let detail = String(a.detail || "").replace(/\s+/g, " ").trim();
    if (/^(Write|Edit|MultiEdit|Read)$/.test(a.name) && detail.includes("/")) detail = detail.split("/").pop();
    const verb = VERBS[a.name] || a.name || "Working";
    return detail ? verb + ": " + detail : verb;
  }

  // ---------------------------------------------------------------- the fleet
  const jobsOf = (n) => (Array.isArray(n && n.jobs) ? n.jobs : []);
  const claudeOf = (st) => ((st && st.providers) || []).find((p) => p.provider === "claude") || ((st && st.providers) || [])[0] || null;
  const limitOf = (st) => (st && st.limit && Number(st.limit.until) * 1000 > Date.now() ? st.limit : null);
  const finishedSince = (n, cutoff) => jobsOf(n).filter((j) => (when(j.finished_at) || 0) >= cutoff);

  // What a stage is doing, in the words on its door.
  function stageState(n) {
    if (n.pending) return { state: "pending", sign: "Checking", note: "looking at it now" };
    if (!n.reachable) return { state: "offline", sign: "No contact", note: "your PC cannot reach it" };
    const st = n.status || {};
    const q = st.queue || {};
    const running = Number(q.running) || 0;
    const lim = limitOf(st);
    const prov = claudeOf(st);
    const service = st.service || "unknown";
    if (service !== "active" && service !== "unknown") return { state: "trouble", sign: "Needs a look", note: "its worker is " + service };
    if (Number(st.heartbeat_age_s) > 180 || Number(st.heartbeat_age_s) < 0) return { state: "trouble", sign: "Needs a look", note: "its worker stopped looking at the queue" };
    if (running > 0) return { state: "rolling", sign: "Rolling", note: running > 1 ? "making " + running + " videos" : "making a video" };
    if (st.paused) return { state: "dark", sign: "Dark", note: st.paused_reason ? "paused: " + st.paused_reason : "paused" };
    if (lim) return { state: "hold", sign: "On hold", note: "until " + clock(Number(lim.until)) };
    if (st.low_disk) return { state: "trouble", sign: "Needs a look", note: "low on disk, new jobs wait" };
    if (prov && !prov.ok) return { state: "trouble", sign: "Needs a look", note: "Claude is not ready" + (prov.error ? ": " + prov.error : "") };
    return { state: "standby", sign: "Standing by", note: "ready for the next job" };
  }

  // The example lot: five stages, made-up jobs, times relative to now.
  function exampleLot() {
    const now = Date.now(), min = 60000, hr = 3600000;
    const iso = (back) => new Date(now - back).toISOString();
    const job = (o) => Object.assign({ provider: "claude", attempts: 1, limit_waits: 0, pulled: false }, o);
    const claude = [{ provider: "claude", installed: true, ok: true, version: "2.1.300 (Claude Code)", auth: "oauth-token", credential_age_days: 23 }];
    const status = (o) => Object.assign({ service: "active", heartbeat_age_s: 2, paused: false, limit: null, low_disk: false,
      disk_free_gb: 71.3, disk_free_pct: 74, min_free_gb: 5, load1: 0.4, cpus: 2, mem_available_mb: 6100, mem_total_mb: 7900,
      uptime_s: 12 * 86400 + 3 * 3600, max_parallel: 1, stuck_handovers: 0, reboot_required: false, worker_version: "1.5.0",
      providers: claude, queue: { inbox: 0, running: 0, done: 0, failed: 0, unpulled: 0 } }, o);
    return {
      demo: true, generated_at: iso(6000), every: 20, fleet_version: "1.5.0",
      nodes: [
        { name: "vps1", channels: ["Space Facts"], sessions: 1, reachable: true,
          status: status({ load1: 1.9, queue: { inbox: 2, running: 1, done: 14, failed: 1, unpulled: 1 } }),
          jobs: [
            job({ id: "20261120-141502-space-facts-7fq2m", state: "running", channel: "Space Facts", title: "Saturn's rings in 60 seconds", submitted_at: iso(31 * min), started_at: iso(12 * min + 41000) }),
            job({ id: "20261120-141503-space-facts-k3x9p", state: "inbox", channel: "Space Facts", title: "Europa's hidden ocean", submitted_at: iso(31 * min) }),
            job({ id: "20261120-141504-space-facts-p81mz", state: "inbox", channel: "Space Facts", title: "The Kuiper belt", submitted_at: iso(31 * min) }),
            job({ id: "20261120-121502-space-facts-a81kd", state: "done", channel: "Space Facts", title: "Why Mars is red", started_at: iso(2 * hr), finished_at: iso(70 * min) }),
            job({ id: "20261120-091502-space-facts-q2w8e", state: "done", channel: "Space Facts", title: "How big is the Sun?", started_at: iso(5 * hr), finished_at: iso(4 * hr), pulled: true }),
          ],
          activity: { "20261120-141502-space-facts-7fq2m": { kind: "tool", name: "Bash", detail: "Render the 1080x1920 video with ffmpeg", mtime: (now - 9000) / 1000 } } },
        { name: "vps2", channels: ["History"], sessions: 1, reachable: true,
          status: status({ load1: 1.7, disk_free_gb: 68, disk_free_pct: 71, uptime_s: 3 * 86400, queue: { inbox: 1, running: 1, done: 9, failed: 0, unpulled: 0 } }),
          jobs: [
            job({ id: "20261120-133010-history-p02xs", state: "running", channel: "History", title: "The Library of Alexandria", submitted_at: iso(52 * min), started_at: iso(47 * min + 5000), attempts: 2, limit_waits: 1 }),
            job({ id: "20261120-133011-history-m4n7b", state: "inbox", channel: "History", title: "Who built the pyramids?", submitted_at: iso(52 * min) }),
            job({ id: "20261120-101145-history-x9k2l", state: "done", channel: "History", title: "The first postal service", started_at: iso(6 * hr), finished_at: iso(5 * hr), pulled: true }),
          ],
          activity: { "20261120-133010-history-p02xs": { kind: "tool", name: "Write", detail: "/home/fleet/fleet/work/20261120-133010-history-p02xs/script.md", mtime: (now - 41000) / 1000 } } },
        { name: "vps3", channels: ["Cooking"], sessions: 1, reachable: true,
          status: status({ load1: 0.05, uptime_s: 40 * 86400, limit: { provider: "claude", kind: "weekly", message: "You've hit your weekly limit", since: (now - 2 * hr) / 1000, until: (now + 38 * hr) / 1000 },
            queue: { inbox: 1, running: 0, done: 21, failed: 0, unpulled: 0 } }),
          jobs: [
            job({ id: "20261120-110000-cooking-b7v1c", state: "inbox", channel: "Cooking", title: "Bread in three ingredients", submitted_at: iso(3 * hr), started_at: iso(2 * hr + 20 * min), limit_waits: 1, reason: "usage limit: You've hit your weekly limit; continues after the reset" }),
            job({ id: "20261120-110001-cooking-r5t6y", state: "outgoing", channel: "Cooking", title: "The perfect boiled egg", submitted_at: iso(3 * hr), reason: "being handed over to vps4" }),
            job({ id: "20261120-080000-cooking-h3j4k", state: "failed", channel: "Cooking", title: "Knife skills for beginners", started_at: iso(8 * hr), finished_at: iso(5 * hr), reason: "timed out after 180m", pulled: true }),
          ],
          activity: {} },
        { name: "vps4", channels: ["Nature"], sessions: 1, reachable: true,
          status: status({ disk_free_gb: 74.9, disk_free_pct: 78, load1: 0.1, reboot_required: true, queue: { inbox: 0, running: 0, done: 7, failed: 0, unpulled: 1 } }),
          jobs: [
            job({ id: "20261120-130000-nature-w1e2r", state: "done", channel: "Nature", title: "How octopuses change colour", started_at: iso(2 * hr), finished_at: iso(25 * min) }),
          ],
          activity: {} },
        { name: "vps5", channels: ["Mysteries"], sessions: 1, reachable: false, error: "ssh: connect to host vps5 port 22: Connection timed out" },
      ],
    };
  }

  // Calls onLook(snapshot, contact) after every look at the lot: every 5 seconds from
  // fleet studio on your PC, or every 20 seconds for the example.
  function watch(onLook) {
    if (LIVE) {
      let snap = null;
      const poll = async () => {
        let contact = true;
        try {
          const r = await fetch("api/studio", { cache: "no-store" });
          if (!r.ok) throw new Error("HTTP " + r.status);
          snap = await r.json();
        } catch (e) {
          contact = false;
        }
        onLook(snap, contact);
      };
      poll();
      setInterval(poll, POLL_MS);
    } else {
      const snap = exampleLot();
      onLook(snap, true);
      setInterval(() => { snap.generated_at = new Date().toISOString(); onLook(snap, true); }, 20000);
    }
  }

  window.FleetStudio = { LIVE, POLL_MS, DAY_MS, when, ago, span, timecode, clock, localTimes, stageNo, plural,
    VERBS, activityText, jobsOf, claudeOf, limitOf, finishedSince, stageState, exampleLot, watch };
})();
