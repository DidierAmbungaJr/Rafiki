# Rafiki Context

Rafiki est un robot compagnon educatif pour enfants, concu pour tourner sur Raspberry Pi.

Objectif produit :

- interagir avec l'enfant de facon courte, claire, bienveillante et adaptee a 5-10 ans ;
- utiliser un LLM local via `llama-server` pour produire une decision structuree ;
- separer la parole, l'emotion, le mouvement et l'affichage ecran ;
- preparer ensuite les briques voix, vision, mouvements et routines.

Etat actuel de la Raspberry :

- le depot local est connecte a `git@github.com:mpoho/Rafiki.git` ;
- `llama-server` existe dans `/home/admin/llama.cpp/build/bin/llama-server` ;
- aucun vrai modele GGUF de chat n'a encore ete trouve dans `/home/admin/llama.cpp/models` ;
- les fichiers GGUF presents sont des vocabulaires trop petits pour lancer Rafiki comme assistant ;
- le modele vise pour la conversation locale est `ggml-org/gemma-3-4b-it-GGUF:Q4_K_M`
  via `llama-server` ;
- les premiers tests couvrent le contrat JSON attendu du LLM, sans dependance au serveur local.
- la reponse vocale locale utilise `espeak-ng`, deja present sur la Raspberry ;
- les peripheriques de lecture HDMI sont visibles hors sandbox, mais aucun micro ALSA
  n'est detecte pour l'instant.

Decision LLM attendue :

- `speech` : texte court a dire a l'enfant ;
- `emotion` : `neutral`, `happy`, `sad`, `surprised` ou `thinking` ;
- `movement` : action robot autorisee, par exemple `none`, `swing`, `dance` ou `stop` ;
- `screen_mode` : `face`, `text`, `learning` ou `quiz` ;
- `screen_content` : contenu a afficher.
