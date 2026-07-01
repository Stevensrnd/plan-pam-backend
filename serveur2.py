import os
import re
import sqlite3
import hmac
import functools
from contextlib import contextmanager

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# CORS : à restreindre au(x) domaine(s) réel(s) de votre app en production.
# CORS(app) ouvre l'API à absolument n'importe quel site web.
CORS(app, origins=os.environ.get("CORS_ORIGINS", "*").split(","))

# Clé secrète réservée aux agents autorisés à recharger des comptes.
# À définir sur Render dans les variables d'environnement (jamais dans le code).
AGENT_API_KEY = os.environ.get("AGENT_API_KEY")

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


def cle_agent_requise(f):
    """Protège une route : exige un en-tête X-Api-Key correspondant à AGENT_API_KEY."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not AGENT_API_KEY:
            app.logger.error("AGENT_API_KEY n'est pas configurée sur le serveur")
            return erreur("Service de rechargement indisponible pour le moment", 503)

        cle_fournie = request.headers.get("X-Api-Key", "")
        if not hmac.compare_digest(cle_fournie, AGENT_API_KEY):
            return erreur("Accès refusé : clé agent invalide", 401)

        return f(*args, **kwargs)
    return wrapper


# ====================================================
# ROUTE 0 : HEALTHCHECK (vérifier que l'API est en ligne)
# ====================================================
@app.route('/', methods=['GET'])
def accueil():
    return jsonify({"status": "API Plan Pam en ligne"}), 200


# ====================================================
# ROUTE 1 : CONSULTER LE SOLDE
# ====================================================
# ATTENTION SÉCURITÉ : cette route renvoie le solde sur simple
# connaissance du numéro de téléphone, sans PIN. N'importe qui connaissant
# un numéro peut voir son solde. C'est le comportement attendu par le
# frontend actuel, mais idéalement il faudrait exiger une authentification
# (PIN ou session) avant de renvoyer une donnée financière.
@app.route('/solde/<telephone>', methods=['GET'])
def charger_solde(telephone):
    if not telephone_valide(telephone):
        return erreur("Numéro de téléphone invalide")

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT solde FROM comptes WHERE telephone = ?", (telephone,)
            )
            compte = cursor.fetchone()

        if compte is None:
            return erreur("Compte introuvable", 404)

        return jsonify({"solde": compte[0]}), 200
    except Exception:
        app.logger.exception("Erreur lors de la consultation du solde")
        return erreur("Erreur interne du serveur", 500)


# ====================================================
# ROUTE 2 : CRÉER UN COMPTE (INSCRIPTION)
# ====================================================
@app.route('/inscription', methods=['POST'])
def creer_compte():
    data = request.get_json(silent=True) or {}
    telephone = data.get('telephone')
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
        return jsonify({
            "status": "success",
            "message": "Compte créé avec succès !",
            "solde": 0.0,
        }), 201
    except sqlite3.IntegrityError:
        return erreur("Ce numéro de téléphone est déjà enregistré")
    except Exception:
        app.logger.exception("Erreur lors de la création du compte")
        return erreur("Erreur interne du serveur", 500)


# ====================================================
# ROUTE 3 : AJOUTER DU SOLDE (RECHARGEMENT)
# ====================================================
@app.route('/ajouter_solde', methods=['POST'])
@cle_agent_requise
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
# ROUTE 4 : VIREMENT ENTRE COMPTES PLAN PAM
# ====================================================
class DestinataireIntrouvable(Exception):
    pass


@app.route('/transfert', methods=['POST'])
def effectuer_transfert():
    data = request.get_json(silent=True) or {}
    expediteur = data.get('expediteur')
    destinataire = data.get('destinataire')
    montant_brut = data.get('montant')
    pin = data.get('pin')

    if not telephone_valide(expediteur) or not telephone_valide(destinataire):
        return erreur("Numéro de téléphone invalide")
    if expediteur == destinataire:
        return erreur("Impossible de faire un virement vers votre propre numéro")
    if not pin:
        return erreur("PIN requis")

    try:
        montant = float(montant_brut)
    except (TypeError, ValueError):
        return erreur("Montant invalide")

    if montant <= 0:
        return erreur("Le montant doit être supérieur à 0")

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT solde, pin_hash FROM comptes WHERE telephone = ?", (expediteur,)
            )
            compte_exp = cursor.fetchone()
            if compte_exp is None:
                return erreur("Compte expéditeur introuvable", 404)

            solde_exp, pin_hash = compte_exp
            if not check_password_hash(pin_hash, pin):
                return erreur("PIN incorrect", 401)

            if solde_exp < montant:
                return erreur("Solde insuffisant")

            # Débit atomique : la condition solde >= montant dans le WHERE
            # empêche un double débit en cas de requêtes simultanées.
            cursor.execute(
                "UPDATE comptes SET solde = solde - ? WHERE telephone = ? AND solde >= ?",
                (montant, expediteur, montant),
            )
            if cursor.rowcount == 0:
                return erreur("Solde insuffisant")

            cursor.execute(
                "UPDATE comptes SET solde = solde + ? WHERE telephone = ?",
                (montant, destinataire),
            )
            if cursor.rowcount == 0:
                # Déclenche le rollback du débit précédent (même connexion/transaction).
                raise DestinataireIntrouvable()

            cursor.execute("SELECT solde FROM comptes WHERE telephone = ?", (expediteur,))
            nouveau_solde = cursor.fetchone()[0]

        return jsonify({
            "statut": "Succès",
            "message": f"Virement de {montant} HTG effectué avec succès !",
            "nouveau_solde": nouveau_solde,
        }), 200

    except DestinataireIntrouvable:
        return erreur("Compte du bénéficiaire introuvable", 404)
    except Exception:
        app.logger.exception("Erreur lors du virement")
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
