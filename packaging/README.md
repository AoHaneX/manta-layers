# Construire la version Windows

Ce dossier produit les fichiers d'une release, nommés selon la convention de release ReefKit lue par ReefKit Launcher :

- `MantaLayers-vX.Y.Z-setup.exe` est l'installeur Inno Setup. Par défaut, il installe pour l'utilisateur courant, sans droits d'administrateur ; l'installation pour tous les utilisateurs reste possible.
- `MantaLayers-vX.Y.Z-win64.zip` contient le même dossier, avec `MantaLayers.exe` à la racine de l'archive, à décompresser n'importe où.
- `SHA256SUMS.txt` donne l'empreinte SHA-256 des deux fichiers.
- `release-notes.md` est le texte de la release GitHub : la section `## X.Y.Z` du `CHANGELOG.md`, puis les téléchargements, l'installation, les données conservées et la vérification d'intégrité.

La release v1.0.0, publiée avant cette convention, garde ses noms d'origine (`MantaLayers-1.0.0-Setup.exe`, `MantaLayers-1.0.0-Windows-Portable.zip`, avec un dossier `MantaLayers\` dans l'archive).

## Prérequis

- Windows 10 ou 11 64 bits.
- Python 3.13 64 bits, avec le lanceur `py`. Une autre version se choisit avec `-PythonArguments "-3.12"`.
- [Inno Setup 6](https://jrsoftware.org/isdl.php), pour l'installeur seulement. Le script cherche `ISCC.exe` dans le `PATH`, dans `Program Files` et dans `%LOCALAPPDATA%\Programs`.

## Construction

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Pour ne construire que le ZIP, ajoutez `-SkipInstaller`. Avec `-Tag vX.Y.Z`, le script s'arrête si le tag ne correspond pas à la version du code.

Le script :

1. crée `build\venv-release` et y installe les versions exactes de `requirements-build.txt` ;
2. lance PyInstaller avec `MantaLayers.spec` ;
3. copie `LICENSE` et `THIRD_PARTY_NOTICES.md` à côté de l'exe, et `collect_licenses.py` place dans `licenses\` les textes complets des composants embarqués : Python, Pillow, PyInstaller, et les LGPL et GPL v3 de Qt et PySide6 (fichiers de `licenses\` ici) ;
4. produit le ZIP puis l'installeur (Inno Setup 6 est obligatoire, sauf avec `-SkipInstaller`) ;
5. vérifie avec `reefkit_release.py` que `MantaLayers.exe` est à la racine du ZIP et que ses chemins sont portables, puis écrit `dist\release\SHA256SUMS.txt` et `dist\release\release-notes.md` ;
6. lance `MantaLayers.exe` depuis le ZIP extrait, sans Python dans le `PATH` et avec un profil utilisateur temporaire : vos modèles, polices et réglages ne sont pas touchés.

`release.json` décrit l'application pour `reefkit_release.py`, outil commun identique dans chaque dépôt ReefKit.

La version vient de `app/__init__.py`.

Les dossiers `build\` et `dist\` sont ignorés par Git.

## Ce que contient la build

| Élément | Contenu |
|---|---|
| Exécutable | `MantaLayers.exe` sans console, avec icône et informations de version |
| Bibliothèques | Python, PySide6-Essentials, Pillow, et la traduction française de Qt |
| Données | `assets/`, le projet `exemples/Manta_Demo.manta` et `fonts/README.txt` |
| Polices | Aucune police : celles placées dans `fonts/` par un développeur ne sont pas redistribuées |
| Détourage par IA | Exclu (`onnxruntime`, `numpy`) ; l'application l'indique et garde la méthode par couleur de fond |
| `opengl32sw.dll` | Exclu (20 Mo, non utilisé) |

## Données de l'utilisateur

L'application n'écrit jamais dans son dossier d'installation. Le ZIP « portable » partage donc ces emplacements avec la version installée.

- **Fichiers :** `%LOCALAPPDATA%\MantaLayers` contient les modèles, les polices importées, les modèles d'IA, les journaux et les copies de récupération.
- **Réglages :** `HKEY_CURRENT_USER\Software\Blue Shrimp\Manta Layers` contient les dossiers mémorisés et le magnétisme.

La désinstallation conserve ces deux emplacements. Pour tout effacer, supprimez-les à la main.

## Contrôles avant publication

Ces contrôles ont été passés le 2026-11-05 sur la build 0.1.0. Ils sont à refaire pour chaque release.

1. Le ZIP, décompressé dans un dossier contenant des accents et des espaces, se lance sans Python installé.
2. L'installation silencieuse fonctionne :

   ```powershell
   MantaLayers-vX.Y.Z-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="C:\Test é\Manta"
   ```

   Elle crée le raccourci du menu Démarrer et l'entrée « Applications installées ».
3. Réinstaller par-dessus remplace `_internal` sans laisser de fichiers de l'ancienne version.
4. La désinstallation (`unins000.exe /VERYSILENT`) retire le dossier, le raccourci et l'entrée, et laisse `%LOCALAPPDATA%\MantaLayers` intact.
5. Une vérification manuelle reste nécessaire sur un Windows sans Python, par exemple Windows Sandbox.

   L'installeur n'est pas signé : SmartScreen affiche « Windows a protégé votre ordinateur ». Il faut alors cliquer sur « Informations complémentaires », puis « Exécuter quand même ».
