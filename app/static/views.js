// Navigation entre les sections (Devoirs / Résultats / Emploi du temps / Personnalisation).
// Chaque section enregistre { el, draw, show? } dans VIEWS ; draw() n'est appelé qu'à la première ouverture.
// La section ouverte est dans l'adresse (#resultats, #edt, #perso) : le bouton « retour » du navigateur fonctionne.
const VIEWS = {};
const HASH = { resultats: "#resultats", edt: "#edt", perso: "#perso", objectifs: "#objectifs" };
const NAV = { current: null, previous: null };   // section affichée et section précédente
let showView = () => {};

const viewFromHash = () => Object.keys(HASH).find(k => HASH[k] === location.hash && VIEWS[k]) || "devoirs";
function go(v) {                      // change de section en ajoutant une entrée à l'historique
  if (v === NAV.current) return;
  history.pushState(null, "", HASH[v] || location.pathname + location.search);
  showView(v);
}
function goBack() { go(NAV.previous && NAV.previous !== "perso" ? NAV.previous : "devoirs"); }

function initViews() {
  const names = ["devoirs", ...Object.keys(VIEWS)];
  const drawn = new Set();
  const panel = n => (n === "devoirs" ? $("#v-devoirs") : VIEWS[n].el);
  showView = v => {
    if (v !== NAV.current) { NAV.previous = NAV.current; NAV.current = v; }
    for (const n of names) panel(n).hidden = n !== v;
    for (const id of ["add", "late"]) $("#" + id).hidden = v !== "devoirs";
    for (const b of document.querySelectorAll(".views button")) b.setAttribute("aria-selected", b.dataset.view === v);
    const av = $("#avatar"); if (av) av.toggleAttribute("aria-current", v === "perso");
    if (v !== "devoirs" && !drawn.has(v)) { VIEWS[v].draw(); drawn.add(v); }
    if (v !== "devoirs" && VIEWS[v].show) VIEWS[v].show();
    window.scrollTo(0, 0);
  };
  for (const b of document.querySelectorAll(".views button")) b.onclick = () => go(b.dataset.view);
  addEventListener("popstate", () => showView(viewFromHash()));
  showView(viewFromHash());
}
