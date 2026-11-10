"""Données de démonstration pour l'onglet Résultats (développement local, jamais utilisé en production).

Usage : DATA_DIR=data-dev python -m app.demo
"""
from . import db

SUBJECTS = [  # matière, élève, classe, min, max
    ("FRANCAIS", 14.2, 12.1, 6.5, 17.8), ("MATHEMATIQUES", 16.8, 11.4, 3.2, 19.5), ("HISTOIRE-GEOGRAPHIE", 13.1, 12.9, 7.0, 18.0),
    ("ANGLAIS LV1", 17.5, 13.8, 7.9, 19.1), ("ITALIEN LV2", 15.4, 13.2, 8.1, 18.9), ("PHYSIQUE-CHIMIE", 12.3, 11.7, 4.5, 17.2),
    ("SCIENCES VIE & TERRE", 15.9, 12.6, 6.0, 18.4), ("ENSEIGN.SCIENTIFIQUE", 14.0, 13.0, 8.3, 17.5), ("ED.PHYSIQUE & SPORT.", 11.8, 13.9, 8.0, 18.5),
    ("ARTS PLASTIQUES", 16.0, 14.1, 9.5, 19.0),
]


def seed() -> None:
    db.init()
    with db.conn() as c:
        c.execute("DELETE FROM averages"); c.execute("DELETE FROM periods")
        for pos, (name, shift) in enumerate((("Trimestre 1", -0.6), ("Trimestre 2", 0.5))):
            for s, st, cl, lo, hi in SUBJECTS:
                c.execute("INSERT INTO averages VALUES (?,?,?,?,?,?)", (f"{name}", s, round(min(20, st + shift), 2), cl, lo, hi))
            c.execute("INSERT INTO periods (name, position, start, end, overall, class_overall) VALUES (?,?,?,?,?,?)",
                      (name, pos, None, None, round(14.6 + shift, 2), 12.7))


if __name__ == "__main__":
    seed()
    print("Résultats de démonstration écrits dans", db.DB_PATH)
