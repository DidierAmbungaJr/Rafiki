# Rafiki V1 - Organisation branches, modules et contrats

Ce document fixe la cible V1 pour reconcilier:

- `rafiki-v1-prototype-public`: serveur PC a jour avec la nouvelle logique;
- `rafiki-raspberry`: code hardware reel Raspberry/Arduino;
- l'app mobile Flutter + FastAPI + SQLite, developpee separement dans `https://github.com/AngisheSALEM/rafiki.git` mais connectee au serveur Rafiki.

## Objectif V1

Demo locale: un parent connecte un enfant a Rafiki sur le meme reseau local.

La V1 est reussie si Rafiki offre:

- latence faible;
- reponse vocale via l'app mobile;
- ecran anime et mouvements via Raspberry/Arduino;
- profils enfants;
- controle parent;
- historique et progres consultables;
- reconnaissance d'objets via camera Raspberry.

## Responsabilites

### PC serveur

Le PC est le cerveau central.

Il garde:

- modele IA puissant via LM Studio;
- orchestration conversationnelle;
- decision des gestes et expressions;
- stockage des profils et de l'historique;
- API centrale appelee par mobile et Raspberry.

Il ne gere pas directement les GPIO, servos, ecran ou camera.

### Raspberry

La Raspberry est un executant hardware simple.

Elle garde:

- controle Arduino/ESP32;
- ecran anime;
- servomoteurs et mouvements;
- camera;
- capture image pour reconnaissance d'objets;
- client HTTP vers le serveur PC.

Elle ne garde pas de logique conversationnelle, pas de LLM, pas de decision pedagogique.

### App mobile

L'app mobile est le peripherique utilisateur et parent.

Elle garde:

- STT;
- TTS;
- configuration de Rafiki;
- profils enfant/parent cote app;
- lancement de conversation;
- historique/progres;
- controle parent et securite.

Elle appelle l'API du serveur PC. Son backend existe deja en FastAPI + SQLite et reste developpe separement.

## Structure cible du monorepo V1

```text
Rafiki/
  server/
    app/
    static/
    docs/
    tests/
    requirements.txt
    README.md

  raspberry/
    app/
    arduino/
    camera/
    docs/
    tests/
    requirements.txt
    README.md

  mobile/
    README.md
    api_contract.md
    integration_notes.md

  shared/
    api/
      rafiki_server_openapi.json
      body_commands.schema.json
      events.schema.json
    docs/
      v1_architecture.md
      local_demo_runbook.md

  README.md
```

Pour eviter de casser le prototype actuel, faire la migration en deux temps:

1. documenter et stabiliser les contrats dans l'etat actuel;
2. renommer/deplacer les dossiers quand les deux branches sources sont presentes localement.

## Contrats API V1

### Mobile vers PC

Le mobile envoie le texte deja transcrit.

```http
POST /api/chat
```

```json
{
  "message": "texte transcrit par l'app mobile",
  "input_mode": "voice_mobile",
  "child_id": "default",
  "parent_id": "default_parent",
  "force_llm": false
}
```

Reponse attendue:

```json
{
  "status": "ok",
  "reply": "texte a lire par le TTS mobile",
  "source": "llm",
  "body_feedback": [
    {
      "type": "expression",
      "name": "joie",
      "intensity": 0.8
    },
    {
      "type": "gesture",
      "name": "saluer",
      "speed": 0.5
    }
  ],
  "session_state": {},
  "history": []
}
```

### Raspberry vers PC

La Raspberry peut envoyer une image camera au cerveau.

```http
POST /api/vision
```

```json
{
  "prompt": "Que vois-tu devant Rafiki ?",
  "filename": "camera.jpg",
  "image_base64": "..."
}
```

### PC vers Raspberry

Decision V1: HTTP pull.

La Raspberry appelle regulierement le serveur PC pour recuperer les commandes de corps en attente.
Les commandes sont stockees dans SQLite cote serveur PC afin de survivre aux appels MCP stdio successifs.

```http
GET /api/body/next
```

Si aucune commande n'est disponible:

```json
{
  "status": "idle",
  "command": null
}
```

Commande corps cible:

