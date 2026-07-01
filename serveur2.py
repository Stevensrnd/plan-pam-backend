import os
import re
import sqlite3
from contextlib import contextmanager

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# CORS : à restreindre au(x) domaine(s) réel(s) de votre app en production.
# CORS(app) ouvre l'API à absolument n'importe quel site web.
CORS(app, origins=os.environ.get("CORS_ORIGINS", "*").split(","))

DB_NAME = "plan_pam.db"


# ====================================================
# GESTION DE LA CONNEXION (context manager = fermeture garantie)
# ====================================================
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialiser_bdd():
    """Crée la table Plan Pam et injecte des comptes de test si vide."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS comptes (
                telephone TEXT PRIMARY KEY,
                solde REAL NOT NULL DEFAULT 0,
                pin_hash TEXT NOT NULL
            )
        ''')

        cursor.execute("SELECT COUNT(*) FROM comptes")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO comptes VALUES (?, ?, ?)",
                ("44445555", 5000.0, generate_password_hash("1234")),
            )
            cursor.execute(
                "INSERT INTO comptes VALUES (?, ?, ?)",
                ("33332222", 1500.0, generate_password_hash("5678")),
            )
            print("Base de données PLAN PAM initialisée avec succès !")


# ====================================================
# VALIDATION DES ENTRÉES
# ====================================================
def telephone_valide(telephone):
    return isinstance(telephone, str) and re.fullmatch(r"\d{8,15}", telephone) is not None


def pin_valide(pin):
    return isinstance(pin, str) and re.fullmatch(r"\d{4,6}", pin) is not None


def erreur(message, code=400):
    return jsonify({"erreur": message}), code


# ====================================================
# ROUTE 1 : CONSULTER LE SOLDE (protégée par PIN)
# ====================================================
@app.route('/solde/<telephone>', methods=['POST'])
def charger_solde(telephone):
    """
    Le solde est une donnée sensible : on exige désormais le PIN
    (envoyé dans le corps JSON) plutôt qu'un simple GET public.
    """
    data = request.get_json(silent=True) or {}
    pin = data.get('pin')

    if not telephone_valide(telephone):
        return erreur("Numéro de téléphone invalide")
    if not pin:
        return erreur("PIN requis")

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT solde, pin_hash FROM comptes WHERE telephone = ?", (telephone,)
            )
            compte = cursor.fetchone()

        if compte is None:
            # Même message que "PIN invalide" pour ne pas révéler
            # si un numéro existe ou non.
            return erreur("Identifiants invalides", 401)

        solde, pin_hash = compte
        if not check_password_hash(pin_hash, pin):
            return erreur("Identifiants invalides", 401)

        return jsonify({"solde": solde}), 200
    except Exception:
        app.logger.exception("Erreur lors de la consultation du solde")
        return erreur("Erreur interne du serveur", 500)


# ====================================================
# ROUTE 2 : CRÉER UN COMPTE
# ====================================================
@app.route('/creer_compte', methods=['POST'])
def creer_compte():
    data = request.get_json(silent=True) or {}
    telephone = data.get('numero')
    pin = data.get('pin')

    if not telephone_valide(telephone):
        return erreur("Numéro de téléphone invalide (8 à 15 chiffres attendus)")
    if not pin_valide(pin):
        return erreur("PIN invalide (4 à 6 chiffres attendus)")

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO comptes VALUES (?, 0.0, ?)",
                (telephone, generate_password_hash(pin)),
            )
        return jsonify({"status": "success", "message": "Compte créé avec succès !"}), 201
    except sqlite3.IntegrityError:
        return erreur("Ce numéro de téléphone est déjà enregistré")
    except Exception:
        app.logger.exception("Erreur lors de la création du compte")
        return erreur("Erreur interne du serveur", 500)


# ====================================================
# ROUTE 3 : AJOUTER DU SOLDE (RECHARGEMENT)
# ====================================================
@app.route('/ajouter_solde', methods=['POST'])
def ajouter_solde():
    data = request.get_json(silent=True) or {}
    telephone = data.get('numero')
    montant_brut = data.get('montant')

    if not telephone_valide(telephone):
        return erreur("Numéro de téléphone invalide")

    try:
        montant = float(montant_brut)
    except (TypeError, ValueError):
        return erreur("Montant invalide")

    if montant <= 0:
        return erreur("Le montant doit être supérieur à 0")

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            # Mise à jour atomique : évite la condition de course
            # (deux requêtes simultanées qui liraient le même solde de départ).
            cursor.execute(
                "UPDATE comptes SET solde = solde + ? WHERE telephone = ?",
                (montant, telephone),
            )
            if cursor.rowcount == 0:
                return erreur("Compte introuvable", 404)

            cursor.execute("SELECT solde FROM comptes WHERE telephone = ?", (telephone,))
            nouveau_solde = cursor.fetchone()[0]

        return jsonify({
            "statut": "Succès",
            "message": f"{montant} HTG ajoutés avec succès !",
            "nouveau_solde": nouveau_solde,
        }), 200

    except Exception:
        app.logger.exception("Erreur lors du rechargement")
        return erreur("Erreur interne du serveur", 500)


# ====================================================
# BLOC DE LANCEMENT APPLICATION
# ====================================================
if __name__ == '__main__':
    initialiser_bdd()
    port = int(os.environ.get("PORT", 5000))
    # En production, ne pas utiliser le serveur de développement Flask :
    # utiliser un serveur WSGI comme gunicorn (ex: gunicorn -w 4 -b 0.0.0.0:PORT app:app)
    app.run(host='0.0.0.0', port=port)
                          
