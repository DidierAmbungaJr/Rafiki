# Rafiki V1 Monorepo

Objectif V1: demo locale avec app mobile + serveur PC + Raspberry.

## Modules

```text
rafiki_orchestrateur/  Serveur PC: LM Studio, LangGraph, MCP, API FastAPI.
raspberry/             Client hardware: HTTP pull, Arduino Mega, ecran, servos.
mobile/                Contrat d'integration avec le repo mobile externe.
shared/                Schemas API partages.
```

Repo mobile source:

```text
https://github.com/AngisheSALEM/rafiki.git
```

## Flux V1

```text
Enfant -> app mobile STT -> backend mobile -> serveur PC /api/chat
                                  -> LM Studio + outils MCP
                                  -> reponse texte -> backend/app mobile TTS
                                  -> commandes corps en file
Raspberry -> GET /api/body/next -> Arduino ecran/servos
```

La Raspberry ne porte pas le LLM, le STT ou le TTS. Elle execute les commandes corps et capture les images camera a la demande.
