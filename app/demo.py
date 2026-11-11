"""Données de démonstration pour les onglets Résultats et Emploi du temps (développement local, jamais en production).
Ne remplit que ce qui manque : les vraies données ne sont jamais écrasées.

Usage : DATA_DIR=data-dev python -m app.demo
"""
from datetime import date, timedelta

from . import db

SUBJECTS = [  # matière, élève, classe, min, max
    ("FRANCAIS", 14.2, 12.1, 6.5, 17.8), ("MATHEMATIQUES", 16.8, 11.4, 3.2, 19.5), ("HISTOIRE-GEOGRAPHIE", 13.1, 12.9, 7.0, 18.0),
    ("ANGLAIS LV1", 17.5, 13.8, 7.9, 19.1), ("ITALIEN LV2", 15.4, 13.2, 8.1, 18.9), ("PHYSIQUE-CHIMIE", 12.3, 11.7, 4.5, 17.2),
    ("SCIENCES VIE & TERRE", 15.9, 12.6, 6.0, 18.4), ("ENSEIGN.SCIENTIFIQUE", 14.0, 13.0, 8.3, 17.5), ("ED.PHYSIQUE & SPORT.", 11.8, 13.9, 8.0, 18.5),
    ("ARTS PLASTIQUES", 16.0, 14.1, 9.5, 19.0),
]


# (jour 0=lundi, début, fin, matière, salle, professeur)
WEEK = [
    (0, "08:00", "09:00", "MATHEMATIQUES", "204", "M. BERNARD"), (0, "09:00", "10:00", "FRANCAIS", "112", "Mme LEROY"),
    (0, "10:15", "11:15", "ANGLAIS LV1", "301", "Mme SMITH"), (0, "11:15", "12:15", "HISTOIRE-GEOGRAPHIE", "108", "M. MOREAU"),
    (0, "14:00", "16:00", "ED.PHYSIQUE & SPORT.", "Gymnase", "M. PETIT"),
    (1, "08:00", "09:00", "PHYSIQUE-CHIMIE", "Labo 2", "Mme ROUX"), (1, "09:00", "10:00", "SCIENCES VIE & TERRE", "Labo 1", "M. FABRE"),
    (1, "10:15", "11:15", "MATHEMATIQUES", "204", "M. BERNARD"), (1, "13:00", "14:00", "ITALIEN LV2", "305", "Mme ROSSI"),
    (1, "14:00", "15:00", "ENSEIGN.SCIENTIFIQUE", "Labo 1", "M. FABRE"), (1, "15:00", "16:00", "ARTS PLASTIQUES", "Art 1", "Mme GIRARD"),
    (2, "08:00", "09:00", "FRANCAIS", "112", "Mme LEROY"), (2, "09:00", "10:00", "ANGLAIS LV1", "301", "Mme SMITH"),
    (2, "10:15", "11:15", "HISTOIRE-GEOGRAPHIE", "108", "M. MOREAU"),
    (3, "08:00", "09:00", "MATHEMATIQUES", "204", "M. BERNARD"), (3, "09:00", "10:00", "PHYSIQUE-CHIMIE", "Labo 2", "Mme ROUX"),
    (3, "10:15", "11:15", "ITALIEN LV2", "305", "Mme ROSSI"), (3, "13:00", "14:00", "FRANCAIS", "112", "Mme LEROY"),
    (3, "14:00", "15:00", "SCIENCES VIE & TERRE", "Labo 1", "M. FABRE"), (3, "14:00", "15:00", "ANGLAIS LV1", "301", "Mme SMITH"),
    (4, "08:00", "09:00", "ENSEIGN.SCIENTIFIQUE", "Labo 1", "M. FABRE"), (4, "09:00", "10:00", "MATHEMATIQUES", "204", "M. BERNARD"),
    (4, "10:15", "11:15", "ARTS PLASTIQUES", "Art 1", "Mme GIRARD"), (4, "11:15", "12:15", "HISTOIRE-GEOGRAPHIE", "108", "M. MOREAU"),
]


def seed_lessons() -> None:
    mon = date.today() - timedelta(days=date.today().weekday())
    n = 0
    with db.conn() as c:
        for w in range(-1, 4):
            for day, a, b, subj, room, teacher in WEEK:
                d = (mon + timedelta(days=7 * w + day)).isoformat()
                canceled = (w == 0 and (day, a) == (1, "15:00")) or (w == 1 and (day, a) == (3, "13:00"))
                status = "Prof. absent" if canceled else ("Salle modifiée" if (w == 0 and (day, a) == (2, "10:15")) else None)
                test = int(w == 0 and (day, a) == (3, "09:00"))
                c.execute("INSERT OR REPLACE INTO lessons (id, start, end, subject, teacher, room, status, canceled, test) VALUES (?,?,?,?,?,?,?,?,?)",
                          (f"demo{n}", f"{d}T{a}", f"{d}T{b}", subj, teacher, room, status, int(canceled), test))
                n += 1


def seed_results() -> None:
    with db.conn() as c:
        c.execute("DELETE FROM averages"); c.execute("DELETE FROM periods")
        for pos, (name, shift) in enumerate((("Trimestre 1", -0.6), ("Trimestre 2", 0.5))):
            for s, st, cl, lo, hi in SUBJECTS:
                c.execute("INSERT INTO averages VALUES (?,?,?,?,?,?)", (f"{name}", s, round(min(20, st + shift), 2), cl, lo, hi))
            c.execute("INSERT INTO periods (name, position, start, end, overall, class_overall) VALUES (?,?,?,?,?,?)",
                      (name, pos, None, None, round(14.6 + shift, 2), 12.7))


def seed() -> None:
    db.init()
    with db.conn() as c:
        has_results = c.execute("SELECT 1 FROM averages LIMIT 1").fetchone()
        has_lessons = c.execute("SELECT 1 FROM lessons LIMIT 1").fetchone()
    if not has_results:
        seed_results()
    if not has_lessons:
        seed_lessons()


if __name__ == "__main__":
    seed()
    print("Données de démonstration ajoutées là où il en manquait dans", db.db_path())
