# Renforcement des preuves de non-régression — 11 septembre 2026

## Périmètre et état initial

Intervention demandée pour renforcer les garde-fous CI, mutations, séquences, interruptions,
couverture, preuves d'incidents et qualifications externes. Le worktree contient des travaux
concurrents ; ils sont conservés. La phase initiale d'implémentation et de validation n'a créé
aucun commit, push, déploiement, message réel ou appel IA payant.

La première suite complète a produit 3 558 succès, deux échecs, un ignoré et 79,63 % de couverture
agrégée. Les échecs préexistants concernent `app/task/live_checkpoint.py`, nouvelle racine de
session autonome, et une annotation différée de `TaskActivitySnapshot` qui empêchait OpenAPI
et donc le contrôle de pagination. La callback a été revue et ajoutée au registre des racines ;
les annotations de la route sont désormais des types disponibles à l'exécution.

## Défaut reproduit dans la preuve du budget

La mutation `task-reservation-ignored` retire les réservations de tokens du calcul d'admission.
Elle a survécu au scénario initial : le budget monétaire refusait la même action et masquait
l'absence du contrôle tokens. Le scénario existant est maintenant paramétré avec budget
monétaire désactivé ou activé. Le cas `tokens-only` détecte la mutation. Cette correction
renforce le test sans modifier la politique budgétaire du produit.

`project/regressions.json` relie cette lacune à son test et sa mutation. Le contrôle lit les
résultats JUnit et la campagne de mutations ; une référence source seule ne suffit pas.

## Garanties ajoutées

- Neuf mutations : transitions invalides, réouverture terminale, budget enfant, double démarrage,
  authentification callback, résultat terminal, déduplication, propriétaire du lease et tokens.
- Plusieurs graines fixes pour les transitions Task et les callbacks Process ; le diagnostic
  conserve la séquence, les identités, les refus et les résultats persistés.
- SIGKILL après commit terminal puis reprise du fan-in ; SIGKILL après effet fournisseur puis
  reprise avec la même clé d'idempotence et un seul effet dans le registre du fournisseur simulé.
- Contrôle négatif réel des deux configurations Playwright : test normal accepté, `test.only`
  rejeté, sans navigateur ni réseau externe nécessaires à cette vérification.
- Planchers de couverture de lignes et branches séparés pour dix domaines de la sélection
  critique ; détection des branches modifiées non couvertes et des domaines absents.
- Rapports backend/navigateur JUnit, Playwright JSON, mutations et preuves de régression.
- Comparateur Lab : budget, répétitions complètes, corpus/juge/version identiques, seuils par
  catégorie et refus des erreurs critiques. Le corpus public existant reste versionné.
- Qualification Matrix : vrais clients/adaptateurs, deux comptes dédiés, réception indépendante
  et octets identiques, conservation des reçus partiels sans relance implicite.

Les nouveaux contrôles ont des cas négatifs : branches manquantes derrière des lignes couvertes,
domaine absent, référence de test ignorée, mutation survivante, corpus ou juge différent,
échec critique noyé dans une bonne moyenne, compte Matrix incorrect, fichier altéré et réponse
perdue après admission. Les tests locaux Matrix remplacent seulement le homeserver HTTP.

## GitLab et limites externes

Sur le dépôt distant audité, l'API a confirmé
`only_allow_merge_if_pipeline_succeeds=false`. `main` permet push et merge aux Maintainers et
interdit le force-push. Le compte connecté est Developer (30).

GitLab valide `.gitlab-ci.yml` sans erreurs ni avertissements. La simulation sur `main` est
refusée par ses permissions ; aucune configuration distante n'a été changée. Le pipeline exige
un runner Shell dédié tagué `galaris-quality`. Un Maintainer doit affecter ce runner, activer
les pipelines réussis obligatoires, refuser les pipelines ignorés et les pushes directs qui
contournent les fusions validées. La qualification de release prépare un bundle sans déploiement.

Les qualifications réelles restent en attente des comptes/destinations dédiés et d'un budget
IA explicite. Aucune réussite locale ne certifie une connexion réelle ni une réception chez
un fournisseur. Le parcours livré couvre Matrix ; les autres protocoles gardent leurs tests
locaux et nécessitent leurs propres comptes et scénarios de réception.

## Validation

Les artefacts sont conservés sous `artifacts/regression-hardening/2026-09-11/`.

| Contrôle exécuté | Résultat |
|---|---|
| Backend complet, JUnit et couverture | 3 610 réussis, un ignoré, huit avertissements ; 79,63 % de la sélection critique agrégée |
| Planchers par domaine | Dix domaines validés, lignes et branches séparées |
| Branches modifiées contre HEAD | Validé ; Git produit le diff sur l'hôte, Python l'analyse dans Docker |
| Mutations | Neuf baselines réussies et neuf défauts détectés, empreintes des sources/tests dans le rapport |
| Registre de régressions | Une lacune de test liée et vérifiée ; neuf mutations détectées ; aucun échec dans le JUnit complet |
| Typage | `make typecheck` réussi ; les cinq scripts livrés également vérifiés séparément avec Pyright strict |
| Lint | `make lint` réussi |
| Collecte Playwright | Tests ordinaires acceptés et `test.only` rejeté par les deux configurations réelles |
| E2E | 63 réussis sur Chromium, Firefox et WebKit, sans retry |
| Composants | 198 réussis et un échec initial de sélecteur Task ; six scénarios Task réussis sur le code actualisé |
| Qualification locale Matrix et portes négatives | 33 réussis, sans accès à un serveur Matrix réel |
| Dernière vérification des portes, dont le diff de couverture | 16 réussis |
| Architecture | Cartographie à jour ; contrôle global bloqué par la parité FR/EN de `features.md`, modifié dans un travail concurrent |
| Formatage global | Deux fichiers préexistants à reformater : `app/task/budget.py` et `app/memory/library_queries.py` ; ils ne sont pas réécrits par cette intervention |
| Diff et shell | `git diff --check` et syntaxe des quatre scripts shell validés |

Le contrôle des branches modifiées a d'abord révélé l'absence de Git dans l'image backend.
`bin/check-coverage.sh` calcule maintenant le diff sur l'hôte, puis le transmet à l'analyseur
conteneurisé, sans ajouter Git au runtime. Un test vérifie les nouvelles lignes et préserve
la distinction avec les branches anciennes non modifiées.

L'échec initial du composant Task provenait de trois éléments `role=status` alors que le
sélecteur en attendait un seul. Le scénario corrigé dans le travail concurrent a été rejoué
avec les cinq autres scénarios du panneau. La suite complète de composants n'est donc pas
présentée comme une exécution finale entièrement verte.

Une exécution backend intermédiaire a chargé l'ancien test du comparateur avant son dernier
durcissement ; elle a été remplacée par l'exécution stabilisée de 3 610 succès. Les résultats
restent des preuves des états testés d'un worktree partagé, pas d'un commit immuable ni d'une
release qualifiée. Les trois répétitions E2E sont configurées en CI ; le passage local ici
consigné exécute chaque scénario une fois par navigateur.
