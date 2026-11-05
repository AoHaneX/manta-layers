# Manta Layers v1.0.0 — Première version publique

Manta Layers est un éditeur d'images à calques de la suite **Blue Shrimp · ReefKit**, conçu pour Windows 10/11 (64 bits).

Cette première version propose une application utilisable entièrement hors ligne, avec une édition non destructive, un format de projet `.manta` et des outils de composition graphique.

### Fonctionnalités principales

- Calques d'images, textes vectoriels, formes, dossiers et sélection multiple.
- Déplacement, rotation, redimensionnement, alignement et magnétisme.
- Sélections rectangulaires, elliptiques et lasso ; masques et gomme non destructifs.
- Outils de couleur, pipette sur le bureau, fond transparent et export PNG/JPEG/WebP.
- Bibliothèque de modèles, créateur de tokens JDR et découpe de spritesheets.
- Historique d'annulation et copies de récupération.

### Télécharger

| Fichier | Utilisation |
| --- | --- |
| `MantaLayers-1.0.0-Setup.exe` | Installation Windows avec raccourcis |
| `MantaLayers-1.0.0-Windows-Portable.zip` | Version autonome : décompresser et lancer `MantaLayers.exe` |
| `SHA256SUMS.txt` | Empreintes SHA-256 pour vérifier les fichiers |

**Python n'est pas nécessaire** pour utiliser les versions Windows distribuées. La version dite « portable » conserve toutefois ses paramètres et données utilisateur dans le profil Windows, comme la version installée.

### Informations importantes

- Le détourage par IA locale n'est pas intégré aux exécutables autonomes ; le détourage par couleur reste disponible.
- Les documents `.manta` peuvent être enregistrés et rouverts, mais l'ouverture par double-clic depuis l'explorateur Windows n'est pas encore prise en charge.
- Les fichiers exécutables ne sont pas signés numériquement ; Windows SmartScreen peut afficher un avertissement. Vérifiez l'origine du téléchargement et les sommes SHA-256.
- Les œuvres graphiques et mascottes ne sont pas sous licence MIT ; voir `LICENSE`.

Documentation : [README](https://github.com/AoHaneX/manta-layers#readme) · [Guide d'utilisation](https://github.com/AoHaneX/manta-layers/blob/master/docs/GUIDE.md) · [Journal des modifications](https://github.com/AoHaneX/manta-layers/blob/master/CHANGELOG.md)

> Cette release est d'abord préparée en **brouillon**. Elle ne doit être publiée qu'après validation de l'installation et du lancement sous Windows.
