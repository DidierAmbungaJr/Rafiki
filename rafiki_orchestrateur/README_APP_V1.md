# Rafiki App V1

Interface locale pour utiliser Rafiki naturellement avec :

- entree texte ;
- entree micro via le navigateur quand disponible ;
- sortie texte ;
- sortie vocale via le navigateur ;
- panneau d'etat orchestrateur + corps Wokwi ;
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
