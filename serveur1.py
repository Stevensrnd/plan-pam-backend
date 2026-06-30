import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3

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
            solde REAL NOT NULL,
            pin TEXT NOT NULL
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM comptes")
    if cursor.fetchone()[0] == 0:
        # Comptes de test initiaux
        cursor.execute("INSERT INTO comptes VALUES ('44445555', 5000.0, '1234')")
        cursor.execute("INSERT INTO comptes VALUES ('33332222', 1500.0, '5678')")
        conn.commit()
        print("Base de données PLAN PAM initialisée avec succès !")
        
    conn.close()
    
            "statut": "Succès",
            "message": f"Le rechargement de {montant} HTG a réussi.",@app.route('/ajouter_solde', methods=['POST'])
def ajouter_solde():
    try:
        data = request.get_json()
        telephone = data.get('numero')
        montant = float(data.get('montant', 0))
        
        if montant <= 0:
            return jsonify({"erreur": "Le montant doit être supérieur à 0"}), 400

        # Connexion sécurisée en utilisant la variable DB_NAME globale
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # 1. Vérifier si le compte existe
        cursor.execute("SELECT solde FROM comptes WHERE telephone = ?", (telephone,))
        compte = cursor.fetchone()

        if compte is None:
            conn.close()
            return jsonify({"erreur": "Compte introuvable"}), 404

        solde_actuel = compte[0]
        nouveau_solde = solde_actuel + montant

        # 2. Mettre à jour le solde dans la table comptes
        cursor.execute("UPDATE comptes SET solde = ? WHERE telephone = ?", (nouveau_solde, telephone))
        conn.commit()
        conn.close()

        return jsonify({
            "statut": "Succès",
            "message": f"{montant} HTG ajoutés avec succès ! Enregistrement mis à jour."
        }), 200

    except Exception as e:
        return jsonify({"erreur": f"Erreur interne du serveur : {str(e)}"}), 500

            "nouveau_solde": nouveau_solde
        }), 200

    except Exception as e:
        return jsonify({"erreur": f"Erreur lors du rechargement : {str(e)}"}), 500


@app.route('/solde/<telephone>', methods=['GET'])
def obtenir_solde(telephone):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT solde FROM comptes WHERE telephone = ?", (telephone,))
    resultat = cursor.fetchone()
    conn.close()
    
    if resultat:
        return jsonify({"telephone": telephone, "solde": resultat[0]}), 200
    return jsonify({"erreur": "Compte Plan Pam introuvable"}), 404

@app.route('/inscription', methods=['POST'])
def inscrire_utilisateur():
    donnees = request.get_json()
    telephone = donnees.get("telephone")
    pin = donnees.get("pin")
    
    if not telephone or not pin or len(pin) < 4:
        return jsonify({"erreur": "Données invalides. Le PIN doit faire au moins 4 chiffres."}), 400
        
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        # Vérifier si le numéro existe déjà
        cursor.execute("SELECT telephone FROM comptes WHERE telephone = ?", (telephone,))
        if cursor.fetchone():
            return jsonify({"erreur": "Ce numéro possède déjà un compte Plan Pam."}), 400
            
        # Création du compte avec un bonus de bienvenue de 0 HTG !
        solde_initial = 0
        cursor.execute("INSERT INTO comptes VALUES (?, ?, ?)", (telephone, solde_initial, pin))
        conn.commit()
        
        return jsonify({
            "statut": "Succès",
            "message": f"Bienvenue sur Plan Pam ! Votre compte a été créé avec un bonus de {solde_initial} HTG.",
            "telephone": telephone,
            "solde": solde_initial
        }), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"erreur": "Erreur lors de l'inscription."}), 500
    finally:
        conn.close()

@app.route('/transfert', methods=['POST'])
def transferer_argent():
    donnees = request.get_json()
    expediteur = donnees.get("expediteur")
    destinataire = donnees.get("destinataire")
    montant = float(donnees.get("montant", 0))
    pin = donnees.get("pin")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT solde, pin FROM comptes WHERE telephone = ?", (expediteur,))
        data_exp = cursor.fetchone()
        
        cursor.execute("SELECT solde FROM comptes WHERE telephone = ?", (destinataire,))
        data_dest = cursor.fetchone()
        
        if not data_exp or not data_dest:
            return jsonify({"erreur": "Numéro expéditeur ou destinataire invalide"}), 400
            
        solde_exp, pin_exp = data_exp
        
        if pin_exp != pin:
            return jsonify({"erreur": "Code PIN Plan Pam incorrect"}), 401
            
        if solde_exp < montant:
            return jsonify({"erreur": "Solde insuffisant sur votre Plan Pam"}), 400
            
        cursor.execute("UPDATE comptes SET solde = ? WHERE telephone = ?", (solde_exp - montant, expediteur))
        cursor.execute("UPDATE comptes SET solde = ? WHERE telephone = ?", (data_dest[0] + montant, destinataire))
        
        conn.commit()
        
        return jsonify({
            "statut": "Succès",
            "message": f"Transfert de {montant} HTG réussi vers {destinataire}.",
            "nouveau_solde": solde_exp - montant
        }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"erreur": "Transaction annulée suite à une erreur"}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    initialiser_bdd()
    port = int(os.environ.get("PORT",5000))
    app.run(host='0.0.0.0', port=port)
