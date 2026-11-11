// Onglet « Résultats » : radar élève / classe par matière + tableau d'écarts.
// Utilise les fonctions globales de la page (el, $, icon, strip) et la constante RESULTS.
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const W = 640, H = 480, CX = 320, CY = 240, R = 170, MAXV = 20;
  const nf = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
  const num = v => (v == null ? "—" : nf.format(v));
  const signed = d => (Math.abs(d) < 0.05 ? "=" : (d > 0 ? "▲ +" : "▼ −") + nf.format(Math.abs(d)));
  const dir = d => (Math.abs(d) < 0.05 ? "" : d > 0 ? "up" : "down");
  const pretty = s => {   // « ED.PHYSIQUE &amp; SPORT. » -> « Ed. physique & sport. »
    const t = s.replace(/&amp;/g, "&").trim().toLowerCase();
    return t.charAt(0).toUpperCase() + t.slice(1);
  };
  const short = s => { const t = pretty(s); return t.length > 22 ? t.slice(0, 21) + "…" : t; };
  const svg = (tag, attrs = {}, text) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  };

  const root = $("#results");
  const periods = RESULTS.periods.filter(p => p.subjects.length);
  let current = periods.length ? periods[periods.length - 1].name : null;
  try { const k = localStorage.getItem("period"); if (periods.some(p => p.name === k)) current = k; } catch (e) {}

  function draw() {
    root.replaceChildren();
    if (!periods.length) {
      root.append(el("div", "rempty", "Pas encore de moyennes. Elles apparaîtront après la prochaine synchronisation avec Pronote."));
      return;
    }
    const period = periods.find(p => p.name === current);

    const chips = el("div", "chips"); chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "Période");
    for (const p of periods) {
      const b = el("button", "chip", p.name); b.type = "button"; b.setAttribute("aria-pressed", p.name === current);
      b.onclick = () => { current = p.name; try { localStorage.setItem("period", current); } catch (e) {} draw(); };
      chips.append(b);
    }
    root.append(chips);

    const rows = period.subjects.map(s => ({ ...s, gap: s.student != null && s.class_avg != null ? s.student - s.class_avg : null }));
    const both = rows.filter(r => r.gap != null);
    root.append(tiles(period, both));

    const grid = el("div", "rgrid");
    grid.append(radarCard(both), tableCard(rows));
    root.append(grid);
  }

  function tile(label, value, sub, cls, color) {
    const t = el("div", "tile " + (cls || ""));
    const k = el("div", "k"); if (color) { const i = el("i"); i.style.background = color; k.append(i); }
    k.append(label);
    const v = el("div", "v " + (cls === "gap" ? dir(value.d) : ""));
    v.append(value.text); if (sub) v.append(" ", el("small", null, sub));
    t.append(k, v);
    return t;
  }

  function tiles(period, both) {
    const box = el("div", "tiles");
    const me = period.overall ?? avg(both.map(r => r.student)), cl = period.class_overall ?? avg(both.map(r => r.class_avg));
    box.append(tile("Moyenne générale", { text: num(me) }, "/20", "", "var(--s-me)"));
    box.append(tile("Moyenne de la classe", { text: num(cl) }, "/20", "", "var(--s-class)"));
    if (me != null && cl != null) box.append(tile("Écart avec la classe", { text: signed(me - cl), d: me - cl }, "", "gap"));
    if (both.length >= 2) {
      const sorted = [...both].sort((a, b) => b.gap - a.gap);
      const top = sorted[0], low = sorted[sorted.length - 1];
      box.append(tile("Point fort", { text: icon(top.subject) + " " + short(top.subject) }, signed(top.gap), ""));
      if (low.gap < -0.05) box.append(tile("À surveiller", { text: icon(low.subject) + " " + short(low.subject) }, signed(low.gap), ""));
    }
    for (const v of box.querySelectorAll(".tile:nth-child(n+4) .v")) v.style.fontSize = "1.15rem";
    return box;
  }
  const avg = a => { const x = a.filter(v => v != null); return x.length ? x.reduce((s, v) => s + v, 0) / x.length : null; };

  function legend() {
    const l = el("div", "legend");
    const a = el("span"), b = el("span");
    const sa = svg("svg", { viewBox: "0 0 28 12", "aria-hidden": "true" });
    sa.append(svg("line", { x1: 0, y1: 6, x2: 28, y2: 6, stroke: "var(--s-me)", "stroke-width": 3, "stroke-linecap": "round" }));
    const sb = svg("svg", { viewBox: "0 0 28 12", "aria-hidden": "true" });
    sb.append(svg("line", { x1: 0, y1: 6, x2: 28, y2: 6, stroke: "var(--s-class)", "stroke-width": 3, "stroke-dasharray": "6 4" }));
    a.append(sa, "Élève"); b.append(sb, "Moyenne de la classe");
    l.append(a, b);
    return l;
  }

  function radarCard(rows) {
    const card = el("section", "rcard"); card.append(el("h2", null, "Positionnement par matière"), legend());
    if (rows.length < 3) { card.append(el("div", "rempty", "Au moins 3 matières notées sont nécessaires pour tracer le radar.")); return card; }
    const wrap = el("div", "radar-wrap");
    const s = svg("svg", { id: "radar", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": "Radar des moyennes par matière : élève et classe. Le détail est dans le tableau." });
    const n = rows.length, ang = i => -Math.PI / 2 + (i * 2 * Math.PI) / n;
    const pt = (i, v, r = R) => [CX + (r * v / MAXV) * Math.cos(ang(i)), CY + (r * v / MAXV) * Math.sin(ang(i))];
    const poly = f => rows.map((r, i) => pt(i, f(r)).map(x => x.toFixed(1)).join(",")).join(" ");

    for (const v of [5, 10, 15, 20]) {   // anneaux : polygones réguliers
      s.append(svg("polygon", { class: "ring" + (v % 10 ? " mid" : ""), points: rows.map((_, i) => pt(i, v).join(",")).join(" ") }));
      s.append(svg("text", { class: "rv", x: CX + 4, y: CY - R * v / MAXV - 3 }, v));
    }
    rows.forEach((_, i) => { const [x, y] = pt(i, MAXV); s.append(svg("line", { class: "axis", x1: CX, y1: CY, x2: x, y2: y })); });

    const g = svg("g", { class: "draw" });
    g.append(svg("polygon", { class: "poly", points: poly(r => r.class_avg), fill: "none",
      stroke: "var(--s-class)", "stroke-width": 2, "stroke-dasharray": "7 4", "stroke-linejoin": "round" }));
    g.append(svg("polygon", { class: "poly", points: poly(r => r.student), fill: "var(--s-me)", "fill-opacity": .2,
      stroke: "var(--s-me)", "stroke-width": 2.5, "stroke-linejoin": "round" }));
    const dotsMe = [], dotsCl = [];
    rows.forEach((r, i) => {
      const [cx, cy] = pt(i, r.class_avg), [mx, my] = pt(i, r.student);
      const dc = svg("circle", { class: "dot", cx, cy, r: 4, fill: "var(--s-class)" });
      const dm = svg("circle", { class: "dot", cx: mx, cy: my, r: 5, fill: "var(--s-me)" });
      dotsCl.push(dc); dotsMe.push(dm); g.append(dc, dm);
    });
    s.append(g);

    const labels = [];
    rows.forEach((r, i) => {
      const c = Math.cos(ang(i)), sn = Math.sin(ang(i)), x = CX + (R + 16) * c, y = CY + (R + 16) * sn;
      const t = svg("text", { class: "lab", x, y: y + (sn > 0.4 ? 12 : sn < -0.4 ? -2 : 4), "text-anchor": c > 0.25 ? "start" : c < -0.25 ? "end" : "middle" },
        icon(r.subject) + " " + short(r.subject));
      labels.push(t); s.append(t);
    });

    const tip = el("div", "tip"); tip.setAttribute("role", "status");
    const rowsEl = () => document.querySelectorAll(".rtable tbody tr");
    const show = i => {
      const r = rows[i], [x, y] = pt(i, Math.max(r.student, r.class_avg));
      tip.replaceChildren();
      tip.append(el("b", null, icon(r.subject) + " " + pretty(r.subject)));
      const line = (color, k, v) => { const d = el("div"); const l = el("span"); if (color) { const m = el("i"); m.style.background = color; l.append(m); } l.append(k); d.append(l, el("span", null, v)); tip.append(d); };
      line("var(--s-me)", "Élève", num(r.student)); line("var(--s-class)", "Classe", num(r.class_avg));
      line(null, "Écart", signed(r.gap));
      if (r.min != null && r.max != null) line(null, "Min – max", `${num(r.min)} – ${num(r.max)}`);
      tip.style.left = (x / W * 100) + "%"; tip.style.top = (y / H * 100) + "%"; tip.classList.add("on");
      dotsMe[i].setAttribute("r", 8); dotsCl[i].setAttribute("r", 7); labels[i].classList.add("on");
      rowsEl().forEach(tr => tr.classList.toggle("on", tr.dataset.subject === r.subject));
    };
    const hide = i => {
      tip.classList.remove("on"); dotsMe[i].setAttribute("r", 5); dotsCl[i].setAttribute("r", 4); labels[i].classList.remove("on");
      rowsEl().forEach(tr => tr.classList.remove("on"));
    };
    rows.forEach((r, i) => {   // zone de survol : un large trait le long de l'axe
      const [x, y] = pt(i, MAXV);
      const h = svg("line", { class: "hit", x1: CX, y1: CY, x2: x, y2: y, stroke: "transparent", "stroke-width": 40, "stroke-linecap": "round", tabindex: 0,
        "aria-label": `${pretty(r.subject)} : élève ${num(r.student)}, classe ${num(r.class_avg)}` });
      h.addEventListener("pointerenter", () => show(i)); h.addEventListener("pointerleave", () => hide(i));
      h.addEventListener("focus", () => show(i)); h.addEventListener("blur", () => hide(i));
      s.append(h);
    });
    wrap.append(s, tip); card.append(wrap);
    card.append(el("p", "rnote", "Échelle de 0 à 20. Plus la forme bleue dépasse la forme orange pointillée, plus l'élève est au-dessus de la moyenne de la classe."));
    return card;
  }

  function tableCard(rows) {
    const card = el("section", "rcard"); card.append(el("h2", null, "Détail par matière"));
    const t = el("table", "rtable");
    const head = el("thead"), hr = el("tr");
    for (const h of ["Matière", "Élève", "Classe", "Écart", "Min–max"]) hr.append(el("th", null, h));
    head.append(hr); t.append(head);
    const body = el("tbody");
    for (const r of [...rows].sort((a, b) => (b.gap ?? -99) - (a.gap ?? -99))) {
      const tr = el("tr"); tr.dataset.subject = r.subject;
      tr.append(el("td", null, icon(r.subject) + " " + pretty(r.subject)), el("td", null, num(r.student)), el("td", null, num(r.class_avg)));
      tr.append(r.gap == null ? el("td", null, "—") : el("td", "gap " + dir(r.gap), signed(r.gap)));
      tr.append(el("td", "minmax", r.min != null && r.max != null ? `${num(r.min)}–${num(r.max)}` : "—"));
      body.append(tr);
    }
    t.append(body); card.append(t);
    return card;
  }

  VIEWS.resultats = { el: root, draw };
})();
