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

  // ---- son : tout est synthétisé (Web Audio), aucun fichier ----
  const NOTES = { C5: 523.25, E5: 659.25, G5: 783.99, C6: 1046.5, E6: 1318.5, G6: 1568, C7: 2093 };
  const ARPEGE = { common: ["C5", "E5", "G5"], rare: ["C5", "E5", "G5", "C6"], epic: ["C5", "E5", "G5", "C6", "E6"],
                   legendary: ["C5", "E5", "G5", "C6", "E6", "G6", "C7"] };

  function makeSound(ctx, out, power = 1, rarity = "common") {
    const noise = (() => { const b = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate), d = b.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1; return b; })();
    const live = [];                                   // gains de la montée : coupés net si on passe l'animation
    const env = (g, t, peak, attack, dur) => { g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(peak, t + attack); g.gain.exponentialRampToValueAtTime(0.0001, t + dur); };
    function tone(f0, t, dur, { type = "sine", gain = 0.3, f1 = null, attack = 0.005, dest = out, keep = false } = {}) {
      const o = ctx.createOscillator(), g = ctx.createGain(); o.type = type; o.frequency.setValueAtTime(f0, t);
      if (f1) o.frequency.exponentialRampToValueAtTime(f1, t + dur);
      env(g, t, gain, attack, dur); o.connect(g); g.connect(dest); o.start(t); o.stop(t + dur + 0.05); if (keep) live.push(g);
    }
    function hiss(t, dur, { type = "lowpass", f0 = 2000, f1 = 200, gain = 0.3, q = 0.7, attack = 0.005, keep = false } = {}) {
      const src = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain(); src.buffer = noise; src.loop = true;
      f.type = type; f.Q.value = q; f.frequency.setValueAtTime(f0, t); f.frequency.exponentialRampToValueAtTime(f1, t + dur);
      env(g, t, gain, attack, dur); src.connect(f); f.connect(g); g.connect(out); src.start(t, Math.random()); src.stop(t + dur + 0.05); if (keep) live.push(g);
    }
    const bell = (f, t, dur = 0.9, gain = 0.2) => { tone(f, t, dur, { gain, attack: 0.003 }); tone(f * 2.76, t, dur * 0.5, { gain: gain * 0.35, attack: 0.002 }); tone(f * 0.5, t, dur * 0.7, { gain: gain * 0.25, type: "triangle" }); };
    return {
      drop(t) {                                      // chute (sifflement) puis choc au contact
        hiss(t, 0.42, { type: "bandpass", f0: 3000, f1: 350, gain: 0.18, q: 1.2 });
        tone(150, t + 0.45, 0.3, { f1: 42, gain: 0.85 }); hiss(t + 0.45, 0.08, { type: "highpass", f0: 1800, f1: 3500, gain: 0.25 });
      },
      charge(t, dur = 1.5) {                         // montée de tension : la hauteur et le grondement grimpent, battements de plus en plus rapides
        const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.setValueAtTime(300, t); lp.frequency.exponentialRampToValueAtTime(5500, t + dur);
        lp.connect(out);
        for (const [type, a, b, g] of [["sawtooth", 70, 760, 0.16], ["square", 140, 1500, 0.05]]) {
          const o = ctx.createOscillator(), gn = ctx.createGain(); o.type = type; o.frequency.setValueAtTime(a, t); o.frequency.exponentialRampToValueAtTime(b, t + dur);
          gn.gain.setValueAtTime(0.0001, t); gn.gain.linearRampToValueAtTime(g, t + dur); o.connect(gn); gn.connect(lp); o.start(t); o.stop(t + dur + 0.1); live.push(gn);
        }
        hiss(t, dur, { type: "lowpass", f0: 200, f1: 1400, gain: 0.3, attack: dur * 0.9, keep: true });
        const n = 18;
        for (let i = 0; i < n; i++) tone(380 + 1300 * (i / n), t + dur * (1 - Math.pow(1 - i / n, 1.8)), 0.06, { type: "triangle", gain: 0.12 + 0.12 * i / n });
      },
      slam(t) {                                      // impact de la bannière
        tone(70, t, 0.7, { f1: 32, gain: 0.8 }); hiss(t, 0.45, { type: "lowpass", f0: 3500, f1: 100, gain: 0.45 }); hiss(t, 0.1, { type: "highpass", f0: 2500, f1: 5000, gain: 0.3 });
      },
      pop(t) {                                       // éclatement d'un feu d'artifice : bang sourd, claquement, crépitement
        tone(190, t, 0.14, { f1: 55, gain: 0.35 }); hiss(t, 0.07, { type: "highpass", f0: 3500, f1: 6500, gain: 0.3 });
        for (let i = 0; i < 4; i++) hiss(t + 0.06 + Math.random() * 0.4, 0.03, { type: "highpass", f0: 5000, f1: 8000, gain: 0.08 + Math.random() * 0.06 });
      },
      finale(t) {                                    // épique : courte fanfare ; légendaire : roulement, fanfare, accord géant, chœur et cymbale
        const brass = (f, s, dur, gain = 0.16) => {
          const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.setValueAtTime(500, s); lp.frequency.exponentialRampToValueAtTime(3200, s + 0.12); lp.connect(out);
          const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, s); g.gain.linearRampToValueAtTime(gain, s + 0.04); g.gain.setValueAtTime(gain, s + dur * 0.7); g.gain.exponentialRampToValueAtTime(0.0001, s + dur); g.connect(lp);
          for (const d of [-6, 0, 6]) { const o = ctx.createOscillator(); o.type = "sawtooth"; o.frequency.value = f; o.detune.value = d; o.connect(g); o.start(s); o.stop(s + dur + 0.05); }
        };
        const timp = (s, gain) => { tone(120, s, 0.45, { f1: 48, gain }); hiss(s, 0.08, { type: "lowpass", f0: 900, f1: 200, gain: gain * 0.4 }); };
        this.slam(t);
        if (rarity === "epic") {
          timp(t + 0.3, 0.5); brass(392, t + 0.45, 0.25); brass(523.3, t + 0.7, 0.25); brass(659.3, t + 0.95, 1.4, 0.2); brass(329.6, t + 0.95, 1.4, 0.12);
          return;
        }
        for (let i = 0; i < 12; i++) timp(t + 0.25 + 0.9 * (1 - Math.pow(1 - i / 12, 1.7)), 0.18 + 0.3 * i / 12);   // roulement de timbales qui s'accélère
        [[261.6, 0], [329.6, 0.2], [392, 0.4], [523.3, 0.6]].forEach(([f, d]) => brass(f, t + 1.2 + d, 0.22, 0.17));
        const hit = t + 2.0;
        for (const f of [130.8, 261.6, 329.6, 392, 523.3, 659.3, 784]) brass(f, hit, 2.8, 0.14);
        timp(hit, 0.9); hiss(hit, 2.2, { type: "highpass", f0: 5500, f1: 3000, gain: 0.3 });                     // cymbale
        const f1 = ctx.createBiquadFilter(), f2 = ctx.createBiquadFilter(), pad = ctx.createGain();            // chœur : voyelle « a » (deux formants)
        f1.type = f2.type = "bandpass"; f1.frequency.value = 700; f2.frequency.value = 1150; f1.Q.value = f2.Q.value = 4;
        pad.gain.setValueAtTime(0.0001, hit - 0.2); pad.gain.linearRampToValueAtTime(0.5, hit + 0.8); pad.gain.exponentialRampToValueAtTime(0.0001, hit + 3.2);
        f1.connect(pad); f2.connect(pad); pad.connect(out);
        for (const f of [196, 261.6, 329.6, 392, 523.3]) for (const d of [-7, 0, 7]) { const o = ctx.createOscillator(); o.type = "sawtooth"; o.frequency.value = f; o.detune.value = d; o.connect(f1); o.connect(f2); o.start(hit - 0.2); o.stop(hit + 3.3); }
        for (let i = 0; i < 16; i++) bell(2500 + Math.random() * 3000, hit + 0.2 + i * 0.13, 0.5, 0.045);
      },
      stopCharge() { const t = ctx.currentTime; for (const g of live) { try { g.gain.cancelScheduledValues(t); g.gain.setTargetAtTime(0.0001, t, 0.02); } catch (e) {} } live.length = 0; },
      burst(t) {                                     // explosion : grosse basse, souffle, claquement
        const k = Math.min(power, 1.4);
        tone(95, t, 0.9 + 0.5 * k, { f1: 26, gain: 0.7 * k });
        hiss(t, 1.0, { type: "lowpass", f0: 9000, f1: 150, gain: 0.5 * k });
        hiss(t, 0.14, { type: "highpass", f0: 3000, f1: 6000, gain: 0.4 });
        tone(1300, t, 0.5, { type: "sawtooth", f1: 60, gain: 0.22 });
        if (rarity === "legendary") { tone(70, t + 0.16, 1.6, { f1: 24, gain: 0.5 }); hiss(t + 0.16, 0.9, { type: "lowpass", f0: 6000, f1: 200, gain: 0.3 }); }
      },
      reveal(t) {                                    // arpège brillant ; plus la rareté est haute, plus il est long et riche
        const seq = ARPEGE[rarity] || ARPEGE.common, step = rarity === "legendary" ? 0.075 : 0.095;
        seq.forEach((n, i) => bell(NOTES[n], t + i * step, 0.9 + i * 0.05, 0.18));
        const end = t + seq.length * step;
        if (rarity === "epic" || rarity === "legendary") {   // accord tenu
          const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 1500; lp.connect(out);
          const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, end); g.gain.linearRampToValueAtTime(rarity === "legendary" ? 0.22 : 0.14, end + 0.25); g.gain.exponentialRampToValueAtTime(0.0001, end + 2); g.connect(lp);
          for (const f of [261.6, 329.6, 392, 523.3, rarity === "legendary" ? 784 : 659.3]) for (const d of [-4, 4]) { const o = ctx.createOscillator(); o.type = "sawtooth"; o.frequency.value = f; o.detune.value = d; o.connect(g); o.start(end); o.stop(end + 2.1); }
        }
        if (rarity === "legendary") {                        // gong et pluie de paillettes
          tone(220, end, 2.2, { gain: 0.25 }); tone(220 * 2.4, end, 1.6, { gain: 0.1 }); tone(220 * 3.76, end, 1.1, { gain: 0.06 });
          for (let i = 0; i < 12; i++) bell(2000 + Math.random() * 2600, end + 0.1 + i * 0.1 + Math.random() * 0.05, 0.5, 0.05);
        } else if (rarity === "epic") for (let i = 0; i < 6; i++) bell(2200 + Math.random() * 1800, end + 0.1 + i * 0.12, 0.45, 0.045);
      },
    };
  }
  let actx = null, master = null;
  const soundOn = () => { try { return localStorage.getItem("pfx-sound") !== "0"; } catch (e) { return true; } };
  function setSound(on) { try { localStorage.setItem("pfx-sound", on ? "1" : "0"); } catch (e) {} if (master) master.gain.value = on ? 0.8 : 0; }
  function unlock() {   // à appeler dans le geste de l'utilisateur (clic) : les navigateurs mobiles l'exigent pour jouer un son
    try {
      if (!actx) {
        const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
        actx = new AC(); const comp = actx.createDynamicsCompressor(); master = actx.createGain();
        comp.threshold.value = -20; comp.knee.value = 12; comp.ratio.value = 10; comp.attack.value = 0.003; comp.release.value = 0.2; master.gain.value = soundOn() ? 0.8 : 0;
        master.connect(comp); comp.connect(actx.destination);
      }
      if (actx.state === "suspended") actx.resume();
    } catch (e) { actx = null; }
  }
  const quiet = { drop() {}, charge() {}, stopCharge() {}, burst() {}, reveal() {} };
  function sounds(power, rarity) { unlock(); return actx ? makeSound(actx, master, power, rarity) : quiet; }
  const buzz = p => { try { if (soundOn() && navigator.vibrate) navigator.vibrate(p); } catch (e) {} };
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
      root.dataset.rarity = rarity;
      root.style.setProperty("--rc", R.color); root.style.setProperty("--rg", R.glow);
      root.innerHTML = `
        <canvas class="pfx-canvas"></canvas><div class="pfx-vignette"></div>
        <div class="pfx-rays"></div><div class="pfx-beam"></div><div class="pfx-frame"></div>
        ${rarity === "epic" || rarity === "legendary" ? `<div class="pfx-banner"><span>${R.label}</span></div>` : ""}
        <div class="pfx-stage">
          <div class="pfx-pack"></div>
          <div class="pfx-ring"></div><div class="pfx-ring r2"></div><div class="pfx-ring r3"></div>
          <div class="pfx-aura"></div>
          <div class="pfx-orbit">${Array.from({ length: rarity === "legendary" ? 10 : 6 }, (_, i) => `<i style="--a:${(360 / (rarity === "legendary" ? 10 : 6)) * i}deg;--d:${(i % 3) * .3}s">✦</i>`).join("")}</div>
          <div class="pfx-card" aria-live="polite">
            <span class="pfx-rarity">${R.label}</span>
            <span class="pfx-icon">${icon}</span>
            <strong class="pfx-name"></strong>
            <span class="pfx-lvl">Paquet du niveau ${level}</span>
          </div>
        </div>
        <div class="pfx-flash"></div>
        <button type="button" class="pfx-mute"></button>
        <button type="button" class="pfx-skip">Passer</button>
        <button type="button" class="btn primary pfx-done">Super !</button>`;
      root.querySelector(".pfx-name").textContent = reward;
      const packEl = root.querySelector(".pfx-pack"); packEl.append(svg());
      const leak = packEl.querySelector(".pfx-leak");
      const canvas = root.querySelector(".pfx-canvas"), g = canvas.getContext("2d");
      const snd = sounds(R.power, rarity);
      const mute = root.querySelector(".pfx-mute");
      const paintMute = () => { const on = soundOn(); mute.textContent = on ? "🔊" : "🔇"; mute.setAttribute("aria-label", on ? "Couper le son" : "Activer le son"); mute.setAttribute("aria-pressed", String(!on)); };
      mute.onclick = () => { setSound(!soundOn()); paintMute(); };
      paintMute();
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
      const spark = (x, y, a, v, life, size, col, grav = 0) => parts.push({ t: "s", x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, life, max: life, size, col, g: grav });
      const FIRE = rarity === "legendary" ? ["#ffd45a", "#ffffff", "#ff6bd6", "#6bd6ff", "#ffb800", "#9dff6b"] : ["#b45bff", "#dcaaff", "#ffffff", "#ff6bd6"];
      function explode(x, y, col) {   // gerbe sphérique + paillettes blanches
        snd.pop(actx ? actx.currentTime : 0);
        const n = rarity === "legendary" ? 90 : 60;
        for (let i = 0; i < n; i++) spark(x, y, (i / n) * 6.283 + rnd(-.05, .05), rnd(90, 360), rnd(.9, 1.7), rnd(1.8, 3), i % 5 === 0 ? "#fff" : col, 240);
        for (let i = 0; i < 18; i++) spark(x, y, rnd(0, 6.283), rnd(20, 140), rnd(1, 2), 1.4, "#fff", 120);
      }
      function firework() {           // fusée qui monte puis éclate à un endroit aléatoire du haut de l'écran
        const tx = rnd(W * .12, W * .88), ty = rnd(H * .1, H * .42), g0 = 900, vy = -Math.sqrt(2 * g0 * (H + 10 - ty));
        parts.push({ t: "r", x: tx + rnd(-20, 20), y: H + 10, vx: rnd(-25, 25), vy, life: 6, max: 12, size: 3, col: "#fff", g: g0, boom: FIRE[(Math.random() * FIRE.length) | 0] });
      }
      function rain() {               // pluie dorée
        parts.push({ t: "c", x: rnd(0, W), y: -10, vx: rnd(-30, 30), vy: rnd(40, 160), life: rnd(3, 4.5), max: 4.5, size: rnd(5, 10), col: ["#ffd45a", "#ffb800", "#fff3b0"][(Math.random() * 3) | 0],
                     rot: rnd(0, 6.28), vr: rnd(-6, 6), g: 150, flip: rnd(0, 6.28) });
      }
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
          if (p.t === "r") {            // fusée : traînée d'étincelles, éclate à son sommet
            spark(p.x, p.y, Math.PI / 2 + rnd(-.4, .4), rnd(20, 70), .4, 2, "#ffd45a", 60);
            if (p.vy >= -30) { parts.splice(i, 1); explode(p.x, p.y, p.boom); continue; }
          }
          const a = Math.max(0, Math.min(1, p.life / (p.max * .5)));
          g.globalAlpha = a; g.strokeStyle = g.fillStyle = p.col;
          if (p.t === "s" || p.t === "r") { g.lineWidth = p.size; g.lineCap = "round"; g.beginPath(); g.moveTo(p.x, p.y); g.lineTo(p.x - p.vx * .035, p.y - p.vy * .035); g.stroke(); }
          else {
            p.vx *= 1 - .9 * dt; p.rot += p.vr * dt; p.flip += 7 * dt;
            g.save(); g.translate(p.x, p.y); g.rotate(p.rot); g.scale(1, Math.cos(p.flip)); g.globalCompositeOperation = "source-over"; g.fillRect(-p.size / 2, -p.size / 3, p.size, p.size * .66); g.restore();
          }
        }
        g.globalAlpha = 1; g.globalCompositeOperation = "source-over";
      }

      // ---- finale des raretés épique et légendaire : bannière, feux d'artifice, pluie dorée, fanfare ----
      function finale() {
        if (rarity !== "epic" && rarity !== "legendary") return;
        const big = rarity === "legendary";
        if (actx) snd.finale(actx.currentTime + 0.25);
        buzz(big ? [120, 60, 120, 60, 200, 80, 300] : [120, 60, 200]);
        later(() => root.classList.add("flash2"), 250);
        const n = big ? 14 : 4;
        for (let i = 0; i < n; i++) later(() => { if (!closed) firework(); }, 150 + i * (big ? 300 : 420));
        if (big) {
          let k = 0;
          const iv = setInterval(() => { if (closed || ++k > 80) return clearInterval(iv); rain(); rain(); }, 50);
          timers.push(iv);
          later(() => { if (!closed) shake = 12; }, 2250);   // coup de cymbale
        }
      }

      // ---- déroulé ----
      const timers = [];
      const later = (fn, ms) => timers.push(setTimeout(fn, ms));
      function go(next) {
        if (phase === next || closed) return;
        phase = next; root.dataset.phase = next;
        if (next === "charge") { root.classList.add("charge"); snd.charge(actx ? actx.currentTime : 0); buzz([40, 60, 40, 50, 40, 40, 40, 30, 40, 20, 40, 15, 60, 10, 80]); }
        if (next === "burst") {
          packEl.style.transform = ""; shake = 22; tBurst = performance.now();
          root.classList.add("burst"); burst();
          if (actx) { snd.stopCharge(); snd.burst(actx.currentTime); snd.reveal(actx.currentTime + 0.32); }
          buzz([220]);
          later(() => go("reveal"), 380);
        }
        if (next === "reveal") { root.classList.add("reveal"); later(() => go("done"), 1100); finale(); }
        if (next === "done") { root.classList.add("done"); root.querySelector(".pfx-done").focus(); root.querySelector(".pfx-skip").hidden = true; }
      }
      function close() {
        if (closed) return; closed = true; cancelAnimationFrame(raf); timers.forEach(clearTimeout); snd.stopCharge();
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
        if (actx) snd.reveal(actx.currentTime);
        root.classList.add("calm", "burst", "reveal", "done"); phase = "done"; root.querySelector(".pfx-skip").hidden = true;
        root.querySelector(".pfx-done").focus(); return;
      }
      if (actx) snd.drop(actx.currentTime);
      t0 = performance.now(); raf = requestAnimationFrame(frame);
      root.querySelector(".pfx-skip").focus();
      later(() => go("charge"), 800);
    });
  }

  return { open, svg, unlock, RARITY, _makeSound: makeSound };
})();
