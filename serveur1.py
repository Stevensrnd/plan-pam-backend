import os
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_NAME = "plan_pam.db"

def initialiser_bdd():
    """Crée la table Plan Pam et injecte des comptes de test si vide."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comptes (
            telephone TEXT PRIMARY KEY,
            solde REAL,
            pin TEXT
        )
    ''')
    
    # Vérification et injection des comptes de test initiaux
    cursor.execute("SELECT COUNT(*) FROM comptes")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO comptes VALUES ('44445555', 5000.0, '1234')")
        cursor.execute("INSERT INTO comptes VALUES ('33332222', 1500.0, '5678')")
        conn.commit()
        print("Base de données PLAN PAM initialisée avec succès !")
    conn.close()

# ====================================================
# ROUTE 1 : CONSULTER LE SOLDE
# ====================================================
@app.route('/solde/<telephone>', methods=['GET'])
def charger_solde(telephone):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT solde FROM comptes WHERE telephone = ?", (telephone,))
        compte = cursor.fetchone()
        conn.close()
        
        if compte:
            return jsonify({"solde": compte[0]}), 200
        else:
            return jsonify({"erreur": "Compte introuvable"}), 404
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500

# ====================================================
# ROUTE 2 : CRÉER UN COMPTE (SANS BONUS)
# ====================================================
@app.route('/creer_compte', methods=['POST'])
def creer_compte():
    try:
        data = request.get_json()
        telephone = data.get('numero')
        pin = data.get('pin')
        
        if not telephone or not pin:
            return jsonify({"erreur": "Champs manquants"}), 400
            
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Le solde initial est configuré à 0 (sans bonus)
        cursor.execute("INSERT INTO comptes VALUES (?, 0.0, ?)", (telephone, pin))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Compte créé avec succès sans bonus !"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"erreur": "Ce numéro de téléphone est déjà enregistré"}), 400
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500

# ====================================================
# ROUTE 3 : AJOUTER DU SOLDE (RECHARGEMENT)
# ====================================================
@app.route('/ajouter_solde', methods=['POST'])
def ajouter_solde():
    try:
        data = request.get_json()
        telephone = data.get('numero')
        montant = float(data.get('montant', 0))
        
        if montant <= 0:
            return jsonify({"erreur": "Le montant doit être supérieur à 0"}), 400

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Vérifier si le compte ciblé existe
        cursor.execute("SELECT solde FROM comptes WHERE telephone = ?", (telephone,))
        compte = cursor.fetchone()

        if compte is None:
            conn.close()
            return jsonify({"erreur": "Compte introuvable"}), 404

        solde_actuel = compte[0]
        nouveau_solde = solde_actuel + montant

        # Appliquer le rechargement
        cursor.execute("UPDATE comptes SET solde = ? WHERE telephone = ?", (nouveau_solde, telephone))
        conn.commit()
        conn.close()

        return jsonify({
            "statut": "Succès",
            "message": f"{montant} HTG ajoutés avec succès !"
        }), 200

    except Exception as e:
        return jsonify({"erreur": f"Erreur interne : {str(e)}"}), 500

# ====================================================
# BLOC DE LANCEMENT (TOUT EN BAS)
# ====================================================
if __name__ == '__main__':
    initialiser_bdd()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
