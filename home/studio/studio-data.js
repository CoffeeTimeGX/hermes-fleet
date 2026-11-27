/* Hermes Fleet Studio: what the board (index.html) and the pixel lot (pixel.html) share.
   Served by `fleet studio` on your PC, it reads your fleet live from api/studio. Opened
   anywhere else, it shows an example lot with made-up jobs. It only reads. */
(function () {
  "use strict";
  const LIVE = window.FLEET_STUDIO_LIVE === true;
  const POLL_MS = 5000;
  const DAY_MS = 24 * 3600 * 1000;

  // ---------------------------------------------------------------- time and words
  // The studio's clock: now, or the moment a replay shows (setNow). Everything that says how long
  // ago something happened reads it, so a replay reads as if it were that moment.
  let shown = null;
  const now = () => (shown == null ? Date.now() : shown);
  const setNow = (t) => { shown = t == null ? null : Number(t); };
  const when = (iso) => { const t = Date.parse(iso || ""); return Number.isNaN(t) ? null : t; };
  function ago(t) {
    const s = Math.max(0, Math.round((now() - t) / 1000));
    if (s < 10) return "just now";
    if (s < 60) return s + " s ago";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 48 * 3600) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " days ago";
  }
  function span(t) {
    const s = Math.max(0, Math.floor((now() - t) / 1000));
    if (s < 60) return s + " s";
    const m = Math.floor(s / 60);
    if (m < 60) return m + " min";
    return Math.floor(m / 60) + " h " + String(m % 60).padStart(2, "0") + " min";
  }
  function timecode(t) {
    const s = Math.max(0, Math.floor((now() - t) / 1000));
    const p = (x) => String(x).padStart(2, "0");
    return p(Math.floor(s / 3600)) + ":" + p(Math.floor(s / 60) % 60) + ":" + p(s % 60);
  }
  function clock(sec) {
    const d = new Date(sec * 1000);
    const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const today = new Date(now());
    if (d.toDateString() === today.toDateString()) return hm;
    return d.toLocaleDateString([], { weekday: "short" }) + " " + hm;
  }
  // The worker writes times as UTC (2026-01-31T21:42:08Z); show them in this device's time.
  const localTimes = (txt) => String(txt || "").replace(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z\b/g,
    (iso) => { const t = Date.parse(iso); return Number.isNaN(t) ? iso : clock(t / 1000); });
  // A channel's colour, the same on both pages (its trailer on the lot, its title cards).
  const TRAILER = ["#d6402f", "#2e86c1", "#27ae60", "#8e44ad", "#e67e22", "#16a085", "#c0392b", "#d4ac0d"];
  const hueOf = (s) => { let h = 2166136261; s = String(s || ""); for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return TRAILER[(h >>> 0) % TRAILER.length]; };
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
  const limitOf = (st) => (st && st.limit && Number(st.limit.until) * 1000 > now() ? st.limit : null);
  const finishedSince = (n, cutoff) => jobsOf(n).filter((j) => (when(j.finished_at) || 0) >= cutoff);
  // The VPS's schedule (`fleet schedule`): null when it works 24/7.
  const scheduleOf = (st) => (st && st.schedule && typeof st.schedule === "object" ? st.schedule : null);
  // Why the schedule starts no job now, in this device's time: "back at 08:00", "next random start at 15:05".
  function offNote(sch) {
    const at = sch.until ? clock(Number(sch.until)) : null;
    if (sch.kind === "random") return at ? "next random start at " + at : "no random start time ahead";
    if (!at) return sch.reason || "off duty";
    const why = { dayoff: "day off", rest: "resting", gap: "a pause after the last video", cap: "done for the day" }[sch.kind];
    return (why ? why + ", " : "") + "back at " + at;
  }

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
    const sch = scheduleOf(st);
    if (service !== "active" && service !== "unknown") return { state: "trouble", sign: "Needs a look", note: "its worker is " + service };
    if (Number(st.heartbeat_age_s) > 180 || Number(st.heartbeat_age_s) < 0) return { state: "trouble", sign: "Needs a look", note: "its worker stopped looking at the queue" };
    if (running > 0) return { state: "rolling", sign: "Rolling", note: running > 1 ? "making " + running + " videos" : "making a video" };
    if (st.paused) return { state: "dark", sign: "Dark", note: st.paused_reason ? "paused: " + st.paused_reason : "paused" };
    if (lim) return { state: "hold", sign: "On hold", note: "until " + clock(Number(lim.until)) };
    if (st.low_disk) return { state: "trouble", sign: "Needs a look", note: "low on disk, new jobs wait" };
    if (prov && !prov.ok) return { state: "trouble", sign: "Needs a look", note: "Claude is not ready" + (prov.error ? ": " + prov.error : "") };
    if (sch && sch.error) return { state: "trouble", sign: "Needs a look", note: "its schedule could not be read" };
    if (sch && sch.open === false) return { state: "off", sign: "Off duty", note: offNote(sch) };
    const more = !sch || !sch.until ? "" : sch.kind === "extra" ? ", extra time until " + clock(Number(sch.until))
      : sch.note && sch.note !== "working" ? ", on duty until " + clock(Number(sch.until)) : "";
    return { state: "standby", sign: "Standing by", note: "ready for the next job" + more };
  }

  // ---------------------------------------------------------------- the past
  // The lot as it stood at a past moment T, rebuilt from the times on each job: a job not yet sent
  // is left out, a job started and not yet finished was rolling, a hold for the usage limit counts
  // from its start to its end. What the record cannot say (a pause, a VPS out of reach, who was
  // doing what) stays as it is now. The replay on both pages uses it.
  function at(snap, T) {
    if (!snap || T == null) return snap;
    const recent = Date.now() - T < 90000;
    const nodes = (snap.nodes || []).map((n) => {
      if (!n.reachable || !n.status) return n;
      const st = n.status, l = st.limit, since = l ? Number(l.since) * 1000 : null;
      const lim = l && since <= T && Number(l.until) * 1000 > T ? l : null;
      const jobs = [];
      for (const j0 of jobsOf(n)) {
        if (j0.state === "moved") { jobs.push(j0); continue; }  // when it left is not on record
        const sub = when(j0.submitted_at), go = when(j0.started_at), fin = when(j0.finished_at);
        const born = sub != null ? sub : go != null ? go : fin;
        if (born == null || born > T) continue;
        let state;
        if (fin != null && fin <= T) state = j0.state;
        else if (go != null && go <= T) {
          const putBack = j0.state === "inbox" || j0.state === "outgoing";  // started, then sent back to wait
          state = !putBack || (since != null && go < since && T < since) ? "running" : j0.state;
        } else state = j0.state === "outgoing" ? "outgoing" : "inbox";
        const j = Object.assign({}, j0, { state });
        if (state !== "done" && state !== "failed") Object.assign(j, { finished_at: null, duration_s: null, exit_code: null, pulled: false });
        if (state === "inbox" && (go == null || go > T)) j.started_at = null;
        if (state !== j0.state || (j.reason && /usage limit/i.test(j.reason) && !lim)) j.reason = null;
        jobs.push(j);
      }
      const c = (s) => jobs.filter((j) => j.state === s).length;
      const queue = Object.assign({}, st.queue, { inbox: c("inbox"), running: c("running"), done: c("done"), failed: c("failed"),
        unpulled: jobs.filter((j) => j.state === "done" && !j.pulled).length });
      return Object.assign({}, n, { status: Object.assign({}, st, { limit: lim, queue }), jobs, activity: recent ? n.activity : {} });
    });
    return Object.assign({}, snap, { nodes, replay: true, generated_at: new Date(T).toISOString(),
      screenings: (snap.screenings || []).filter((s) => (when(s.finished_at) || 0) <= T) });
  }
  // Each VPS's last 24 hours for the replay strip: its takes (done, failed or still rolling, or
  // stopped by the usage limit) and its holds, as [from, to, kind] in milliseconds.
  function spans(snap) {
    const t = Date.now(), t0 = t - DAY_MS;
    return ((snap && snap.nodes) || []).map((n) => {
      const out = [], st = n.status || {}, since = st.limit ? Number(st.limit.since) * 1000 : null;
      for (const j of jobsOf(n)) {
        const go = when(j.started_at);
        if (go == null || j.state === "moved") continue;
        let to = when(j.finished_at), kind = j.state;
        if (to == null) {
          if (j.state === "running") to = t;
          else if (since != null && since > go) { to = since; kind = "held"; } else continue;
        }
        if (to >= t0) out.push([Math.max(go, t0), Math.min(to, t), kind]);
      }
      if (st.limit) {
        const a = since, b = Math.min(t, Number(st.limit.until) * 1000);
        if (b > t0 && a < t) out.push([Math.max(a, t0), b, "hold"]);
      }
      return { name: n.name, reachable: !!n.reachable, spans: out };
    });
  }

  // ---------------------------------------------------------------- the replay strip
  // The last 24 hours, one row for each VPS, with a playhead. Drag or click it, or use the arrow
  // keys (10 minutes, or an hour with Shift), Page Up and Down (3 hours), Home and End. Calls
  // o.onPick(t) with the moment picked; set(snap, t) draws it (t null: now, live). o.palette
  // gives the colours, or a function that returns them (read again at each drawing).
  function strip(cv, o) {
    const base = { bg: "#111", row: "#232323", grid: "rgba(255,255,255,.16)", text: "#bdb7a8", done: "#4caf61",
      failed: "#e0533f", running: "#e3b54b", held: "#b59a45", hold: "#7d76c4", head: "#ffffff", font: "10px sans-serif", names: 0 };
    const colours = () => Object.assign({}, base, typeof o.palette === "function" ? o.palette() : o.palette || {});
    let rows = [], T = null, down = false, pal = colours();
    cv.tabIndex = 0;
    cv.style.touchAction = "none";
    cv.setAttribute("role", "slider");
    cv.setAttribute("aria-label", o.label || "Moment to replay, in the last 24 hours");
    cv.setAttribute("aria-valuemin", "0");
    cv.setAttribute("aria-valuemax", "1440");
    const range = () => { const t = Date.now(); return [t - DAY_MS, t]; };
    const inner = (w) => [pal.names, Math.max(10, w - pal.names - 3)];
    function draw() {
      pal = colours();
      const dpr = window.devicePixelRatio || 1, w = Math.max(60, cv.clientWidth), h = Math.max(16, cv.clientHeight);
      const bw = Math.round(w * dpr), bh = Math.round(h * dpr);
      if (cv.width !== bw || cv.height !== bh) { cv.width = bw; cv.height = bh; }
      const g = cv.getContext("2d"), [a, b] = range(), [x0, iw] = inner(w), axis = h >= 34 ? 12 : 0;
      const X = (t) => x0 + ((t - a) / (b - a)) * iw, n = Math.max(1, rows.length), rh = (h - axis) / n;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.fillStyle = pal.bg; g.fillRect(0, 0, w, h);
      g.font = pal.font;
      rows.forEach((r, i) => {
        const y = Math.round(i * rh) + 1, rr = Math.max(2, Math.round(rh) - 2);
        g.fillStyle = pal.row; g.fillRect(x0, y, iw, rr);
        if (pal.names) { g.fillStyle = pal.text; g.fillText(r.name, 2, y + rr / 2 + 4, pal.names - 6); }
        for (const [s, e, kind] of r.spans) {
          g.fillStyle = pal[kind] || pal.done;
          g.fillRect(Math.round(X(s)), y + (kind === "hold" ? Math.floor(rr / 3) : 0), Math.max(2, Math.round(X(e) - X(s))), kind === "hold" ? Math.max(1, Math.ceil(rr / 3)) : rr);
        }
      });
      for (let k = Math.ceil(a / 3600000) * 3600000; k <= b; k += 3600000) {
        const x = Math.round(X(k)), hr = new Date(k).getHours();
        g.fillStyle = pal.grid; g.fillRect(x, 0, 1, h - axis + (axis && hr % 6 === 0 ? 3 : 0));
        if (axis && hr % 6 === 0 && x + 30 < w) { g.fillStyle = pal.text; g.fillText(String(hr).padStart(2, "0") + ":00", x + 2, h - 2); }
      }
      const x = Math.round(X(T == null ? b : T));
      g.fillStyle = pal.head; g.fillRect(x - 1, 0, 2, h - axis + 2);
      g.fillRect(x - 3, 0, 6, 2);
    }
    function aria() {
      const [a, b] = range(), t = T == null ? b : T;
      cv.setAttribute("aria-valuenow", String(Math.round((t - a) / 60000)));
      cv.setAttribute("aria-valuetext", T == null ? "Now, live" : clock(t / 1000));
    }
    const tAt = (e) => {
      const r = cv.getBoundingClientRect(), [a, b] = range(), [x0, iw] = inner(r.width);
      return a + Math.max(0, Math.min(1, (e.clientX - r.left - x0) / iw)) * (b - a);
    };
    cv.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      down = true;
      try { cv.setPointerCapture(e.pointerId); } catch (err) { /* the drag ends where the pointer leaves */ }
      o.onPick(tAt(e));
    });
    cv.addEventListener("pointermove", (e) => { if (down) o.onPick(tAt(e)); });
    const up = () => { down = false; };
    cv.addEventListener("pointerup", up);
    cv.addEventListener("pointercancel", up);
    cv.addEventListener("keydown", (e) => {
      const [a, b] = range(), cur = T == null ? b : T, hr = 3600000;
      const to = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[e.key];
      let t = null;
      if (to) t = cur + to * (e.shiftKey ? hr : hr / 6);
      else if (e.key === "PageUp") t = cur - 3 * hr;
      else if (e.key === "PageDown") t = cur + 3 * hr;
      else if (e.key === "Home") t = a;
      else if (e.key === "End") t = b;
      if (t == null) return;
      e.preventDefault();
      o.onPick(Math.max(a, Math.min(b, t)));
    });
    return { set(snap, t) { rows = spans(snap); T = t == null ? null : t; aria(); draw(); }, draw };
  }

  // ---------------------------------------------------------------- the screening room
  // The finished videos you have collected (fleet pull), newest first, play here in a box over the
  // page. fleet studio serves them from your results folder on your PC; the example has none.
  let box = null;
  function play(s, art) {
    if (!box) {
      const css = document.createElement("style");
      css.textContent = ".fs-play{padding:0;border:3px solid #f4efe2;background:#141210;color:#f4efe2;max-width:min(96vw,760px);box-shadow:6px 6px 0 rgba(0,0,0,.45)}" +
        ".fs-play::backdrop{background:rgba(8,7,6,.72)}.fs-play .fs-head{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;padding:10px 12px 8px}" +
        ".fs-play b{font-size:16px;line-height:1.25}.fs-play small{display:block;color:#bdb7a8;font-size:12.5px;margin-top:3px}" +
        ".fs-play button{font:inherit;font-weight:600;font-size:13px;color:#141210;background:#f4efe2;border:0;padding:6px 9px;cursor:pointer}" +
        ".fs-play button:hover{background:#fff}.fs-play button:focus-visible{outline:3px solid #e3b54b;outline-offset:2px}" +
        ".fs-play .fs-body{background:#000;display:flex;justify-content:center}" +
        ".fs-play video,.fs-play .fs-art{display:block;max-width:100%;max-height:min(76vh,960px)}.fs-play .fs-art{image-rendering:pixelated;width:min(70vw,240px);height:auto}" +
        ".fs-play p{margin:0;padding:9px 12px 11px;font-size:13px;color:#d9d3c4;max-width:62ch}";
      document.head.appendChild(css);
      box = document.createElement("dialog");
      box.className = "fs-play";
      box.setAttribute("aria-label", "Screening room");
      box.innerHTML = '<div class="fs-head"><div><b></b><small></small></div><button type="button">Close</button></div><div class="fs-body"></div><p hidden></p>';
      document.body.appendChild(box);
      box.querySelector("button").addEventListener("click", () => box.close());
      box.addEventListener("click", (e) => { if (e.target === box) box.close(); });  // a click beside the box
      box.addEventListener("close", () => {
        const v = box.querySelector("video");
        if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
        box.querySelector(".fs-body").textContent = "";
      });
    }
    const t = when(s.finished_at);
    box.querySelector("b").textContent = s.title || s.id;
    box.querySelector("small").textContent = [s.channel, s.node, t ? "finished " + clock(t / 1000) : ""].filter(Boolean).join(" · ");
    const body = box.querySelector(".fs-body"), note = box.querySelector("p");
    body.textContent = "";
    if (s.video) {
      const v = document.createElement("video");
      v.controls = true; v.autoplay = true; v.playsInline = true; v.preload = "auto";
      if (s.poster) v.poster = s.poster;
      v.src = s.video;
      body.appendChild(v);
      note.hidden = true;
    } else {
      if (art) { art.classList.add("fs-art"); body.appendChild(art); }
      note.hidden = false;
      note.textContent = s.example ? "This is the example lot: there are no real videos here. On your PC, fleet studio plays the videos you have collected with fleet pull."
        : "This job left no video file that the studio can play.";
    }
    if (!box.open) { if (box.showModal) box.showModal(); else box.setAttribute("open", ""); }
    box.querySelector("button").focus();
  }

  // ---------------------------------------------------------------- the example lot
  // Five stages and a day of made-up jobs, with times relative to now. It moves on now and then:
  // a take ends, the next script starts, a new one comes in.
  const TITLES = {
    "Space Facts": ["The Great Red Spot", "How rockets steer", "Venus is hotter than Mercury", "The Oort cloud", "The life of a star", "Neutron stars", "Why Pluto is a dwarf planet"],
    History: ["The invention of paper", "Lighthouses of the ancient world", "The first coins", "Medieval castles", "The first calendars", "Canals that changed trade"],
    Nature: ["Why cats purr", "Fireflies", "Penguins in winter", "Coral reefs", "The monarch's long flight", "Tide pools"],
  };
  const STEPS = [{ kind: "tool", name: "WebSearch", detail: "facts and sources for the script" }, { kind: "tool", name: "Write", detail: "/home/fleet/fleet/work/script.md" },
    { kind: "tool", name: "Bash", detail: "Make the voice-over" }, { kind: "tool", name: "Bash", detail: "Render the 1080x1920 video with ffmpeg" },
    { kind: "text", text: "The video is rendered. Checking that it plays from start to end." }];
  // The starter ideas, as `fleet ideas` lists them until you change the list (STARTER_IDEAS in the CLI).
  const IDEAS = [
    { title: "Trend looker", note: "A zeppelin over the lot, coming later. It watches what blows up in each channel's niche, and Hermes proposes a video the same day. You say go, and it skips ahead in that channel's queue.", status: "idea" },
    { title: "Post everywhere", note: "Each short also goes to Facebook Reels and Pinterest, through their official APIs. Same video, more reach.", status: "idea" },
    { title: "Go multilingual", note: "A dubbed copy of each video in Spanish, Portuguese or Hindi, with translated captions, for extra channels.", status: "idea" },
    { title: "Answer comments early", note: "In a video's first hours, Hermes drafts replies on Telegram for you to send, and keeps viewers' questions as new topics.", status: "idea" },
    { title: "Titles people search for", note: "Before it names a video, Hermes checks what people search for and the videos it would compete with.", status: "idea" },
    { title: "Remake the hits", note: "When a video takes off, the Sunday plan suggests a part 2 or a new angle.", status: "idea" },
    { title: "Affiliate links", note: "Matching links from your own list go in each description, with the disclosure line.", status: "idea" },
    { title: "Run series", note: "Recurring formats like \"Part 3\" or \"Day 12 of...\", planned in the week plan, so viewers come back.", status: "idea" },
  ];
  let made = 0;
  function exampleJob(ch, o) {
    const t = when(o.submitted_at) || Date.now(), d = new Date(t), p = (x) => String(x).padStart(2, "0");
    made += 1;
    const id = d.getUTCFullYear() + p(d.getUTCMonth() + 1) + p(d.getUTCDate()) + "-" + p(d.getUTCHours()) + p(d.getUTCMinutes()) + p(d.getUTCSeconds()) +
      "-" + ch.toLowerCase().replace(/[^a-z0-9]+/g, "-") + "-" + ((made * 7919 + 104729) % 60466176).toString(36).padStart(5, "0").slice(-5);
    return Object.assign({ id, channel: ch, provider: "claude", attempts: 1, limit_waits: 0, pulled: false }, o);
  }
  function exampleLot() {
    const t = Date.now(), min = 60000, iso = (back) => new Date(t - back).toISOString();
    // a finished take: started a minutes ago, finished b minutes ago
    const past = (ch, title, a, b, o) => exampleJob(ch, Object.assign({ state: "done", title, submitted_at: iso((a + 6 + (a % 4) * 5) * min),
      started_at: iso(a * min), finished_at: iso(b * min), duration_s: (a - b) * 60, exit_code: 0, pulled: true }, o));
    const claude = [{ provider: "claude", installed: true, ok: true, version: "2.1.300 (Claude Code)", auth: "oauth-token", credential_age_days: 23 }];
    const status = (o) => Object.assign({ service: "active", heartbeat_age_s: 2, paused: false, limit: null, low_disk: false,
      disk_free_gb: 71.3, disk_free_pct: 74, min_free_gb: 5, load1: 0.4, cpus: 2, mem_available_mb: 6100, mem_total_mb: 7900,
      uptime_s: 12 * 86400 + 3 * 3600, max_parallel: 1, stuck_handovers: 0, reboot_required: false, worker_version: "1.8.0",
      providers: claude, queue: {} }, o);
    const SF = "Space Facts", HI = "History", CO = "Cooking", NA = "Nature";
    const snap = {
      demo: true, generated_at: iso(6000), every: 20, fleet_version: "1.8.0",
      ideas: IDEAS.map((i) => Object.assign({}, i)), ideas_starter: true,
      nodes: [
        { name: "vps1", channels: [SF], sessions: 1, reachable: true, status: status({ load1: 1.9 }),
          jobs: [
            exampleJob(SF, { state: "running", title: "Saturn's rings in 60 seconds", submitted_at: iso(31 * min), started_at: iso(12 * min + 41000) }),
            exampleJob(SF, { state: "inbox", title: "Europa's hidden ocean", submitted_at: iso(31 * min) }),
            exampleJob(SF, { state: "inbox", title: "The Kuiper belt", submitted_at: iso(31 * min) }),
            past(SF, "Why Mars is red", 120, 70, { pulled: false }), past(SF, "How big is the Sun?", 300, 240),
            past(SF, "How comets get their tails", 660, 612), past(SF, "Why the Moon has phases", 935, 880),
            past(SF, "The coldest place in space", 1190, 1132), past(SF, "What is a light year?", 1420, 1365),
          ] },
        { name: "vps2", channels: [HI], sessions: 1, reachable: true, status: status({ load1: 1.7, disk_free_gb: 68, disk_free_pct: 71, uptime_s: 3 * 86400 }),
          jobs: [
            exampleJob(HI, { state: "running", title: "The Library of Alexandria", submitted_at: iso(52 * min), started_at: iso(47 * min + 5000), attempts: 2, limit_waits: 1 }),
            exampleJob(HI, { state: "inbox", title: "Who built the pyramids?", submitted_at: iso(52 * min) }),
            past(HI, "Ancient Olympic games", 170, 110), past(HI, "The first postal service", 360, 300),
            past(HI, "How the printing press spread", 790, 720),
            past(HI, "The Silk Road", 842, 800, { state: "failed", exit_code: 1, reason: "Claude Code exited with code 1" }),
            past(HI, "The first maps", 1075, 1012), past(HI, "Roman roads", 1330, 1270),
          ] },
        { name: "vps3", channels: [CO], sessions: 1, reachable: true,
          status: status({ load1: 0.05, uptime_s: 40 * 86400, limit: { provider: "claude", kind: "weekly", message: "You've hit your weekly limit", since: (t - 120 * min) / 1000, until: (t + 38 * 60 * min) / 1000 } }),
          jobs: [
            exampleJob(CO, { state: "inbox", title: "Bread in three ingredients", submitted_at: iso(180 * min), started_at: iso(140 * min), limit_waits: 1, reason: "usage limit: You've hit your weekly limit; continues after the reset" }),
            exampleJob(CO, { state: "outgoing", title: "The perfect boiled egg", submitted_at: iso(180 * min), reason: "being handed over to vps4" }),
            past(CO, "Knife skills for beginners", 480, 300, { state: "failed", exit_code: 124, reason: "timed out after 180m" }),
            past(CO, "Crispy roast potatoes", 900, 845), past(CO, "Tomato sauce from scratch", 1150, 1090), past(CO, "Fluffy pancakes", 1400, 1340),
          ] },
        { name: "vps4", channels: [NA], sessions: 1, reachable: true, status: status({ disk_free_gb: 74.9, disk_free_pct: 78, load1: 0.1, reboot_required: true,
            schedule: { open: false, kind: "gap", reason: "pause after a video", until: (t + 35 * min) / 1000, tz: "UTC",
              summary: "works around the clock; a 1h pause after each video" } }),
          jobs: [
            past(NA, "How octopuses change colour", 120, 25, { pulled: false }), past(NA, "How whales sleep", 610, 560),
            past(NA, "The secret life of bees", 1000, 950), past(NA, "Why leaves change colour", 1260, 1205),
          ] },
        { name: "vps5", channels: ["Mysteries"], sessions: 1, reachable: false, error: "ssh: connect to host vps5 port 22: Connection timed out" },
      ],
    };
    snap.screenings = [];
    for (const n of snap.nodes) {
      if (!n.reachable) continue;
      recount(n);
      for (const j of n.jobs) if (j.state === "done") snap.screenings.push(screening(n, j));
    }
    snap.screenings.sort((a, b) => when(b.finished_at) - when(a.finished_at));
    busy(snap);
    return snap;
  }
  const screening = (n, j) => ({ node: n.name, id: j.id, channel: j.channel, title: j.title, finished_at: j.finished_at, video: null, poster: null, example: true });
  function recount(n) {  // the queue as the worker would count it
    const c = (s) => n.jobs.filter((j) => j.state === s).length;
    n.status.queue = { inbox: c("inbox"), running: c("running"), done: c("done"), failed: c("failed"), unpulled: n.jobs.filter((j) => j.state === "done" && !j.pulled).length };
  }
  function busy(snap) {  // what each example session is doing, a new step every 40 seconds
    const t = Date.now();
    for (const n of snap.nodes) {
      if (!n.reachable) continue;
      n.activity = {};
      for (const j of n.jobs.filter((x) => x.state === "running")) {
        const k = Math.floor((t - when(j.started_at)) / 40000);
        n.activity[j.id] = Object.assign({ mtime: (t - 4000 - (k % 3) * 5000) / 1000 }, STEPS[Math.max(0, k) % STEPS.length]);
      }
    }
  }
  let turn = 0;
  function move(snap) {  // one stage moves on: its take ends, its next script starts or one comes in
    const t = Date.now(), iso = (x) => new Date(x).toISOString();
    for (const n of snap.nodes) {  // an example pause that is over ends
      const s = n.status && n.status.schedule;
      if (s && s.until && Number(s.until) * 1000 <= t) n.status.schedule = null;
    }
    const open = snap.nodes.filter((n) => n.reachable && !(n.status.limit && Number(n.status.limit.until) * 1000 > t)
      && !(n.status.schedule && n.status.schedule.open === false));
    if (!open.length) return;
    const n = open[turn++ % open.length], ch = n.channels[0], list = TITLES[ch] || [ch + " #" + (turn + 1)];
    const fresh = () => exampleJob(ch, { state: "inbox", title: list[(made + turn) % list.length], submitted_at: iso(t - 60000) });
    const run = n.jobs.find((j) => j.state === "running");
    if (run) {
      Object.assign(run, { state: "done", finished_at: iso(t), duration_s: Math.round((t - when(run.started_at)) / 1000), exit_code: 0 });
      snap.screenings.unshift(screening(n, run));
      snap.screenings.length = Math.min(snap.screenings.length, 24);
    }
    let next = n.jobs.find((j) => j.state === "inbox");
    if (!run && !next) { next = fresh(); n.jobs.unshift(next); }
    if (next) Object.assign(next, { state: "running", started_at: iso(t) });
    if (run && n.jobs.filter((j) => j.state === "inbox").length < 1) n.jobs.unshift(fresh());
    n.jobs = n.jobs.filter((j) => j.state !== "done" && j.state !== "failed" || when(j.finished_at) > t - DAY_MS).slice(0, 14);
    recount(n);
  }

  // Calls onLook(snapshot, contact) after every look at the lot: every 5 seconds from
  // fleet studio on your PC, or every 20 seconds for the example (which moves on every 75).
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
      const look = () => { snap.generated_at = new Date().toISOString(); busy(snap); onLook(snap, true); };
      onLook(snap, true);
      setInterval(look, 20000);
      setInterval(() => { move(snap); look(); }, 75000);
    }
  }

  window.FleetStudio = { LIVE, POLL_MS, DAY_MS, now, setNow, when, ago, span, timecode, clock, localTimes, hueOf, stageNo, plural,
    VERBS, activityText, jobsOf, claudeOf, limitOf, scheduleOf, offNote, finishedSince, stageState, at, spans, strip, play, exampleLot, watch };
})();
