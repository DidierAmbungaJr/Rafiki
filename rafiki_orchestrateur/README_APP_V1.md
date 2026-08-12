# Rafiki App V1

Interface locale pour utiliser Rafiki naturellement avec :

- entree texte ;
- entree micro via le navigateur quand disponible ;
- sortie texte ;
- sortie vocale via le navigateur ;
- panneau d'etat orchestrateur + futur lien Raspberry ;
- profil enfant et journal parent.

## Lancement

Depuis `rafiki_orchestrateur` :

```bash
python rafiki_app.py
```

Puis ouvrir :

```text
http://127.0.0.1:7860
```

LM Studio doit etre lance avec le serveur OpenAI-compatible actif sur l'URL
configuree dans `.env`.

## Mode serveur PC pour Raspberry

Pour que la Raspberry utilise ce PC comme cerveau Rafiki, configure :

```env
RAFIKI_APP_HOST=0.0.0.0
RAFIKI_APP_PORT=7860
LMSTUDIO_MODEL=bonsai-27b
RAFIKI_APP_CORS_ORIGINS=*
```

Puis la Raspberry appelle :

```text
http://IP_DU_PC:7860/api/chat
```

L'app mobile peut appeler le meme endpoint apres transcription Whisper locale :

```json
{
  "message": "texte transcrit",
  "input_mode": "voice_mobile"
}
```

Le suivi complet du chantier serveur PC + orchestrateur Raspberry est dans :

```text
docs/ARCHITECTURE_PC_RASPBERRY_LMSTUDIO.md
```
