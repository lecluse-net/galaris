# Rappel vide dans une conversation — 17 septembre 2026

> Version destinée à la publication : seuls les résultats agrégés et les conclusions
> techniques sont conservés. Les requêtes, titres, extraits, identités et références
> individuelles du corpus privé ont été retirés. Les exemples synthétiques actuels
> ne reproduisent pas cette campagne historique.

Statut : **régression v8 reproduite ; correction locale v10 sans seuil de pertinence**.
La production n'a pas été modifiée. Les diagnostics distants ont utilisé des processus
temporaires et des lectures SQL, sans édition de fichier ni mutation de contenu/configuration.

## Constat vérifié

Une conversation présentait `enabled=true`, `count=0`, `retrieved_count=0` et
`error=null` dans ses métadonnées. Aucun brief mémoire ne figurait dans le prompt.
Son identifiant, ses participants, ses horaires et ses messages ne sont pas publiés.

Le rejeu reconstruit la question et les deux messages récents depuis l'appel LLM persisté,
avec l'agent et le contact exacts. Il utilise l'état courant du corpus, pas un snapshot
historique figé. Il reproduit le résultat vide : recherche hybride saine, modèle configuré
`nomic`, couverture **1 145/1 145**, aucun retrait par l'admission finale. La sélection a déjà
éliminé tous les candidats avant cette admission. L'index et les droits ne sont pas la cause
de ce résultat lors du rejeu.

## Cause

La règle v8 estime son bruit de fond avec la médiane des **meilleurs candidats retenus**,
déjà sélectionnés pour leur proximité avec la question. Cette population est biaisée.
La fusion globale/thématique fournit ici 80 candidats vectoriels :

| Mesure | Valeur |
|---|---:|
| Meilleure similarité | 0,749198 |
| Médiane de la sélection | 0,676337 |
| Seuil v8 après marge de 0,10 | **0,776337** |
| Médiane des 1 145 items admissibles | 0,611363 |
| Même règle sur cette population | **0,711363** |

Le seuil v8 dépasse le meilleur candidat, pourtant pertinent. Aucun candidat
lexical ne dépasse non plus le seuil sur cette formulation abrégée : zéro mémoire.

`error=null` signifie ici qu'aucune exception n'est remontée au provider de contexte. Les
métadonnées du brief ne conservent pas assez de diagnostics pour expliquer à elles seules
une abstention ou un repli du moteur. La comparaison des candidats était nécessaire.

## Essai intermédiaire v9 et preuve historique

Le candidat v9 calcule la médiane sur la population vectorielle admissible **avant LIMIT**,
avec un seul score par item. Les mêmes filtres ACL, contact, validité, modèle et génération
s'appliquent. Une CTE SQL partagée réutilise les scores calculés par la recherche exacte ;
aucun nouveau modèle, dictionnaire, appel LLM ou appel supplémentaire d'embedding n'est ajouté.
Le minimum absolu, la marge et les autres règles restent inchangés.

Un test PostgreSQL crée une population dont les meilleurs candidats sont proches entre eux
et le reste distant : v8 rejette même la bonne réponse ; v9 la restitue. Il échoue avant
correction puis passe après. Le rejeu distant du candidat, chargé seulement en mémoire dans
un processus isolé, restitue **quatre candidats**, dont le souvenir pertinent au troisième rang.
Cela rétablit la présence de la preuve utile ; cela ne démontre pas que les quatre résultats
sont tous nécessaires ni que leur ordre est optimal.

## Contrôles de non-régression et limites

Les 78 questions du corpus privé ont été comparées v8/v9 avec un embedding partagé
par paire. Elles sont désormais connues et ne constituent pas un nouveau holdout.

| Série | Première ancre v8 → v9 | Ancre dans les dix premiers v8 → v9 | Négatifs non vides v8 → v9 |
|---|---:|---:|---:|
| Mise au point, 44 positifs + 3 négatifs | 41 → 41 | 42 → 42 | 0 → **1** |
| Ancien holdout, 13 positifs + 5 négatifs | 10 → 10 | 12 → 12 | 0 → 0 |
| Ancienne validation, 10 positifs + 3 négatifs | 9 → 9 | 10 → 10 | 1 → **2** |

La correction conserve les positions des ancres positives mais ajoute deux faux
positifs ; un faux positif antérieur subsiste. Cet essai v9 a été abandonné au
profit du contrat v10, qui privilégie explicitement le rappel.

Six paires de mesures séquentielles sur le round de production, embedding partagé : hors
première paire, médiane totale environ **401 → 442 ms**, recherche des candidats vectoriels
environ **105 → 111 ms**. Le chemin v9 effectue aussi l'hydratation/admission des quatre hits
absents de v8. L'échantillon est petit, sans charge simultanée maîtrisée : il ne qualifie pas
le p95 en charge. Le premier rejeu v9 avec appel fournisseur a duré 858 ms.

Validation locale : test reproduisant le défaut rouge avant correction ; 48 tests ciblés
puis **481 tests du périmètre réussis** (suite courante, incluant d'autres tests ajoutés
simultanément dans le dépôt), typage réussi. Le premier contrôle d'architecture a passé
les vérifications statiques mais sa suite isolée a rencontré un épuisement des pools
réseau Docker. La reprise a ensuite été arrêtée par une cartographie devenue obsolète
pendant des modifications concurrentes hors périmètre (Browser/settings). Le contrôle
global d'architecture n'est donc pas déclaré réussi pour cet état du dépôt. Les fichiers
de ces autres travaux sont préservés.

