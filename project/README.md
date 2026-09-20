# Pilotage du projet Galaris

Ce répertoire contient les artefacts internes qui expliquent ou gouvernent l’évolution du projet,
sans faire partie de la documentation utilisateur, administrateur ou développeur publiée sous
[`docs/`](../docs/README.md).

## Décisions

Les [décisions d’architecture](decisions/README.md) enregistrent les choix structurels acceptés,
leur contexte et leurs conséquences. Elles expliquent pourquoi une frontière existe ; les contrats,
modèles, implémentations et tests restent l’autorité sur le comportement courant.

Les intentions qui ne sont pas encore nécessairement livrées restent dans l’index des
[plans](plans/README.md). Un plan terminé ou remplacé est supprimé : les décisions, contrats,
tests et documents canoniques en conservent la connaissance durable utile.

## Fiabilisation transversale

La [matrice des contrats et preuves](audits/2026-09-19-fiabilisation-transversale.md)
relie les corrections conversationnelles aux garanties de persistance, d'arrêt, de
capacité, de recherche et de ressources à préserver dans les travaux suivants.
