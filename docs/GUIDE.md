# Guide d'utilisation de Manta Layers

Ce guide détaille les manipulations de l'interface. Pour l'installation et la liste des raccourcis, voir le [README](../README.md).

## Calques

- **Déplacement :** sélectionnez le calque dans l'image, puis faites-le glisser avec le bouton gauche. Les flèches du clavier le déplacent de 1 px, ou de 10 px avec `Maj`. Une série de pressions rapprochées forme une seule étape d'historique.
- **Redimensionnement :** tirez sur les petits carrés cyan aux quatre coins. Pour un réglage précis, modifiez Échelle X et Échelle Y dans le panneau de droite.
- **Rotation :** tirez sur la poignée jaune au-dessus de l'objet, ou réglez l'angle à droite. `Maj` contraint l'angle par pas de 15°.
- **Opacité :** 0 % rend le calque invisible, 100 % le rend opaque.
- **Visibilité :** cliquez sur l'œil à gauche du nom. Son fond est cyan quand le calque est visible, transparent quand il est masqué.
- **Type de calque :** une petite icône, placée entre l'œil et le nom, indique un calque image, texte ou forme.
- **Ordre :**
  - les flèches ↑ et ↓ de la ligne déplacent le calque d'un cran ;
  - la poignée ≡ se fait glisser vers une nouvelle position de la liste.
- **Verrouillage :** cliquez sur le cadenas de la ligne. Le bouton devient bleu. Le calque ne peut alors plus être transformé, modifié, déplacé dans la liste, dupliqué ni supprimé.
- **Symétrie :** un calque peut être retourné horizontalement ou verticalement, sans modifier son image source.
- **Import rapide :** glissez une ou plusieurs images depuis l'Explorateur sur le canvas. Chacune devient un calque.
- **Menu contextuel :** un clic droit sur le canvas permet de copier, couper, coller, verrouiller, retourner, rogner, détourer, enregistrer ou supprimer un calque.

## Sélection multiple, dossiers et fusion

- **Sélection multiple :** cochez la case d'un calque, ou faites `Ctrl` + clic sur son nom.
  - Un clic droit dans le panneau propose, pour les calques cochés, « Créer un dossier de calques », « Fusionner les calques », « Supprimer » et « Créer un modèle ».
  - Un clic droit sur un calque non coché le coche seul.
  - `Suppr` supprime les calques cochés, sauf pendant la saisie d'un texte.
  - Glisser un calque coché sur le canvas déplace toute la sélection.
- **Dossiers :**
  - la flèche ▾/▸ replie ou déplie le dossier ;
  - l'œil masque tout le dossier, sur le canvas comme dans les exports ;
  - un double-clic sur le nom le renomme, et la poignée ≡ le déplace ;
  - glissez un calque sur la moitié basse d'un dossier pour l'y faire entrer, ailleurs pour l'en sortir ;
  - un dossier vidé disparaît.
- **Fusion :** les calques cochés et visibles deviennent un seul calque image, à la place du plus haut. Si des calques non cochés placés entre eux les recouvrent, une confirmation prévient que l'aspect changerait.

## Texte

- **Créer un texte :** utilisez le bouton « Ajouter du texte », ou activez l'outil Texte (`T`) et cliquez sur le canvas à l'endroit où le texte doit commencer. Un double-clic sur un texte existant le rouvre.
  - Un éditeur flottant affiche le résultat en direct : `Ctrl+Entrée` valide, `Échap` annule.
  - La création ou la modification compte pour une seule étape d'historique.
- **Propriétés :** le contenu, la police, la taille, la couleur et le fond se règlent dans « Propriétés du calque », sous l'onglet Calques. Ces champs n'apparaissent que pour un calque texte.
  - Le contenu se saisit dans une zone multiligne, et chaque ligne est conservée au rendu.
  - La couleur des caractères et la couleur de fond ont des contrôles séparés. Le fond est transparent par défaut et épouse le texte.
