# Reprise des qualifications du 15 novembre

Date : 16 novembre 2026.

Cette reprise poursuit les cinq chantiers de l'[index des plans](../plans/README.md),
sans nouveau mécanisme applicatif de supervision. Les diagnostics locaux sont conservés
sous `artifacts/improvement-2026-11-16-continuation/` et dans les campagnes de benchmark.
Les modifications concurrentes du worktree ne sont pas attribuées à ce lot.

## Arrêt physique et nettoyage des SDK

Le scénario ajouté à la qualification des images réelles attend une action locale du SDK,
avant l'accord humain. Il demande deux fois l'arrêt, vérifie la disparition du sous-processus
avant `stopped`, puis transmet un accord tardif et représente le même contexte. Aucun effet
ni réouverture ne doit apparaître. Les modèles, transports et fichiers sont synthétiques ;
les SDK et leurs sous-processus sont réels, isolés sans accès réseau ni secrets applicatifs.

L'image Claude initiale échoue : elle annonce `stopped` alors qu'un sous-processus SDK est
encore vivant. Le bridge possède désormais explicitement le client SDK dans un contexte
asynchrone, dont la sortie attend la déconnexion. La qualification précédente vérifiait
les réponses, outils et permissions, sans exercer cet arrêt physique ; l'ancien test AST
imposant un appel à `query` ne protégeait pas cette garantie. Il est retiré au profit du
scénario exécuté avec le vrai SDK, qui vérifie aussi l'entrée streaming et les permissions.

Un second défaut est reproduit indépendamment : des demandes d'arrêt répétées interrompent
le nettoyage asynchrone déjà engagé. Le test échoue avant correction, car le nettoyage ne
se termine pas. La demande commune est maintenant signalée une seule fois, sur la boucle
de l'acteur. L'attente de collègue et l'arrêt humain utilisent cette même opération.
Les trois variantes couvrent l'arrêt humain, l'attente de collègue et une annulation interne
antérieure du SDK. Son compteur d'annulation ne peut pas remplacer notre propre signal :
une version intermédiaire ainsi implémentée empêchait l'arrêt de Codex et a été écartée.
L'interruption Codex comportait aussi deux RPC successifs, dont l'attente pouvait rester
sans borne devant une permission en attente. Le runtime géré tente désormais une seule
interruption pendant cinq secondes maximum, puis son contexte ferme le client SDK détenu.
La voie non gérée conserve son client partagé. Le scénario bloqué avant cette correction
passe ensuite avec le SDK réel et sans processus restant.

La recherche de variantes a trouvé deux points d'annulation dans le support partagé :
attente des contributions et commande HTTP d'arrêt. Tous deux passent par l'opération
idempotente. L'impact est la fiabilité et la libération de ressources ; aucune vulnérabilité
d'autorisation ni accélération globale n'est déduite de ces observations.

## Réussite des missions et coût

La campagne appariée compare les prompts complets figés avant/après sur les mêmes entrées,
outils, réponses synthétiques, références, modèle et effort : 120 cas, trois répétitions,
soit 720 épisodes terminés, avec une limite de dépense de 1 USD. Le candidat précise quand
arrêter les lectures devenues suffisantes et remplace une mention obsolète des revues de
Goal par leurs cycles de travail. Les cas, traductions et répétitions restent regroupés
par scénario ; aucun nouvel évaluateur n'est ajouté au chemin utilisateur.

| Mesure | Référence | Candidat |
|---|---:|---:|
| Réussites des oracles synthétiques | 304/360 (84,44 %) | 314/360 (87,22 %) |
| Médiane par épisode | 3,810 s | 3,662 s |
| Coût enregistré | 0,387924 USD | 0,384641 USD |
| Appels d'outils moyens, épisodes mesurables | 1,457 | 1,397 |

Les 48 grappes de scénarios donnent une différence moyenne de 3,30 points, intervalle
bootstrap à 95 % de [0,35 ; 6,77] points. Il y a 22 paires gagnées, 12 perdues et 326
inchangées. Les compteurs d'outils sont disponibles pour 350 épisodes par bras ; les
exceptions de comportement du modèle restent des échecs, jamais des gains d'infrastructure.
Le coût total mesuré est de 0,772565 USD, sans coût inconnu ni arrêt budgétaire.

La revue des échecs relève une tentative de modification de Document dans le cas de lecture
seule du candidat, absente de ce cas dans la référence. La référence échoue également une
fois sur une admission malgré un refus vérifié. Une moyenne meilleure ne compense pas une
nouvelle tentative d'effet interdit : **la consigne expérimentale est retirée**. Ces effets
sont simulés et ne modifient aucune ressource réelle. La terminologie des cycles de Goal
reste corrigée ; aucun gain de cette seule correction documentaire n'est revendiqué.
Les données publiques ont déjà servi à cette analyse et ne constituent pas une réserve
indépendante. L'amélioration de missions métier réelles n'est donc pas déclarée acquise.
Les preuves figées restent sous `artifacts/operating-benchmark.continuation-after-20261116/`.

## Dépendances et limites

- Le modèle d'embeddings sélectionné, Nomic, échoue encore sur un seul texte synthétique.
  Le choix de conserver ce modèle ou de basculer vers Qwen 4B avec réindexation reste en attente ;
  aucun profil ni index applicatif n'est modifié par cette qualification.
- Les quatre sondes réelles de recherche rendent des résultats, mais signalent entre un
  et trois moteurs indisponibles. `make check-search` retourne 2 pour cette dégradation,
  qui n'est pas présentée comme une recette réussie.
- Les essais avec de vrais nouveaux utilisateurs nécessitent encore participants et créneau.
  Les parcours automatisés précédents ne remplacent pas ces observations.
- Les images de qualification ne sont pas des runtimes utilisateurs déployés. La correction
  du template doit être intégrée aux images gérées avant de bénéficier aux exécutions réelles.
  Aucun commit, déploiement ni `make validate` n'est effectué par cette reprise.
