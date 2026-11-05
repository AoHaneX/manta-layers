# Composants tiers

Le code de Manta Layers est distribué sous licence MIT, et ses illustrations sont réservées (voir [`LICENSE`](LICENSE)).

La version Windows autonome (installeur et archive portable) redistribue en plus les composants ci-dessous, chacun sous sa propre licence.

Les textes complets sont livrés dans le dossier `licenses\` de l'application installée ou décompressée. Ce dossier est construit par `packaging\build.ps1` à partir des paquets réellement embarqués.

| Composant | Version | Licence | Emplacement dans la build | Texte complet |
|---|---|---|---|---|
| Qt (QtCore, QtGui, QtWidgets, QtSvg, QtNetwork, greffons et traductions) | 6.12.0 | GNU LGPL v3 | `_internal\PySide6\Qt6*.dll`, `plugins\`, `translations\` | `licenses\LGPL-3.0.txt`, `licenses\GPL-3.0.txt` |
| PySide6-Essentials, Shiboken6 | 6.12.0 | GNU LGPL v3 | `_internal\PySide6\`, `_internal\shiboken6\` | `licenses\LGPL-3.0.txt`, `licenses\GPL-3.0.txt` |
| Python (interpréteur et bibliothèque standard), avec bzip2, libffi, OpenSSL 3, expat, mpdecimal, zlib… | 3.13 | PSF License Version 2, plus les licences de ces composants | `_internal\python313.dll`, `*.pyd`, `libcrypto-3*.dll`, `libssl-3*.dll`, `libffi-8.dll`, `base_library.zip` | `licenses\Python-LICENSE.txt` |
| Pillow, avec brotli, FreeType, HarfBuzz, Little CMS, libavif, libjpeg-turbo, libpng, libwebp, OpenJPEG, LibTIFF, xz et zlib-ng | 13.0.0 | MIT-CMU, plus les licences de ces bibliothèques | `_internal\PIL\` | `licenses\Pillow-LICENSE.txt` |
| Chargeur de PyInstaller (bootloader) | 6.16.0 | GPL v2 ou ultérieure, avec exception autorisant la distribution de programmes construits | `MantaLayers.exe` | `licenses\PyInstaller-COPYING.txt` |
| Microsoft Visual C++ Runtime | 14.x | Microsoft Distributable Code (termes de licence de Visual Studio) | `_internal\VCRUNTIME140*.dll`, `_internal\PySide6\MSVCP140*.dll` | Conditions rappelées dans `licenses\Python-LICENSE.txt` |

Les versions correspondent à `packaging\requirements-build.txt`. Ce tableau est à mettre à jour avec ce fichier.

## Qt et PySide6 (LGPL v3)

Manta Layers utilise Qt et PySide6 sous les termes de la **GNU Lesser General Public License version 3**. Cette licence complète la GNU GPL version 3, dont le texte est joint lui aussi.

- **Liaison dynamique :** les bibliothèques sont chargées dynamiquement et livrées sans modification, sous forme de fichiers séparés (`_internal\PySide6\*.dll` et `*.pyd`). Vous pouvez les remplacer par une autre version compatible de Qt 6 ou de PySide6, construite par vos soins.
- **Code source :**
  - Qt : <https://download.qt.io/archive/qt/6.12/> et <https://code.qt.io/cgit/qt/>.
  - PySide6 et Shiboken6 : <https://code.qt.io/cgit/pyside/pyside-setup.git/> (étiquette `v6.12.0`) et <https://download.qt.io/official_releases/QtForPython/>.
  - Une copie de ces sources est fournie sur simple demande (voir la page du projet : <https://github.com/AoHaneX/manta-layers>).
- **Composants tiers de Qt :** Qt contient lui-même des composants tiers (par exemple PCRE2, HarfBuzz, FreeType, libpng, libjpeg, double-conversion, md4c). Leur liste et leurs licences sont publiées par le projet Qt : <https://doc.qt.io/qt-6/licenses-used-in-qt.html>.

Qt est une marque déposée de The Qt Company Ltd. Manta Layers n'est ni affilié à The Qt Company ni approuvé par elle.

## Composants non redistribués

- **onnxruntime et numpy** servent au détourage par IA, qui est facultatif. Ils ne sont pas inclus dans la version Windows autonome.
- **Les modèles ONNX** (U²-Net, IS-Net) ne sont jamais livrés. L'utilisateur les télécharge lui-même, après confirmation, depuis leur dépôt d'origine, sous leurs propres licences.
- **Les polices** placées par un développeur dans `fonts\` ne sont pas incluses dans la build.
