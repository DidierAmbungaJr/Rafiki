# Backend mobile - Adaptation V1

Repo cible:

```text
https://github.com/AngisheSALEM/rafiki.git
```

Fichiers modifies dans la copie d'integration:

```text
backend/app/services/ai_dialog.py
backend/app/api/v1/endpoints/audio.py
```

## Changement principal

Le backend mobile appelle maintenant le serveur PC Rafiki:

```text
POST {LLM_ORCHESTRATOR_URL}/api/chat
```

au lieu de:

```text
POST {LLM_ORCHESTRATOR_URL}/api/predict
```

Payload envoye au serveur PC:

```json
{
  "message": "texte transcrit",
  "input_mode": "voice_mobile",
  "child_id": "default",
  "parent_id": "default_parent",
  "session_id": "default_session",
  "child_profile": {
    "name": "Leo"
  },
  "parental_controls": {
    "safe_mode": true
  }
}
```

Mapping de reponse:

```text
speech_text <- reply
emotion     <- derivee localement depuis reply
pi_action   <- {}
```

`pi_action` reste present pour compatibilite avec la reponse actuelle du backend mobile, mais la Raspberry n'est plus commandee directement par le backend mobile.

## Responsabilite Raspberry V1

Le backend mobile ne pousse plus de commande WebSocket vers la Raspberry apres une reponse IA.

Le flux V1 est:

```text
backend mobile -> serveur PC /api/chat
serveur PC -> file body_commands SQLite
Raspberry -> serveur PC /api/body/next
```

## Verification faite

La copie d'integration du backend mobile compile avec:

```powershell
python -m compileall .tmp\mobile-app-inspect\backend\app
```
