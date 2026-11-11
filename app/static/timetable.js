// Section « Emploi du temps » : vue semaine (grille horaire) ou agenda (mobile), couleurs pastel par matière.
// Utilise les fonctions globales de la page (el, $, icon, hue) et la constante LESSONS.
(() => {
  const PH = 62;                       // pixels par heure (grille)
  const root = $("#timetable");
  const mq = matchMedia("(max-width: 760px)");
  const lessons = LESSONS.map(l => ({ ...l, s: new Date(l.start), e: new Date(l.end) }));
  const DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
  const hm = d => d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const dayFmt = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long" });
  const pretty = s => { const t = s.replace(/&amp;/g, "&").trim().toLowerCase(); return t.charAt(0).toUpperCase() + t.slice(1); };
  const short = s => { const t = pretty(s); return t.length > 26 ? t.slice(0, 25) + "…" : t; };
  const ymd = d => d.toLocaleDateString("sv-SE");
  const monday = d => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return x; };
  const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };

  const weeks = lessons.map(l => +monday(l.s));
  const minWeek = weeks.length ? Math.min(...weeks) : +monday(new Date());
  const maxWeek = weeks.length ? Math.max(...weeks) : +monday(new Date());
  let weekStart = monday(new Date());
  if (+weekStart < minWeek) weekStart = new Date(minWeek);
  if (+weekStart > maxWeek) weekStart = new Date(maxWeek);

  const svc = (tag, cls, text) => el(tag, cls, text);

  // ---- « en ce moment » / « prochain cours » ----
  function nowInfo() {
    const now = new Date();
    const live = lessons.filter(l => !l.canceled && l.s <= now && now < l.e);
    const cur = live[0];
    if (cur) return { kind: "now", text: `En ce moment : ${pretty(cur.subject)}${cur.room ? " · salle " + cur.room : ""}, jusqu'à ${hm(cur.e)}`, l: cur };
    const next = lessons.filter(l => !l.canceled && l.s > now).sort((a, b) => a.s - b.s)[0];
    if (!next) return null;
    const diff = Math.round((new Date(next.s.getFullYear(), next.s.getMonth(), next.s.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5);
    const when = diff === 0 ? "aujourd'hui" : diff === 1 ? "demain" : DAYS[(next.s.getDay() + 6) % 7] + " " + next.s.getDate();
    return { kind: "next", text: `Prochain cours : ${pretty(next.subject)}, ${when} à ${hm(next.s)}${next.room ? " · salle " + next.room : ""}`, l: next };
  }

  // ---- placement côte à côte des cours simultanés ----
  function lanes(items) {
    let cluster = [], end = 0;
    const flush = () => { const n = Math.max(...cluster.map(x => x.lane)) + 1; cluster.forEach(x => x.lanes = n); };
    for (const it of [...items].sort((a, b) => a.s - b.s || a.e - b.e)) {
      if (cluster.length && +it.s >= end) { flush(); cluster = []; end = 0; }
      const used = cluster.filter(x => +x.e > +it.s).map(x => x.lane);
      let lane = 0; while (used.includes(lane)) lane++;
      it.lane = lane; cluster.push(it); end = Math.max(end, +it.e);
    }
    if (cluster.length) flush();
    return items;
  }

  function badges(l) {
    const out = [];
    if (l.canceled) out.push(["Annulé", "bad"]);
    else if (l.status) out.push([l.status, "warn"]);
    if (l.test) out.push(["Contrôle", "test"]);
    if (l.detention) out.push(["Retenue", "bad"]);
    if (l.outing) out.push(["Sortie", "warn"]);
    return out;
  }
  const details = l => [`${pretty(l.subject)}`, `${hm(l.s)} – ${hm(l.e)}`, l.room && "Salle " + l.room, l.teacher, l.status, l.memo].filter(Boolean).join("\n");

  function lessonEl(l, tall) {
    const e = svc("div", "tt-lesson" + (l.canceled ? " canceled" : "")); e.style.setProperty("--h", hue(l.subject)); e.title = details(l);
    // même illustration de fond que les cartes de devoirs (voile blanc à gauche pour la lisibilité) ; pas pour un cours annulé (hachuré)
    const bg = !l.canceled && bgOf(l.subject);
    if (bg) { e.classList.add("bg"); e.style.backgroundImage = `var(--veil), url(/static/fonds/${bg}.jpg)`; }
    const head = svc("div", "tt-subj"); head.append(svc("span", "tt-ico", icon(l.subject)), svc("span", null, short(l.subject)));
    e.append(head);
    const bs = badges(l);
    // « full » : tout ; « notime » : sans l'horaire (déjà lisible sur l'axe) pour laisser la place aux pastilles ; « short » : titre + horaire ou pastilles
    if (tall === "full" || (tall === "short" && !bs.length)) e.append(svc("div", "tt-time", `${hm(l.s)} – ${hm(l.e)}`));
    const meta = [l.room && "Salle " + l.room, l.teacher].filter(Boolean).join(" · ");
    if (meta && (tall === "full" || tall === "notime" || tall === true)) e.append(svc("div", "tt-meta", meta));
    if (bs.length) { const b = svc("div", "tt-badges"); for (const [t, k] of bs) b.append(svc("span", "tt-badge " + k, t)); e.append(b); }
    const now = new Date(); if (!l.canceled && l.s <= now && now < l.e) e.classList.add("live");
    return e;
  }

  // ---- grille horaire ----
  function grid(days, byDay) {
    const all = lessons;
    const h0 = Math.min(8, Math.floor(Math.min(...all.map(l => l.s.getHours() + l.s.getMinutes() / 60))));
    const h1 = Math.max(17, Math.ceil(Math.max(...all.map(l => l.e.getHours() + l.e.getMinutes() / 60))));
    const g = svc("div", "tt-grid"); g.style.setProperty("--n", days.length); g.style.setProperty("--ph", PH + "px");
    g.append(svc("div", "tt-corner"));
    const today = ymd(new Date());
    for (const d of days) {
      const h = svc("div", "tt-dayhead" + (ymd(d) === today ? " today" : ""));
      h.append(svc("span", null, DAYS[(d.getDay() + 6) % 7]), svc("b", null, d.getDate())); g.append(h);
    }
    const hours = svc("div", "tt-hours"); hours.style.height = (h1 - h0) * PH + 14 + "px";
    for (let h = h0; h <= h1; h++) { const t = svc("div", null, h + " h"); t.style.top = (h - h0) * PH + "px"; hours.append(t); }
    g.append(hours);
    for (const d of days) {
      const col = svc("div", "tt-col" + (ymd(d) === today ? " today" : "")); col.style.height = (h1 - h0) * PH + 14 + "px";
      for (const l of lanes(byDay[ymd(d)] || [])) {
        const top = (l.s.getHours() + l.s.getMinutes() / 60 - h0) * PH, hgt = Math.max(24, (l.e - l.s) / 36e5 * PH - 3);
        const hasB = badges(l).length;
        const b = lessonEl(l, hgt >= 80 ? "full" : hgt >= 52 ? (hasB ? "notime" : "full") : hgt >= 38 ? "short" : "min");
        if (hgt < 38) b.classList.add("tiny");
        b.style.top = top + "px"; b.style.height = hgt + "px";
        b.style.left = `calc(${l.lane / l.lanes * 100}% + 2px)`; b.style.width = `calc(${100 / l.lanes}% - 4px)`;
        col.append(b);
      }
      if (ymd(d) === today) {
        const n = new Date(), y = (n.getHours() + n.getMinutes() / 60 - h0) * PH;
        if (y >= 0 && y <= (h1 - h0) * PH) { const line = svc("div", "tt-now"); line.style.top = y + "px"; line.title = hm(n); col.append(line); }
      }
      g.append(col);
    }
    return g;
  }

  // ---- agenda (mobile) ----
  function agenda(days, byDay) {
    const box = svc("div", "tt-agenda"), today = ymd(new Date());
    for (const d of days) {
      const items = (byDay[ymd(d)] || []).sort((a, b) => a.s - b.s);
      if (!items.length) continue;
      const sec = svc("section", "tt-day" + (ymd(d) === today ? " today" : ""));
      sec.append(svc("h3", null, `${pretty(DAYS[(d.getDay() + 6) % 7])} ${dayFmt.format(d)}`));
      for (const l of items) {
        const row = svc("div", "tt-row"), t = svc("div", "tt-rt"); t.append(svc("b", null, hm(l.s)), svc("span", null, hm(l.e)));
        row.append(t, lessonEl(l, "notime")); sec.append(row);
      }
      box.append(sec);
    }
    return box;
  }

  function draw() {
    root.replaceChildren();
    if (!lessons.length) {
      root.append(svc("div", "rempty", "Pas encore d'emploi du temps. Il apparaîtra après la prochaine synchronisation avec Pronote."));
      return;
    }
    const bar = svc("div", "tt-bar");
    const prev = svc("button", "chip", "‹"), next = svc("button", "chip", "›"), todayB = svc("button", "chip", "Aujourd'hui");
    prev.title = "Semaine précédente"; next.title = "Semaine suivante";
    prev.disabled = +weekStart <= minWeek; next.disabled = +weekStart >= maxWeek;
    const cur = +monday(new Date());
    todayB.hidden = +weekStart === cur || cur < minWeek || cur > maxWeek;
    prev.onclick = () => { weekStart = addDays(weekStart, -7); draw(); };
    next.onclick = () => { weekStart = addDays(weekStart, 7); draw(); };
    todayB.onclick = () => { weekStart = new Date(cur); draw(); };
    const fri = addDays(weekStart, 4);
    bar.append(prev, svc("h2", "tt-title", `Semaine du ${dayFmt.format(weekStart)} au ${dayFmt.format(fri)}`), next, todayB);
    root.append(bar);

    const info = nowInfo();
    if (info) root.append(svc("div", "tt-info " + info.kind, info.text));

    const end = addDays(weekStart, 7), byDay = {};
    for (const l of lessons) if (l.s >= weekStart && l.s < end) (byDay[ymd(l.s)] ||= []).push({ ...l });
    const weekItems = Object.values(byDay).flat();
    if (!weekItems.length) { root.append(svc("div", "rempty", "Aucun cours cette semaine (vacances ?).")); return; }
    const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)).filter((d, i) => i < 5 || (byDay[ymd(d)] || []).length);
    root.append(mq.matches ? agenda(days, byDay) : grid(days, byDay));
  }

  mq.addEventListener("change", () => { if (!root.hidden) draw(); });
  setInterval(() => { if (!root.hidden) draw(); }, 60000);   // « en cours » et trait de l'heure
  document.addEventListener("keydown", ev => {
    if (root.hidden || ev.target.closest("input, textarea, select, dialog") || document.querySelector("dialog[open]")) return;
    const b = ev.key === "ArrowLeft" ? $(".tt-bar .chip:first-child") : ev.key === "ArrowRight" ? $(".tt-bar .chip:nth-of-type(2)") : null;
    if (b && !b.disabled) b.click();
  });
  VIEWS.edt = { el: root, draw };
})();
