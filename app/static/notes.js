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
  let onlyNew = false;

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

  function row(g) {
    const li = el("li", "nrow" + (g.unseen ? " new" : ""));
    const left = el("div", "n-main");
    const t = el("div", "n-subj"); t.append(icon(g.subject) + " " + pretty(g.subject));
    if (g.unseen) t.append(el("span", "n-new", "Nouvelle"));
    const meta = [fmtDate(g.date)];
    if (g.added && g.added > g.date) meta.push(`ajoutée le ${fmtShort(g.added)}`);   // note saisie avec une date ancienne
    if (g.coef != null && g.coef !== 1) meta.push(`coef ${nf.format(g.coef)}`);
    if (g.class_avg != null) meta.push(`classe ${nf.format(g.class_avg)}` + (g.max != null ? ` (max ${nf.format(g.max)})` : ""));
    left.append(t, el("div", "n-meta", meta.join(" · ")));
    if (g.comment) left.append(el("div", "n-com", g.comment));
    const v = el("div", "n-val" + (g.class_avg == null ? "" : g.grade > g.class_avg + 0.05 ? " up" : g.grade < g.class_avg - 0.05 ? " down" : ""));
    v.append(nf.format(g.grade), el("small", null, "/20"));
    li.append(left, v);
    return li;
  }

  function section(title, list) {
    const s = el("section", "rcard"); s.append(el("h2", null, title));
    const ul = el("ul", "nlist"); for (const g of list) ul.append(row(g));
    s.append(ul); return s;
  }

  function draw() {
    root.replaceChildren();
    badge();
    if (!gradesList.length) { root.append(el("div", "rempty", "Pas encore de notes. Elles apparaîtront après la prochaine synchronisation avec Pronote.")); return; }
    const fresh = gradesList.filter(g => g.unseen), rest = gradesList.filter(g => !g.unseen);
    const bar = el("div", "chips"); bar.setAttribute("role", "group"); bar.setAttribute("aria-label", "Filtre");
    for (const [label, val] of [["Toutes", false], [`Pas encore vues (${fresh.length})`, true]]) {
      const b = el("button", "chip", label); b.type = "button"; b.setAttribute("aria-pressed", onlyNew === val);
      b.onclick = () => { onlyNew = val; draw(); }; bar.append(b);
    }
    if (fresh.length && !READONLY) { const b = el("button", "chip", "✓ Tout marquer comme vu"); b.type = "button"; b.onclick = async () => { await markSeen(); draw(); }; bar.append(b); }
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
