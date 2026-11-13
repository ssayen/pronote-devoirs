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
    const sec = el("section", "g-sec g-packs"); sec.id = "g-packs";
    sec.append(el("h2", null, open.length > 1 ? `Paquets à ouvrir (${open.length})` : "Paquets"));
    if (!open.length) { sec.append(el("p", "g-empty", "Aucun paquet à ouvrir. Un nouveau paquet arrive à chaque niveau gagné.")); return sec; }
    for (const p of open) {
      const row = el("div", "g-pack-card"), art = el("div", "g-pack-art"), txt = el("div", "g-txt");
      art.append(PackFX.svg());
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
      await PackFX.open({ reward: j.reward, rarity: j.rarity, icon: j.icon || "🎁", level });
      await refresh();
    } catch (e) { btn.disabled = false; toast("Impossible d'ouvrir le paquet, réessayer"); }
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

  const canDeliver = () => READONLY || document.documentElement.dataset.role === "admin";   // le parent coche (l'admin aussi, pour tester)

  async function setDelivered(level, delivered, box) {
    box.disabled = true;
    try {
      const r = await fetch(`/api/packs/${level}/delivered`, { method: "POST", headers: JSON_HDR, body: JSON.stringify({ delivered }) });
      if (!r.ok) throw new Error(r.status);
      await refresh();
    } catch (e) { box.checked = !delivered; box.disabled = false; toast("Enregistrement impossible, réessayer"); }
  }

  function rewards(g) {
    const got = g.packs_list.filter(p => p.opened_at).sort((a, b) => !!a.delivered_at - !!b.delivered_at || b.level - a.level);   // à remettre d'abord
    if (!got.length) return null;
    const pending = got.filter(p => !p.delivered_at).length;
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
    }
    sec.append(ul); return sec;
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
    root.replaceChildren(levelCard(data), packs(data), missions(data));
    const r = rewards(data); if (r) root.append(r);
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
    if (READONLY || celebrating || !g || !g.celebrate || !g.celebrate.length) return;
    celebrating = true;
    try {
      const list = g.celebrate;
      fetch("/api/missions/celebrated", { method: "POST", headers: JSON_HDR, body: JSON.stringify({ ids: list.map(m => m.id) }) }).catch(() => {});
      let goPacks = false;
      for (let i = 0; i < list.length; i++) {
        const last = i === list.length - 1;
        const r = await PackFX.celebrate({ label: list[i].label, points: list[i].points, packs: last ? g.packs : 0 });
        if (r === "packs") { goPacks = true; break; }
      }
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
