# 0076 — Extension des conversions de fichiers pour les aperçus

Statut : accepté

## Décision

Conserver dans `core.preview` uniquement le point d’extension des conversions serveur,
indépendamment de l’affichage historique des pièces jointes, contenus intégrés et miniatures.
La refonte des aperçus et la page de démonstration ont été retirées.

La surface publique expose `PreviewFile`, `PreviewConverter`, `register_preview_converter`
et `prepare_preview`. Un convertisseur est enregistré au bootstrap avec son nom, sa version,
son prédicat MIME/nom de fichier, sa priorité et son contexte asynchrone de conversion.
Le convertisseur compatible de priorité maximale est choisi ; les égalités sont départagées
par ordre alphabétique du nom. Les noms en double sont refusés.

L’appelant autorise et matérialise le fichier avant `prepare_preview`, puis consomme le
résultat dans ce contexte. Le convertisseur préserve l’original, borne ses ressources et
nettoie son dérivé temporaire à la sortie, y compris en cas d’erreur ou d’annulation.
Les erreurs remontent à l’appelant. Sans convertisseur compatible, le fichier original
est retourné tel quel. Le téléchargement continue à utiliser l’original.

## Portée actuelle

Aucun convertisseur concret n’est enregistré et les routes d’aperçu existantes n’appellent
pas encore ce point d’extension. Il n’ajoute ni route, ni cache, ni miniature, ni changement
frontend. C’est une bibliothèque sans capacité à activer dans `back/modules.py`.

Une future intégration pourra convertir un format exotique vers un format déjà pris en charge
par sa visionneuse (image, audio, vidéo, PDF, 3D ou texte), en ajoutant le convertisseur et
son branchement serveur, sans refaire les composants d’affichage.
