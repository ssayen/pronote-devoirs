// Navigation entre les sections (Devoirs / Résultats / Emploi du temps).
// Chaque section enregistre { el, draw } dans VIEWS ; draw() n'est appelé qu'à la première ouverture.
// La section ouverte est mémorisée dans l'adresse (#resultats, #edt).
const VIEWS = {};
const HASH = { resultats: "#resultats", edt: "#edt" };

function initViews() {
  const names = ["devoirs", ...Object.keys(VIEWS)];
  const drawn = new Set();
  const panel = n => (n === "devoirs" ? $("#v-devoirs") : VIEWS[n].el);
  function show(v) {
    for (const n of names) panel(n).hidden = n !== v;
    for (const id of ["add", "late"]) $("#" + id).hidden = v !== "devoirs";
    for (const b of document.querySelectorAll(".views button")) b.setAttribute("aria-selected", b.dataset.view === v);
    if (v !== "devoirs" && !drawn.has(v)) { VIEWS[v].draw(); drawn.add(v); }
    if (v !== "devoirs" && VIEWS[v].show) VIEWS[v].show();
  }
  for (const b of document.querySelectorAll(".views button")) {
    b.onclick = () => { history.replaceState(null, "", HASH[b.dataset.view] || location.pathname); show(b.dataset.view); };
  }
  show(Object.keys(HASH).find(k => HASH[k] === location.hash) || "devoirs");
}
