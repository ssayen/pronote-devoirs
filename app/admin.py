"""Compte administrateur de test : se comporte comme un élève, sans QR code Pronote, avec des données de démonstration
et des outils pour tester la gamification (ajout de points).

Usage : python -m app.admin create <identifiant>        (le mot de passe est demandé)
Docker : docker compose exec app python -m app.admin create <identifiant>
"""
import getpass
import sys

from . import accounts, db, demo


def create_admin(login: str, password: str) -> int:
    login = accounts.normalize(login)
    if not accounts.LOGIN_RE.fullmatch(login):
        raise ValueError("Identifiant : 3 à 32 caractères (lettres, chiffres, . _ -).")
    if len(password) < 8:
        raise ValueError("Mot de passe : 8 caractères minimum.")
    accounts.init()
    uid = accounts.create(login, password, role="admin")
    if uid is None:
        raise ValueError("Cet identifiant est déjà pris.")
    with db.as_user(uid):
        db.init()
        demo.seed()   # moyennes, emploi du temps, notes : de quoi voir missions, points et paquets
    return uid


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "create":
        sys.exit(__doc__)
    pw = getpass.getpass("Mot de passe : ")
    if pw != getpass.getpass("Confirmer : "):
        sys.exit("Les mots de passe diffèrent.")
    try:
        create_admin(sys.argv[2], pw)
    except ValueError as e:
        sys.exit(f"Échec : {e}")
    print("Compte administrateur créé.")


if __name__ == "__main__":
    main()
