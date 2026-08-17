# Guide Rapide - Lancement et Test de Rafiki

Ce guide rassemble les commandes essentielles pour démarrer et tester l'ensemble du système Rafiki (PC, Raspberry Pi, Arduino et application mobile).

> [!IMPORTANT]
> **Réseau :** Le PC et la Raspberry Pi doivent être connectés au **même réseau local** (Wi-Fi ou Ethernet).
> Grâce au système d'auto-découverte UDP (Zero-conf), la Raspberry Pi détecte automatiquement l'IP dynamique du PC.

---

## 1. Cerveau / Serveur (PC)

### A. Démarrer LM Studio
1. Ouvrez LM Studio.
2. Chargez votre modèle LLM vision/text (ex: `bonsai-27b`).
3. Démarrez le serveur local compatible OpenAI sur le port **1234**.

### B. Activer et Lancer l'Orchestrateur
Ouvrez un terminal PowerShell à la racine du projet :

```powershell
cd C:\Users\ODC\Desktop\Didier\Rafiki\rafiki_orchestrateur
..\.venv\Scripts\Activate.ps1

# Configuration de l'environnement
$env:RAFIKI_MODE="hardware"
$env:RAFIKI_APP_HOST="0.0.0.0"
$env:RAFIKI_APP_PORT="7860"
$env:LMSTUDIO_BASE_URL="http://127.0.0.1:1234/v1"
$env:LMSTUDIO_API_KEY="lm_studio"
$env:LMSTUDIO_MODEL="bonsai-27b"

# Démarrage du serveur
python rafiki_app.py
```
*(Au démarrage, le serveur lance également le répondeur de découverte UDP pour annoncer automatiquement son IP sur le réseau local).*

---

## 2. Corps, Caméra et Moteurs (Raspberry Pi & Arduino)

### A. Arduino Mega (Programmation du corps)
Depuis le PC (si Arduino connecté en USB), compilez et téléversez sur le Mega :
```powershell
arduino-cli compile --fqbn arduino:avr:mega .\raspberry\arduino\rafiki_mega_expressions_mouvements
arduino-cli upload -p COM5 --fqbn arduino:avr:mega .\raspberry\arduino\rafiki_mega_expressions_mouvements
```
*(Remplacez `COM5` par le port réel de votre carte).*

### B. Démarrer le Client Corps (Mouvements) sur Raspberry Pi
Connectez-vous en SSH à la Raspberry Pi et lancez le client. Grâce à l'auto-découverte UDP, vous n'avez pas besoin de spécifier l'IP du PC :
```bash
cd ~/Rafiki
.venv/bin/python -m raspberry.app.body_pull_client --body-port /dev/ttyACM0 --session-id default_session
```
*(Si vous souhaitez spécifier manuellement l'URL, passez l'option `--brain-url http://<IP_DU_PC>:7860`).*

### C. Démarrer le Serveur de Caméra (Vision) sur Raspberry Pi
Dans un autre terminal SSH sur la Raspberry Pi, lancez le service de capture et d'analyse vidéo :
```bash
cd ~/Rafiki
.venv/bin/python -m raspberry.app.vision_server --host 0.0.0.0 --port 8000
```
*(Le serveur de vision détectera également l'IP du PC et s'auto-enregistrera. L'IP de la caméra sera mémorisée par le serveur PC).*

---

## 3. Application Mobile (Flutter - Optionnel)

Pour compiler et lancer l'application de contrôle sur émulateur ou téléphone physique :
```powershell
cd C:\Users\ODC\Desktop\Didier\Rafiki\mobile\app\mobile
flutter run
```
* **Émulateur Android (sur le même PC) :** Connectez l'application à `10.0.2.2:7860` (ou `127.0.0.1:7860` pour l'émulateur iOS/Windows).
* **Téléphone Physique (sur le même Wi-Fi) :** Saisissez l'adresse IP affichée au démarrage du serveur PC (ex: `192.168.1.50:7860`).

---

## 4. Outils de Diagnostic et Tests Rapides (PC)

### Vérifier l'état de la caméra et du corps
Depuis un PowerShell sur votre PC :

```powershell
# Santé générale et connexion des modules (Body / Vision)
Invoke-RestMethod http://127.0.0.1:7860/api/health

# État détaillé et URL actuelle de la caméra Raspberry
Invoke-RestMethod http://127.0.0.1:7860/api/vision/status | ConvertTo-Json

# Déclencher une capture d'image test pour valider le flux vidéo
Invoke-RestMethod http://127.0.0.1:7860/api/vision/capture
```

### Exécuter les tests unitaires / d'intégration
```powershell
# Tests du contrat API serveur
cd C:\Users\ODC\Desktop\Didier\Rafiki\rafiki_orchestrateur
..\.venv\Scripts\python.exe test_v1_http_pull_contract.py
```