Les [résultats réduits](2026-09-17-memory-empty-round-results.json) conservent le diagnostic,
les comparaisons agrégées et les médianes, sans observations individuelles.
Ces résultats et ces temps concernent exclusivement l'essai intermédiaire v9.

## Correction retenue : v10 sans seuil

Le rappel classe les candidats lexicaux et vectoriels disponibles puis retourne les meilleurs
jusqu'à la limite demandée. Il n'applique plus de minimum absolu de similarité, de marge au
bruit de fond, de distance maximale au meilleur résultat ni de minimum de couverture lexicale.
Les noms et identifiants en texte libre ne sont plus des filtres éliminatoires. Les titres,
URI et UUID exacts gardent leur priorité ; URI et UUID restent des résolutions exactes.
Les voisins structurels doivent porter des termes de la question, sans minimum de couverture ;
les simples voisins du graphe restent des bonus, pas des candidatures autonomes.

Les contrôles d'accès, contact, validité, révision et génération complète restent applicables,
ainsi que la déduplication conservatrice. Le calcul SQL de médiane du candidat v9 disparaît.
Le modèle configuré est conservé ; aucun appel LLM ou embedding supplémentaire n'est ajouté.
Ce contrat est commun au brief agent et aux recherches Memory/Documents via File Sharing.

Le compromis est explicite : une question sans réponse dans le corpus peut quand même recevoir
des souvenirs proches. L'agent doit apprécier leur utilité ; leur score ou leur présence ne
démontre pas une réponse. Les mesures d'abstention v8/v9 ne qualifient donc pas ce nouveau contrat.

Deux scénarios échouent avant correction : candidats de faible similarité tous éliminés,
et autre entité éliminée malgré sa disponibilité. Les tests vérifient désormais la limite,
la première position de la meilleure réponse, la priorité d'un titre exact et la restitution
de candidats pour un identifiant textuel inconnu. La garantie d'abstention précédente est
remplacée intentionnellement par ce contrat de rappel sans seuil.

### Rejeu local du corpus privé avec le modèle configuré

Les mêmes 78 cas connus ont été rejoués en lecture seule, v8/v10 dans un ordre alterné,
avec un embedding nomic partagé par paire. Aucun accès à la production n'est nécessaire
pour ce rejeu. Les [résultats v10](2026-09-17-memory-topk-results.json) sont distincts de
l'essai intermédiaire v9.

| Série | Première ancre v8 → v10 | Ancre dans les dix premiers v8 → v10 | Négatifs non vides v8 → v10 |
|---|---:|---:|---:|
| Mise au point, 44 positifs + 3 négatifs | 41 → 41 | 42 → 43 | 0 → 3 |
| Ancien holdout, 13 positifs + 5 négatifs | 10 → 10 | 12 → 13 | 0 → 5 |
| Ancienne validation, 10 positifs + 3 négatifs | 9 → 10 | 10 → 10 | 1 → 3 |

Au total : **66/67 ancres positives dans les dix premiers contre 64/67**, et 61/67 au
premier rang contre 60/67. Aucun rang d'ancre positif ne recule dans ce jeu connu. L'ensemble reste une
régression connue, pas une qualification indépendante ni une preuve d'utilité aval.

Les 11 questions sans réponse annotée produisent des candidats, comme le prévoit le
nouveau contrat. Cela ne signifie pas que le corpus répond à ces questions. La médiane
locale de durée totale passe de **295 à 450 ms** ; le rappel restitue davantage d'items
à hydrater et réadmettre. Tous les cas sont hybrides, sans dégradation. Cette mesure
séquentielle avec embeddings partagés ne qualifie ni le coût fournisseur à froid ni le p95
en charge. Le code retire les filtres de pertinence et le calcul de médiane sans ajouter
d'appel fournisseur ; aucune promesse de latence identique n'en découle.

Les 49 tests ciblés passent, dont les faibles similarités, le repli lexical, les droits,
les révisions et la résolution exacte. Les anciennes attentes d'exclusion des correspondances
partielles, d'une salutation et d'un faible candidat sémantique deviennent des garanties
de classement et de restitution ; ce changement de contrat est intentionnel.

La suite élargie Memory, contexte conversationnel, façade agent et File Sharing passe :
**483 tests**, deux avertissements de dépréciation SlowAPI. Le typage des fichiers mémoire
modifiés passe sans erreur. Un premier `make typecheck` complet a réussi ; sa reprise après
retrait des helpers inutilisés est arrêtée par une modification concurrente de
`back/bridge/n8n/client.py:87` (`reportUnnecessaryIsInstance`), hors périmètre de ce correctif.
Ce travail concurrent est préservé. `make architecture-check` s'arrête sur les cartographies
générées devenues obsolètes pendant les travaux Browser/n8n/settings ; la correction mémoire
ne change aucune route, déclaration de module ou dépendance. Les validations globales ne sont
donc pas déclarées vertes sur l'état partagé courant. Aucun `make validate` global de
publication n'est déclaré.

La [décision 0108](../decisions/0108-memory-document-retrieval.md) porte le contrat réalisé.
Le [plan mémoire](../plans/amelioration-globale-memoire.md) conserve les qualifications et extensions restantes.
La correction est conservée dans le dépôt local ; son déploiement reste à effectuer.
