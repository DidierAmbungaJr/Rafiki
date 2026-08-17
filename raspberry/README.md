# Rafiki Raspberry V1

La Raspberry reste un exécuteur matériel simple. Cette intégration reprend le
protocole HTTP du dépôt Raspberry Pi de référence : le PC conserve les
commandes, la Pi les récupère (« pull ») puis les transmet à l'Arduino Mega.

Elle fait :

- contrôle série de l'Arduino Mega ;
- écran TFT et servomoteurs via `arduino/rafiki_mega_expressions_mouvements.ino` ;
- HTTP pull vers le serveur PC ;
- enregistrement et envoi d'images de la caméra, si le microservice vision est installé.

Elle ne fait pas :

- LLM local ;
- STT ;
- TTS ;
- décision pédagogique.

## Architecture réseau

```text
PC (serveur Rafiki :7860)                 Raspberry Pi
GET  /api/body/next       <-------------  body_pull_client.py
POST /api/body/status     <-------------  heartbeat + résultat Arduino
POST /api/vision/register <-------------  service caméra (optionnel)
POST /api/vision/upload   <-------------  images Base64 (optionnel)
GET  /api/vision/capture  ------------->  /capture/json de la caméra (optionnel)
```

Le PC doit écouter sur le réseau local (`RAFIKI_APP_HOST=0.0.0.0`) et la Pi doit
utiliser l'adresse IPv4 Wi-Fi/Ethernet du PC. Depuis la Pi, `127.0.0.1` désigne
la Pi elle-même, jamais le PC.

Les endpoints de diagnostic sont :

- `GET /health` ou `GET /api/health` : santé du serveur ;
- `GET /api/bridge/status` : état de la Pi, de la file et de la caméra ;
- `GET /api/body/status` : dernier heartbeat du corps.

## Installation manuelle

Sur la Raspberry :

```bash
cd ~/Rafiki
python3 -m venv .venv
.venv/bin/pip install -r raspberry/requirements.txt
ls /dev/ttyACM* /dev/ttyUSB*
```

Lance ensuite le client. Grâce au système d'auto-découverte UDP, vous pouvez omettre l'argument `--brain-url` (il cherchera le PC sur le réseau local) :

```bash
.venv/bin/python -m raspberry.app.body_pull_client \
  --body-port /dev/ttyACM0 \
  --session-id default_session
```

*(Si vous préférez spécifier manuellement l'URL, passez l'option `--brain-url http://IP_DU_PC:7860`).*

Avant de lancer le client, vous pouvez vérifier l'accessibilité réseau depuis la Pi :

```bash
curl http://IP_DU_PC:7860/health
```

Le client appelle `GET /api/body/next`, envoie `POST /api/body/status` toutes
les cinq secondes et redémarre ses requêtes après une indisponibilité réseau.
Le PC ne le considère connecté que si ce heartbeat est récent.

Les commandes supportées côté Arduino sont :

- `set_expression` → `E0..E9` + `SHOW_EYES` ;
- `motor_gesture` → `B0..B9` ou `BSTOP` ;
- `screen_text` → `TEXT:<message>`.

## Démarrage automatique avec systemd

Les modèles sont fournis dans `raspberry/systemd/`. Ils supposent que le dépôt
est dans `~/Rafiki`; adapte le fichier de service si ce n'est pas le cas.

```bash
mkdir -p ~/.config/systemd/user ~/.config/rafiki
cp raspberry/systemd/rafiki-body.service ~/.config/systemd/user/
cp raspberry/systemd/rafiki.env.example ~/.config/rafiki/rafiki.env
nano ~/.config/rafiki/rafiki.env
systemctl --user daemon-reload
systemctl --user enable --now rafiki-body.service
systemctl --user status rafiki-body.service
```

Dans `~/.config/rafiki/rafiki.env`, renseigne `RAFIKI_BRAIN_URL` avec l'IPv4 du
PC. Pour que le service utilisateur continue après un redémarrage sans session
graphique ouverte, exécute une fois :

```bash
sudo loginctl enable-linger "$USER"
```

Pour consulter les journaux :

```bash
journalctl --user -u rafiki-body.service -f
```

## Sécurité réseau

Ce pont est prévu pour un Wi-Fi/LAN de confiance. N'expose pas le port 7860 sur
Internet ; limite le pare-feu Windows au profil privé et aux appareils du réseau
Rafiki.
