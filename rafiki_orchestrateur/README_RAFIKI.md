# Rafiki — Agent LLM central + orchestration MCP

Ce dossier contient un prototype complet pour tester l'orchestration Rafiki sur PC avant le passage sur Raspberry Pi.

## 1. Rôle de chaque fichier

| Fichier | Rôle |
|---|---|
| `mcp_rafiki_systems_server.py` | Serveur MCP qui expose les systèmes Rafiki sous forme d'outils : mémoire, parole, vision, expressions, gestes, journal parent, activité éducative, fallback cloud. |
| `rafiki_agent.py` | Agent central LangGraph + LM Studio. Il charge les outils MCP et décide lesquels appeler selon la demande. |
| `test_rafiki_tools.py` | Test du serveur MCP sans LLM. À lancer en premier pour vérifier que les outils marchent. |
| `test_rafiki_agent_prompts.txt` | Liste de prompts à utiliser pour tester l'agent. |
| `requirements.txt` | Dépendances Python. |
| `.env.example` | Configuration à copier en `.env`. |

## 2. Installation PC

Dans le dossier du projet :

```bash
python -m venv .venv
```

### Windows PowerShell

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

### Linux / Ubuntu / Raspberry Pi

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 3. Préparer LM Studio

1. Ouvre LM Studio.
2. Charge ton modèle `Gemma 3n 4B`.
3. Active le serveur local OpenAI-compatible.
4. Vérifie que l'URL est bien : `http://127.0.0.1:1234/v1`.
5. Dans `.env`, adapte `LMSTUDIO_MODEL` si le nom affiché par LM Studio est différent.

## 4. Test 1 — Vérifier MCP sans LLM

```bash
python test_rafiki_tools.py
```

Ce test doit afficher les outils disponibles puis finir par :

```text
✅ Tous les tests MCP locaux sont passés.
```

Tant que ce test ne passe pas, il ne faut pas encore tester l'agent LLM.

## 5. Test 2 — Vérifier l'agent central avec LM Studio

```bash
python rafiki_agent.py
```

Puis teste par exemple :

```text
Bonjour Rafiki, présente-toi à un enfant de 7 ans.
```

Ou en mode une seule requête :

```bash
python rafiki_agent.py --once "Propose une activité de calcul et fais une expression de joie"
```

Pour voir les appels d'outils :

```bash
python rafiki_agent.py --debug
```

## 6. Passage futur sur Raspberry Pi

Pour passer de la simulation au robot réel :

1. Installer Mosquitto sur Raspberry Pi.
2. Mettre dans `.env` :

```env
RAFIKI_MODE=raspberry
RAFIKI_MQTT_ENABLED=true
RAFIKI_MQTT_BROKER=localhost
```

3. Adapter dans `mcp_rafiki_systems_server.py` :
   - `speech_say()` pour appeler Piper réellement.
   - `vision_observe()` pour appeler la caméra + modèle vision.
   - `motor_gesture()` et `expression_set()` pour publier les commandes attendues par l'ESP32-S3.

## 7. Topics MQTT proposés pour ESP32-S3

Commandes envoyées par Rafiki vers ESP32-S3 :

```text
rafiki/esp32/commands
```

Format JSON :

```json
{
  "source": "rafiki_mcp",
  "action": "set_expression",
  "params": {
    "emotion": "joie",
    "intensity": 0.8
  },
  "created_at": "..."
}
```

Autres actions possibles :

```json
{
  "action": "motor_gesture",
  "params": {
    "gesture": "saluer",
    "speed": 0.5
  }
}
```

Statut envoyé par ESP32-S3 vers Rafiki :

```text
rafiki/esp32/status
```

Exemple :

```json
{
  "battery": 82,
  "motors": "ok",
  "display": "ok"
}
```
