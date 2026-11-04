# Manta Layers — v0.1.0

**Éditeur d'images à calques pour Windows, dans l'univers Blue Shrimp / ReefKit.**

La raie manta bleue fournie pour le projet est intégrée telle quelle en tant que **mascotte, logo provisoire et illustration**, sans remplacement du dessin. Les fichiers `assets/manta.png`, `assets/manta_icon.png` et `assets/manta.ico` sont dans le dossier livré.

## Démarrage rapide sur Windows

1. Décompressez **entièrement** le ZIP dans un dossier où vous avez le droit d'écrire (par exemple `Documents\MantaLayers`). Ne lancez pas le `.bat` depuis l'aperçu de l'archive.
2. Installez **Python 3.11 ou plus récent**, si ce n'est pas déjà fait, depuis [python.org](https://www.python.org/downloads/windows/). Pendant l'installation, cochez l'option **Add Python to PATH**. Une version récente de Python prise en charge par PySide6 est conseillée.
3. Double-cliquez sur **`lancer_manta_layers.bat`**. Au premier démarrage, le script crée `.venv`, télécharge les dépendances nécessaires puis démarre l'application. **Connexion internet requise une seule fois pour ces bibliothèques**.
4. Au démarrage, le document exemple contient ta raie manta sur un calque éditable. Utilise **Fichier > Nouveau projet** pour choisir dans une seule fenêtre la largeur, la hauteur et le fond d'un canvas vide.

L'application s'ouvre sans fenêtre de console. Les erreurs inattendues sont signalées et enregistrées dans `%LOCALAPPDATA%\MantaLayers\logs\manta.log` (plantages : `crash.log`) ; pour les voir en direct, lancez `lancer_manta_layers.bat --console` depuis un terminal. Le lanceur met à jour les bibliothèques quand `requirements.txt` change. Pour refaire l'installation à la main, lancez `installer_dependances.bat`. Les dépendances se trouvent **uniquement dans `.venv`**, sans modifier l'installation Python globale.

### Linux / macOS (développement)

Le script `lancer_linux_mac.sh` est fourni à titre expérimental (Python 3.11 ou plus récent requis ; lancer avec `bash lancer_linux_mac.sh`). Cible principale : Windows 11.

## Fonctionnalités implémentées

