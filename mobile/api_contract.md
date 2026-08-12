# Contrat API Mobile Backend -> Serveur PC Rafiki

## Appel conversation

Le backend mobile remplace l'ancien appel orchestrateur `/api/predict` par:

```http
POST http://IP_DU_PC:7860/api/chat
```

Requete:

```json
{
  "message": "texte transcrit par STT mobile",
  "input_mode": "voice_mobile",
  "child_id": "child_123",
  "parent_id": "parent_456",
  "session_id": "session_789",
  "child_profile": {
    "name": "Leo",
    "age": 7,
    "language": "francais simple",
    "interests": ["histoires", "calcul"],
    "level": "debutant"
  },
  "parental_controls": {
    "safe_mode": true,
    "allowed_topics": ["lecture", "calcul", "histoires"],
    "blocked_topics": []
  },
  "force_llm": false
}
```

Reponse:

```json
{
  "status": "ok",
  "reply": "texte a lire avec le TTS mobile",
  "source": "llm",
  "input_mode": "voice_mobile",
  "session_state": {},
  "history": [],
  "body_feedback": []
}
```

Le backend mobile garde l'historique et les progres dans sa base SQLite.

## Mapping backend mobile actuel

Dans le repo `https://github.com/AngisheSALEM/rafiki.git`, le fichier cible principal est:

```text
backend/app/services/ai_dialog.py
```

Aujourd'hui il appelle:

```text
{settings.LLM_ORCHESTRATOR_URL}/api/predict
```

Pour la V1, remplacer par:

```text
{settings.LLM_ORCHESTRATOR_URL}/api/chat
```

Et mapper:

- `speech_text` <- `reply`;
- `emotion` <- emotion UI mobile locale ou dernier etat corps si disponible;
- `pi_action` <- laisser vide cote mobile, car la Raspberry recupere les commandes par HTTP pull depuis le serveur PC.

## Statut corps

Le backend mobile peut lire le statut du corps via le serveur PC:

```http
GET http://IP_DU_PC:7860/api/status
```

Pour la V1, le mobile ne commande pas directement la Raspberry. Le serveur PC decide, la Raspberry poll.
