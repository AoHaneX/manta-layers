# Architecture technique de Manta Layers

Note pour les développeurs. L'usage est décrit dans le [README](../README.md).

## Principes

- **Modèle séparé du rendu.** Les modules sans Qt (`model.py`, `textpath.py`, `selection.py`, `background.py`) contiennent les données et les calculs. Ils se testent sans interface. `graphics.py` et `window.py` les traduisent en objets Qt.
- **Rien n'est rasterisé définitivement.** Les images sources ne sont jamais réécrites. Remplissages, traits de gomme, masques de calque et formes de texte restent des réglages, rejoués au rendu.
- **Toute modification passe par `QUndoStack`.** `DocumentCommand` mémorise un instantané du document avant et après. `SelectionCommand` mémorise les masques de sélection compressés en PNG.

## Modules

| Module | Rôle | Dépend de Qt |
|---|---|---|
| `model.py` | `Document`, `Layer`, validation et compatibilité des projets | non |
| `textpath.py` | Géométrie des trajectoires de texte : droit, arc, U, U inversé, Bézier ; poignées | non |
| `selection.py` | Masques de sélection : formes, baguette, combinaisons, adoucissement, masques de calque | non |
| `background.py` | Détourage : couleur de fond (sans IA) et modèles ONNX facultatifs, téléchargement explicite | non |
| `storage.py` | Format `.manta` (ZIP + `manifest.json` + PNG), écriture atomique vérifiée | non |
| `templates.py`, `paths.py` | Bibliothèque de modèles, dossier de données utilisateur | non |
| `graphics.py` | Canvas, item de texte vectoriel, rendu et cache des calques, ponts Pillow ↔ Qt | oui |
| `background_dialog.py` | Aperçu du détourage, calcul en arrière-plan (`QThread`) | oui |
| `window.py` | Fenêtre, outils, propriétés, historique, presse-papiers, récupération de session | oui |
| `dialogs.py`, `widgets.py`, `icons.py`, `theme.py` | Boîtes de dialogue, petits widgets, pictogrammes, charte ReefKit | oui |

## Texte

Un calque texte reste du texte : `text`, police, taille, couleur, et une trajectoire définie par `text_deformation` (la forme), `curve_intensity` et `path_controls`.

- `textpath.sample_path()` renvoie la polyligne de la trajectoire, dans les coordonnées locales de l'item.
- L'arc reprend exactement la courbe des versions précédentes : les anciens projets s'affichent à l'identique.
- Les formes U sont des demi-ellipses (100 = demi-cercle).
- La courbe personnalisée est une Bézier cubique ; ses deux points de contrôle sont exprimés en fractions de la largeur.
- `CurvedTextGraphicItem` place chaque glyphe sur cette polyligne (tangente ou lettres droites). Chaque ligne d'un texte multiligne suit la même forme.
- Le cadre de l'item épouse les glyphes réellement dessinés.
- Les poignées (sommet, ou points de contrôle) sont déplacées en direct ; le relâchement crée une seule commande.
- L'outil Texte et le double-clic ouvrent un éditeur flottant (`InlineTextEditor`) avec aperçu en direct. Ctrl+Entrée valide, Échap annule.

## Sélections et masques de calque

- La sélection est un masque `L` (0 à 255) de la taille du document. Elle est conservée dans la fenêtre, pas dans le projet.
- Le mode **pixel parfait** produit des valeurs 0 ou 255 seulement. Le mode doux sur-échantillonne les ellipses et peut flouter les bords (adoucissement).
- La baguette compare les quatre canaux RGBA à la tolérance près. Un pixel entièrement transparent n'a pas de couleur : une graine transparente sélectionne la transparence, une graine opaque l'ignore.
- `document_mask_to_layer()` reporte un masque du document dans les pixels sources d'un calque, à travers sa transformation (position, échelle, rotation, retournements), avec les mêmes conventions que le rendu Qt.
- **Supprimer, couper, masquer et révéler** modifient le **masque du calque** (`Layer.mask`, une ressource PNG 8 bits). L'image source n'est jamais touchée.
- Copier et couper vers un nouveau calque, ainsi que Ctrl+glisser, créent un calque avec les pixels visibles de la sélection, à leur position.

## Détourage

| Méthode | Dépendances | Usage |
|---|---|---|
| Couleur de fond | aucune | Zone reliée aux bords, de couleur proche de la couleur dominante des bords |
| IA locale | `onnxruntime`, `numpy` (`requirements-ai.txt`) | Modèle U²-Net ou IS-Net `.onnx` exécuté sur le processeur |

- Les modèles se trouvent dans `%LOCALAPPDATA%\MantaLayers\models`.
- Aucun modèle n'est téléchargé sans confirmation explicite (bouton « Télécharger un modèle… », u2netp de 4,6 Mo).
- Le résultat s'applique comme masque du calque, corrigeable ensuite avec les sélections (« masquer » ou « révéler »). Il peut aussi créer un nouveau calque détouré.
- **Limite assumée :** seule la suppression du fond entier est prise en charge. La segmentation d'un objet choisi au clic ne l'est pas, car ces modèles n'acceptent pas de point de référence.

## Historique et sauvegarde

- Les déplacements, redimensionnements, rotations et déformations à la souris forment une commande au relâchement.
- Les flèches du clavier déplacent le calque (Maj : 10 px) ; les pressions rapprochées sont fusionnées par `mergeWith`.
- Le format de projet est en **version 2**. Les versions 1 (dont les anciens `.mcrab`) sont converties à l'ouverture ; une version plus récente est refusée avec un message clair.
- Rendu des calques image : `PIXMAP_CACHE` garde les calques affichés ; `RENDER_CACHE` garde les rendus avant masque, indexés par l'asset et la suite des remplacements, traits et remplissages rejoués. Un nouveau trait ou remplissage repart du plus long préfixe déjà rendu : il ne coûte que lui-même, et son annulation est immédiate.
- La sauvegarde écrit un fichier temporaire, le force sur le disque (`fsync`), le relit (`open_project`), puis remplace l'ancien fichier.
- **Récupération de session :**
  - toutes les 60 s, si le document a des modifications non enregistrées, une copie est écrite dans `%LOCALAPPDATA%\MantaLayers\recovery`, protégée par un `QLockFile` ;
  - au démarrage, les copies dont le verrou est libre (session terminée de façon imprévue) sont proposées à la restauration ;
  - une fermeture normale ou un enregistrement les supprime.

## Tests

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

- `tests/conftest.py` fournit une fenêtre isolée : réglages et dossier de récupération temporaires, plateforme Qt hors écran par défaut.
- Les tests de détourage utilisent des images synthétiques, une fausse session ONNX et un faux téléchargement. Ils ne demandent ni réseau ni modèle.