- **Forme du texte :** choisissez Droit, Arc, U, U inversé ou Courbe personnalisée dans « Forme ».
  - Le curseur règle la courbure de l'arc (de -100 à +100) ou la profondeur des U (de 0 à 100, 100 donnant un demi-cercle).
  - Chaque ligne suit la même trajectoire.
  - « Lettres verticales » garde les caractères droits au lieu de les faire suivre la pente.
- **Poignées de déformation :** un texte sélectionné affiche sa trajectoire en pointillés et ses poignées cyan.
  - L'arc et les U ont une poignée au sommet ; la courbe personnalisée a deux points de contrôle, avec leurs tangentes.
  - Tirer le sommet d'un texte droit le transforme en arc.
  - Le guide n'apparaît jamais dans les exports.
- **Polices :**
  - `Fichier > Importer une police…` copie des fichiers TTF, OTF ou TTC dans `%LOCALAPPDATA%\MantaLayers\fonts`, où elles sont rechargées à chaque lancement.
  - La dernière police choisie devient celle des textes suivants.
  - Les polices ne sont pas intégrées au fichier `.manta`. À l'ouverture d'un projet, Manta Layers signale celles qui manquent et conserve leur nom tant que vous n'en choisissez pas une autre.

## Formes, guides et rognage

- **Formes :** dans l'onglet Outils > Formes, glissez sur le canvas. `Maj` contraint à un carré, un cercle ou un angle de 45°.
  - La couleur de l'onglet Outils sert de remplissage.
  - Les dimensions, le remplissage, le contour, l'épaisseur, l'arrondi et le nombre de côtés se règlent dans les propriétés.
  - Les bulles, pensées et bandeaux se trouvent dans la bibliothèque de modèles.
- **Guides et magnétisme :** pendant un déplacement, des guides cuivrés apparaissent sur les bords et les centres du document et des autres calques, et le calque s'y aimante. `Alt` ignore le magnétisme ; Affichage > Magnétisme des guides le désactive.
- **Rognage :**
  - Édition > Rogner les marges transparentes du calque retire les bords vides sans déplacer l'image ;
  - Édition > Recadrer le document sur son contenu ajuste le document à ses calques.
