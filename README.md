# Manta Layers — v0.1.0

**Éditeur d'images à calques pour Windows, dans l'univers Blue Shrimp / ReefKit.**

La raie manta bleue fournie pour le projet est intégrée telle quelle en tant que **mascotte, logo provisoire et illustration**, sans remplacement du dessin. Les fichiers `assets/manta.png`, `assets/manta_icon.png` et `assets/manta.ico` sont dans le dossier livré.

## Démarrage rapide sur Windows

1. Décompressez **entièrement** le ZIP dans un dossier où vous avez le droit d'écrire (par exemple `Documents\MantaLayers`). Ne lancez pas le `.bat` depuis l'aperçu de l'archive.
2. Installez **Python 3.11 ou plus récent**, si ce n'est pas déjà fait, depuis [python.org](https://www.python.org/downloads/windows/). Pendant l'installation, cochez l'option **Add Python to PATH**. Une version récente de Python prise en charge par PySide6 est conseillée.
3. Double-cliquez sur **`lancer_manta_layers.bat`**. Au premier démarrage, le script crée `.venv`, télécharge les dépendances nécessaires puis démarre l'application. **Connexion internet requise une seule fois pour ces bibliothèques**.
4. Au démarrage, le document exemple contient ta raie manta sur un calque éditable. Utilise **Fichier > Nouveau projet** pour choisir dans une seule fenêtre la largeur, la hauteur et le fond d'un canvas vide.

Pour refaire l'installation à la main, lancez `installer_dependances.bat`. Les dépendances se trouvent **uniquement dans `.venv`**, sans modifier l'installation Python globale.

### Linux / macOS (développement)

Le script `lancer_linux_mac.sh` est fourni à titre expérimental. Cible principale : Windows 11.

## Fonctionnalités implémentées

