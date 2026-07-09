# Rafiki — Corps + écran dans Wokwi

Ce module ajoute à Rafiki une couche **mouvements + écran** simulée dans Wokwi, exactement dans la logique du workshop MCP/MQTT :

```text
Utilisateur → Agent LLM central → outil MCP → MQTT → ESP32 Wokwi → OLED + servos
                                           ↑                         ↓
                                      statut MQTT ← rafiki/468994098570147841/body/status
```

## 1. Composants simulés

| Élément | Rôle | GPIO ESP32 |
|---|---|---:|
| OLED SSD1306 128x64 | visage + texte court | SDA 21, SCL 22 |
| Servo tête | mouvement de tête | 18 |
| Servo bras gauche | mouvement bras gauche | 19 |
| Servo bras droit | mouvement bras droit | 23 |
| Buzzer | petit feedback sonore | 5 |

## 2. Topics MQTT

| Type | Topic | Sens |
|---|---|---|
| Commandes | `rafiki/468994098570147841/body/cmd` | MCP/PC → Wokwi |
| Statut | `rafiki/468994098570147841/body/status` | Wokwi → MCP/PC |

Broker par défaut :

```text
broker.emqx.io:1883
```

## 3. Créer le projet dans Wokwi

1. Va sur Wokwi.
2. Crée un nouveau projet **ESP32 MicroPython**.
3. Remplace le fichier `main.py` par `wokwi/main.py`.
4. Remplace le fichier `diagram.json` par `wokwi/diagram.json`.
5. Ajoute un nouveau fichier `ssd1306.py` et colle le contenu de `wokwi/ssd1306.py`.
6. Lance la simulation.
7. Attends que l'écran affiche `Rafiki pret`.

## 4. Tester sans LLM avec MQTT Explorer

Publie sur le topic :

```text
rafiki/468994098570147841/body/cmd
```

Exemples de messages JSON :

```json
{"action":"expression","name":"happy","text":"Bravo !"}
```

```json
{"action":"gesture","name":"greet","repeat":1}
```

```json
{"action":"gesture","name":"celebrate","repeat":1}
```

```json
{"action":"pose","head":70,"left_arm":130,"right_arm":50}
```

```json
{"action":"screen_text","expression":"thinking","text":"Je reflechis..."}
```

```json
{"action":"demo"}
```

Tu dois aussi pouvoir t'abonner au statut :

```text
rafiki/468994098570147841/body/status
```

## 5. Installer les dépendances Python côté PC

Dans ton dossier Python où se trouve ton agent Rafiki :

```bash
pip install fastmcp paho-mqtt
```

Si tu utilises `uv`, tu peux lancer le serveur MCP avec :

```bash
uv run --with fastmcp --with paho-mqtt fastmcp run mcp_rafiki_body_server.py
```

## 6. Tester le serveur MCP Body sans LLM

1. Lance d'abord la simulation Wokwi.
2. Va dans le dossier `mcp`.
3. Exécute :

```bash
python test_body_mcp_direct.py
```

Le script doit :

- attendre le statut Wokwi ;
- afficher une expression heureuse ;
- faire le geste de salutation ;
- changer une pose ;
- afficher le dernier statut.

## 7. Ajouter le serveur Body à ton agent Rafiki

Dans ton `rafiki_agent.py`, là où tu crées `MultiServerMCPClient`, ajoute un deuxième serveur MCP.

### Option Windows avec chemin absolu

```python
"RafikiBodyWokwi": {
    "transport": "stdio",
    "command": "uv",
    "args": [
        "run",
        "--with", "fastmcp",
        "--with", "paho-mqtt",
        "fastmcp",
        "run",
        "C:\\Users\\ODC\\Desktop\\Didier\\agent-llm\\mcp_rafiki_body_server.py"
    ]
}
```

### Option Linux / Ubuntu / Raspberry Pi

```python
"RafikiBodyWokwi": {
    "transport": "stdio",
    "command": "uv",
    "args": [
        "run",
        "--with", "fastmcp",
        "--with", "paho-mqtt",
        "fastmcp",
        "run",
        "/home/didier/rafiki/mcp_rafiki_body_server.py"
    ]
}
```

## 8. Prompt système à ajouter à ton agent

Ajoute ce bloc dans le `SystemMessage` de ton agent :

```text
Tu peux contrôler le corps de Rafiki via les outils MCP du serveur RafikiBodyWokwi.
Quand l'enfant réussit, utilise une expression joyeuse et un geste de célébration.
Quand Rafiki réfléchit, affiche l'expression thinking et fais un petit geste de réflexion.
Quand il salue, utilise le geste greet.
Quand il y a une alerte ou une erreur importante, utilise l'expression alert.
Ne bouge pas les servos de manière excessive : privilégie les gestes prédéfinis.
```

## 9. Prompts de test avec ton agent

```text
Rafiki, salue l'enfant avec ton écran et ton bras.
```

```text
Rafiki, fais une expression de réflexion et montre que tu cherches une réponse.
```

```text
L'enfant a donné la bonne réponse. Félicite-le avec ton écran et tes mouvements.
```

```text
Montre une alerte SOS sur ton écran et fais un geste d'alerte.
```

```text
Mets ta tête à 70 degrés, le bras gauche à 130 degrés et le bras droit à 50 degrés.
```

## 10. Passage futur vers Raspberry Pi

Quand Wokwi marche, la logique reste la même :

- les outils MCP ne changent presque pas ;
- MQTT peut rester identique ;
- `main.py` sera remplacé par un script Raspberry qui contrôle le vrai OLED et les vrais moteurs/servos ;
- l'agent LLM continue à appeler les mêmes outils MCP.

C'est pour ça qu'on sépare bien :

```text
Agent LLM / MCP = cerveau
Wokwi ESP32 = corps simulé
Raspberry Pi = corps réel plus tard
```