```json
{
  "id": "uuid",
  "created_at": "2026-08-12T00:00:00Z",
  "target": "body",
  "action": "set_expression",
  "params": {
    "emotion": "joie",
    "intensity": 0.8
  }
}
```

Actions V1 minimales:

- `set_expression`;
- `motor_gesture`;
- `screen_text`;
- `camera_observe`;
- `status_ping`.

### Source de verite profils et historique

Decision V1: le backend mobile est la source de verite pour les profils enfant/parent, l'historique et les progres.

Le serveur PC garde seulement:

- l'etat conversationnel necessaire a la session locale;
- un cache temporaire si utile pour reduire la latence;
- les evenements produits pendant la conversation avant retour vers le backend mobile.

Le backend mobile envoie au serveur PC le contexte utile au moment de l'appel, par exemple `child_id`, age, langue, interets, niveau, restrictions parentales et identifiant de session.

### Vision Raspberry

Decision V1: image a la demande.

La Raspberry n'observe pas en continu. Elle capture et envoie une image seulement quand:

- l'enfant ou le parent demande a Rafiki de regarder;
- l'app mobile declenche une action de reconnaissance;
- le serveur PC demande explicitement une observation dans la session.

## Strategie branches

### Branche source serveur

`rafiki-v1-prototype-public` reste la source du module `server/`.

Actions:

- garder la logique LM Studio, LangGraph et MCP;
- renommer `rafiki_orchestrateur/` vers `server/` quand la migration commence;
- retirer les artefacts Python generes du suivi Git;
- documenter le contrat API mobile/Raspberry.

### Branche source Raspberry

`rafiki-raspberry` devient la source du module `raspberry/`.

Actions:

- importer le code hardware reel dans `raspberry/`;
- isoler Arduino/ESP32 dans `raspberry/arduino/`;
- isoler camera dans `raspberry/camera/`;
- remplacer tout appel LLM local par des appels HTTP vers `RAFIKI_BRAIN_URL`;
- garder la Raspberry comme executant.

### Branche V1 propre

Creer une branche de reconciliation:

```powershell
git checkout -b rafiki-v1-monorepo
```

Puis importer par etapes:

1. module `server/`;
2. module `raspberry/`;
3. dossier `mobile/` avec contrat et notes d'integration;
4. dossier `shared/` avec schemas et runbook demo locale.

## Decisions restantes

- Ajouter `child_id`, `parent_id`, `session_id` et le contexte enfant explicitement aux endpoints serveur.
- Definir les limites du controle parent V1: pause conversation, mode enfant, historique, rapport, restrictions themes.
- Definir comment le serveur PC renvoie les evenements au backend mobile: dans la reponse `/api/chat`, endpoint dedie, ou synchronisation appelee par le backend mobile.
- Definir la cadence HTTP pull Raspberry: par exemple 2 a 5 appels/seconde pendant une conversation active, puis cadence reduite au repos.

## Checklist migration

- [x] Recuperer localement la branche `rafiki-raspberry`.
- [x] Creer `rafiki-v1-monorepo`.
- [ ] Deplacer `rafiki_orchestrateur/` vers `server/`.
- [x] Importer le hardware reel dans `raspberry/`.
- [x] Ajouter `mobile/api_contract.md`.
- [x] Ajouter schemas JSON dans `shared/api/`.
- [x] Ajouter endpoints body HTTP pull: `GET /api/body/next` et eventuellement `POST /api/body/status`.
- [x] Ajouter contexte mobile aux requetes serveur: `child_id`, `parent_id`, `session_id`, profil enfant et restrictions parentales.
- [x] Ajouter test de contrat serveur: `/api/chat` -> file corps SQLite -> `/api/body/next` -> `/api/body/status`.
- [ ] Tester `GET /api/health` depuis mobile et Raspberry.
- [ ] Tester `POST /api/chat` depuis mobile avec STT/TTS.
- [ ] Tester capture camera Raspberry a la demande -> `POST /api/vision`.
- [ ] Tester decision PC -> mouvement/ecran Raspberry.
- [ ] Mesurer latence complete: STT -> serveur -> TTS -> corps.
