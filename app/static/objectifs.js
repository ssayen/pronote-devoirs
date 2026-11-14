// Onglet « Objectifs » : niveau, missions, paquets, historique des points. Pastille de niveau + barre sur l'avatar.
// Utilise les fonctions globales de la page (el, $, toast, JSON_HDR), READONLY (compte parent) et la constante GAME.
(() => {
  const root = $("#goals");
  const nf = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
  const pts = n => `${n} pt${n > 1 ? "s" : ""}`;
  const day = iso => new Date(iso + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
  const daysLeft = iso => Math.ceil((new Date(iso + "T23:59:59") - new Date()) / 86400000);
  const label = m => m.label;
  let data = GAME;

  // ---- pastille de niveau et barre sur l'avatar ----
  const wrap = $(".avwrap");
  const badge = el("button", "lvl"), bar = el("span", "xp"), fill = el("i");
  badge.type = "button";
  bar.append(fill); wrap.append(badge, bar);
  function paintAvatar(g) {
    badge.textContent = g.level; fill.style.width = g.pct + "%";
    const t = `Niveau ${g.level} · ${g.into} / ${g.per_level} points` + (g.packs ? ` · ${g.packs} paquet${g.packs > 1 ? "s" : ""} à ouvrir` : "");
    wrap.title = t; badge.classList.toggle("gift", g.packs > 0);
    badge.setAttribute("aria-label", g.packs ? `Niveau ${g.level}, ${g.packs} paquet${g.packs > 1 ? "s" : ""} à ouvrir : voir mes paquets` : `Niveau ${g.level} : voir mes objectifs`);
    bar.setAttribute("role", "progressbar"); bar.setAttribute("aria-label", t);
    bar.setAttribute("aria-valuemin", 0); bar.setAttribute("aria-valuemax", g.per_level); bar.setAttribute("aria-valuenow", g.into);
  }
  paintAvatar(GAME);
  let wantPacks = false;
  const scrollPacks = () => { const p = $("#g-packs"); if (!p) return; p.scrollIntoView({ behavior: "smooth", block: "center" }); p.classList.remove("focus"); void p.offsetWidth; p.classList.add("focus"); };
  badge.onclick = ev => {          // un clic sur la pastille mène aux objectifs, directement aux paquets s'il y en a à ouvrir
    ev.stopPropagation(); wantPacks = data.packs > 0;
    if (NAV.current === "objectifs") { refresh(); } else go("objectifs");
  };

  const meter = (pct, cls = "") => { const m = el("div", "meter " + cls), i = el("i"); i.style.width = Math.max(0, Math.min(100, pct)) + "%"; m.append(i); return m; };

  function levelCard(g) {
    const c = el("section", "g-level");
    const big = el("div", "g-big"); big.append(el("small", null, "Niveau"), el("b", null, String(g.level)));
    const side = el("div", "g-side");
    side.append(el("div", "g-line", `${g.into} / ${g.per_level} points`), meter(g.pct),
                el("div", "g-sub", `Encore ${pts(g.to_next)} avant le niveau ${g.level + 1} · ${pts(g.points)} au total`));
    c.append(big, side);
    return c;
  }

  function packs(g) {
    const open = g.packs_list.filter(p => !p.opened_at);
    if (!open.length && g.has_rewards === false) return null;      // pas de récompense définie : pas de paquets, seulement l'animation de niveau
    const sec = el("section", "g-sec g-packs"); sec.id = "g-packs";
    sec.append(el("h2", null, open.length > 1 ? `Paquets à ouvrir (${open.length})` : "Paquets"));
    if (!open.length) { sec.append(el("p", "g-empty", "Aucun paquet à ouvrir. Un nouveau paquet arrive à chaque niveau gagné.")); return sec; }
    for (const p of open) {
      const row = el("div", "g-pack-card"), art = el("div", "g-pack-art"), txt = el("div", "g-txt");
      art.append(PackFX.pack(true));
      txt.append(`Paquet du niveau ${p.level}`, el("p", "g-sub", "Une récompense t'attend à l'intérieur !"));
      row.append(art, txt);
      if (READONLY) row.append(el("span", "g-pack-wait", "à ouvrir par l'élève"));
      else {
        const b = el("button", "g-open", "Ouvrir !"); b.type = "button";
        b.onclick = () => openPack(p.level, b);
        row.append(b);
      }
      sec.append(row);
    }
    return sec;
  }

  async function openPack(level, btn) {
    PackFX.unlock();       // le son doit être autorisé dans le geste de clic, avant la requête
    btn.disabled = true;
    try {
      const r = await fetch(`/api/packs/${level}/open`, { method: "POST" });
      if (!r.ok) throw new Error(r.status);
      const j = await r.json();
      await PackFX.open({ reward: j.reward, rarity: j.rarity, icon: j.icon || "🎁", level, bonus: j.bonus });
      await refresh();
    } catch (e) { btn.disabled = false; toast(String(e.message) === "409" ? "Aucune récompense n'est définie pour le moment : demande à ton parent." : "Impossible d'ouvrir le paquet, réessayer"); }
  }

  function missionCard(m) {
    const c = el("article", "g-mission");
    const top = el("div", "g-mtop");
    top.append(el("span", "g-mlabel", label(m)), el("span", "g-pts", "+" + pts(m.points)));
    c.append(top);
    if (m.status === "active") {
      const p = m.progress, left = daysLeft(m.expires_at);
      const pct = m.kind === "beat_class" ? (p.current >= p.target ? 100 : Math.max(0, 100 * p.current / p.target))
                                          : 100 * p.current / Math.max(p.target, 1e-9);
      c.append(meter(pct), el("div", "g-sub", `${p.text} · ${left > 1 ? `encore ${left} jours` : left === 1 ? "dernier jour" : "se termine aujourd'hui"}`));
    } else {
      c.classList.add(m.status);
      c.append(el("div", "g-sub", m.status === "done" ? `✅ Réussie le ${day(m.done_at)}` : `⌛ Expirée le ${day(m.expires_at)}`));
    }
    return c;
  }

  function missions(g) {
    const sec = el("section", "g-sec");
    sec.append(el("h2", null, "Missions en cours"));
    const act = g.missions.filter(m => m.status === "active");
    if (!act.length) sec.append(el("p", "g-empty", "Pas de mission pour l'instant : de nouvelles apparaîtront après la prochaine synchronisation."));
    const grid = el("div", "g-grid"); for (const m of act) grid.append(missionCard(m)); sec.append(grid);
    const past = g.missions.filter(m => m.status !== "active");
    if (past.length) {
      const det = el("details", "g-past"); det.append(el("summary", null, `Missions terminées (${past.length})`));
      const gr = el("div", "g-grid"); for (const m of past) gr.append(missionCard(m)); det.append(gr); sec.append(det);
    }
    return sec;
  }

  const canDeliver = () => READONLY || document.documentElement.dataset.role === "admin" || !document.documentElement.dataset.account;   // le parent coche et gère les récompenses (l'admin aussi, pour tester ; en mode local sans compte, aussi)

  async function setDelivered(level, delivered, box, part = "reward") {
    box.disabled = true;
    try {
      const r = await fetch(`/api/packs/${level}/delivered`, { method: "POST", headers: JSON_HDR, body: JSON.stringify({ delivered, part }) });
      if (!r.ok) throw new Error(r.status);
      await refresh();
    } catch (e) { box.checked = !delivered; box.disabled = false; toast("Enregistrement impossible, réessayer"); }
  }

  function rewards(g) {
    const todo = p => !p.delivered_at + (p.bonus && !p.bonus_delivered_at ? 1 : 0);   // éléments encore à remettre (récompense + bonus)
    const got = g.packs_list.filter(p => p.opened_at).sort((a, b) => (todo(b) > 0) - (todo(a) > 0) || b.level - a.level);   // à remettre d'abord
    if (!got.length) return null;
    const pending = got.reduce((s, p) => s + todo(p), 0);
    const sec = el("section", "g-sec");
    sec.append(el("h2", null, "Récompenses obtenues" + (pending ? ` (${pending} à remettre)` : "")));
    const ul = el("ul", "g-list g-rewards");
    for (const p of got) {
      const li = el("li", "rar rar-" + (p.rarity || "common") + (p.delivered_at ? " given" : ""));
      const main = el("span", "g-rw");
      main.append(`${p.icon || "🎁"} Niveau ${p.level} : ${p.reward}`, el("span", "rtag", (PackFX.RARITY[p.rarity] || {}).label || ""));
      li.append(main);
      if (canDeliver()) {
        const lab = el("label", "g-deliver"), box = el("input"); box.type = "checkbox"; box.checked = !!p.delivered_at;
        box.onchange = () => setDelivered(p.level, box.checked, box);
        lab.append(box, " Remise");
        li.append(lab);
      } else li.append(el("span", "g-state" + (p.delivered_at ? " ok" : ""), p.delivered_at ? "✅ Remise" : "À recevoir"));
      ul.append(li);
      if (p.bonus) {   // bonus systématique (ex. crédits) : à remettre séparément
        const b = el("li", "rar rar-" + (p.rarity || "common") + " bonus" + (p.bonus_delivered_at ? " given" : ""));
        b.append(el("span", "g-rw", `➕ Bonus du niveau ${p.level} : ${p.bonus}`));
        if (canDeliver()) {
          const lab = el("label", "g-deliver"), box = el("input"); box.type = "checkbox"; box.checked = !!p.bonus_delivered_at;
          box.onchange = () => setDelivered(p.level, box.checked, box, "bonus");
          lab.append(box, " Remis"); b.append(lab);
        } else b.append(el("span", "g-state" + (p.bonus_delivered_at ? " ok" : ""), p.bonus_delivered_at ? "✅ Remis" : "À recevoir"));
        ul.append(b);
      }
    }
    sec.append(ul); return sec;
  }

  // ---- récompenses de l'élève : le parent (et l'admin, pour tester) les définit par rareté ; l'élève ne voit pas cette liste ----
  const RARS = ["common", "rare", "epic", "legendary"];
  const RW = { bonus: { unit: "", rules: {} }, list: null, weights: { common: 50, rare: 30, epic: 15, legendary: 5 }, editing: null };
  async function rwApi(method, url, body) {
    const r = await fetch(url, { method, headers: JSON_HDR, body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) {   // on remonte le message du serveur (texte en français) pour que le formulaire explique l'erreur
      let msg = String(r.status);
      try { const d = (await r.json()).detail; msg = typeof d === "string" ? d : "Valeurs invalides : vérifie les champs (nombres de 0 à 100, textes pas trop longs)."; } catch (e) {}
      throw new Error(msg);
    }
    const j = await r.json(); if (j.rewards) RW.list = j.rewards; if (j.bonus) RW.bonus = j.bonus; return j;
  }
  function rewardsEditor() {
    const sec = el("section", "g-sec g-rwedit"); sec.id = "g-rwedit";
    const rarLabel = r => (PackFX.RARITY[r] || {}).label || r;
    const fail = e => toast(e && e.message && isNaN(e.message) ? e.message : "Enregistrement impossible, réessayer");
    function paint() {
      sec.replaceChildren(el("h2", null, "Récompenses de l'élève"));
      if (!RW.list) { sec.append(el("p", "g-empty", "Chargement…")); return; }
      sec.append(el("p", "g-sub", "Tu choisis ce que l'élève peut gagner. À chaque niveau, un paquet tire d'abord une rareté au hasard, puis une récompense de cette rareté parmi celles ci-dessous. L'élève ne voit pas cette liste."));
      if (!RW.list.length) {
        const box = el("div", "g-rwnone");
        box.append(el("b", null, "Aucune récompense définie."), " L'élève ne reçoit pas de paquet : à chaque niveau gagné, il a seulement droit à une animation.");
        const b = el("button", "btn", "Charger la liste d'exemples"); b.type = "button";
        b.onclick = async () => { try { await rwApi("POST", "/api/rewards/examples"); paint(); } catch (e) { fail(e); } };
        box.append(el("div"), b); sec.append(box);
      }
      const present = RARS.filter(r => RW.list.some(x => x.rarity === r)), total = present.reduce((s, r) => s + RW.weights[r], 0);
      for (const r of RARS) {
        const items = RW.list.filter(x => x.rarity === r), meta = PackFX.RARITY[r] || {};
        const grp = el("div", "g-rwgrp rar-" + r); grp.style.setProperty("--rc", meta.color || "#999");
        const head = el("div", "g-rwhead");
        head.append(el("b", null, rarLabel(r)), el("span", "g-rwodds", items.length ? `≈ ${Math.round(100 * RW.weights[r] / total)} % des paquets` : "jamais tirée tant qu'elle est vide"));
        grp.append(head);
        const ul = el("ul", "g-rwlist");
        for (const x of items) ul.append(RW.editing === x.id ? editRow(x) : row(x));
        grp.append(ul, addForm(r)); sec.append(grp);
      }
      sec.append(bonusCard());
    }
    function bonusCard() {   // bonus systématique : ajouté à la récompense tirée, nombre tiré entre min et max selon la rareté
      const card = el("div", "g-rwgrp g-bonus"); card.style.setProperty("--rc", "#ffb800");
      card.append(el("div", "g-rwhead"));
      card.firstChild.append(el("b", null, "Bonus systématique"), el("span", "g-rwodds", "en plus de la récompense tirée, à chaque paquet"));
      card.append(el("p", "g-sub", "Ex. une monnaie locale (des crédits) : le nombre est tiré au hasard entre le minimum et le maximum de la rareté obtenue. Laisse « max » vide ou à 0 pour une rareté sans bonus. Tu le coches « Remis » dans la liste des récompenses obtenues, comme la récompense."));
      const f = el("form", "g-bonusform"), unit = el("input", "g-rwt"), rows = {};
      unit.value = RW.bonus.unit || ""; unit.maxLength = 20; unit.placeholder = "ex. : crédits"; unit.setAttribute("aria-label", "Nom de la monnaie ou du bonus");
      const u = el("label", "g-bonusunit"); u.append("Nom (au pluriel) : ", unit); f.append(u);
      for (const r of RARS) {
        const rule = RW.bonus.rules[r] || {}, lo = el("input", "g-num"), hi = el("input", "g-num");
        for (const [i, v, n] of [[lo, rule.min, "minimum"], [hi, rule.max, "maximum"]]) { i.type = "number"; i.min = 0; i.max = 100; i.value = v == null ? "" : v; i.setAttribute("aria-label", `${n}, ${rarLabel(r)}`); }
        const line = el("div", "g-bonusrow"); line.style.setProperty("--rc", (PackFX.RARITY[r] || {}).color || "#999");
        line.append(el("b", null, rarLabel(r)), " de ", lo, " à ", hi); f.append(line); rows[r] = [lo, hi];
      }
      const b = el("button", "btn primary", "Enregistrer le bonus"); b.type = "submit";
      const err = el("p", "g-rwerr"); err.setAttribute("role", "alert"); f.append(b, err);
      const show = m => { err.textContent = m; if (m) toast(m); };
      f.onsubmit = async ev => {
        ev.preventDefault(); show("");
        const rules = {};
        for (const r of RARS) { const lo = rows[r][0].value, hi = rows[r][1].value; rules[r] = hi === "" || +hi < 1 ? null : { min: lo === "" ? +hi : +lo, max: +hi }; }
        if (Object.values(rules).some(Boolean) && !unit.value.trim()) { show("Indique le nom de la monnaie (par exemple « crédits ») pour activer un bonus."); unit.focus(); return; }
        try { await rwApi("PUT", "/api/rewards/bonus", { unit: unit.value, rules }); toast("Bonus enregistré"); paint(); } catch (er) { show(er && er.message && isNaN(er.message) ? er.message : "Enregistrement impossible, réessayer"); }
      };
      card.append(f); return card;
    }
    function row(x) {
      const li = el("li"); li.append(el("span", "g-rwico", x.icon || "🎁"), el("span", "g-rwlab", x.label));
      const e = el("button", "g-rwb", "✏️"); e.type = "button"; e.title = "Modifier"; e.setAttribute("aria-label", "Modifier " + x.label); e.onclick = () => { RW.editing = x.id; paint(); };
      const d = el("button", "g-rwb", "🗑️"); d.type = "button"; d.title = "Supprimer"; d.setAttribute("aria-label", "Supprimer " + x.label);
      d.onclick = async () => { if (!confirm(`Supprimer « ${x.label} » ?`)) return; try { await rwApi("DELETE", "/api/rewards/" + x.id); paint(); } catch (er) { fail(er); } };
      li.append(e, d); return li;
    }
    function editRow(x) {
      const f = el("form", "g-rwform"), ico = el("input", "g-rwi"), lab = el("input", "g-rwt"), sel = el("select", "g-rws");
      ico.value = x.icon || ""; ico.maxLength = 8; ico.placeholder = "🎁"; ico.setAttribute("aria-label", "Icône");
      lab.value = x.label; lab.maxLength = 80; lab.required = true; lab.setAttribute("aria-label", "Récompense");
      for (const r of RARS) { const o = el("option", null, rarLabel(r)); o.value = r; o.selected = r === x.rarity; sel.append(o); }
      sel.setAttribute("aria-label", "Rareté");
      const ok = el("button", "btn primary", "Enregistrer"), no = el("button", "btn", "Annuler"); ok.type = "submit"; no.type = "button";
      no.onclick = () => { RW.editing = null; paint(); };
      f.onsubmit = async ev => { ev.preventDefault(); try { await rwApi("PUT", "/api/rewards/" + x.id, { label: lab.value, rarity: sel.value, icon: ico.value }); RW.editing = null; paint(); } catch (er) { fail(er); } };
      f.append(ico, lab, sel, ok, no); const li = el("li", "editing"); li.append(f); setTimeout(() => lab.focus(), 0); return li;
    }
    function addForm(r) {
      const f = el("form", "g-rwform add"), ico = el("input", "g-rwi"), lab = el("input", "g-rwt");
      ico.maxLength = 8; ico.placeholder = "🎁"; ico.setAttribute("aria-label", "Icône (emoji)");
      lab.maxLength = 80; lab.required = true; lab.placeholder = `Ajouter une récompense ${rarLabel(r).toLowerCase()}…`; lab.setAttribute("aria-label", "Nouvelle récompense " + rarLabel(r));
      const b = el("button", "btn", "Ajouter"); b.type = "submit";
      f.onsubmit = async ev => { ev.preventDefault(); try { await rwApi("POST", "/api/rewards", { label: lab.value, rarity: r, icon: ico.value }); paint(); } catch (er) { fail(er); } };
      f.append(ico, lab, b); return f;
    }
    paint();
    fetch("/api/rewards").then(r => r.ok ? r.json() : Promise.reject()).then(j => { RW.list = j.rewards; RW.weights = j.weights; RW.bonus = j.bonus || RW.bonus; if (sec.isConnected) paint(); }).catch(() => { if (!RW.list) sec.append(el("p", "g-empty", "Impossible de charger les récompenses.")); });
    return sec;
  }

  function history(g) {
    const sec = el("section", "g-sec"); sec.append(el("h2", null, "Derniers points"));
    if (!g.history.length) { sec.append(el("p", "g-empty", "Les notes de 16 ou plus et les missions réussies rapportent des points : 16-17 = 1 pt, 18-19 = 2 pts, 20 = 3 pts.")); return sec; }
    const ul = el("ul", "g-list");
    for (const h of g.history) { const li = el("li"); li.append(el("b", null, "+" + h.points), " " + h.label.replace(/&amp;/g, "&")); ul.append(li); }
    sec.append(ul); return sec;
  }

  function admin() {   // outils de test : compte administrateur seulement
    const sec = el("section", "g-sec g-admin");
    sec.append(el("h2", null, "Outils de test (administrateur)"));
    const row = el("div", "g-adm");
    row.append(el("span", "g-sub", "M'octroyer des points :"));
    for (const n of [1, 3, 10, 25]) {
      const b = el("button", "btn", "+" + n); b.type = "button";
      b.onclick = async () => {
        try {
          const r = await fetch("/api/admin/points", { method: "POST", headers: JSON_HDR, body: JSON.stringify({ points: n }) });
          if (!r.ok) throw new Error(r.status);
          await refresh(); toast(`+${pts(n)} ajouté${n > 1 ? "s" : ""}`);
        } catch (e) { toast("Impossible d'ajouter les points"); }
      };
      row.append(b);
    }
    sec.append(row);
    const row2 = el("div", "g-adm");
    row2.append(el("span", "g-sub", "Tester la célébration :"));
    const t = el("button", "btn", "🏆 Simuler une mission réussie (+5 pts)"); t.type = "button";
    t.onclick = async () => {
      try {
        const r = await fetch("/api/admin/mission-done", { method: "POST" });
        if (!r.ok) throw new Error(r.status);
        await refresh();      // la célébration s'affiche au rafraîchissement
      } catch (e) { toast("Impossible de simuler la mission"); }
    };
    row2.append(t); sec.append(row2); return sec;
  }

  function draw() {
    if (!data.packs_list) { root.replaceChildren(el("p", "g-empty", "Chargement…")); return; }   // la page ne contient que le résumé ; le détail arrive par /api/game
    root.replaceChildren(levelCard(data), ...[packs(data)].filter(Boolean), missions(data));
    const r = rewards(data); if (r) root.append(r);
    if (canDeliver()) root.append(rewardsEditor());
    root.append(history(data));
    if (document.documentElement.dataset.role === "admin") root.append(admin());
  }

  async function refresh() {
    try {
      const r = await fetch("/api/game"); if (!r.ok) throw new Error(r.status);
      data = await r.json(); paintAvatar(data); draw(); celebrate(data);
      if (wantPacks) { wantPacks = false; setTimeout(scrollPacks, 60); }
    } catch (e) { /* on garde ce qui est affiché */ }
  }

  // ---- célébration des missions réussies, à la prochaine ouverture (l'état « déjà célébrée » est côté serveur : une seule fois, quel que soit l'appareil) ----
  let celebrating = false;
  async function celebrate(g) {
    const lvls = (g && g.levelup) || [];
    if (READONLY || celebrating || !g || !((g.celebrate && g.celebrate.length) || lvls.length)) return;
    celebrating = true;
    try {
      const list = g.celebrate || [];
      fetch("/api/missions/celebrated", { method: "POST", headers: JSON_HDR, body: JSON.stringify({ ids: list.map(m => m.id), levels: lvls }) }).catch(() => {});
      let goPacks = false;
      for (let i = 0; i < list.length; i++) {
        const last = i === list.length - 1 && !lvls.length;
        const r = await PackFX.celebrate({ label: list[i].label, points: list[i].points, packs: last ? g.packs : 0 });
        if (r === "packs") { goPacks = true; break; }
      }
      if (!goPacks && lvls.length) await PackFX.celebrate({ level: Math.max(...lvls), packs: g.packs });   // plusieurs niveaux d'un coup : on célèbre le plus haut
      if (goPacks) { wantPacks = true; if (NAV.current === "objectifs") refresh(); else go("objectifs"); }
      else if (NAV.current === "objectifs") refresh();
    } finally { celebrating = false; }
  }
  async function check() {          // au retour dans l'app : la synchro a pu valider une mission entre-temps
    try { const r = await fetch("/api/game"); if (r.ok) { data = await r.json(); paintAvatar(data); celebrate(data); } } catch (e) { /* hors ligne */ }
  }
  if (!READONLY) {
    setTimeout(() => celebrate(GAME), 700);
    document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") check(); });
  }

  VIEWS.objectifs = { el: root, draw, show: refresh };
})();
