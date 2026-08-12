# Rafiki Raspberry V1

La Raspberry reste un executant hardware simple.

Elle fait:

- controle serie de l'Arduino Mega;
- ecran TFT et servomoteurs via `arduino/rafiki_mega_expressions_mouvements.ino`;
- HTTP pull vers le serveur PC;
- camera a la demande, a brancher ensuite sur `POST /api/vision`.

Elle ne fait pas:

- LLM local;
- STT;
- TTS;
- decision pedagogique.

## Installation

```bash
cd Rafiki
python -m venv .venv
.venv/bin/pip install -r raspberry/requirements.txt
```

## Lancer le client corps

```bash
.venv/bin/python -m raspberry.app.body_pull_client \
  --brain-url http://IP_DU_PC:7860 \
  --body-port /dev/ttyACM0
```

Le client appelle:

```text
GET  /api/body/next
POST /api/body/status
```

Les commandes supportees cote Arduino:

- `set_expression` -> `E0..E9` + `SHOW_EYES`;
- `motor_gesture` -> `B0..B9` ou `BSTOP`;
- `screen_text` -> `TEXT:<message>`.
