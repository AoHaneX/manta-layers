# Instructions courtes pour Codex / développeurs

- Projet **Manta Layers**, éditeur d'images local, Python + PySide6 + Pillow, interface ReefKit.
- Point d'entrée `main.py`. Sur Windows, lanceur `lancer_manta_layers.bat`.
- Modèle sans dépendance Qt dans `app/model.py`. Sérialisation `.manta` dans `app/storage.py`.
- Canvas, rendu des calques (avec cache) et export dans `app/graphics.py`. Fenêtre et actions dans `app/window.py` ; pictogrammes dans `app/icons.py`, widgets dans `app/widgets.py`, boîtes de dialogue dans `app/dialogs.py`.
- Couleurs uniquement via les jetons `COLORS` de `app/theme.py`. Données utilisateur (modèles, polices importées) sous `app/paths.user_data_directory()`, jamais dans le dossier de l'application.
- Toute modification persistante du document doit passer par `QUndoCommand` / `QUndoStack` ; ne pas modifier le modèle directement depuis les widgets sans transaction.
- Préserver **exactement** le dessin de la mascotte `assets/manta.png`. Ne pas le régénérer ni le déformer : icônes dérivées autorisées par redimensionnement nearest-neighbor.
- Ne jamais rasteriser définitivement les images source ou les calques de texte. Conserver les propriétés (position, taille, angle, etc.) éditables dans le projet.
- Tester `python -m unittest discover -s tests -v` ; vérifier manuellement sous Windows après toute modification Qt.
- Phase suivante : Warp à points de contrôle (champ réservé `text_warp`), sans casser le format `.manta`. Le texte sur trajectoire est fait.
- Ne pas introduire d'API distante, de télémétrie ni de comptes utilisateur sans demande explicite.
