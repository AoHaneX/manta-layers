# Instructions courtes pour Codex / développeurs

- Projet **Manta Layers**, éditeur d'images local, Python + PySide6 + Pillow, interface ReefKit.
- Point d'entrée `main.py`. Sur Windows, lanceur `lancer_manta_layers.bat`.
- Modèle sans dépendance Qt dans `app/model.py`. Sérialisation `.manta` dans `app/storage.py`.
- Canvas et export dans `app/graphics.py`. Fenêtre et actions dans `app/window.py`.
- Toute modification persistante du document doit passer par `QUndoCommand` / `QUndoStack` ; ne pas modifier le modèle directement depuis les widgets sans transaction.
- Préserver **exactement** le dessin de la mascotte `assets/manta.png`. Ne pas le régénérer ni le déformer : icônes dérivées autorisées par redimensionnement nearest-neighbor.
- Ne jamais rasteriser définitivement les images source ou les calques de texte. Conserver les propriétés (position, taille, angle, etc.) éditables dans le projet.
- Tester `python -m unittest discover -s tests -v` ; vérifier manuellement sous Windows après toute modification Qt.
- Phase suivante : texte sur trajectoire (arc, U, U inversé), puis Warp à points de contrôle, sans casser le format `.manta`.
- Ne pas introduire d'API distante, de télémétrie ni de comptes utilisateur sans demande explicite.
