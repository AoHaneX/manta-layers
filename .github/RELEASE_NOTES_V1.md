# Manta Layers v1.0.0 — Windows

Manta Layers v1.0.0 est disponible pour **Windows 10 et 11, 64 bits**. Cet éditeur d'images à calques fait partie de la suite **Blue Shrimp · ReefKit**. Il permet de composer des visuels avec des images, du texte et des formes, avec une édition non destructive, un historique d'annulation et le format de projet `.manta`.

Les deux distributions Windows embarquent Python et les dépendances nécessaires. **Aucune installation de Python n'est requise.**

### Installateur — Setup

Téléchargez **MantaLayers-1.0.0-Setup.exe**, puis suivez l'assistant.

L'installation se fait par défaut pour votre compte Windows, sans droits d'administrateur. Elle crée un raccourci dans le menu Démarrer et propose un raccourci facultatif sur le bureau.

La désinstallation conserve vos modèles, polices importées, réglages, journaux et fichiers de récupération.

### Version portable — ZIP

Téléchargez **MantaLayers-1.0.0-Windows-Portable.zip**, extrayez toute l'archive, puis lancez **MantaLayers.exe**.

Aucune installation nécessaire. Conservez l'exécutable et le dossier `_internal` côte à côte. Comme pour la version installée, les réglages et données utilisateur sont conservés dans votre compte Windows : cette version est autonome, mais pas entièrement indépendante du profil utilisateur.

### Code source — ZIP et TAR.GZ

GitHub fournit automatiquement **Source code (zip)** et **Source code (tar.gz)** lors de la publication de cette version. Ces archives contiennent le code source du tag `v1.0.0`, pas l'application Windows déjà compilée.

### Empreintes SHA-256

**Setup — `MantaLayers-1.0.0-Setup.exe`**
```text
8480BEF8F4566AB3947FDEA80CA4946F1319B9DE4DD99020793A8BD9EA463737
```

**Portable — `MantaLayers-1.0.0-Windows-Portable.zip`**
```text
3EFBD471F87D1B0E07871D9D3991DE5411B2840D1B72EAE70C321F34F19C8EAB
```

Le fichier **SHA256SUMS.txt** joint à cette release contient les empreintes des deux distributions Windows. Les archives de code source générées par GitHub ne figurent pas dans ce fichier.

### Informations importantes

- Les exécutables ne sont pas signés numériquement : Windows SmartScreen peut afficher un avertissement.
- Le détourage par IA locale n'est pas inclus dans les distributions Windows, mais le détourage par couleur de fond reste disponible.
- La documentation complète est disponible dans le [README](https://github.com/AoHaneX/manta-layers#readme) et le [guide d'utilisation](https://github.com/AoHaneX/manta-layers/blob/master/docs/GUIDE.md).