- **Dimensions du document :** le bouton « Redimensionner le projet » du panneau de gauche, ou un clic sur les dimensions affichées sous le titre, change la largeur et la hauteur.
- **Déposer une image :** une image glissée depuis l'explorateur ouvre la fenêtre « Open image ». « Create new » crée un document transparent aux dimensions exactes de l'image, qui devient « Calque 0 » (les autres images déposées s'y ajoutent en calques centrés) ; si le document actuel a des modifications non enregistrées, elles sont proposées à l'enregistrement d'abord. « Add current » ajoute chaque image en calque centré dans le document actuel, sans changer sa taille. Fermer la fenêtre n'importe rien. Le bouton « Importer des images » ajoute toujours directement des calques.

## Sélections et masques

- **Outils :** Rectangle (`M`), Ellipse, Baguette magique (`W`) et lasso (`L`, libre ou polygonal), dans l'onglet Outils.
  - **Combinaison :** `Maj` ajoute, `Alt` soustrait, `Maj+Alt` garde l'intersection. Le mode par défaut se choisit aussi dans la liste.
  - **Bords :** « Pixel parfait » donne des bords nets pour le pixel art ; sinon, l'adoucissement floute les bords.
  - **Baguette :** sa tolérance va de 0 à 255 sur les canaux R, V, B et alpha. Elle agit sur les pixels contigus ou sur toute l'image, et sur le calque visé ou sur tous les calques.
  - **Baguette sur le calque visé :** elle lit les pixels de l'image elle-même. Sur un calque agrandi ou réduit, elle sélectionne aussi les liserés plus fins qu'un pixel du document, et un clic hors du cadre sélectionne la partie du calque qui dépasse. Cette précision s'applique au calque analysé tant qu'il n'est ni déplacé ni transformé.
  - **Affichage :** « Afficher le masque » voile en rouge les zones non sélectionnées.
  - **Historique :** chaque changement de sélection s'annule.
  - **Fin de la sélection :** passer à un autre outil, désactiver l'outil de sélection ou changer d'onglet retire la sélection et ses pointillés. `Ctrl+Z` la rétablit. Passer d'un outil de sélection à un autre la conserve.
- **Contenu sélectionné :**
  - `Suppr` efface la sélection du calque visé ;
  - `Ctrl+C` et `Ctrl+X` copient ou coupent ses pixels, et un collage revient au même endroit ;
  - `Ctrl+J` et `Ctrl+Maj+J` les copient ou coupent vers un nouveau calque. `Entrée` sur le canvas, comme le bouton « Séparer en nouveau calque », équivaut à `Ctrl+Maj+J` ;
  - `Ctrl` + glisser à l'intérieur de la sélection déplace le contenu.
- **Masque non destructif :** ces opérations passent par le masque du calque, et l'image source n'est jamais modifiée. Le menu Sélection permet de masquer, de révéler ou de supprimer ce masque. Un calque texte reste vectoriel : on peut copier son rendu vers un nouveau calque, mais pas l'effacer au pixel près.

## Couleurs, gomme, crayon et pots de peinture

- **Calque visé :** la gomme, le crayon et les pots agissent sur le calque sélectionné, ou à défaut sur le dernier calque choisi. Un clic d'outil sur le canvas ne change jamais la sélection.
- **Pipette :**
  - Le petit bouton pipette sous chaque aperçu de couleur prélève un pixel du canvas.
  - L'aperçu et les champs HEX, RVB et HSL restent synchronisés, et chacun peut être modifié.
  - Sous la couleur d'un texte, la pipette applique la couleur prélevée au texte sélectionné.
- **Pipette écran :** le bouton « Pipette écran » de l'onglet Outils, ou le menu Outils, prélève une couleur n'importe où sur le bureau, sur un ou plusieurs écrans. L'écran est figé le temps du prélèvement : cliquez, ou appuyez sur `Échap` (ou faites un clic droit) pour annuler.
- **Pots de peinture :** cliquez sur une couleur du calque visé pour la remplacer par la couleur courante.
  - Le pot simple remplit la zone de pixels similaires contigus.
  - Le pot accompagné d'un `+` remplace les pixels similaires partout sur le calque.
  - La tolérance RVB va de 0 à 255 (15 par défaut). Elle ignore les pixels entièrement transparents, y compris ceux déjà gommés.
- **Recolorisation :** « Préserver ombres et reflets » applique la nouvelle teinte en conservant les écarts de luminosité de l'image d'origine. Les contours du pixel art restent nets.
- **Gomme :** activez-la avec `E` ou son icône.
  - **Tailles :** les tailles 1, 2, 4, 8, 16 et 32 px sont exprimées en pixels réels du calque, quel que soit le zoom. Une taille personnalisée va jusqu'à 2048 px, et `[` / `]` changent la taille.
  - **Modes :** le mode Pixel Art efface sans anticrénelage, avec une empreinte carrée ou ronde ; le mode classique utilise une gomme ronde à dureté réglable.
  - **Opacité :** elle s'applique une fois par trait. Un trait à 25 % retire 25 % de l'opacité, même en repassant au même endroit.
  - **Tracé :** `Maj` + clic relie le dernier point en ligne droite.
  - **Historique :** un glissement complet forme une seule étape.
- **Crayon :** activez-le avec `B` ou le bouton « Crayon », sous « Remplissage + ». Il dessine avec la couleur courante de l'onglet Outils.
  - **Réglages :** il reprend ceux de la gomme : tailles de 1 à 32 px en pixels réels du calque (ou personnalisée), mode Pixel Art ou classique, dureté et opacité. `[` / `]` changent la taille.
  - **Ordre :** crayon, gomme et remplissages sont rejoués dans l'ordre où vous les avez faits : un trait de gomme passé sur un trait de crayon l'efface, et inversement.
  - **Tracé :** comme la gomme, `Maj` + clic relie le dernier point en ligne droite, et un glissement forme une seule étape.
- **Non destructif :** les remplissages, remplacements de couleur et traits de gomme ou de crayon sont conservés comme réglages du calque. L'image source intégrée au projet n'est jamais modifiée.

## Supprimer l'arrière-plan

On y accède par le bouton de l'onglet Outils, par le menu Outils ou par un clic droit sur un calque image.

- **Couleur de fond (sans IA) :** idéale pour un fond uni ou un pixel art.
- **IA locale (facultative) :** un modèle U²-Net ou IS-Net s'exécute sur le processeur.
  - Cette méthode est réservée à l'installation de développement : installez `requirements-ai.txt`.
  - Ensuite, « Télécharger un modèle… » propose U²-Net léger (4,6 Mo), toujours après confirmation. Vous pouvez aussi placer un fichier `.onnx` dans `%LOCALAPPDATA%\MantaLayers\models`.
  - La version Windows autonome n'inclut pas cette méthode.
- **Aperçu et résultat :** un aperçu sur damier précède toute application. Le résultat devient un masque du calque, corrigeable avec les sélections, ou un nouveau calque détouré.

Aucune image n'est envoyée sur Internet.

## Modèles, tokens et spritesheets

- **Bibliothèque de modèles :** Insertion > Bibliothèque de modèles (`Ctrl+Maj+B`) insère un modèle au centre, ses calques restant séparés.
  - Renommer, Modifier, Dupliquer et Supprimer gèrent vos modèles. Pendant une modification, « Sauvegarder le projet » enregistre le modèle.
  - Les modèles fournis (bulles, encadrés, bandeaux, étiquettes, cadres, groupes de formes) se dupliquent pour être modifiés.
- **Créer un modèle :**
  - `Fichier > Enregistrer comme modèle…` enregistre le document courant, et `Nouveau projet > Depuis un modèle` le réutilise ;
  - le menu contextuel des calques cochés crée aussi un modèle.

  Chaque modèle contient ses images et sa miniature, et le modèle original reste inchangé.
- **Tokens :** Outils > Créateur de tokens produit un portrait détouré dans un cadre, en PNG transparent ou en nouveau calque.
- **Spritesheets :** Outils > Découper une spritesheet découpe une planche en PNG séparés ou en calques.

## Fichiers, historique et récupération

- **Historique :** dans l'onglet « Historique », cliquez sur une étape pour revenir à cet état. L'historique garde jusqu'à 100 étapes.
- **Enregistrer :** `Ctrl+Maj+S` enregistre le projet `.manta`, que vous pourrez modifier plus tard. `Ctrl+S` exporte l'image finale en PNG, JPEG ou WebP. Le damier du canvas représente la transparence, que le PNG et le WebP conservent.
- **Dossiers mémorisés :** les dossiers d'ouverture, d'import et d'export sont retenus, séparément pour chaque modèle.
- **Récupération de session :** tant que des modifications ne sont pas enregistrées, une copie de travail est écrite chaque minute. Si Manta Layers se ferme de façon imprévue, la copie est proposée au lancement suivant : restaurer, supprimer ou plus tard.

## Espace de travail

- **Panneau d'utilitaires :** le panneau de gauche se replie et se rouvre avec sa languette ou avec `F9`.
- **Zoom et défilement :**
  - la molette zoome de 1 % à 6400 %, de même que `Ctrl++` et `Ctrl+-` ;
  - maintenez le bouton central de la souris pour faire défiler le canvas ;
  - « Cadrer le document » (`Ctrl+0`) recentre la vue.
- **Fenêtres peu hautes :** quand la fenêtre manque de hauteur, les panneaux défilent au lieu de comprimer leurs contrôles.
