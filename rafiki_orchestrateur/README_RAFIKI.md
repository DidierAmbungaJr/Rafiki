# Rafiki - Serveur cerveau PC

Ce dossier contient le serveur PC de Rafiki. Il garde le calcul lourd:

- agent central LangGraph;
- LM Studio OpenAI-compatible avec `bonsai-27b`;
- tools MCP systeme: memoire, profil enfant, parole placeholder, vision, activites educatives, journal parent;
- API FastAPI appelee par l'app mobile et, plus tard, par l'orchestrateur Raspberry.

La simulation de test du corps a ete retiree. La Raspberry gerera le corps reel dans un chantier separe.

## Fichiers principaux

| Fichier | Role |
|---|---|
| `rafiki_app.py` | Serveur FastAPI expose au Wi-Fi local. |
| `rafiki_agent.py` | Agent central LangGraph + LM Studio + tools MCP. |
| `mcp_rafiki_systems_server.py` | Tools MCP locaux: memoire, vision, activites, journal, commandes generiques. |
| `test_rafiki_tools.py` | Test des tools MCP sans LLM. |
| `test_rafiki_educational_flow.py` | Test du flux pedagogique local. |
| `docs/ARCHITECTURE_PC_RASPBERRY_LMSTUDIO.md` | Document de travail PC + mobile + Raspberry. |
| `docs/PLAN_V1_MONOREPO.md` | Plan de reconciliation des branches serveur, Raspberry et entree mobile pour la V1. |

## Installation

```powershell
cd rafiki_orchestrateur
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Configuration LM Studio

Dans LM Studio:

1. charge `bonsai-27b`;
2. active le serveur OpenAI-compatible;
3. verifie que l'URL est `http://127.0.0.1:1234/v1`.

Variables importantes:

```env
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_API_KEY=lm_studio
LMSTUDIO_MODEL=bonsai-27b

RAFIKI_APP_HOST=0.0.0.0
RAFIKI_APP_PORT=7860
RAFIKI_APP_CORS_ORIGINS=*
```

## Tests

Sans LLM:

```powershell
python test_rafiki_tools.py
python test_rafiki_educational_flow.py
```

Avec LM Studio:

```powershell
python rafiki_agent.py --once "Bonjour Rafiki, presente-toi a un enfant en deux phrases." --debug
```

Pour une vraie demo Bonsai sans routage local rapide:

```powershell
python rafiki_agent.py --once "Propose une petite activite sur la pluie pour un enfant de 7 ans." --force-llm --debug
```

Serveur HTTP:

```powershell
python rafiki_app.py
```

Puis depuis le meme Wi-Fi:

```text
http://IP_DU_PC:7860/api/health
```

L'app mobile envoie le texte transcrit par Whisper a `POST /api/chat` et lit le champ `reply`.
Pour forcer une vraie demo Bonsai via l'API, ajouter `"force_llm": true` au JSON de `/api/chat`.

## Scenario d'allumage

Chaque nouvelle conversation commence par l'accueil officiel de Rafiki:

```text
Bonjour, je suis Rafiki. Je peux parler avec toi, t'aider à apprendre, faire de petites activités, garder quelques souvenirs utiles et regarder autour de moi quand ma caméra est branchée. Qu'est-ce que tu veux faire maintenant ?
```

En API, l'app peut lancer ce scenario avec:

```text
POST /api/start
```
