# Journal des versions

Chaque section `## X.Y.Z` devient la partie « Nouveautés » des notes de la release GitHub `vX.Y.Z` (`packaging/reefkit_release.py`).

## Prochaine version

### Distribution Windows
- Les fichiers suivent la convention de release ReefKit, lue par ReefKit Launcher : `MantaLayers-vX.Y.Z-setup.exe`, `MantaLayers-vX.Y.Z-win64.zip` avec `MantaLayers.exe` à la racine de l'archive, `SHA256SUMS.txt` et des notes de version structurées. La release 1.0.0 garde ses fichiers et leurs noms.
- Un tag `vX.Y.Z` construit et vérifie la version sur Windows x64, puis prépare une release brouillon, publiée à la main.

## 1.0.0 — 5 novembre 2026

### Corrections (audit de release)
- Un calque tourné dont la largeur et la hauteur ont des échelles différentes reste un rectangle : il n'est plus affiché ni exporté cisaillé, et effacer, couper ou déplacer une sélection, détourer ou rogner ce calque touche exactement les pixels affichés ; la poignée de redimensionnement garde le coin opposé immobile. Les projets qui contenaient un tel calque l'affichent désormais sans cisaillement.
- Un export d'image qui échoue (disque plein, droits, format) laisse intact le fichier qu'il devait remplacer ; le WebP, limité à 16 383 pixels de côté, est refusé avec un message au lieu de produire un fichier vide. L'export des tokens bénéficie de la même protection.
- Les textes propres à Qt (boutons Oui/Non, Annuler, sélecteur de couleur, « Suppr » dans les menus) sont en français ; la question des modifications non enregistrées propose « Enregistrer », « Ne pas enregistrer » et « Annuler ».
- La liste des calques se reconstruit environ quatre fois plus vite : avec 1 000 calques, une action ne fige plus l'interface pendant 4 à 5 secondes.

### Ajouts
- Un outil Crayon, sous « Remplissage + » dans l'onglet Outils (raccourci `B`), dessine avec la couleur courante, aux tailles et réglages de la gomme (pixel art ou classique, dureté, opacité). Ses traits sont conservés comme ceux de la gomme, sans modifier l'image source, et rejoués dans l'ordre avec gomme et remplissages.
- Un bouton « Redimensionner le projet » dans les utilitaires du panneau de gauche change la largeur et la hauteur du document.

### Distribution Windows
- Version Windows autonome, sans Python à installer : un installeur (`MantaLayers-<version>-Setup.exe`, pour l'utilisateur courant sans droits d'administrateur, ou pour tous les utilisateurs) et une archive portable (`MantaLayers-<version>-Windows-Portable.zip`), construits par `packaging\build.ps1` (PyInstaller et Inno Setup, versions figées). La désinstallation conserve les modèles, polices, journaux et réglages de l'utilisateur.
- Dans cette version autonome, le détourage par IA locale est indiqué comme non inclus, au lieu de proposer une commande `pip` ; la méthode par couleur de fond reste disponible.
- Les licences des composants tiers redistribués (Qt et PySide6 sous LGPL v3, Python, Pillow et ses bibliothèques, chargeur PyInstaller, runtime Microsoft) sont décrites dans `THIRD_PARTY_NOTICES.md` et leurs textes complets livrés dans le dossier `licenses` de l'application.
- L'archive portable utilise des chemins conformes au format ZIP : elle se décompresse correctement hors de Windows.

