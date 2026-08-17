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

## Pont Raspberry Pi

Le serveur PC expose maintenant le protocole HTTP du dépôt de référence
[`rafiki-in-a-rasberry-pi-part`](https://github.com/AngisheSALEM/rafiki-in-a-rasberry-pi-part) :

- file et heartbeat du corps : `GET /api/body/next`, `POST|GET /api/body/status` ;
- diagnostic du pont : `GET /health`, `GET /api/bridge/status` ;
- caméra optionnelle : `POST /api/vision/register`, `POST /api/vision/upload`,
  `GET /api/vision/latest`, `GET|POST /api/vision/capture`.

Les instructions de déploiement de la Pi et le service systemd sont dans
[`raspberry/README.md`](raspberry/README.md).
