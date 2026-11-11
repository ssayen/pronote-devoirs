// Personnalisation : avatar affiché en haut à droite (galerie) et thème clair / sombre.
// Les choix sont enregistrés sur le serveur (PUT /api/settings) : ils persistent entre les appareils et les redéploiements.
// Utilise les fonctions globales de la page (el, $, toast, JSON_HDR) et les constantes SETTINGS, AVATARS.
(() => {
  const root = $("#v-perso"), btn = $("#avatar");
  const byId = Object.fromEntries(AVATARS.map(a => [a.id, a]));
  let avatar = byId[SETTINGS.avatar] ? SETTINGS.avatar : null;
  let theme = SETTINGS.theme || "auto";
  const src = id => `/static/avatars/${id}.jpg`;

  function paintButton() {
    btn.replaceChildren();
    btn.classList.toggle("empty", !avatar);
    if (avatar) {
      const i = el("img"); i.src = src(avatar); i.alt = ""; btn.append(i);
      btn.title = `Mon profil (avatar : ${byId[avatar].name})`; btn.setAttribute("aria-label", btn.title);
    } else {
      btn.append(el("span", null, "?"));
      btn.title = "Mon profil (aucun avatar choisi)"; btn.setAttribute("aria-label", btn.title);
    }
  }

  async function save(patch) {
    const r = await fetch("/api/settings", { method: "PUT", headers: JSON_HDR, body: JSON.stringify(patch) });
    if (!r.ok) throw new Error(r.status);
  }

  async function choose(id) {
    if (id === avatar) return;
    const before = avatar;
    avatar = id; paintButton(); draw();                    // affichage immédiat, annulé si l'enregistrement échoue
    try {
      await save({ avatar: id });
      toast(id ? `Avatar enregistré : ${byId[id].name}` : "Avatar retiré");
    } catch (e) {
      avatar = before; paintButton(); draw(); toast("Enregistrement impossible, réessayer");
    }
  }

  const THEMES = [["auto", "Automatique", "Suit l'appareil"], ["light", "Clair", ""], ["dark", "Sombre", ""]];
  async function chooseTheme(t) {
    if (t === theme) return;
    const before = theme;
    theme = t; applyTheme(t); draw();
    try {
      await save({ theme: t });
      toast("Thème enregistré : " + THEMES.find(x => x[0] === t)[1].toLowerCase());
    } catch (e) {
      theme = before; applyTheme(before); draw(); toast("Enregistrement impossible, réessayer");
    }
  }
  // ancien réglage (mémorisé dans ce navigateur avant l'existence de cette page) : repris une seule fois
  try {
    const old = localStorage.getItem("theme");
    if (old) {
      localStorage.removeItem("theme");
      if (theme === "auto" && (old === "light" || old === "dark")) { theme = old; applyTheme(old); save({ theme: old }).catch(() => {}); }
    }
  } catch (e) {}

  function tile(id, name) {
    const b = el("button", "av-tile"); b.type = "button"; b.setAttribute("aria-pressed", id === avatar);
    const face = el("span", "av-face" + (id ? "" : " none"));
    if (id) { const i = el("img"); i.src = src(id); i.alt = ""; i.loading = "lazy"; i.width = i.height = 512; face.append(i); } else face.append("?");
    b.append(face, el("span", "av-name", name));
    if (id === avatar) b.append(el("span", "av-check", "✓"));
    b.onclick = () => choose(id);
    return b;
  }

  function draw() {
    root.replaceChildren();
    const head = el("div", "pv-head");
    const back = el("button", "chip", "‹ Retour"); back.type = "button"; back.onclick = goBack;
    head.append(back, el("h2", "tt-title", "Personnalisation"));
    root.append(head);

    const card = el("section", "rcard");
    card.append(el("h2", null, "Mon avatar"));
    const cur = el("div", "av-current");
    const big = el("span", "av-face big" + (avatar ? "" : " none"));
    if (avatar) { const i = el("img"); i.src = src(avatar); i.alt = ""; big.append(i); } else big.append("?");
    const txt = el("div");
    txt.append(el("b", null, avatar ? byId[avatar].name : "Pas encore d'avatar"),
               el("div", "hint", avatar ? "Visible en haut à droite de l'écran." : "Choisir une image ci-dessous : elle s'affichera en haut à droite."));
    cur.append(big, txt); card.append(cur);

    if (!AVATARS.length) { card.append(el("div", "rempty", "Aucun avatar disponible.")); root.append(card); return; }
    const grid = el("div", "av-grid"); grid.setAttribute("role", "group"); grid.setAttribute("aria-label", "Galerie d'avatars");
    for (const a of AVATARS) grid.append(tile(a.id, a.name));
    if (avatar) grid.append(tile(null, "Aucun"));
    card.append(grid);
    root.append(card);

    const look = el("section", "rcard"); look.id = "look";
    look.append(el("h2", null, "Apparence"));
    const tg = el("div", "th-grid"); tg.setAttribute("role", "group"); tg.setAttribute("aria-label", "Thème");
    for (const [id, name, sub] of THEMES) {
      const b = el("button", "th-opt"); b.type = "button"; b.setAttribute("aria-pressed", id === theme);
      const p = el("span", "th-prev " + id); b.append(p, name);
      if (sub) b.append(el("span", "th-sub", sub));
      b.onclick = () => chooseTheme(id);
      tg.append(b);
    }
    look.append(tg); root.append(look);
  }

  // ---- menu déroulant de l'avatar : une entrée par élément de MENU (ajouter ici les futures options) ----
  const menu = $("#avatar-menu");
  const MENU = [
    { label: "Changer d'avatar", icon: () => (avatar ? src(avatar) : null), action: () => go("perso") },
    { label: "Apparence (clair / sombre)", icon: () => null, mark: "◐", action: () => { go("perso"); setTimeout(() => { const l = $("#look"); if (l) l.scrollIntoView({ behavior: "smooth", block: "start" }); }, 50); } },
  ];
  const items = () => [...menu.querySelectorAll("[role=menuitem]")];
  function closeMenu(focusBtn) {
    if (menu.hidden) return;
    menu.hidden = true; btn.setAttribute("aria-expanded", "false");
    if (focusBtn) btn.focus();
  }
  function openMenu(focusFirst) {
    menu.replaceChildren();
    for (const m of MENU) {
      const b = el("button"); b.type = "button"; b.setAttribute("role", "menuitem");
      const ico = el("span", "m-ico"), u = m.icon && m.icon();
      if (u) { const i = el("img"); i.src = u; i.alt = ""; ico.append(i); } else ico.append(m.mark || "?");
      b.append(ico, m.label);
      b.onclick = () => { closeMenu(false); m.action(); };
      menu.append(b);
    }
    menu.hidden = false; btn.setAttribute("aria-expanded", "true");
    if (focusFirst) items()[0].focus();
  }
  btn.onclick = ev => { ev.stopPropagation(); if (menu.hidden) openMenu(ev.detail === 0); else closeMenu(false); };
  document.addEventListener("click", ev => { if (!menu.hidden && !menu.contains(ev.target)) closeMenu(false); });
  document.addEventListener("keydown", ev => {
    if (menu.hidden) return;
    if (ev.key === "Escape") { ev.preventDefault(); closeMenu(true); return; }
    if (ev.key === "Tab") { closeMenu(false); return; }
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const l = items(), i = l.indexOf(document.activeElement);
      l[(i + (ev.key === "ArrowDown" ? 1 : -1) + l.length) % l.length].focus();
    }
  });
  btn.addEventListener("keydown", ev => { if (ev.key === "ArrowDown" && menu.hidden) { ev.preventDefault(); openMenu(true); } });
  paintButton();
  VIEWS.perso = { el: root, draw };
})();