### Corrections (outils)
- Choisir une couleur en cliquant dans le carré du sélecteur la donne vraiment quand on part du noir (couleur d'un nouveau texte, contour d'une forme) : la luminosité monte au maximum au lieu de rester à zéro, ce qui laissait le texte noir. Le curseur de luminosité permet toujours de revenir au noir.
- La baguette magique appliquée au calque visé lit les pixels de son image, et non plus un rendu à la taille du document : sur un calque réduit ou agrandi, un liseré plus fin qu'un pixel du document se sélectionne et s'efface, et un clic hors du cadre sélectionne la partie du calque qui dépasse. Séparer cette sélection en nouveau calque garde l'échelle, la rotation et les retouches du calque d'origine.
- Quitter les outils de sélection (autre outil, bouton de l'outil, autre onglet) retire la sélection et ses pointillés, au lieu de les laisser affichés ; `Ctrl+Z` la rétablit.
- Le sous-titre et les dimensions du document, dans le panneau de gauche, sont en bleu foncé et restent lisibles sur le haut clair de l'illustration.
- Valider une courbure en attente en cliquant sur un autre calque ne détruit plus la scène pendant qu'elle traite ce clic.
- Les outils appliqués à un calque dont l'image est endommagée (baguette, copie de la sélection, détourage, rognage, recadrage, fusion, tokens, spritesheets) affichent un message ciblé au lieu de l'erreur inattendue ; la baguette « tous les calques » ignore ces calques.
- Passer une forme fermée en ligne ou en flèche lui donne un contour visible.
- La gomme ronde de 1 ou 2 px efface ses pixels (les traits de ce type déjà enregistrés effacent désormais aussi).
- L'export d'un token demande avant de remplacer le fichier dont l'extension a été complétée.
- « Copier » est proposé dans le menu du canvas dès qu'une sélection existe, même sur un calque texte.
- La découpe de spritesheets refuse l'ajout en calques avant d'extraire des sprites qui ne tiendraient pas dans le projet.

### Corrections (robustesse des données)
- Un projet peut compter jusqu'à 10 000 calques, à l'enregistrement comme à la relecture : une planche découpée en plus de 1 000 sprites s'enregistre et se copie pour la récupération. Au-delà, l'ajout est refusé avec un message, et un projet trop volumineux est refusé avant l'écriture, avec sa raison.
- Copier ou exporter un calque dont l'image est endommagée est refusé, au lieu de produire son hachurage de remplacement ; un calque copié garde ses couleurs exactes.
- Après une restauration, la copie de récupération est réécrite aussitôt : une seconde panne ne fait plus perdre le travail restauré.
- Une copie de récupération impossible à écrire est signalée (une fois par session, puis dans la barre d'état) ; une erreur inattendue reste dans le thread de récupération et n'ouvre plus de boîte de dialogue hors de l'interface.
- La taille des réglages du projet (64 Mo au plus) est vérifiée avant l'écriture.

### Corrections (audit V3)
- Fermer la fenêtre, enregistrer ou exporter valide d'abord ce qui est en cours de saisie (nom, texte, valeurs, texte sur le canvas) : la dernière saisie n'est plus perdue.
- La gomme efface exactement ce que montre son aperçu, y compris la gomme douce et sur un calque retourné ; l'aperçu ne recalcule plus que la zone touchée.
- La fusion ne coupe plus le contour épais des formes à angles aigus.
- Replier un dossier ne désélectionne plus le calque courant ; rétablir une création resélectionne le calque créé.
- Une action impossible à afficher ne vide plus l'historique de rétablissement et ne laisse plus le document « modifié ».
- Annuler un redimensionnement du document restaure toute la sélection.
- « Enregistrer sous » demande avant de remplacer le fichier dont l'extension a été complétée.
- La copie de récupération d'un document abandonné est supprimée ; un projet forgé aux traits de gomme démesurés ne gèle plus l'application.
- Un projet dont une image est endommagée s'ouvre : l'image est hachurée et signalée, le reste reste modifiable.
- Le collage d'une copie revient à son emplacement d'origine même quand Windows notifie le presse-papiers en retard.
- Le texte est placé par caractère perçu : accents décomposés, emoji et drapeaux ne sont plus coupés.
- La pipette et le pot lisent la couleur exacte des pixels semi-transparents.
- Historique : les calques, traits et remplissages inchangés sont partagés entre étapes : la mémoire de l'historique ne grandit plus avec le carré du nombre de traits de gomme.
- Export et vignettes : moins de copies en mémoire, vignettes rendues directement à leur taille.
- `window.py` découpé en modules (fichiers, calques, texte, sélections, couleurs, panneaux), canvas déplacé dans `canvas.py`.

### Nouvelles fonctionnalités
- Sélection multiple de calques par cases à cocher (ou Ctrl+clic) et menu contextuel : créer un dossier, fusionner, supprimer, créer un modèle ; Suppr supprime les calques cochés ; glisser un calque coché déplace toute la sélection.
- Dossiers de calques : repli, renommage, visibilité globale (canvas et exports), déplacement et glisser-déposer des calques ; structure enregistrée (format 3).
- Fusion de calques avec transparence et transformations, et avertissement quand des calques intermédiaires changeraient l'aspect.
- Lasso libre et lasso polygonal.
- La touche Entrée sépare la sélection en nouveau calque (comme le bouton « Séparer en nouveau calque »).
- Rognage des marges transparentes d'un calque sans le déplacer ; recadrage du document sur son contenu.
- Guides d'alignement cuivrés et magnétisme (désactivable, Alt pour l'ignorer).
- Formes vectorielles éditables : rectangle, ellipse, polygone, ligne, flèche, et bulles, pensées et bandeaux.
- Pipette sur tout le bureau, avec loupe d'aperçu, multi-écrans et mise à l'échelle Windows.
- Bibliothèque de modèles d'éléments, modèles fournis (bulles, encadrés, bandeaux, étiquettes, cadres, groupes de formes), modification d'un modèle.
- Créateur de tokens pour jeux de rôle et découpe de spritesheets (PNG ou calques).
- Mémorisation des dossiers d'ouverture, d'import et d'export, séparément pour chaque modèle.
- Texte vectoriel édité directement sur le canvas : outil Texte (`T`), double-clic, aperçu en direct.
- Formes de texte : droit, arc, U, U inversé et courbe de Bézier personnalisée, avec poignées interactives et option « Lettres verticales ».
- Sélections rectangle, ellipse et baguette magique (contigu ou global, tolérance RGBA), avec ajout, soustraction, intersection, mode pixel parfait ou adoucissement, contour et vue du masque.
- Copier, couper, effacer et déplacer le contenu sélectionné via un masque de calque non destructif ; copie et coupe vers un nouveau calque.
- Suppression locale de l'arrière-plan avec aperçu : méthode par couleur de fond sans IA, ou modèle ONNX facultatif téléchargé uniquement après confirmation.
- Déplacement au clavier avec fusion des pressions dans l'historique.
- Récupération de la session après une fermeture imprévue.
- Format de projet version 2 ; la version 1 et les `.mcrab` restent lisibles. Sauvegardes vérifiées par relecture.
- Suite de tests pytest, images synthétiques, sans réseau ni modèle.

### Corrections
- Une image impossible à afficher n'entre plus dans l'historique et ne bloque plus l'interface ; les images de plus de 67 mégapixels sont refusées dès l'import.
- Le zoom n'est plus bloqué sur les très petits ou très grands documents ; plage portée de 1 % à 6400 %.
- L'opacité de la gomme s'applique une fois par trait au lieu de s'additionner à chaque empreinte (aperçu et rendu final).
- Les retours à la ligne du texte sont conservés au rendu ; chaque ligne suit la courbure.
- Le fond et le cadre de sélection d'un texte épousent les lettres au lieu d'être quatre fois trop hauts.
- La courbure réglée au clavier, à la molette ou par clic sur le curseur est enregistrée.
- La pipette fournit la couleur de remplissage : le pot remplace la couleur cliquée par celle-ci, sans blocage « déjà appliquée ».
- Modifier un champ des propriétés n'arrondit plus les autres valeurs (position, échelle, courbure).
- Un calque verrouillé ne peut plus être déplacé dans la liste par glisser-déposer.
- Un remplissage contigu ne traverse plus une zone gommée auparavant ; les anciens projets gardent leur rendu.
- Le chemin du projet ne change qu'après un enregistrement réussi ; une police invalide n'est plus copiée.
- Une simple sélection ne marque plus le document comme modifié.
- L'orientation EXIF des photos est appliquée à l'import ; seuls PNG, JPEG, WebP, BMP et GIF sont décodés, et les assets d'un projet doivent être en PNG ; Pillow 13 est exigé pour ses correctifs de sécurité.
- Un modèle abîmé est signalé au lieu de bloquer la galerie ; le panneau gauche défile sur les écrans peu hauts.
- Fermer le dialogue de détourage n'attend plus la fin du calcul ou du téléchargement ; un échec de téléchargement inattendu n'est plus annoncé comme une installation réussie.
- Une copie de récupération dont les métadonnées manquent est proposée au lieu de rester sur le disque ; les métadonnées sans copie sont nettoyées.
- Quitter un champ X, Y ou rotation qui affiche une valeur bornée ne déplace plus le calque ; plages élargies.
- Annuler ou rétablir pendant un glissement sur le canvas abandonne le glissement au lieu de provoquer une erreur et de bloquer le canvas.
- Au démarrage, chaque copie de récupération est proposée (restaurer, supprimer ou plus tard) : les copies d'autres sessions ne sont plus supprimées sans avoir été montrées.
- Les erreurs inattendues sont enregistrées dans `%LOCALAPPDATA%\MantaLayers\logs` et signalées, même sans console.
- Quitter pendant un détourage par IA attend la fin du calcul au lieu de faire planter l'application.
- Les sprites exportés depuis un calque dont le nom contient `:` ou d'autres caractères interdits (« Token : … ») sont écrits sous un nom valide, au lieu de finir dans un flux NTFS caché.
- La case d'un dossier de calques coche puis décoche ses calques à chaque clic.
- Le lanceur met à jour les bibliothèques quand `requirements.txt` change (correctifs de sécurité de Pillow) ; un Pillow trop ancien est signalé au démarrage.
- La gomme efface le pixel situé sous le pointeur (elle visait le voisin dans sa moitié droite) ; les traits des projets existants gardent leur rendu.
- Un fichier `.manta` ou un modèle compressé autrement qu'en DEFLATE est refusé proprement ; un modèle abîmé ne bloque plus la bibliothèque.
- Exporter « carte.final » écrit « carte.final.png » au lieu d'écraser « carte.png » ; un nom complété déjà présent demande confirmation.
- Renommer, dupliquer ou supprimer un modèle qui a disparu du disque est signalé dans « Nouveau projet ».
- Le cadre « épais » des tokens n'accepte plus une bordure qu'il ne peut pas dessiner ; la bordure maximale suit le cadre et la taille.
- Fermer la pipette écran par Alt+F4 ne la désactive plus jusqu'au redémarrage.
- Le téléchargement d'un modèle d'IA vérifie son empreinte (celle publiée par rembg), sa taille et une adresse HTTPS ; aucun fichier partiel ne reste en cas d'erreur.
- Une image trop grande est refusée avec un message en français ; un document trop grand pour être exporté ne peut plus être créé ni agrandi.
- La miniature d'un modèle est conservée quand il est renommé ou dupliqué ; un modèle aux dimensions invalides n'apparaît plus.
- Le repli d'un dossier n'est plus annulé par Ctrl+Z ; un déplacement de sélection sans pixel n'ajoute plus d'étape vide à l'historique.
- La molette horizontale ne dézoome plus ; le zoom suit l'amplitude de la molette (pavés tactiles) ; le zoom fin de l'aperçu des tokens descend sous 42 %.

### Améliorations
- Rendu des calques image mis en cache : une action ne recalcule plus que les calques modifiés.
- Damier de transparence dessiné par motif, beaucoup plus rapide.
- La gomme et les pots visent le dernier calque sélectionné, même après un clic dans le vide.
- Poignée de rotation à distance constante à l'écran, quels que soient l'échelle et le zoom.
- Polices importées rangées dans le dossier de l'utilisateur ; les polices absentes d'un projet ouvert sont signalées.
- Dimensions du document modifiables dans une seule fenêtre.
- Validation renforcée des fichiers `.manta` corrompus.
- Scripts : vérification de Python 3.11+, mise à jour de pip non bloquante, reprise d'une installation interrompue sous Linux/macOS.
- Les boîtes de dialogue prennent la couleur des panneaux au lieu de celle du système, sur laquelle leurs libellés étaient peu lisibles.
- Rendu incrémental des calques image : un nouveau trait de gomme ou remplissage ne rejoue plus toutes les opérations précédentes (101ᵉ trait sur une image 4000 × 4000 : 0,04 s au lieu de 3,3 s ; annulation immédiate).
- Copie de récupération écrite en arrière-plan : plus de gel de l'interface toutes les minutes sur les gros documents.
- Aperçu du détourage par couleur calculé sur une copie réduite ; empreintes de gomme douce mises en cache.
- Icônes nettes sur les écrans haute densité ; noms accessibles pour les boutons à icône.
- Distribution : dépendance `PySide6-Essentials` au lieu du paquet PySide6 complet ; application lancée sans console (`--console` pour le diagnostic) ; licence MIT pour le code, illustrations réservées (`LICENSE`).
- Outillage : `pyproject.toml` (pytest, ruff, mypy), imports triés.
- Code : `window.py` découpé (`icons.py`, `widgets.py`, `dialogs.py`, `paths.py`), couleurs centralisées dans le thème, code mort retiré, tests de non-régression ajoutés et isolés des réglages de l'utilisateur.
- Remplissages, baguette magique et détourage par couleur environ 70 fois plus rapides (2048² : 3,5 s → 0,05 s) ; le masque de détourage est calculé en arrière-plan avant la fermeture de la fenêtre.
- Lassos et ellipses des grands documents : 112 Mo au lieu de 1,4 Go à 8192² ; tokens de grande taille sans image intermédiaire géante (16 Gio évités).
- Sauvegarde environ 40 fois plus rapide (images PNG rangées sans recompression) ; export sans aller-retour PNG (24 Mpx : 1,8 s → 0,04 s).
- Mémoire : les images et masques plus utilisés sont libérés, les fenêtres d'outils sont détruites après usage, un calque sans retouche n'est plus gardé deux fois en cache.
- Spritesheets : grille limitée à l'image, aperçu réduit aux lignes et confirmation au-delà de 10 000 cases.
- Aperçus des tokens, des sprites et du détourage nets sur les écrans à 150 %.
- Code : récupération de session et export sortis de `window.py` (`recovery.py`, `export.py`), découpe des sprites unifiée, duplications et code mort retirés ; mypy s'exécute sans erreur.
- Tests : vrais glissements à la souris (déplacement, redimensionnement, rotation, gomme, Ctrl+glisser), molette, fichiers, dialogues et mémoire.

## 0.1.0 — 22 octobre 2026

- Création de l'éditeur PySide6 et interface ReefKit.
- Intégration de la raie manta fournie par le projet en logo, icône et projet de démonstration.
- Ajout/import de calques image, calques texte, visibilité, ordre, verrouillage et opacité.
- Déplacement, échelle via quatre poignées et propriétés, rotation via poignée et propriétés.
- Historique de modifications par `QUndoStack` et `QUndoCommand`.
- Sauvegarde/chargement d'un projet natif `.manta`.
- Export composite PNG, JPEG et WebP.
- Scripts de lancement/install Windows et suite de tests de base.
- Commandes d'ordre et verrouillage accessibles sur chaque ligne de calque.
- Suppression directe du calque sélectionné avec Suppr ou Retour arrière.
- Onglets Calques et Historique regroupés dans le panneau latéral.
- Rafraîchissement complet du canvas pendant les transformations pour supprimer les traînées de poignées.
- Renommage de l'application en Manta Layers, avec lecture conservée des anciens projets.
- Import rapide par glisser-déposer d'une ou plusieurs images directement sur le canvas.
- Utilisation de la mascotte PNG originale comme icône de fenêtre et de barre des tâches.
- Application de la charte ReefKit v0.1 avec palette et composants centralisés dans un thème QSS.
- Ajout d'états visuels cohérents pour le survol, l'appui, le focus clavier et la désactivation.
- Distinction visuelle de l'import principal et de la suppression destructive.
- Allègement des fonds derrière les textes et correction de la lisibilité des commandes de calque.
- Ajout de l'onglet Outils avec ajout de texte, pipette, lecture hexadécimale et palette ReefKit.
- Ajout du remplacement non destructif de tous les pixels partageant une couleur exacte.
- Mise en couleur de la boîte de fermeture : enregistrer en cyan et ignorer en rouge.
- Maintien d'un cadenas bleu nuit lisible sur le fond cyan de l'état verrouillé.
- Regroupement de la couleur dans un éditeur synchronisé avec aperçu et champs HEX, RVB et HSL modifiables.
- Génération automatique de neuf variations par pas de 10 %, du plus foncé au plus clair.
- Ajout du défilement vertical global du panneau droit pour les fenêtres de faible hauteur.
- Stabilisation des lignes de calque pour empêcher le chevauchement entre type, nom et actions.
- Ouverture du sélecteur de couleur par clic direct sur l'aperçu coloré.
- Renforcement explicite des couleurs Enregistrer cyan et Ignorer rouge dans la boîte de fermeture.
- Ajout d'une poignée ≡ permettant de réordonner les calques par glisser-déposer, avec annulation dans l'historique.
- Application directe du cyan et du rouge aux boutons Save et Discard pour contourner le style natif de la boîte Windows.
- Ajout du menu contextuel bleu du canvas avec copier, couper, coller, verrouiller, retourner et supprimer.
- Prise en charge de Ctrl+C, Ctrl+X et Ctrl+V pour les calques image et les images du presse-papiers système.
- Ajout des retournements horizontal et vertical non destructifs.
- Affichage des propriétés de texte uniquement pour les calques texte.
- Affichage des propriétés du calque uniquement dans l'onglet Calques.
- Ajout de Dupliquer au menu contextuel du canvas.
- Ajout d'un aperçu rectangulaire cliquable pour la couleur du texte.
- Import permanent de polices TTF, OTF et TTC depuis le menu Fichier.
- Simplification des libellés et suppression des blocs d'aide de l'interface.
- Ajout d'un panneau d'outils gauche repliable, avec languette persistante et raccourci F9.
- Correction du repli du panneau gauche : masquage complet, canvas redimensionné et languette indépendante de 30 px.
- Suppression de la barre de la languette : la flèche flotte désormais directement sur le bord du canvas.
- Passage de la languette de repli au cyan de l'action principale.
- Dimensions du document cliquables et redimensionnement annulable de la zone de travail et de l'export final.
- Remplacement de la case de visibilité par un bouton œil coloré selon son état.
- Ajout de pictogrammes image et T alignés entre la visibilité et le nom des calques.
- Passage du format de projet à `.manta`, avec ouverture conservée des anciens `.mcrab`.
- Ctrl+S dédié à l'image finale PNG et sauvegarde du projet séparée dans le menu Fichier.
- Export individuel d'un calque image depuis le menu contextuel.
- Remplacement de Nouveau document par Nouveau projet avec largeur, hauteur et fond regroupés dans une seule fenêtre.
- Ajout d'une pipette compacte sous chaque aperçu de couleur, y compris pour la couleur des calques texte.
- Ajout d'un pot de peinture pour remplir une zone contiguë de couleur exacte.
- Ajout d'un pot `+` pour remplacer une couleur exacte partout sur le calque image.
- Conservation non destructive des remplissages dans le projet et prise en charge par l'historique Annuler/Rétablir.
- Ajout d'une tolérance RVB de 0 à 255 aux pots de peinture, avec une valeur initiale de 15.
- Préservation explicite des pixels transparents et des zones séparées en mode contigu.
- Ajout d'une recolorisation intelligente conservant les ombres, nuances et reflets d'origine.
- Accélération de la sélection des couleurs similaires au moyen de masques Pillow traités par image.
- Ajout de la gomme non destructive avec raccourci E et aperçu à la taille réelle sur le canvas.
- Tailles de gomme 1, 2, 4, 8, 16 et 32 px, taille personnalisée, formes carrée et circulaire.
- Modes Pixel Art net et classique rond avec dureté et opacité réglables.
- Interpolation des déplacements rapides, Maj + clic en ligne droite et réglage de taille avec [ et ].
- Un trait complet de gomme correspond à une seule commande d'historique et reste sérialisé dans le projet `.manta`.
- Affichage en temps réel de la transparence produite par la gomme pendant le déplacement.
- Séparation contextuelle des options : tolérance/recolorisation pour les seaux, réglages de brosse pour la gomme.
- Passage du texte nouvellement créé au noir par défaut et ajout d'une zone d'édition multiligne défilable.
- Séparation des propriétés Couleur du texte et Couleur de fond, avec fond transparent réversible.
- Ajout du texte éditable sur trajectoire, avec une courbure unique signée de -100 (vers le bas) à +100 (vers le haut) ; les anciens modes arcs, U et vague sont convertis automatiquement.
- Réglages non destructifs d'intensité, d'espacement, d'alignement et d'orientation des caractères.
- Ajout d'une courbe guide pointillée et d'une poignée cyan manipulable directement sur le canvas.
- Regroupement d'un glissement complet de poignée en une seule commande Annuler/Rétablir.
- Conservation des trajectoires dans les projets `.manta` et utilisation du même rendu pour le canvas et l'export.
- Préparation du modèle pour une future déformation Warp sans rasterisation du texte.
- Bibliothèque locale de modèles : enregistrement, galerie avec miniatures, renommage, duplication, suppression et création d'un projet depuis un modèle.

## Prévu ensuite

- Déformation Warp non destructive des formes de lettres.
- Recadrage, filtres, masques et optimisation des performances.
