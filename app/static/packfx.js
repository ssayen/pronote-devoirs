// Ouverture de paquet en plein écran : arrivée, charge (le paquet tremble, la lumière monte), flash, explosion de particules,
// apparition de la carte récompense aux couleurs de sa rareté. PackFX.open({ reward, rarity, icon, level }) -> Promise (fin de l'animation).
// PackFX.svg() renvoie le dessin du paquet (réutilisé dans la liste des paquets).
const PackFX = (() => {
  const RARITY = {
    common:    { label: "Commun",     color: "#9fb0c3", glow: "#c9d6e4", power: 0.6 },
    rare:      { label: "Rare",       color: "#3b9bff", glow: "#8cc4ff", power: 0.9 },
    epic:      { label: "Épique",     color: "#b45bff", glow: "#dcaaff", power: 1.15 },
    legendary: { label: "Légendaire", color: "#ffb800", glow: "#ffe08a", power: 1.7 },
  };
  const SVGNS = "http://www.w3.org/2000/svg";
  let uid = 0;

  function svg() {   // le paquet : un coffret violet aux arêtes dorées ; couvercle et joint lumineux animés séparément
    const n = ++uid;
    const box = document.createElementNS(SVGNS, "svg");
    box.setAttribute("viewBox", "0 0 220 250"); box.setAttribute("class", "pfx-svg"); box.setAttribute("aria-hidden", "true");
    box.innerHTML = `
      <defs>
        <linearGradient id="pfL${n}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5a33c0"/><stop offset="1" stop-color="#22114d"/></linearGradient>
        <linearGradient id="pfR${n}" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7143e0"/><stop offset="1" stop-color="#2d1768"/></linearGradient>
        <linearGradient id="pfT${n}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a77bff"/><stop offset="1" stop-color="#6a3fd6"/></linearGradient>
        <linearGradient id="pfG${n}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff3b0"/><stop offset="1" stop-color="#ffb800"/></linearGradient>
      </defs>
      <g class="pfx-body" stroke="#ffd45a" stroke-width="3" stroke-linejoin="round">
        <polygon points="20,100 110,145 110,235 20,190" fill="url(#pfL${n})"/>
        <polygon points="200,100 110,145 110,235 200,190" fill="url(#pfR${n})"/>
        <g transform="matrix(1 .5 0 1 0 0)"><polygon points="65,126 78,152 65,178 52,152" transform="translate(0,-6)" fill="url(#pfG${n})" stroke="none"/></g>
        <g transform="matrix(1 -.5 0 1 0 0)"><polygon points="155,244 168,270 155,296 142,270" transform="translate(0,-6)" fill="url(#pfG${n})" stroke="none"/></g>
      </g>
      <g class="pfx-lid" stroke="#ffd45a" stroke-width="3" stroke-linejoin="round">
        <polygon points="110,55 200,100 110,145 20,100" fill="url(#pfT${n})"/>
        <polygon points="110,74 164,100 110,126 56,100" fill="none" stroke-width="2" opacity=".85"/>
        <polygon points="20,100 110,145 110,160 20,115" fill="#3a1f84"/>
        <polygon points="200,100 110,145 110,160 200,115" fill="#4a2aa3"/>
      </g>
      <polygon class="pfx-leak" points="20,108 110,153 200,108 200,114 110,159 20,114" fill="#fff"/>`;
    return box;
  }

  function open({ reward, rarity = "common", icon = "🎁", level }) {
    return new Promise(resolve => {
      const R = RARITY[rarity] || RARITY.common;
      const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
      const root = document.createElement("div");
      root.className = "pfx"; root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-label", "Ouverture de paquet");
      root.style.setProperty("--rc", R.color); root.style.setProperty("--rg", R.glow);
      root.innerHTML = `
        <canvas class="pfx-canvas"></canvas><div class="pfx-vignette"></div>
        <div class="pfx-rays"></div><div class="pfx-beam"></div>
        <div class="pfx-stage">
          <div class="pfx-pack"></div>
          <div class="pfx-ring"></div><div class="pfx-ring r2"></div><div class="pfx-ring r3"></div>
          <div class="pfx-card" aria-live="polite">
            <span class="pfx-rarity">${R.label}</span>
            <span class="pfx-icon">${icon}</span>
            <strong class="pfx-name"></strong>
            <span class="pfx-lvl">Paquet du niveau ${level}</span>
          </div>
        </div>
        <div class="pfx-flash"></div>
        <button type="button" class="pfx-skip">Passer</button>
        <button type="button" class="btn primary pfx-done">Super !</button>`;
      root.querySelector(".pfx-name").textContent = reward;
      const packEl = root.querySelector(".pfx-pack"); packEl.append(svg());
      const leak = packEl.querySelector(".pfx-leak");
      const canvas = root.querySelector(".pfx-canvas"), g = canvas.getContext("2d");
      const prevFocus = document.activeElement;
      const prevOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      document.body.append(root);

      // ---- dimensions du canevas ----
      let W = 0, H = 0, dpr = 1;
      const fit = () => {
        dpr = Math.min(window.devicePixelRatio || 1, 2); W = innerWidth; H = innerHeight;
        canvas.width = W * dpr; canvas.height = H * dpr; g.setTransform(dpr, 0, 0, dpr, 0, 0);
      };
      fit(); addEventListener("resize", fit);

      // ---- particules ----
      const parts = [];
      const rnd = (a, b) => a + Math.random() * (b - a);
      const palette = [R.color, R.glow, "#ffffff", "#ffd45a", R.color];
      const center = () => { const r = packEl.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
      const spark = (x, y, a, v, life, size, col) => parts.push({ t: "s", x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life, max: life, size, col, g: 0 });
      const confetti = (x, y, power) => {
        const a = rnd(-Math.PI * 0.95, -Math.PI * 0.05), v = rnd(250, 900) * Math.min(power, 1.4);
        parts.push({ t: "c", x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life: rnd(1.8, 3.4), max: 3.4, size: rnd(6, 12), col: palette[(Math.random() * palette.length) | 0],
                     rot: rnd(0, 6.28), vr: rnd(-9, 9), g: 900, flip: rnd(0, 6.28) });
      };
      function burst() {
        const [x, y] = center(), p = R.power;
        for (let i = 0; i < 150 * p; i++) spark(x, y, rnd(0, 6.283), rnd(250, 1000) * Math.min(p, 1.3), rnd(0.5, 1.3), rnd(1.5, 3.2), palette[(Math.random() * palette.length) | 0]);
        for (let i = 0; i < 90 * p; i++) confetti(x, y, p);
        if (rarity === "legendary") setTimeout(() => { if (!closed) for (let i = 0; i < 70; i++) confetti(rnd(0, W), -20, 1); }, 500);
      }
      let last = 0, closed = false, raf = 0, phase = "in", t0 = 0, tBurst = 0, shake = 0;
      function frame(now) {
        if (closed) return;
        raf = requestAnimationFrame(frame);
        const dt = Math.min((now - (last || now)) / 1000, 0.05); last = now;
        const t = now - t0;
        // paquet : tremblement croissant pendant la charge, lumière du joint qui monte
        if (phase === "charge") {
          const k = Math.min((t - 800) / 1500, 1), amp = 1 + 11 * k * k;
          packEl.style.transform = `translate(${Math.sin(t / 22) * amp}px, ${Math.cos(t / 27) * amp * .6}px) rotate(${Math.sin(t / 31) * amp * .35}deg) scale(${1 + .12 * k})`;
          leak.style.opacity = k; leak.style.filter = `drop-shadow(0 0 ${6 + 26 * k}px ${k > .6 ? R.color : "#fff"})`;
          root.style.setProperty("--charge", k.toFixed(3));
          const [x, y] = center();
          if (Math.random() < 0.25 + k * 1.1) spark(x + rnd(-70, 70), y + rnd(-10, 60), -Math.PI / 2 + rnd(-.5, .5), rnd(80, 260) * (.5 + k), rnd(.5, 1.1), rnd(1.2, 2.6), k > .5 ? R.glow : "#ffd45a");
          if (t > 2300) go("burst");
        }
        // secousse de l'écran à l'explosion
        if (phase !== "in" && phase !== "charge" && shake > 0) {
          shake = Math.max(0, shake - dt * 28);
          root.querySelector(".pfx-stage").style.transform = `translate(${rnd(-shake, shake)}px, ${rnd(-shake, shake)}px)`;
        }
        g.clearRect(0, 0, W, H); g.globalCompositeOperation = "lighter";
        for (let i = parts.length - 1; i >= 0; i--) {
          const p = parts[i]; p.life -= dt;
          if (p.life <= 0) { parts.splice(i, 1); continue; }
          p.vy += p.g * dt; p.x += p.vx * dt; p.y += p.vy * dt;
          const a = Math.max(0, Math.min(1, p.life / (p.max * .5)));
          g.globalAlpha = a; g.strokeStyle = g.fillStyle = p.col;
          if (p.t === "s") { g.lineWidth = p.size; g.lineCap = "round"; g.beginPath(); g.moveTo(p.x, p.y); g.lineTo(p.x - p.vx * .035, p.y - p.vy * .035); g.stroke(); }
          else {
            p.vx *= 1 - .9 * dt; p.rot += p.vr * dt; p.flip += 7 * dt;
            g.save(); g.translate(p.x, p.y); g.rotate(p.rot); g.scale(1, Math.cos(p.flip)); g.globalCompositeOperation = "source-over"; g.fillRect(-p.size / 2, -p.size / 3, p.size, p.size * .66); g.restore();
          }
        }
        g.globalAlpha = 1; g.globalCompositeOperation = "source-over";
      }

      // ---- déroulé ----
      const timers = [];
      const later = (fn, ms) => timers.push(setTimeout(fn, ms));
      function go(next) {
        if (phase === next || closed) return;
        phase = next; root.dataset.phase = next;
        if (next === "charge") root.classList.add("charge");
        if (next === "burst") {
          packEl.style.transform = ""; shake = 22; tBurst = performance.now();
          root.classList.add("burst"); burst();
          later(() => go("reveal"), 380);
        }
        if (next === "reveal") { root.classList.add("reveal"); later(() => go("done"), 1100); }
        if (next === "done") { root.classList.add("done"); root.querySelector(".pfx-done").focus(); root.querySelector(".pfx-skip").hidden = true; }
      }
      function close() {
        if (closed) return; closed = true; cancelAnimationFrame(raf); timers.forEach(clearTimeout);
        removeEventListener("resize", fit); removeEventListener("keydown", onKey, true);
        root.classList.add("out");
        setTimeout(() => { root.remove(); document.body.style.overflow = prevOverflow; if (prevFocus && prevFocus.focus) prevFocus.focus(); resolve(); }, calm ? 0 : 250);
      }
      const onKey = ev => {
        if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); phase === "done" ? close() : skip(); }
        else if (ev.key === "Tab") { ev.preventDefault(); (phase === "done" ? root.querySelector(".pfx-done") : root.querySelector(".pfx-skip")).focus(); }
      };
      addEventListener("keydown", onKey, true);
      const skip = () => { timers.forEach(clearTimeout); timers.length = 0; phase === "in" || phase === "charge" ? (root.classList.add("charge"), go("burst")) : go("done"); };
      root.querySelector(".pfx-skip").onclick = skip;
      root.querySelector(".pfx-done").onclick = close;

      if (calm) {   // mouvement réduit : pas de secousse ni de particules, la carte apparaît directement
        root.classList.add("calm", "burst", "reveal", "done"); phase = "done"; root.querySelector(".pfx-skip").hidden = true;
        root.querySelector(".pfx-done").focus(); return;
      }
      t0 = performance.now(); raf = requestAnimationFrame(frame);
      root.querySelector(".pfx-skip").focus();
      later(() => go("charge"), 800);
    });
  }

  return { open, svg, RARITY };
})();