| Fonctionnalité | État |
|---|---|
| Création de projet aux dimensions souhaitées, fond transparent/blanc/noir | ✅ |
| Import PNG, JPG/JPEG, WebP, BMP et GIF fixe (première image) | ✅ |
| Calques indépendants, sélection, renommage, duplication, suppression | ✅ |
| Réorganisation, masquage, verrouillage, opacité | ✅ |
| Déplacement à la souris, redimensionnement par quatre poignées, rotation par poignée | ✅ |
| Coordonnées, échelles et angles ajustables précisément dans le panneau de propriétés | ✅ |
| Calques de texte simples : contenu, police, taille, couleur, rotation | ✅ |
| Annuler/rétablir, onglet Historique des actions (jusqu'à 100) | ✅ |
| Projet modifiable sauvegardé dans un fichier `.manta` (ZIP/JSON + PNG d'origine) | ✅ |
| Export image composite PNG avec alpha, JPEG sur fond blanc, WebP | ✅ |
| Mascotte et ressources graphiques incluses ; exemple `.manta` | ✅ |
| Texte courbé et texte sur trajectoire éditables | ✅ |
| Déformation Warp réelle des formes de lettres | **Pas encore** — architecture préparée |
| Effets colorimétriques, recadrage, masques, IA | **Pas encore** — après V0.1 |
| Historique conservé après fermeture du logiciel | **Pas encore** — historique de session uniquement |
| Installation sous forme de `.exe` autonome | **Pas encore** — lancement `.bat` + Python |

## Manipulation de l'interface

- **Déplacement** : sélectionne le calque dans l'image, puis fais-le glisser avec le bouton gauche.
- **Redimensionnement** : sélectionne le calque ; tire sur les **petits carrés cyan** aux quatre coins. Pour un contrôle plus précis, modifie Échelle X / Y dans le panneau de droite.
- **Rotation** : tire sur la **poignée jaune** située au-dessus de l'objet, ou ajuste l'angle à droite ; **Maj** contraint l'angle par pas de 15°.
- **Panoramique** : maintiens le **bouton central** de la souris et glisse sur le canvas ; **molette** pour zoomer ; bouton « Cadrer le document » pour recentrer.
- **Opacité** : 0 % = invisible, 100 % = opaque.
- **Visibilité** : clique sur l'œil à gauche du nom. Son fond devient cyan lorsque le calque est visible et transparent lorsqu'il est masqué.
- **Type de calque** : une petite image ou un `T`, placé entre l'œil et le nom, identifie respectivement les calques image et texte.
- **Import rapide** : glisse une ou plusieurs images depuis l'Explorateur directement sur le canvas ; un calque est créé pour chaque image.
- **Ordre** : utilise les flèches ↑ et ↓ directement sur la ligne du calque.
- **Ordre manuel** : maintiens la poignée ≡ d'un calque puis fais-la glisser vers sa nouvelle position dans la liste.
- **Verrouillage** : clique sur le cadenas de la ligne. Le bouton devient bleu et le calque ne peut plus être transformé, modifié, dupliqué ou supprimé jusqu'à son déverrouillage.
- **Menu contextuel** : clic droit sur le canvas pour copier, couper, coller, verrouiller, retourner ou supprimer un calque.
- **Symétrie** : retourne un calque image horizontalement ou verticalement sans modifier son fichier source.
- **Propriétés contextuelles** : contenu, police, taille, couleur et édition ne sont affichés que lorsqu'un calque texte est sélectionné.
- **Texte lisible** : les nouveaux calques texte utilisent le noir par défaut. Le contenu se modifie dans une zone multiligne avec curseur et défilement vertical ; la couleur des caractères et la couleur de fond disposent de contrôles séparés, avec un fond transparent par défaut.
- **Texte sur trajectoire** : les calques texte proposent Droit, Arc vers le haut, Arc vers le bas, U, U inversé et Vague. L'intensité, l'espacement, l'alignement et l'orientation des caractères restent modifiables sans rasteriser le texte.
- **Manipulation directe** : sélectionne un texte courbé pour afficher sa trajectoire pointillée et sa poignée cyan. Fais glisser la poignée pour régler la courbure en temps réel ; tout le glissement constitue une seule opération dans l'historique. Le guide peut être masqué et n'apparaît jamais dans les exports.
- **Polices personnalisées** : utilise `Fichier > Importer une police…` pour copier durablement des fichiers TTF, OTF ou TTC dans le dossier `fonts`. Ils sont rechargés aux lancements suivants.
- **Panneau contextuel** : les propriétés du calque sont visibles uniquement dans l'onglet Calques.
- **Espace de travail** : replie ou rouvre le panneau d'outils gauche avec sa languette ou avec `F9`.
- **Dimensions finales** : clique sur les dimensions affichées sous le titre pour modifier la largeur et la hauteur du document. La zone de travail et l'export utilisent immédiatement ce nouveau format.
- **Pipette et couleur** : le petit bouton pipette placé sous chaque aperçu de couleur permet de prélever directement un pixel du canvas. Dans Outils, l'aperçu et les champs HEX, RVB et HSL restent synchronisés et peuvent tous être modifiés ; sous la couleur d'un texte, la pipette applique le prélèvement au texte sélectionné.
- **Pots de peinture** : le pot simple remplit uniquement la zone de pixels similaires contigus ; le pot accompagné d'un `+` remplace les pixels similaires partout sur le calque. La tolérance RVB est réglable de 0 à 255 (15 par défaut, 0 pour une correspondance exacte) et ignore les pixels entièrement transparents.
- **Recolorisation intelligente** : l'option « Préserver ombres et reflets » applique la nouvelle teinte tout en conservant les différences de luminosité de l'image d'origine. Les contours du pixel art restent nets, sans anticrénelage ajouté.
- **Modifications non destructives** : les remplissages et remplacements de couleur sont conservés comme réglages du calque, annulables dans l'historique, sans altérer l'image source intégrée au projet.
- **Gomme** : active-la avec `E` ou son icône. Les tailles prédéfinies 1, 2, 4, 8, 16 et 32 px restent exprimées dans les pixels réels du calque, quel que soit le zoom ; une taille personnalisée jusqu'à 2048 px est également disponible.
- **Gomme Pixel Art ou classique** : le mode Pixel Art efface sans anticrénelage avec une empreinte carrée ou circulaire. Le mode classique utilise une gomme ronde avec dureté et opacité réglables. L'effacement est visible en temps réel pendant le glissement ; maintiens le clic pour tracer sans trous, ou utilise Maj + clic pour relier le dernier point en ligne droite.
- **Options contextuelles** : tolérance et recolorisation ne s'affichent que lorsqu'un pot de peinture est actif. Les réglages de taille, forme, mode, dureté et opacité de gomme ne s'affichent que lorsque la gomme est active.
- **Historique de gomme** : un glissement complet correspond à une seule opération Annuler/Rétablir. Les traits restent non destructifs dans le projet `.manta`, respectent le verrouillage et l'export conserve leur transparence.
- **Calque texte** : bouton « Ajouter du texte », puis onglet « Propriétés ».
- **Historique** : onglet « Historique » ; clique sur une ancienne étape pour revenir à cet état.
- **Fond transparent** : damier visible dans l'éditeur ; export PNG et WebP conservent la transparence.

### Raccourcis

| Action | Raccourci |
|---|---|
| Nouveau | `Ctrl+N` |
| Ouvrir projet | `Ctrl+O` |
| Importer image | `Ctrl+I` |
| Ajouter texte | `Ctrl+T` |
| Sauvegarder l'image finale, PNG par défaut | `Ctrl+S` |
| Sauvegarder le projet `.manta` | `Ctrl+Maj+S` |
| Annuler | `Ctrl+Z` |
| Rétablir | `Ctrl+Y` ou `Ctrl+Maj+Z` |
| Dupliquer le calque | `Ctrl+D` |
| Supprimer le calque | `Suppr` |
| Copier le calque image | `Ctrl+C` |
| Couper le calque image | `Ctrl+X` |
| Coller une image du presse-papiers | `Ctrl+V` |
| Cadrer le document | `Ctrl+0` |
| Activer/désactiver la gomme | `E` |
| Réduire/augmenter la gomme | `[` / `]` |

## Architecture du code

```text
MantaLayers/
├── main.py                     # lanceur Python
├── lancer_manta_layers.bat     # lanceur Windows (installe au premier démarrage)
├── installer_dependances.bat   # installation explicite
├── requirements.txt
├── tests_windows.bat           # diagnostic/tests après installation
├── AGENTS.md                   # consignes courtes pour les développements Codex
├── README.md
├── CHANGELOG.md
├── assets/
│   ├── manta.png               # illustration originale PNG RGBA
│   ├── manta_icon.png          # ancienne déclinaison d'icône conservée
│   └── manta.ico               # icône Windows
├── fonts/                           # polices personnalisées importées
├── app/
│   ├── model.py                # document/calques, pas de dépendance Qt
│   ├── storage.py              # format natif de projet .manta
│   ├── graphics.py             # canvas Qt, transformation et rendu
│   ├── theme.py                # tokens et feuille de style ReefKit centralisés
│   └── window.py               # fenêtre, actions, historique, contrôles
├── exemples/
│   └── Manta_Demo.manta        # projet modifiable avec la mascotte
└── tests/
    ├── test_model.py           # tests du modèle et du format de projet
    ├── test_color_fill.py      # tolérance, zones contiguës, alpha et recolorisation
    └── test_gui_smoke.py       # tests d'intégration GUI Qt (offscreen)
```

**Choix architecturaux :** modèle `Document`/`Layer` isolé de Qt ; affichage `QGraphicsScene` ; chaque modification validée crée un `QUndoCommand` dans `QUndoStack` ; historique de snapshots du modèle (plus facile à comprendre pour cette première version, à remplacer par des commandes ciblées lorsque le volume devient important) ; export via scène temporaire sans handles ni rectangles de sélection ; fichiers projet en ZIP avec manifeste JSON et les images PNG sources.

L'interface applique la charte ReefKit commune : palette bleu nuit/cyan, composants légers sans aplats derrière les libellés, focus clavier visible, action d'import principale et suppression clairement signalée comme destructive. Les valeurs partagées sont regroupées dans `app/theme.py`.

Le panneau droit conserve la taille utile de ses onglets et de ses champs. Lorsque la fenêtre manque de hauteur, une barre de défilement verticale permet d'atteindre les propriétés sans comprimer ni superposer les contrôles.

**Format `.manta` :** ouvre-le avec 7-Zip pour consulter `manifest.json` et `assets/*.png`. Les images originales restent présentes, et la position/rotation/échelle sont conservées séparément. Les anciens fichiers `.mcrab` restent lisibles et sont proposés en `.manta` lors de leur prochaine sauvegarde.

## Tests

Une fois les dépendances installées, ouvre un terminal dans ce dossier et exécute :

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Avant toute modification majeure : création d'un projet vide, import de 3 images, déplacement, redimensionnement, annuler/rétablir, duplication, fermeture/réouverture d'un `.manta`, export PNG/WebP/JPEG.

## Limites connues de cette V0.1

- La déformation par enveloppe Warp des formes de lettres n'est pas encore implémentée ; le modèle prévoit déjà un emplacement distinct pour ce futur moteur.
- L'historique est limité à 100 commandes et **n'est pas sérialisé** dans `.manta`.
- Les commandes mémorisent des snapshots du modèle ; c'est simple pour démarrer, mais à optimiser avant les très gros documents.
- Pas de redimensionnement du canvas après sa création, ni de recadrage, masques, filtres, calques de réglage ou PSD.
- Gestion de très grandes images potentiellement lente (rendu Qt simple, pas de cache de tuiles).
- La présentation du canvas n'effectue pas d'anti-aliasing des images pour préserver le pixel-art ; le rendu de texte dépend des polices installées.
- L'application a été conçue pour Windows mais cette archive **ne contient pas de binaire `.exe` autonome**.

## Pour développer la suite

1. Stabiliser la prise en main : sélection/multisélection, poignées de rotation, tests UI et performances.
2. Ajouter l'**enveloppe Warp**, contrôlée par des points de Bézier.
3. Ajouter recadrage, masques, réglages d'image non destructifs et export calque par calque.
4. Quand les fonctionnalités sont stables, envisager **PyInstaller** et intégration dans le launcher ReefKit.

Les images de mascotte restent les ressources provisoires fournies par le propriétaire du projet ; aucune licence de redistribution distincte n'est présumée.