| Fonctionnalité | État |
|---|---|
| Création de projet aux dimensions souhaitées, fond transparent/blanc/noir | ✅ |
| Import PNG, JPG/JPEG, WebP, BMP et GIF fixe (première image), jusqu'à 67 mégapixels par image (8192 × 8192) | ✅ |
| Calques indépendants, sélection, renommage, duplication, suppression | ✅ |
| Réorganisation, masquage, verrouillage, opacité | ✅ |
| Déplacement à la souris, redimensionnement par quatre poignées, rotation par poignée | ✅ |
| Coordonnées, échelles et angles ajustables précisément dans le panneau de propriétés | ✅ |
| Calques de texte multilignes : contenu, police, taille, couleur, fond, rotation | ✅ |
| Annuler/rétablir, onglet Historique des actions (jusqu'à 100) | ✅ |
| Projet modifiable sauvegardé dans un fichier `.manta` (ZIP/JSON + PNG d'origine) | ✅ |
| Modèles locaux réutilisables avec galerie, miniature et ressources intégrées | ✅ |
| Export image composite PNG avec alpha, JPEG sur fond blanc, WebP | ✅ |
| Mascotte et ressources graphiques incluses ; exemple `.manta` | ✅ |
| Texte vectoriel éditable sur le canvas : droit, arc, U, U inversé, courbe de Bézier personnalisée, poignées de déformation | ✅ |
| Sélections rectangle, ellipse et baguette magique ; ajout, soustraction, intersection ; pixel parfait ou adouci | ✅ |
| Copier, couper, effacer et déplacer le contenu sélectionné, via un masque de calque non destructif | ✅ |
| Suppression locale de l'arrière-plan avec aperçu : couleur de fond (sans IA) ou modèle ONNX facultatif | ✅ |
| Restauration de la session après une fermeture imprévue | ✅ |
| Déformation Warp réelle des formes de lettres | **Pas encore** — architecture préparée |
| Pots de peinture, recolorisation et gomme non destructifs | ✅ |
| Sélection multiple de calques (cases à cocher, Ctrl+clic) ; menu : dossier, fusion, suppression, modèle | ✅ |
| Dossiers de calques : repli, renommage, visibilité globale, glisser-déposer | ✅ |
| Fusion de calques (transparence, transformations, avertissement si l'aspect changerait) | ✅ |
| Lasso libre et lasso polygonal | ✅ |
| Rognage des marges transparentes d'un calque ; recadrage du document sur son contenu | ✅ |
| Guides d'alignement et magnétisme pendant le déplacement | ✅ |
| Formes vectorielles : rectangle, ellipse, polygone, ligne, flèche (bulles et bandeaux dans les modèles) | ✅ |
| Pipette sur tout le bureau, même hors de Manta Layers | ✅ |
| Bibliothèque de modèles d'éléments, avec modèles fournis (bulles, encadrés, bandeaux, étiquettes, cadres) | ✅ |
| Créateur de tokens pour jeux de rôle (PNG transparent) | ✅ |
| Découpe de spritesheets en PNG ou en calques | ✅ |
| Mémorisation des dossiers d'enregistrement, par modèle | ✅ |
| Filtres et réglages d'image (luminosité, contraste…) | **Pas encore** |
| Segmentation d'un objet choisi au clic | **Non prise en charge** — seul le fond entier est supprimé |
| Historique conservé après fermeture du logiciel | **Pas encore** — la session est restaurée, pas son historique |
| Installation sous forme de `.exe` autonome | **Pas encore** — lancement `.bat` + Python |

## Manipulation de l'interface

- **Déplacement** : sélectionne le calque dans l'image, puis fais-le glisser avec le bouton gauche.
- **Redimensionnement** : sélectionne le calque ; tire sur les **petits carrés cyan** aux quatre coins. Pour un contrôle plus précis, modifie Échelle X / Y dans le panneau de droite.
- **Rotation** : tire sur la **poignée jaune** située au-dessus de l'objet, ou ajuste l'angle à droite ; **Maj** contraint l'angle par pas de 15°.
- **Panoramique** : maintiens le **bouton central** de la souris et glisse sur le canvas ; **molette** pour zoomer, de 1 % à 6400 % ; bouton « Cadrer le document » pour recentrer.
- **Opacité** : 0 % = invisible, 100 % = opaque.
- **Visibilité** : clique sur l'œil à gauche du nom. Son fond devient cyan lorsque le calque est visible et transparent lorsqu'il est masqué.
- **Type de calque** : une petite image ou un `T`, placé entre l'œil et le nom, identifie respectivement les calques image et texte.
- **Import rapide** : glisse une ou plusieurs images depuis l'Explorateur directement sur le canvas ; un calque est créé pour chaque image.
- **Ordre** : utilise les flèches ↑ et ↓ directement sur la ligne du calque.
- **Ordre manuel** : maintiens la poignée ≡ d'un calque puis fais-la glisser vers sa nouvelle position dans la liste.
- **Sélection multiple** : coche la case d'un calque, ou `Ctrl` + clic sur son nom. Un clic droit dans le panneau propose « Créer un dossier de calques », « Fusionner les calques », « Supprimer » et « Créer un modèle » pour les calques cochés ; un clic droit sur un calque non coché le coche seul. `Suppr` supprime les calques cochés (sauf pendant la saisie d'un texte). Glisser un calque coché sur le canvas déplace toute la sélection.
- **Dossiers** : la flèche ▾/▸ replie ou déplie, l'œil masque tout le dossier (canvas et exports), un double-clic sur le nom le renomme, la poignée ≡ déplace le dossier. Glisse un calque sur la moitié basse d'un dossier pour l'y faire entrer, ailleurs pour l'en sortir. Un dossier vidé disparaît.
- **Fusion** : les calques cochés visibles deviennent un seul calque image, à la place du plus haut. Si des calques non cochés situés entre eux les recouvrent, une confirmation prévient que l'aspect changerait.
- **Formes** : onglet Outils > Formes, glisse sur le canvas (`Maj` : carré, cercle ou angle de 45°). La couleur de l'onglet Outils sert de remplissage ; dimensions, remplissage, contour, épaisseur, arrondi et nombre de côtés se règlent dans les propriétés.
- **Guides et magnétisme** : en déplaçant un calque, des guides cuivrés apparaissent sur les bords et centres du document et des autres calques ; le calque s'y aimante. `Alt` ignore le magnétisme ; Affichage > Magnétisme des guides le désactive.
- **Rognage** : Édition > Rogner les marges transparentes du calque (ou clic droit sur le canvas) ; Édition > Recadrer le document sur son contenu.
- **Pipette écran** : bouton « Pipette écran » de l'onglet Outils ou menu Outils. L'écran est figé le temps du prélèvement : clique n'importe où, `Échap` ou clic droit pour annuler. La couleur va à l'outil actif (couleur des outils, ou couleur du texte si la pipette de texte était active).
- **Modèles** : Insertion > Bibliothèque de modèles (`Ctrl+Maj+B`) insère un modèle au centre, ses calques restant séparés ; Renommer, Modifier (Sauvegarder le projet enregistre alors le modèle), Dupliquer et Supprimer gèrent vos modèles. Les modèles fournis se dupliquent pour être modifiés.
- **Tokens et spritesheets** : menu Outils > Créateur de tokens / Découper une spritesheet.
- **Verrouillage** : clique sur le cadenas de la ligne. Le bouton devient bleu et le calque ne peut plus être transformé, modifié, déplacé dans la liste, dupliqué ou supprimé jusqu'à son déverrouillage.
- **Menu contextuel** : clic droit sur le canvas pour copier, couper, coller, verrouiller, retourner ou supprimer un calque.
- **Symétrie** : retourne un calque image horizontalement ou verticalement sans modifier son fichier source.
- **Propriétés contextuelles** : contenu, police, taille, couleur et édition ne sont affichés que lorsqu'un calque texte est sélectionné.
- **Texte lisible** : les nouveaux calques texte utilisent le noir par défaut. Le contenu se modifie dans une zone multiligne avec curseur et défilement vertical ; chaque ligne est conservée au rendu. La couleur des caractères et la couleur de fond disposent de contrôles séparés, avec un fond transparent par défaut ; le fond épouse le texte.
- **Écrire sur le canvas** : active l'outil Texte (`T`) puis clique où le texte doit commencer, ou double-clique sur un texte existant. Un éditeur flottant affiche le résultat en direct ; `Ctrl+Entrée` valide, `Échap` annule. La création ou la modification compte pour une seule étape d'historique.
- **Forme du texte** : choisis Droit, Arc, U, U inversé ou Courbe personnalisée dans « Forme ». Le curseur règle la courbure de l'arc (-100 à +100) ou la profondeur des U (0 à 100, 100 = demi-cercle) ; chaque ligne suit la même trajectoire. Le réglage au clavier ou à la molette est enregistré après une courte pause, en une seule étape d'historique. « Lettres verticales » garde les caractères droits au lieu de suivre la pente.
- **Poignées de déformation** : sélectionne un texte pour afficher sa trajectoire pointillée et ses poignées cyan : le sommet pour l'arc et les U, deux points de contrôle (avec leurs tangentes) pour la courbe personnalisée. Tirer le sommet d'un texte droit le transforme en arc. Tout le glissement constitue une seule opération dans l'historique ; le guide n'apparaît jamais dans les exports.
- **Sélections** : outils Rectangle (`M`), Ellipse et Baguette magique (`W`) dans l'onglet Outils. `Maj` ajoute, `Alt` soustrait, `Maj+Alt` garde l'intersection ; le mode par défaut se choisit aussi dans la liste. « Pixel parfait » donne des bords nets pour le pixel art, sinon l'adoucissement floute les bords. La baguette a une tolérance de 0 à 255 sur les canaux R, V, B et alpha, en pixels contigus ou sur toute l'image, sur le calque visé ou sur tous les calques. « Afficher le masque » voile en rouge les zones non sélectionnées. Chaque changement de sélection est annulable.
- **Contenu sélectionné** : `Suppr` efface la sélection du calque visé, `Ctrl+C` / `Ctrl+X` copient ou coupent ses pixels (un collage revient au même endroit), `Ctrl+J` / `Ctrl+Maj+J` les copient ou coupent vers un nouveau calque (le bouton « Séparer en nouveau calque » des outils Rectangle, Ellipse et Baguette magique fait la même chose que `Ctrl+Maj+J`), et `Ctrl` + glisser à l'intérieur de la sélection les déplace. Ces opérations passent par le **masque du calque** : l'image source n'est jamais modifiée et le menu Sélection permet de masquer, révéler ou supprimer ce masque. Un calque texte reste vectoriel : on peut copier son rendu vers un nouveau calque, pas l'effacer au pixel près.
- **Supprimer l'arrière-plan** : bouton de l'onglet Outils, menu Outils ou clic droit sur un calque image. La méthode « Couleur de fond » fonctionne sans IA, idéale pour un fond uni ou un pixel art. La méthode « IA locale » utilise un modèle U²-Net exécuté sur le processeur, après installation de `requirements-ai.txt`. Un aperçu sur damier précède toute application ; le résultat devient un masque du calque, corrigeable avec les sélections, ou un nouveau calque détouré. Aucune image n'est envoyée sur Internet et aucun modèle n'est téléchargé sans confirmation.
- **Déplacement au clavier** : les flèches déplacent le calque sélectionné de 1 px (10 px avec `Maj`) ; une série de pressions rapprochées forme une seule étape d'historique.
- **Récupération de session** : tant que des modifications ne sont pas enregistrées, une copie de travail est conservée chaque minute. Si Manta Layers se ferme de façon imprévue, la copie est proposée au lancement suivant.
- **Polices personnalisées** : utilise `Fichier > Importer une police…` pour copier durablement des fichiers TTF, OTF ou TTC dans ton dossier utilisateur (`%LOCALAPPDATA%\MantaLayers\fonts` sous Windows, `~/.local/share/MantaLayers/fonts` ailleurs). Elles sont rechargées aux lancements suivants, de même que les polices placées dans le dossier `fonts` de l'application. Les polices ne sont pas intégrées au fichier `.manta` : à l'ouverture d'un projet, Manta Layers signale celles qui manquent et conserve leur nom tant que tu n'en choisis pas une autre.
- **Modèles** : utilise `Fichier > Enregistrer comme modèle…`, puis `Nouveau projet > Depuis un modèle`. Chaque modèle contient ses images et sa miniature ; les calques instanciés sont verrouillés par défaut et le modèle original reste inchangé.
- **Police mémorisée** : la dernière police choisie devient celle des prochains calques texte, y compris après redémarrage. Une police système de remplacement est utilisée si elle n'est plus disponible.
- **Panneau contextuel** : les propriétés du calque sont visibles uniquement dans l'onglet Calques.
- **Espace de travail** : replie ou rouvre le panneau d'outils gauche avec sa languette ou avec `F9`.
- **Dimensions finales** : clique sur les dimensions affichées sous le titre pour modifier, dans une seule fenêtre, la largeur et la hauteur du document. La zone de travail et l'export utilisent immédiatement ce nouveau format.
- **Pipette et couleur** : le petit bouton pipette placé sous chaque aperçu de couleur permet de prélever directement un pixel d'un calque image du canvas. Dans Outils, la couleur prélevée devient la couleur courante ; l'aperçu et les champs HEX, RVB et HSL restent synchronisés et peuvent tous être modifiés. Sous la couleur d'un texte, la pipette applique le prélèvement au texte sélectionné.
- **Calque visé par les outils** : la gomme et les pots agissent sur le calque sélectionné, ou à défaut sur le dernier calque choisi. Un clic d'outil sur le canvas ne change jamais la sélection.
- **Pots de peinture** : clique sur une couleur du calque visé pour la remplacer par la couleur courante. Le pot simple remplit uniquement la zone de pixels similaires contigus ; le pot accompagné d'un `+` remplace les pixels similaires partout sur le calque. La tolérance RVB est réglable de 0 à 255 (15 par défaut, 0 pour une correspondance exacte) et ignore les pixels entièrement transparents, y compris ceux déjà gommés.
- **Recolorisation intelligente** : l'option « Préserver ombres et reflets » applique la nouvelle teinte tout en conservant les différences de luminosité de l'image d'origine. Les contours du pixel art restent nets, sans anticrénelage ajouté.
- **Modifications non destructives** : les remplissages et remplacements de couleur sont conservés comme réglages du calque, annulables dans l'historique, sans altérer l'image source intégrée au projet.
- **Gomme** : active-la avec `E` ou son icône. Les tailles prédéfinies 1, 2, 4, 8, 16 et 32 px restent exprimées dans les pixels réels du calque, quel que soit le zoom ; une taille personnalisée jusqu'à 2048 px est également disponible.
- **Gomme Pixel Art ou classique** : le mode Pixel Art efface sans anticrénelage avec une empreinte carrée ou circulaire. Le mode classique utilise une gomme ronde avec dureté réglable. Dans les deux modes, l'opacité s'applique une fois par trait : un trait à 25 % retire 25 % de l'opacité, même en repassant au même endroit pendant le glissement. L'effacement est visible en temps réel pendant le glissement ; maintiens le clic pour tracer sans trous, ou utilise Maj + clic pour relier le dernier point en ligne droite.
- **Options contextuelles** : tolérance et recolorisation ne s'affichent que lorsqu'un pot de peinture est actif. Les réglages de taille, forme, mode, dureté et opacité de gomme ne s'affichent que lorsque la gomme est active.
- **Historique de gomme** : un glissement complet correspond à une seule opération Annuler/Rétablir. Les traits restent non destructifs dans le projet `.manta`, respectent le verrouillage et l'export conserve leur transparence.
- **Calque texte** : bouton « Ajouter du texte », puis section « Propriétés du calque » sous l'onglet « Calques ».
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
| Supprimer le calque, ou effacer la sélection si elle existe | `Suppr` |
| Copier le calque image ou la sélection | `Ctrl+C` |
| Couper le calque image ou la sélection | `Ctrl+X` |
| Coller une image du presse-papiers | `Ctrl+V` |
| Cadrer le document | `Ctrl+0` |
| Activer/désactiver la gomme | `E` |
| Réduire/augmenter la gomme | `[` / `]` |
| Outil texte | `T` |
| Valider / annuler l'édition d'un texte | `Ctrl+Entrée` / `Échap` |
| Sélection rectangulaire / baguette magique / lasso | `M` / `W` / `L` |
| Lasso polygonal : fermer / retirer un point / annuler | double-clic ou `Entrée` / `Retour arrière` / `Échap` |
| Bibliothèque de modèles | `Ctrl+Maj+B` |
| Ignorer le magnétisme pendant un déplacement | `Alt` |
| Tout sélectionner / désélectionner / inverser | `Ctrl+A` / `Ctrl+Maj+A` / `Ctrl+Maj+I` |
| Afficher le masque de sélection | `Ctrl+M` |
| Copier / couper la sélection vers un nouveau calque | `Ctrl+J` / `Ctrl+Maj+J` |
| Séparer la sélection en nouveau calque (sur le canvas) | `Entrée` |
| Déplacer le contenu sélectionné | `Ctrl` + glisser |
| Déplacer le calque de 1 px / 10 px | flèches / `Maj` + flèches |

## Architecture du code

```text
MantaLayers/
├── main.py                     # lanceur Python
├── lancer_manta_layers.bat     # lanceur Windows (installe au premier démarrage)
├── installer_dependances.bat   # installation explicite
├── requirements.txt            # PySide6 (modules essentiels) et Pillow
├── requirements-dev.txt        # + pytest, pytest-cov
├── requirements-ai.txt         # facultatif : onnxruntime et numpy pour le détourage IA
├── pyproject.toml              # réglages de pytest, ruff et mypy
├── LICENSE                     # MIT pour le code, illustrations réservées
├── docs/ARCHITECTURE.md        # documentation technique
├── tests_windows.bat           # diagnostic/tests après installation
├── AGENTS.md                   # consignes courtes pour les développements Codex
├── README.md
├── CHANGELOG.md
├── assets/
│   ├── manta.png               # illustration originale PNG RGBA
│   ├── manta_icon.png          # ancienne déclinaison d'icône conservée
│   ├── manta.ico               # icône Windows
│   └── sidebar_ocean.png       # fond du panneau gauche
├── fonts/                      # polices livrées avec l'application (facultatif)
├── app/
│   ├── model.py                # document/calques, pas de dépendance Qt
│   ├── textpath.py             # géométrie des trajectoires de texte (sans Qt)
│   ├── selection.py            # masques de sélection (sans Qt)
│   ├── background.py           # détourage local, IA facultative (sans Qt)
│   ├── background_dialog.py    # aperçu et calcul du détourage
│   ├── storage.py              # format natif de projet .manta
│   ├── templates.py            # bibliothèque locale de modèles
│   ├── paths.py                # dossier de données de l'utilisateur, noms de fichiers valides
│   ├── recovery.py             # copies de récupération de la session
│   ├── export.py               # écriture de l'image finale (PNG, JPEG, WebP)
│   ├── diagnostics.py          # journal des erreurs (logs/manta.log)
│   ├── graphics.py             # rendu des calques, texte vectoriel, gomme, exports
│   ├── canvas.py               # canvas Qt : outils souris et clavier
│   ├── theme.py                # tokens et feuille de style ReefKit centralisés
│   ├── icons.py                # pictogrammes vectoriels
│   ├── widgets.py              # widgets de la liste des calques et du panneau
│   ├── dialogs.py              # nouveau projet et dimensions du document
│   ├── layer_panel.py          # lignes de calques cochables et de dossiers
│   ├── imaging.py              # marges transparentes et spritesheets (sans Qt)
│   ├── shape_item.py           # formes vectorielles : géométrie et rendu
│   ├── shape_panel.py          # propriétés des formes
│   ├── screen_picker.py        # pipette sur tout le bureau
│   ├── builtin_templates.py    # modèles d'éléments fournis
│   ├── template_library.py     # bibliothèque de modèles d'éléments
│   ├── tokens.py, token_dialog.py   # créateur de tokens
│   ├── sprite_dialog.py        # découpe de spritesheets
│   ├── window.py               # fenêtre principale, propriétés, historique
│   ├── commands.py             # étapes de l'historique (annuler/rétablir)
│   ├── window_panels.py        # construction des panneaux et des menus
│   ├── file_flows.py           # nouveau, ouvrir, enregistrer, exporter, récupération
│   ├── layer_flows.py          # panneau des calques, dossiers, fusion
│   ├── text_flows.py           # texte : formes, couleurs, saisie sur le canvas
│   ├── selection_flows.py      # sélections, presse-papiers, masques, recadrage
│   └── color_tools.py          # gomme, pipette, pot de peinture, couleurs
├── exemples/
│   └── Manta_Demo.manta        # projet modifiable avec la mascotte
└── tests/
    ├── conftest.py             # fenêtre isolée (réglages et récupération temporaires)
    ├── test_model.py, test_templates.py, test_history_save.py   # modèle, formats, historique, récupération
    ├── test_textpath.py, test_text_editing.py                  # courbes et édition du texte
    ├── test_selection.py, test_selection_tools.py              # masques et outils de sélection
    ├── test_background.py, test_background_ui.py               # détourage (images synthétiques, sans modèle)
    ├── test_color_fill.py, test_edge_cases.py                  # pots, gomme, cas limites
    ├── test_folders.py, test_layer_panel.py                    # dossiers, sélection multiple, fusion
    ├── test_lasso_trim.py, test_shapes_guides.py               # lassos, rognage, formes, guides
    ├── test_screen_picker.py, test_templates_tools.py          # pipette écran, modèles, tokens, sprites
    ├── test_pending_edits.py, test_preview_parity.py           # saisies en cours, aperçu de la gomme
    ├── test_audit_fixes.py, test_export.py                     # corrections de l'audit V3, export
    └── test_gui_smoke.py                                       # intégration Qt
```

**Choix architecturaux :** modèle `Document`/`Layer` isolé de Qt ; affichage `QGraphicsScene` ; chaque modification validée crée un `QUndoCommand` dans `QUndoStack` ; historique de snapshots du modèle dont les calques inchangés sont partagés d'une étape à l'autre ; rendu des calques image mis en cache, si bien qu'une action ne recalcule que les calques modifiés, et rendu incrémental : un nouveau trait ou remplissage repart du rendu précédent ; une action dont le rendu échoue est annoncée et n'entre pas dans l'historique ; export via scène temporaire sans handles ni rectangles de sélection ; fichiers projet en ZIP avec manifeste JSON et les images PNG sources.

Les modèles et les polices importées sont rangés dans le dossier de données de l'utilisateur (`%LOCALAPPDATA%\MantaLayers` sous Windows), jamais dans le dossier de l'application.

L'interface applique la charte ReefKit commune : palette bleu nuit/cyan, composants légers sans aplats derrière les libellés, focus clavier visible, action d'import principale et suppression clairement signalée comme destructive. Les valeurs partagées sont regroupées dans `app/theme.py`.

Le panneau droit conserve la taille utile de ses onglets et de ses champs. Lorsque la fenêtre manque de hauteur, une barre de défilement verticale permet d'atteindre les propriétés sans comprimer ni superposer les contrôles.

**Format `.manta` (versions 2 et 3) :** un projet qui utilise des dossiers ou des formes est enregistré en version 3 ; les autres restent en version 2, lisibles par les versions précédentes de Manta Layers. ouvre-le avec 7-Zip pour consulter `manifest.json` et `assets/*.png`. Les images originales restent présentes ; position, rotation, échelle, formes de texte et masques de calque sont conservés séparément. Les projets en version 1 et les anciens fichiers `.mcrab` restent lisibles et sont enregistrés en version 2 lors de leur prochaine sauvegarde. Chaque sauvegarde est écrite dans un fichier temporaire, vérifiée par relecture, puis remplace l'ancien fichier.

Pour le détail technique (modules, rendu du texte, masques, détourage, historique), voir [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tests

Une fois les dépendances installées, ouvre un terminal dans ce dossier et exécute (ou double-clique sur `tests_windows.bat`) :

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

Contrôles statiques (facultatifs, configurés dans `pyproject.toml`) : `ruff check app tests` et `mypy app`.
Couverture des tests : `.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing` (`pytest-cov` fait partie de `requirements-dev.txt`).

Les tests utilisent des images synthétiques : ils ne demandent ni réseau ni modèle d'IA.

### Détourage par IA (facultatif)

```bat
.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

Ensuite, dans la fenêtre « Supprimer l'arrière-plan », utilise « Télécharger un modèle… » (U²-Net léger, 4,6 Mo, après confirmation) ou place un fichier `.onnx` de la famille U²-Net / IS-Net dans `%LOCALAPPDATA%\MantaLayers\models`.

Avant toute modification majeure : création d'un projet vide, import de 3 images, déplacement, redimensionnement, annuler/rétablir, duplication, fermeture/réouverture d'un `.manta`, export PNG/WebP/JPEG.

## Limites connues de cette V0.1

- La déformation par enveloppe Warp des formes de lettres n'est pas encore implémentée ; le texte suit une trajectoire, ses glyphes ne sont pas déformés.
- La sélection n'est pas enregistrée dans le projet. Effacer au pixel près n'est possible que sur les calques image : un texte reste vectoriel.
- Le détourage supprime le fond entier ; il ne segmente pas un objet choisi au clic. L'IA dépend de dépendances facultatives et d'un modèle présent sur le disque.
- Les changements de sélection comptent dans l'historique (ils s'annulent comme les autres actions), mais une simple sélection ne marque pas le document comme modifié.
- L'historique est limité à 100 commandes et **n'est pas sérialisé** dans `.manta`.
- Les commandes mémorisent des snapshots du modèle ; les calques, traits et remplissages inchangés y sont partagés.
- Le redimensionnement du document change la zone de travail sans déplacer les calques ; le document peut être recadré sur son contenu, mais pas encore librement. Pas de filtres, de calques de réglage ni de PSD.
- Un document est limité à 120 millions de pixels pour rester exportable : les fenêtres Nouveau projet et Dimensions refusent davantage (un ancien projet plus grand s'ouvre toujours, sans pouvoir être exporté).
- Images limitées à 67 mégapixels par calque ; le premier affichage d'une très grande image reste lent (pas de cache de tuiles).
- Les polices ne sont pas intégrées aux projets `.manta`.
- La présentation du canvas n'effectue pas d'anti-aliasing des images pour préserver le pixel-art ; le rendu de texte dépend des polices installées.
- L'application a été conçue pour Windows mais cette archive **ne contient pas de binaire `.exe` autonome**.

## Pour développer la suite

1. Dossiers imbriqués et réglages d'image non destructifs.
2. Ajouter l'**enveloppe Warp** des glyphes (champ réservé `text_warp`).
3. Ajouter le recadrage libre et des réglages d'image non destructifs.
4. Quand les fonctionnalités sont stables, envisager **PyInstaller** et intégration dans le launcher ReefKit.

## Licence et ressources

Le **code source** est distribué sous la licence MIT. Le fichier [`LICENSE`](LICENSE) précise aussi ce qu'elle ne couvre pas.

Les **illustrations, mascottes, logos, icônes et fonds propres à Manta Layers et ReefKit** (dossier `assets/`), ainsi que le projet d'exemple `exemples/Manta_Demo.manta`, sont exclus de la licence MIT : tous droits réservés, comme l'indique [`LICENSE`](LICENSE). Leur présence dans ce dépôt ou dans une version distribuée n'accorde pas d'autorisation de les réutiliser, modifier ou redistribuer. Toute réutilisation nécessite une autorisation écrite préalable.

Les polices placées dans `fonts/` restent soumises à leurs licences respectives.