(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const state = {
    data: null,
    building: null,   // building code, or "district"
    sports: "none",   // "none" | "all" | "sport:<code>"
    pto: "none",      // "none" | "all" | "only"
    ptoToken: null,   // secret filename component, derived from the code
    ptoEvents: null,  // loaded lazily once unlocked
  };

  // --- SHA-256 ------------------------------------------------------------
  // Written out rather than using crypto.subtle, which is unavailable on
  // file:// pages (not a secure context) and would break the offline preview.
  const sha256Hex = (() => {
    const K = new Uint32Array([
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
      0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
      0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
      0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
      0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
      0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ]);
    const rr = (x, n) => (x >>> n) | (x << (32 - n));

    return function (str) {
      const bytes = new TextEncoder().encode(str);
      const len = bytes.length;
      const blocks = Math.ceil((len + 9) / 64);
      const buf = new Uint8Array(blocks * 64);
      buf.set(bytes);
      buf[len] = 0x80;
      const dv = new DataView(buf.buffer);
      const bits = len * 8;
      dv.setUint32(blocks * 64 - 8, Math.floor(bits / 4294967296));
      dv.setUint32(blocks * 64 - 4, bits >>> 0);

      const H = new Uint32Array([
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
      ]);
      const w = new Uint32Array(64);

      for (let b = 0; b < blocks; b++) {
        for (let i = 0; i < 16; i++) w[i] = dv.getUint32(b * 64 + i * 4);
        for (let i = 16; i < 64; i++) {
          const x = w[i - 15], y = w[i - 2];
          const s0 = rr(x, 7) ^ rr(x, 18) ^ (x >>> 3);
          const s1 = rr(y, 17) ^ rr(y, 19) ^ (y >>> 10);
          w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
        }
        let a = H[0], bb = H[1], c = H[2], d = H[3];
        let e = H[4], f = H[5], g = H[6], h = H[7];
        for (let i = 0; i < 64; i++) {
          const S1 = rr(e, 6) ^ rr(e, 11) ^ rr(e, 25);
          const ch = (e & f) ^ (~e & g);
          const t1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
          const S0 = rr(a, 2) ^ rr(a, 13) ^ rr(a, 22);
          const maj = (a & bb) ^ (a & c) ^ (bb & c);
          const t2 = (S0 + maj) >>> 0;
          h = g; g = f; f = e; e = (d + t1) >>> 0;
          d = c; c = bb; bb = a; a = (t1 + t2) >>> 0;
        }
        H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + bb) >>> 0;
        H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
        H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0;
        H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
      }
      return Array.from(H, (x) => x.toString(16).padStart(8, "0")).join("");
    };
  })();

  // Must mirror scripts/build.py exactly.
  const normalizeCode = (s) => s.trim().split(/\s+/).join(" ").toLowerCase();
  const ptoGateHash = (code) => sha256Hex("mfc-pto-gate:" + normalizeCode(code));
  const ptoFeedToken = (code) => sha256Hex("mfc-pto-feed:" + normalizeCode(code)).slice(0, 24);

  const CATEGORY_COLORS = {
    "no-school": "var(--c-noschool)",
    "journey": "var(--c-journey)",
    "holiday": "var(--c-holiday)",
    "first-last": "var(--c-firstlast)",
    "event": "var(--c-event)",
    "sports": "var(--c-sports)",
    "pto-meeting": "var(--c-pto-meeting)",
    "pto-event": "var(--c-pto-event)",
    "school": "var(--c-school)",
    "staff": "var(--c-staff)",
    "observance": "var(--c-observance)",
  };

  // ---------------------------------------------------------------- helpers

  // Base URL is derived from where this page is actually served, so the
  // subscribe links keep working no matter which host it ends up on.
  const siteBase = new URL(".", location.href).href.replace(/\/$/, "");

  const feedUrl = (file) => `${siteBase}/feeds/${file}`;
  const webcalUrl = (file) => feedUrl(file).replace(/^https?:/, "webcal:");

  function fmtDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
      weekday: "short", month: "short", day: "numeric", timeZone: "UTC",
    });
  }

  function fmtRange(startIso, endIso) {
    if (startIso === endIso) return fmtDate(startIso);
    const a = fmtDate(startIso);
    const b = fmtDate(endIso);
    return `${a} – ${b}`;
  }

  function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("show"), 2600);
  }

  // ------------------------------------------------------------ feed choice

  function chosenFeed() {
    const { building, sports, pto, ptoToken } = state;
    if (!building) return null;

    if (building === "mecc" && ptoToken) {
      if (pto === "only") {
        return { file: `pto-${ptoToken}.ics`, label: "MECC PTO events only" };
      }
      if (pto === "all") {
        return { file: `mecc-pto-${ptoToken}.ics`, label: "MECC (PK–2) + PTO calendar" };
      }
    }

    if (sports.startsWith("sport:")) {
      const code = sports.slice(6);
      return {
        file: `varsity-${code}.ics`,
        label: labelForSport(code),
      };
    }
    if (building === "mhs" && sports === "all") {
      return { file: "mhs-varsity.ics", label: "Mason High School (9–12) + all varsity sports" };
    }
    if (sports === "all") {
      // non-MHS building that still wants sports: give them the combined name
      return { file: "varsity-all.ics", label: "MHS varsity athletics — all sports" };
    }
    if (building === "district") {
      return { file: "district.ics", label: "Mason City Schools — whole district" };
    }
    const b = state.data.buildings.find((x) => x.code === building);
    return { file: `${building}.ics`, label: `${b.name} (grades ${b.grades})` };
  }

  function labelForSport(code) {
    const f = state.data.feeds.find((x) => x.sport === code);
    return f ? `MHS ${f.title}` : `MHS varsity ${code}`;
  }

  // ------------------------------------------------------------------ views

  function renderBuildings() {
    const grid = $("buildingGrid");
    grid.innerHTML = "";

    const options = state.data.buildings.map((b) => ({
      code: b.code,
      title: `${b.abbr} — grades ${b.grades}`,
      sub: b.published ? b.blurb : "Not built yet. MECC and the high school came first.",
      disabled: !b.published,
      name: b.name,
    }));

    options.push({
      code: "district",
      title: "Whole district",
      sub: "Kids in more than one building? Every district-wide date, nothing school-specific.",
      disabled: false,
      name: "Mason City Schools",
    });

    for (const opt of options) {
      const btn = document.createElement("button");
      btn.className = "card";
      btn.type = "button";
      btn.setAttribute("role", "radio");
      btn.setAttribute("aria-checked", "false");
      btn.dataset.building = opt.code;
      btn.disabled = opt.disabled;
      btn.innerHTML = `
        <span class="card-title">${opt.title}</span>
        <span class="card-sub">${opt.sub}</span>
        ${opt.disabled ? '<span class="card-tag">Coming soon</span>' : ""}`;
      btn.addEventListener("click", () => selectBuilding(opt.code));
      grid.appendChild(btn);
    }
  }

  function selectBuilding(code) {
    state.building = code;
    state.sports = "none";
    state.pto = "none";

    document.querySelectorAll("#buildingGrid .card").forEach((c) => {
      c.setAttribute("aria-checked", String(c.dataset.building === code));
    });
    document.querySelectorAll("#sportsStep .card").forEach((c) => {
      c.setAttribute("aria-checked", String(c.dataset.sports === "none"));
    });
    document.querySelectorAll("#ptoStep .card").forEach((c) => {
      c.setAttribute("aria-checked", String(c.dataset.pto === "none"));
    });
    document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));

    // Sports only make sense for the high school; PTO only for MECC.
    const ptoAvailable = code === "mecc" && state.data.pto && state.data.pto.enabled;
    $("sportsStep").classList.toggle("is-hidden", code !== "mhs");
    $("ptoStep").classList.toggle("is-hidden", !ptoAvailable);
    $("subscribeStep").classList.remove("is-hidden");

    renderSubscribe();
    const target = code === "mhs" ? "sportsStep" : ptoAvailable ? "ptoStep" : "subscribeStep";
    $(target).scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function unlockPto(code) {
    const msg = $("ptoCodeMsg");
    const input = $("ptoCode");

    if (ptoGateHash(code) !== state.data.pto.gateHash) {
      msg.textContent = "That code isn't right. Check with the MECC PTO — it's case-insensitive.";
      msg.className = "codemsg bad";
      input.setAttribute("aria-invalid", "true");
      return false;
    }

    state.ptoToken = ptoFeedToken(code);
    input.removeAttribute("aria-invalid");
    msg.textContent = `Unlocked — ${state.data.pto.eventCount} PTO events added.`;
    msg.className = "codemsg ok";
    $("ptoCardAll").classList.add("unlocked");
    $("ptoCardSub").textContent = `${state.data.pto.eventCount} PTO events across the school year.`;
    $("ptoCardAll").querySelector(".lock").textContent = "✓";
    $("ptoOnlyWrap").hidden = false;

    try { sessionStorage.setItem("mfc_pto", code); } catch { /* private mode */ }

    selectPto("all");

    // Load the event list for the preview. It lives behind the same token, so
    // the PTO schedule is not readable from the public calendar.json.
    if (!state.ptoEvents && window.__PTO_EVENTS__) {
      state.ptoEvents = window.__PTO_EVENTS__;
      renderSubscribe();
    } else if (!state.ptoEvents) {
      fetch(`pto-${state.ptoToken}.json`, { cache: "no-cache" })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (d) { state.ptoEvents = d.events; renderSubscribe(); } })
        .catch(() => { /* preview is optional; the feed still works */ });
    }
    return true;
  }

  function selectPto(choice) {
    state.pto = choice;
    document.querySelectorAll("#ptoStep .card").forEach((c) => {
      c.setAttribute("aria-checked", String(c.dataset.pto === choice));
    });
    $("ptoOnlyChip").setAttribute("aria-pressed", String(choice === "only"));
    renderSubscribe();
  }

  function renderSportChips() {
    const wrap = $("sportChips");
    const sportFeeds = state.data.feeds.filter((f) => f.kind === "sport");
    wrap.innerHTML = "";

    if (!sportFeeds.length) {
      wrap.innerHTML = '<p class="chip-empty">No sport schedules published yet for 2026–2027. ' +
        'This fills in automatically once Mason athletics posts them.</p>';
      return;
    }
    for (const f of sportFeeds) {
      const b = document.createElement("button");
      b.className = "chip";
      b.type = "button";
      b.setAttribute("aria-pressed", "false");
      b.textContent = `${f.title} (${f.events})`;
      b.addEventListener("click", () => {
        state.sports = `sport:${f.sport}`;
        document.querySelectorAll("#sportsStep .card").forEach((c) => c.setAttribute("aria-checked", "false"));
        document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true");
        renderSubscribe();
        $("subscribeStep").scrollIntoView({ behavior: "smooth", block: "start" });
      });
      wrap.appendChild(b);
    }
  }

  function renderSubscribe() {
    const feed = chosenFeed();
    if (!feed) return;

    const https = feedUrl(feed.file);
    const webcal = webcalUrl(feed.file);
    const meta = state.data.feeds.find((f) => f.file === feed.file);
    const count = meta ? meta.events : 0;
    const name = `${feed.label} — Mason Family Calendar`;

    $("chosenLabel").innerHTML =
      `You picked <strong>${feed.label}</strong> — ${count} ${count === 1 ? "date" : "dates"} in this feed.`;

    $("btnApple").href = webcal;
    $("btnGoogle").href =
      "https://calendar.google.com/calendar/r?cid=" + encodeURIComponent(webcal);
    $("btnOutlook").href =
      "https://outlook.live.com/calendar/0/addfromweb?url=" + encodeURIComponent(https) +
      "&name=" + encodeURIComponent(name);
    $("feedUrl").value = https;
    $("downloadLink").href = https;

    renderPreview(feed.file);
  }

  function fmtTime(hhmm) {
    if (!hhmm) return "";
    const [h, m] = hhmm.split(":").map(Number);
    const suffix = h >= 12 ? "pm" : "am";
    const hour12 = h % 12 === 0 ? 12 : h % 12;
    return m === 0 ? `${hour12}${suffix}` : `${hour12}:${String(m).padStart(2, "0")}${suffix}`;
  }

  function academicRows(audience) {
    return state.data.academicEvents
      .filter((e) => {
        const auds = e.audiences || ["all"];
        if (audience === "district") return auds.includes("all");
        return auds.includes("all") || auds.includes(audience);
      })
      .map((e) => {
        const override = (e.byAudience || {})[audience];
        const summary = override && override.summary ? override.summary : e.summary;
        return {
          sort: e.start,
          date: fmtRange(e.start, e.end),
          summary,
          color: CATEGORY_COLORS[e.category] || "var(--ink-3)",
        };
      });
  }

  function sportsRows(sportCode) {
    return (state.data.sportsEvents || [])
      .filter((g) => !sportCode || g.sport === sportCode)
      .map((g) => ({
        sort: g.date + (g.time || ""),
        date: fmtDate(g.date) + (g.time ? ` · ${fmtTime(g.time)}` : ""),
        summary: g.summary,
        color: CATEGORY_COLORS.sports,
      }));
  }

  function ptoRows() {
    return (state.ptoEvents || []).map((e) => ({
      sort: e.start + (e.time || ""),
      date: fmtRange(e.start, e.end) + (e.time ? ` · ${fmtTime(e.time)}` : ""),
      summary: e.summary,
      color: CATEGORY_COLORS[e.category] || "var(--c-pto-event)",
    }));
  }

  function renderPreview(file) {
    const box = $("preview");
    const audience = state.building;
    const isSportsOnly = file.startsWith("varsity-");
    const sportCode = file.startsWith("varsity-") && file !== "varsity-all.ics"
      ? file.replace(/^varsity-|\.ics$/g, "")
      : null;
    const includesSports = isSportsOnly || file === "mhs-varsity.ics";
    const isPtoOnly = file.startsWith("pto-");
    const includesPto = isPtoOnly || file.startsWith("mecc-pto-");

    let rows = [];
    if (!isSportsOnly && !isPtoOnly) rows = rows.concat(academicRows(audience));
    if (includesSports) rows = rows.concat(sportsRows(sportCode));
    if (includesPto) rows = rows.concat(ptoRows());
    rows.sort((a, b) => (a.sort < b.sort ? -1 : a.sort > b.sort ? 1 : 0));

    let note = "";
    if (includesSports && state.data.sports.gameCount === 0) {
      note = `<p class="help"><strong>No 2026–2027 games are posted by Mason athletics yet.</strong>
        The feed is live and checks daily — games appear on their own, no need to re-subscribe.</p>`;
    }

    if (!rows.length) {
      box.innerHTML = `<h3>What you'll get</h3>${note}`;
      return;
    }

    const html = rows.map((r) => `<li>
        <span class="evdate">${r.date}</span>
        <span class="evname"><span class="dot" style="background:${r.color}"></span>${r.summary}</span>
      </li>`).join("");

    box.innerHTML = `<h3>Everything in this feed</h3>${note}<ul class="evlist">${html}</ul>`;
  }

  function renderLegend() {
    const legend = $("legend");
    const entries = [
      ["first-last", "First / last day"],
      ["no-school", "No school (staff work day)"],
      ["journey", "Journey Day"],
      ["holiday", "Holiday or break"],
      ["event", "School event"],
      ["sports", "Athletics"],
      ["pto-event", "PTO event"],
      ["pto-meeting", "PTO meeting"],
      ["school", "School day info"],
      ["staff", "Staff appreciation"],
      ["observance", "Cultural / religious observance"],
    ];
    legend.innerHTML = entries.map(([k, label]) =>
      `<span><span class="dot" style="background:${CATEGORY_COLORS[k]}"></span>${label}</span>`
    ).join("");
  }

  function renderAllDates() {
    const box = $("allDates");
    const byMonth = new Map();
    for (const e of state.data.academicEvents) {
      const key = e.start.slice(0, 7);
      if (!byMonth.has(key)) byMonth.set(key, []);
      byMonth.get(key).push(e);
    }
    const parts = [];
    for (const [key, events] of [...byMonth.entries()].sort()) {
      const [y, m] = key.split("-").map(Number);
      const title = new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-US",
        { month: "long", year: "numeric", timeZone: "UTC" });
      const rows = events.map((e) => {
        const color = CATEGORY_COLORS[e.category] || "var(--ink-3)";
        const scope = (e.audiences || ["all"]).includes("all")
          ? ""
          : ` <em>(${(e.audiences || []).map((a) => a.toUpperCase()).join(", ")})</em>`;
        return `<li><span class="evdate">${fmtRange(e.start, e.end)}</span>
          <span class="evname"><span class="dot" style="background:${color}"></span>${e.summary}${scope}</span></li>`;
      }).join("");
      parts.push(`<div class="month"><h4>${title}</h4><ul class="evlist">${rows}</ul></div>`);
    }
    box.innerHTML = parts.join("");
  }

  function renderStatus() {
    const s = state.data.sports;
    const built = new Date(state.data.generated);
    $("builtAt").textContent =
      `Feeds last rebuilt ${built.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}. ` +
      `Rebuilt automatically every day.`;
    $("freshness").textContent =
      `${state.data.feeds.length} feeds · ${state.data.year} school year · rebuilt ` +
      `${built.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;

    const el = $("sportsStatusText");
    if (s.gameCount > 0) {
      el.innerHTML = `${s.gameCount} varsity events across ${s.sports.length} sports, ` +
        `pulled from ${s.sourcesChecked} published schedule PDFs.`;
    } else {
      el.innerHTML = `Mason athletics has not posted its 2026–2027 schedules yet — as of the last ` +
        `check, the site still had last season's PDFs up. The sports feeds are live and valid ` +
        `but empty. They fill in automatically within a day of the new schedules going up, ` +
        `so you can subscribe now and forget about it.`;
    }

    $("allSportsSub").textContent = s.gameCount > 0
      ? `${s.gameCount} varsity events across ${s.sports.length} sports.`
      : "Live now, fills in automatically when Mason posts the new schedules.";
  }

  // ------------------------------------------------------------------ wire

  function wireStaticHandlers() {
    document.querySelectorAll("#sportsStep .card").forEach((card) => {
      card.addEventListener("click", () => {
        state.sports = card.dataset.sports;
        document.querySelectorAll("#sportsStep .card").forEach((c) =>
          c.setAttribute("aria-checked", String(c === card)));
        document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
        renderSubscribe();
      });
    });

    document.querySelectorAll("#ptoStep .card").forEach((card) => {
      card.addEventListener("click", () => {
        const choice = card.dataset.pto;
        if (choice === "all" && !state.ptoToken) {
          $("ptoCode").focus();
          $("ptoCodeMsg").textContent = "Enter the PTO access code to unlock this option.";
          $("ptoCodeMsg").className = "codemsg";
          return;
        }
        selectPto(choice);
      });
    });

    $("ptoForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const code = $("ptoCode").value;
      if (!code.trim()) return;
      if (unlockPto(code)) {
        $("subscribeStep").scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });

    $("ptoOnlyChip").addEventListener("click", () => {
      if (!state.ptoToken) return;
      selectPto("only");
      $("subscribeStep").scrollIntoView({ behavior: "smooth", block: "start" });
    });

    $("btnCopy").addEventListener("click", async () => {
      const value = $("feedUrl").value;
      try {
        await navigator.clipboard.writeText(value);
        toast("Feed link copied");
      } catch {
        $("feedUrl").select();
        toast("Press ⌘C / Ctrl+C to copy");
      }
    });

    $("feedUrl").addEventListener("focus", (e) => e.target.select());

    $("reportLink").addEventListener("click", (e) => {
      e.preventDefault();
      toast("Add your contact or GitHub issues link here");
    });
  }

  // ------------------------------------------------------------------ init

  // A self-contained preview build inlines the data as window.__CALENDAR__ so the
  // page works from a file:// URL with no server. Otherwise fetch it normally.
  const load = window.__CALENDAR__
    ? Promise.resolve(window.__CALENDAR__)
    : fetch("calendar.json", { cache: "no-cache" }).then((r) => {
        if (!r.ok) throw new Error(`calendar.json ${r.status}`);
        return r.json();
      });

  load
    .then((data) => {
      state.data = data;
      renderBuildings();
      renderSportChips();
      renderLegend();
      renderAllDates();
      renderStatus();
      wireStaticHandlers();

      // Remember an unlocked code for the rest of the browser session, so
      // going back to change a choice does not mean typing it again.
      if (data.pto && data.pto.enabled) {
        try {
          const saved = sessionStorage.getItem("mfc_pto");
          if (saved && ptoGateHash(saved) === data.pto.gateHash) {
            $("ptoCode").value = saved;
          }
        } catch { /* private mode */ }
      }
    })
    .catch((err) => {
      $("freshness").textContent = "Could not load calendar data: " + err.message;
      console.error(err);
    });
})();
