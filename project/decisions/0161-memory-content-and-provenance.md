# 0161 — Souvenirs décrits par leur contenu et leur provenance

- Statut : Accepted
- Date : 2026-10-06

## Contrat

Un souvenir possède un titre, un contenu, des mots-clés, une provenance, des dates et des
droits d'accès. Sa nature distingue les souvenirs, documents, pièces jointes, dossiers,
fichiers et répertoires. Les contacts et sujets sont identifiés par leur source canonique.

Le rappel classe les candidats autorisés à partir des preuves lexicales et sémantiques,
du contexte thématique, des relations, des provenances et de la fraîcheur. La diversité
favorise la couverture des termes, identités et faits demandés et limite les répétitions.
Une temporalité explicite garde ses règles de sélection et de priorité.

Les API, outils, acquisitions Dream et formulaires partagent ces mêmes informations.
Les projections métier conservent leur identité de source, leur propriétaire et leurs
protections. Les révisions et reprises conservent le contenu et les effets déjà appliqués.

## Vérification

Les tests d'intégration couvrent le rappel, la temporalité, les révisions, les projections,
la déduplication, les droits et l'isolation des contacts. Les parcours d'interface couvrent
la recherche, l'édition et la navigation dans le graphe sur écran mobile et ordinateur.
DbAdmin fait converger le schéma et les snapshots structurés vers ces contrats.

Le retrait des anciens types ne transforme que les champs système des métadonnées
mémoire, des checkpoints Dream mémoire et des expériences Lab d'extraction mémoire.
Les mots-clés, contenus JSON rédigés, valeurs testées, valeurs par défaut et exemples
des schémas, captures de sources et journaux d'appels conservent leurs données même
lorsqu'ils emploient les mêmes noms de champs.
Le test de migration vérifie cette préservation, le rollback et l'idempotence.
