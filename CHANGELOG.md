# Journal des versions

## Non publié

### Nouvelles fonctionnalités
- Texte vectoriel édité directement sur le canvas : outil Texte (`T`), double-clic, aperçu en direct.
- Formes de texte : droit, arc, U, U inversé et courbe de Bézier personnalisée, avec poignées interactives et option « Lettres verticales ».
- Sélections rectangle, ellipse et baguette magique (contigu ou global, tolérance RGBA), avec ajout, soustraction, intersection, mode pixel parfait ou adoucissement, contour et vue du masque.
- Copier, couper, effacer et déplacer le contenu sélectionné via un masque de calque non destructif ; copie et coupe vers un nouveau calque.
- Suppression locale de l'arrière-plan avec aperçu : méthode par couleur de fond sans IA, ou modèle ONNX facultatif téléchargé uniquement après confirmation.
- Déplacement au clavier avec fusion des pressions dans l'historique.
- Récupération de la session après une fermeture imprévue.
- Format de projet version 2 ; la version 1 et les `.mcrab` restent lisibles. Sauvegardes vérifiées par relecture.
- Suite de tests pytest : 168 tests, images synthétiques, sans réseau ni modèle.

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

### Améliorations
- Rendu des calques image mis en cache : une action ne recalcule plus que les calques modifiés.
- Damier de transparence dessiné par motif, beaucoup plus rapide.
- La gomme et les pots visent le dernier calque sélectionné, même après un clic dans le vide.
- Poignée de rotation à distance constante à l'écran, quels que soient l'échelle et le zoom.
- Polices importées rangées dans le dossier de l'utilisateur ; les polices absentes d'un projet ouvert sont signalées.
- Dimensions du document modifiables dans une seule fenêtre.
- Validation renforcée des fichiers `.manta` corrompus.
- Scripts : vérification de Python 3.11+, mise à jour de pip non bloquante, reprise d'une installation interrompue sous Linux/macOS.
- Code : `window.py` découpé (`icons.py`, `widgets.py`, `dialogs.py`, `paths.py`), couleurs centralisées dans le thème, code mort retiré, tests de non-régression ajoutés et isolés des réglages de l'utilisateur.

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
