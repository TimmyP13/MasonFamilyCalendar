(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const state = {
    data: null,
    building: null,   // building code, or "district"
    sports: "none",   // "none" | "all" | "sport:<code>"
  };

  const CATEGORY_COLORS = {
    "no-school": "var(--c-noschool)",
    "journey": "var(--c-journey)",
    "holiday": "var(--c-holiday)",
    "first-last": "var(--c-firstlast)",
    "event": "var(--c-event)",
    "sports": "var(--c-sports)",
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
    const { building, sports } = state;
    if (!building) return null;

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

    document.querySelectorAll("#buildingGrid .card").forEach((c) => {
      c.setAttribute("aria-checked", String(c.dataset.building === code));
    });
    document.querySelectorAll("#sportsStep .card").forEach((c) => {
      c.setAttribute("aria-checked", String(c.dataset.sports === "none"));
    });
    document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));

    // Sports only make sense for the high school.
    $("sportsStep").classList.toggle("is-hidden", code !== "mhs");
    $("subscribeStep").classList.remove("is-hidden");

    renderSubscribe();
    const target = code === "mhs" ? "sportsStep" : "subscribeStep";
    $(target).scrollIntoView({ behavior: "smooth", block: "start" });
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

  function renderPreview(file) {
    const box = $("preview");
    const audience = state.building;
    const isSportsOnly = file.startsWith("varsity-");
    const sportCode = file.startsWith("varsity-") && file !== "varsity-all.ics"
      ? file.replace(/^varsity-|\.ics$/g, "")
      : null;
    const includesSports = isSportsOnly || file === "mhs-varsity.ics";

    let rows = [];
    if (!isSportsOnly) rows = rows.concat(academicRows(audience));
    if (includesSports) rows = rows.concat(sportsRows(sportCode));
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
    })
    .catch((err) => {
      $("freshness").textContent = "Could not load calendar data: " + err.message;
      console.error(err);
    });
})();
