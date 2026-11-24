# 0325 — Index partagé des ressources courantes

## Décision

Dream produit un index des Documents lisibles par leurs extracteurs, des fichiers
documentaires du catalogue ou du stockage natif, du courrier admis et des tâches
métier terminées. Chaque domaine conserve sa ressource et ses droits. Memory
conserve les souvenirs personnels, dont ceux choisis par Dream à partir des
conversations. Les messages de Chat et la voix suivent ce parcours personnel.
La documentation produit conserve son index dédié.

| Table | Responsabilité |
| --- | --- |
| `resource_index_sources` | URI et empreinte courantes, avec un pointeur par source. |
| `resource_index_contents` | Analyse réutilisable pour des octets, une politique et un format compatibles. |
| `resource_index_passages` | Texte, localisateurs de citation, recherche lexicale et vecteurs facultatifs. |
| `resource_index_links` | Relations typées entre deux sources courantes, avec preuves. |

L'index peut proposer un topic existant. Les affectations métier et la synthèse
éditoriale d'un Document restent prioritaires. Le courrier a un espace de déduplication
par compte. Une recherche dans `memory://` rassemble les résultats de Memory et de
l'index courant, et une recherche exacte peut réutiliser les passages déjà extraits.
Les permissions natives s'appliquent avant classement et la source est revalidée
avant exposition. Un lien exige l'accès actuel aux deux pièces.

Les relations de vente utilisent une référence de commande et un émetteur explicites.
Une adresse de client ou de destinataire peut désigner un contact du carnet courant
si elle a une correspondance exacte et unique. Un nom seul reste une mention textuelle.
Ce rapprochement établit ce que déclare la source. La vérification de l'origine et de
l'authenticité d'un document relève du domaine fournisseur.

Les pointeurs deviennent immédiatement inexploitables lorsque leur source change
ou disparaît. Dream peut republier un contenu restauré. La maintenance élimine par
lots les pointeurs obsolètes et les passages devenus orphelins.
