# Rafiki - Serveur PC LM Studio et orchestrateur Raspberry

Ce document sert de cahier de travail pour separer clairement trois chantiers:

1. le serveur Rafiki sur PC, qui heberge le cerveau LM Studio et les tools MCP;
2. l'orchestrateur Raspberry, qui gere le corps reel de Rafiki;
3. l'app mobile, qui sert de micro, de baffle et heberge Whisper.

## Objectif

L'app mobile garde l'audio: micro, Whisper local et sortie haut-parleur.
La Raspberry garde le corps reel de Rafiki: camera, ecran, moteurs et capteurs.
Le PC garde le calcul lourd: LM Studio avec `bonsai-27b`, LangGraph et les tools MCP.

Flux principal:

```text
Enfant -> App mobile micro -> Whisper mobile -> HTTP Wi-Fi -> PC Rafiki Server
                                                     -> LM Studio bonsai-27b
                                                     -> tools MCP
                                                     -> reponse texte -> App mobile baffle
                                                     -> feedback corps -> Raspberry
```

## Fonctionnalite 1 - Serveur PC Rafiki

Le serveur PC se lance depuis `rafiki_orchestrateur`:

```powershell
python rafiki_app.py
```

Variables importantes dans `.env`:

```env
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_API_KEY=lm_studio
LMSTUDIO_MODEL=bonsai-27b

RAFIKI_APP_HOST=0.0.0.0
RAFIKI_APP_PORT=7860
RAFIKI_APP_CORS_ORIGINS=*
```

Avec `RAFIKI_APP_HOST=0.0.0.0`, la Raspberry et l'app mobile peuvent appeler le serveur via:

```text
http://IP_DU_PC:7860/api/chat
```

Endpoints utiles:

```text
GET  /api/health
POST /api/chat
POST /api/vision
GET  /api/status
```

Exemple `POST /api/chat`:

```json
{
  "message": "Bonjour Rafiki, propose une activite de calcul.",
  "input_mode": "voice"
}
```

Exemple `POST /api/vision`:

```json
{
  "prompt": "Que vois-tu devant Rafiki ?",
  "filename": "camera.jpg",
  "image_base64": "..."
}
```

## Vision avec LM Studio

La vision passe par l'outil MCP `vision_observe`.
Elle peut analyser une image avec LM Studio si ces variables sont activees:

```env
RAFIKI_VISION_ENABLED=true
RAFIKI_VISION_MODEL=nom-du-modele-vision
RAFIKI_VISION_TIMEOUT_SECONDS=90
```

Important: `bonsai-27b` peut etre excellent comme cerveau texte, mais il faut verifier dans LM Studio s'il accepte les entrees image. Si ce n'est pas le cas, garder `LMSTUDIO_MODEL=bonsai-27b` pour le cerveau et mettre `RAFIKI_VISION_MODEL` sur un modele vision compatible.

## Fonctionnalite 2 - App mobile audio

L'app mobile devient le peripherique audio de Rafiki:

- elle capture le micro;
- elle transcrit avec Whisper local;
- elle envoie le texte au serveur PC;
- elle lit la reponse `reply` avec le haut-parleur du telephone;
- elle peut afficher un etat simple: ecoute, reflechit, parle, erreur reseau.

Configuration visee dans l'app:

```env
RAFIKI_BRAIN_URL=http://IP_DU_PC:7860
RAFIKI_BRAIN_TIMEOUT_SECONDS=180
```

Contrat minimal `POST /api/chat`:

```json
{
  "message": "texte transcrit par Whisper",
  "input_mode": "voice_mobile",
  "force_llm": false
}
```

Reponse attendue:

```json
{
  "status": "ok",
  "reply": "texte a lire au haut-parleur",
  "source": "llm",
  "body_feedback": []
}
```

Si l'app est native, CORS n'est generalement pas un probleme. Si elle utilise WebView, Expo web ou une page de test navigateur, garder `RAFIKI_APP_CORS_ORIGINS=*` pendant le developpement.
Pour une demo reelle avec Bonsai, envoyer temporairement `"force_llm": true`.

## Fonctionnalite 3 - Orchestrateur Raspberry

La prochaine etape cote Raspberry consiste a retirer l'appel LLM local lent. La Raspberry doit surtout recevoir ou executer les actions de corps.

Configuration visee sur la Raspberry:

```env
RAFIKI_BRAIN_URL=http://IP_DU_PC:7860
RAFIKI_BRAIN_TIMEOUT_SECONDS=180
```

Si la Raspberry garde une entree texte directe ou un bouton local, elle peut aussi appeler:

```python
POST {RAFIKI_BRAIN_URL}/api/chat
-> {"reply": "...", "source": "llm", "body_feedback": []}
```

Pour la camera:

```python
POST {RAFIKI_BRAIN_URL}/api/vision
-> {"status": "ok", "vision": {...}}
```

La Raspberry reste responsable de capturer l'audio/image et de jouer la voix ou les mouvements reels. Le PC ne doit pas dependre des GPIO Raspberry.
Si l'app mobile remplace le micro et le baffle, la Raspberry n'a plus besoin de gerer l'audio principal.

## Checklist

- [x] Exposer le serveur PC sur le reseau local.
- [x] Configurer `bonsai-27b` comme modele LM Studio principal.
- [x] Ajouter un endpoint serveur pour la vision base64.
- [x] Brancher `vision_observe` sur LM Studio quand active.
- [x] Documenter l'app mobile comme micro, baffle et Whisper local.
- [ ] Tester depuis une autre machine: `GET http://IP_DU_PC:7860/api/health`.
- [ ] Tester depuis l'app mobile: Whisper -> `/api/chat` -> lecture de `reply`.
- [ ] Ajouter le client HTTP dans l'orchestrateur Raspberry.
- [ ] Ajouter capture camera Raspberry -> `/api/vision`.
- [ ] Mesurer latence avant/apres.
