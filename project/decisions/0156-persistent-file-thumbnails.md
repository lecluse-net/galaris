# 0156 — Miniatures persistantes préparées par Dream

Statut : accepté. Date : 2026-10-04.

## Décision

Le mécanisme déterministe `memory.file_thumbnails` prépare les miniatures des fichiers
identifiés du catalogue et des pièces jointes documentaires actives. Il réutilise les
leases, reçus et reprises de Dream, sans LLM ni nouvelle file de tâches. File Share
possède la sélection et l'accès aux sources externes derrière son port Dream existant.
Memory possède les pièces jointes et leurs droits. Aucun changement de schéma n'est requis.

Les rendus PNG sont publiés atomiquement sur le stockage durable des miniatures. Une
ouverture HTTP et un traitement Dream utilisent le même dérivé et sérialisent les
productions concurrentes par clé, sans conserver de registre de verrous inactifs.
Une source externe est identifiée par sa version, sa connexion et ses octets ; une
pièce jointe possède une identité immuable. Le cache n'accorde aucun droit : la source
reste contrôlée avant lecture et après rendu. Un reçu de succès peut être rejoué
après une interruption sans recalculer une image déjà enregistrée.

Le navigateur isolé rend les formats 3D autonomes avec Three.js, une limite de
32 millions d'octets, deux millions de sommets, deux rendus simultanés et un contexte
éphémère de trente secondes. Seules les bibliothèques locales sont disponibles ;
les dépendances réseau du modèle sont refusées. La visionneuse interactive existante
reste chargée dans le frontend lorsqu'un utilisateur ouvre le modèle.

## Régression et vérification

La miniature 3D documentaire vivait uniquement dans le composant Vue : sa destruction
perdait l'image et la réouverture recalculait le modèle. Les tests de pixels et de caméra
vérifiaient le rendu pendant une ouverture, sans garantir sa conservation.
Le parcours de réouverture vérifie désormais qu'une image serveur suffit sans endpoint
de téléchargement du modèle. Les tests PostgreSQL vérifient la réutilisation du PNG
produit par Dream, les refus d'accès et la nouvelle génération après modification d'une
source. Les tests Chromium couvrent le rendu isolé et le refus de dépendances externes.
