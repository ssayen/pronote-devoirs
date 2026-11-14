// Onglet « Notes » : flux des notes, les plus récentes d'abord ; celles que l'élève n'a pas encore vues sont mises en avant
// (état « vu » enregistré sur le serveur : la date d'une note ne suffit pas, un enseignant peut en saisir une avec une date ancienne).
// Une note est marquée « vue » quand on quitte l'onglet ou sur « Tout marquer comme vu ». Le parent voit l'état sans le modifier.
// Utilise les fonctions globales de la page (el, $, icon, toast, JSON_HDR, READONLY) et la constante GRADES.
(() => {
  const root = $("#notes");
  const nf = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  const pretty = s => { const t = s.replace(/&amp;/g, "&").trim().toLowerCase(); return t.charAt(0).toUpperCase() + t.slice(1); };
  const fmtDate = d => new Date(d + "T12:00:00").toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
  const fmtShort = d => new Date(d + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
  const gradesList = GRADES;                       // déjà triées : date décroissante
  let onlyNew = false, mode = "flux";                 // « flux » : liste chronologique (par défaut) ; « matiere » : regroupées par matière, filtrées par trimestre

  // périodes (trimestres) qui ont des notes, dans l'ordre de l'année ; « courante » : celle qui contient aujourd'hui, sinon la dernière commencée
  const PERIODS = (() => {
    const order = RESULTS.periods.map(p => p.name), at = n => (order.indexOf(n) < 0 ? 99 : order.indexOf(n));
    return [...new Set(gradesList.map(g => g.period))].sort((a, b) => at(a) - at(b));
  })();
  function currentPeriod() {
    const info = RESULTS.periods.filter(p => PERIODS.includes(p.name));
    const inside = info.find(p => p.start && p.end && p.start <= TODAY && TODAY <= p.end);
    const started = info.filter(p => !p.start || p.start <= TODAY);
    return (inside || started[started.length - 1] || info[info.length - 1] || {}).name || PERIODS[PERIODS.length - 1] || null;
  }
  let period = currentPeriod();                       // null = toute l'année
  const mean = (list, key) => {                       // moyenne pondérée par les coefficients (comme Pronote) ; null s'il n'y a rien à moyenner
    let s = 0, w = 0;
    for (const g of list) { const v = g[key]; if (v == null) continue; const c = g.coef == null ? 1 : g.coef; s += v * c; w += c; }
    return w ? s / w : null;
  };

  const unseenIds = () => gradesList.filter(g => g.unseen).map(g => g.id);
  function badge() {
    const n = unseenIds().length, b = $("#nbadge");
    b.hidden = !n; b.textContent = n;
    b.title = n ? `${n} note${n > 1 ? "s" : ""} pas encore vue${n > 1 ? "s" : ""}` : "";
  }

  async function markSeen(keepalive) {            // marque tout ce qui est affiché comme vu
    if (READONLY) return;
    const ids = unseenIds();
    if (!ids.length) return;
    try {
      const r = await fetch("/api/grades/seen", { method: "POST", headers: JSON_HDR, body: JSON.stringify({ ids }), keepalive: !!keepalive });
      if (!r.ok) throw new Error(r.status);
      for (const g of gradesList) if (ids.includes(g.id)) g.unseen = 0;
      badge();
    } catch (e) { if (!keepalive) toast("Enregistrement impossible, réessayer"); }
  }

  const base = g => (g.out_of > 0 ? g.out_of : 20);
  const orig = (g, v) => nf.format(Math.round(v * base(g) / 20 * 100) / 100);   // valeur ramenée sur 20 → barème d'origine

  function row(g, grouped = false) {   // grouped : vue par matière, la matière est déjà le titre
    const li = el("li", "nrow" + (g.unseen ? " new" : ""));
    const left = el("div", "n-main");
    const t = el("div", "n-subj"); t.append(grouped ? fmtDate(g.date) : icon(g.subject) + " " + pretty(g.subject));
    if (g.unseen) t.append(el("span", "n-new", "Nouvelle"));
    const meta = grouped ? [] : [fmtDate(g.date)];
    if (g.added && g.added > g.date) meta.push(`ajoutée le ${fmtShort(g.added)}`);   // note saisie avec une date ancienne
    if (g.class_avg != null) meta.push(`classe ${orig(g, g.class_avg)}` + (g.max != null ? ` (max ${orig(g, g.max)})` : ""));
    left.append(t, el("div", "n-meta", meta.join(" · ")));
    if (g.comment) left.append(el("div", "n-com", g.comment));
    const v = el("div", "n-val" + (g.class_avg == null ? "" : g.grade > g.class_avg + 0.05 ? " up" : g.grade < g.class_avg - 0.05 ? " down" : ""));
    v.append(orig(g, g.grade), el("small", null, "/" + nf.format(base(g))));
    const r = el("div", "n-right"); r.append(v);
    if (base(g) !== 20) r.append(el("span", "n-on20", `soit ${nf.format(g.grade)}/20`));   // équivalent sur 20 (celui des points et objectifs)
    if (g.coef != null && g.coef !== 1) r.append(el("span", "n-coef", `coef ${nf.format(g.coef)}`));   // seulement si ≠ 1 (la moyenne est pondérée)
    li.append(left, r);
    return li;
  }

  function section(title, list) {
    const s = el("section", "rcard"); s.append(el("h2", null, title));
    const ul = el("ul", "nlist"); for (const g of list) ul.append(row(g));
    s.append(ul); return s;
  }

  function subjectView(bar) {
    const chips = el("div", "chips"); chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "Trimestre");
    for (const [label, val] of [...PERIODS.map(n => [n, n]), ["Toute l'année", null]]) {
      const b = el("button", "chip", label); b.type = "button"; b.setAttribute("aria-pressed", period === val);
      b.onclick = () => { period = val; draw(); }; chips.append(b);
    }
    root.append(chips);
    const list = gradesList.filter(g => period === null || g.period === period);
    if (!list.length) { root.append(el("div", "rempty", "Aucune note pour cette période.")); return; }
    const by = new Map();
    for (const g of list) { if (!by.has(g.subject)) by.set(g.subject, []); by.get(g.subject).push(g); }
    const groups = [...by.entries()].sort(([a, x], [b, y]) => (y.some(g => g.unseen) - x.some(g => g.unseen)) || pretty(a).localeCompare(pretty(b), "fr"));   // matières avec des notes non vues d'abord
    for (const [subj, notes] of groups) {
      const sec = el("section", "rcard"), h = el("h2", "n-gh");
      const m = mean(notes, "grade"), c = mean(notes, "class_avg"), fresh = notes.filter(g => g.unseen).length;
      h.append(el("span", null, icon(subj) + " " + pretty(subj)));
      if (fresh) h.append(el("span", "n-new", `${fresh} nouvelle${fresh > 1 ? "s" : ""}`));
      const stat = el("span", "n-avg" + (m != null && c != null ? (m > c + 0.05 ? " up" : m < c - 0.05 ? " down" : "") : ""));
      stat.append(m == null ? "" : `Moyenne ${nf.format(m)}/20`, c == null ? "" : el("small", null, ` · classe ${nf.format(c)}`), el("small", null, ` · ${notes.length} note${notes.length > 1 ? "s" : ""}`));
      h.append(stat); sec.append(h);
      const ul = el("ul", "nlist"); for (const g of notes) ul.append(row(g, true)); sec.append(ul); root.append(sec);
    }
  }

  function draw() {
    root.replaceChildren();
    badge();
    if (!gradesList.length) { root.append(el("div", "rempty", "Pas encore de notes. Elles apparaîtront après la prochaine synchronisation avec Pronote.")); return; }
    const fresh = gradesList.filter(g => g.unseen), rest = gradesList.filter(g => !g.unseen);
    const views = el("div", "chips"); views.setAttribute("role", "group"); views.setAttribute("aria-label", "Affichage");
    for (const [label, val] of [["🕒 Chronologique", "flux"], ["📚 Par matière", "matiere"]]) {
      const b = el("button", "chip", label); b.type = "button"; b.setAttribute("aria-pressed", mode === val);
      b.onclick = () => { mode = val; draw(); }; views.append(b);
    }
    if (fresh.length && !READONLY) { const b = el("button", "chip", "✓ Tout marquer comme vu"); b.type = "button"; b.onclick = async () => { await markSeen(); draw(); }; views.append(b); }
    root.append(views);
    if (mode === "matiere") { subjectView(); return; }
    const bar = el("div", "chips"); bar.setAttribute("role", "group"); bar.setAttribute("aria-label", "Filtre");
    for (const [label, val] of [["Toutes", false], [`Pas encore vues (${fresh.length})`, true]]) {
      const b = el("button", "chip", label); b.type = "button"; b.setAttribute("aria-pressed", onlyNew === val);
      b.onclick = () => { onlyNew = val; draw(); }; bar.append(b);
    }
    root.append(bar);
    if (onlyNew) {
      root.append(fresh.length ? section(READONLY ? "Pas encore vues par l'élève" : "Pas encore vues", fresh) : el("div", "rempty", "Toutes les notes ont été vues."));
      return;
    }
    if (fresh.length) root.append(section(READONLY ? "Nouvelles notes (pas encore vues par l'élève)" : "Nouvelles notes", fresh));
    if (rest.length) root.append(section(fresh.length ? "Notes déjà vues" : "Toutes les notes", rest));
  }

  badge();
  addEventListener("pagehide", () => { if (NAV.current === "notes") markSeen(true); });
  VIEWS.notes = { el: root, draw, hide: () => markSeen() };
})();
