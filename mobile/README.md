# Rafiki Mobile V1

Repo mobile source:

```text
https://github.com/AngisheSALEM/rafiki.git
```

Ce repo contient:

- `mobile/`: app Flutter;
- `backend/`: backend FastAPI + SQLite;
- STT/TTS cote mobile/backend mobile;
- profils enfants/parents;
- historique et progres.

Decision V1: le backend mobile est la source de verite pour les profils, parents, historique et progres.

Le serveur PC Rafiki reste le cerveau LLM local et expose l'API appelee par le backend mobile.

Voir aussi:

```text
api_contract.md
```
