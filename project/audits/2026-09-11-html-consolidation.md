# Consolidation après l'audit des 30 commits — 11 septembre 2026

Suite autorisée de l'[audit du commit 9c59a87a](2026-09-11-last-30-commits.md).
Les changements restent dans le worktree, avec les travaux préexistants conservés.
Aucun commit ni déploiement n'est créé. Le durcissement des aperçus HTML actifs (point 3)
est exclu conformément à la demande. Aucun budget par défaut n'est introduit.

## Corrections et garanties

| Point | Résultat concret |
|---|---|
| 1 — Tests et limites de connexion | Le quota HTTP s'applique aux routes modulaires FastAPI. Tests avec limiteur activé : défaut, deux logins, champs invalides, IP distinctes, en-tête non fiable au niveau ASGI et réouverture de fenêtre. |
| 1 — Généralisation HTML | Le test de messagerie déjà corrigé dans le worktree est conservé. Les uploads exercent le vrai dépôt de fichiers, l'ordre d'insertion, le changement de document, l'annulation et la lecture seule. L'E2E abandonne l'ancienne attente de scripts inline pour le contrat éditorial statique existant. La sonde de restauration utilise du HTML et conserve la comparaison SHA-256 exacte. |
| 1 — Sessions | Le test de préférences vocales emploie une session HTTP distincte par personne, conformément à la révocation des familles de session lors d'un changement de compte. |
| 1 — Skills | Guide runtime Galaris et trois skills de développement actualisés : fragments HTML, profils, blocs et révisions, limites explicites pour les autres formats. L'exemple Lab de suivi Goal indique HTML. |
| 2 — Autorisations | Suites HTTP, MCP, ressources, WebRTC, transports et révocations du travail en cours vérifiées. Le relevé de consommation reprend le périmètre de gestion Task. Les exceptions AST concernant le catalogue minimal et les coroutines audio ont été revues et alignées. |
| 4 — Reprise | Restauration isolée réussie : 24 écritures concurrentes récupérées, aucune écriture acquittée perdue, PostgreSQL/fichiers/clés/ACL contrôlés, 48 secondes. Upgrade depuis HEAD~30, convergence répétée et rollback avec ancien code réussis. |
| 5 — Budgets facultatifs | Panneau de consommation et API protégée : usage enregistré de la lignée, réservations des phases actives, reste disponible et absence de limite explicites. Même comptabilité que l'admission. Aucun changement de valeurs par défaut. |
| 6 — Frontend | L'éditeur HTML devient asynchrone ; chaque build produit une mesure reproductible des imports initiaux JS/CSS. |
| 7 — Lab | Six cas synthétiques versionnés, import HTTP authentifié testé, refus d'écraser un dataset existant, guide de répétition et de revue humaine. Aucun modèle ni fournisseur appelé pour cet import. |

Le quota reste **par IP et endpoint**, en mémoire dans l'unique worker. La sonde ASGI
n'est pas une validation de la configuration proxy : l'accès direct au backend et la confiance
dans les en-têtes transférés restent des propriétés du déploiement.

Le relevé de budget est un instantané à rafraîchir. Les plafonds et restes `null` signifient
« aucune limite ». Les réservations sont des estimations d'admission, pas des plafonds de
facturation fournisseur. Les appels incomplets ou les harnais déclarant partiellement leur
usage empêchent de présenter le montant comme une facture finale.

## Mesure frontend

Comparaison du commit audité et du worktree consolidé, avec le même script
`front/scripts/report-build.mjs` et le manifeste Vite de production :

| Graphe initial JS/CSS | Commit audité | Worktree consolidé | Évolution |
|---|---:|---:|---:|
| Octets bruts | 3 547 837 | 1 898 570 | −46,5 % |
| Octets gzip par fichier | 998 497 | 598 304 | −40,1 % |
| Tous les chunks JS/CSS, bruts | 6 684 878 | 6 746 461 | +0,9 % |

Les imports dynamiques, polices et appels API sont exclus du graphe initial. Le service worker
continue à précacher l'application complète : 8 990,05 Kio dans cette construction, contre
8 929,38 Kio lors de l'audit. Le gain concerne le code requis immédiatement ; il ne signifie
ni une réduction équivalente du téléchargement PWA total ni une mesure de latence utilisateur.
Le worktree contient aussi les changements d'équipes en cours ; ce n'est pas un A/B isolant
une seule ligne. Le gros moteur d'édition est désormais dans son chunk différé.

## Validation

| Vérification | Résultat |
|---|---|
| Backend complet | 3 560 réussis, un ignoré, huit avertissements, en 185 secondes. |
| Contrôles de sécurité ciblés après alignement | 24 réussis, dont refus HTTP et révocation en appel WebRTC. |
| Composants réels Chromium | 196 réussis, sans retry, en 5,8 minutes. |
| E2E Chromium / Firefox / WebKit | 60 autres parcours réussis lors de la suite complète ; scénario HTML corrigé puis réussi sur les trois navigateurs (trois tests, 14 secondes). Les 63 parcours ont ainsi été validés, sans relance des 60 parcours inchangés. |
| Typage strict, unités frontend, traductions | 0 erreur ; 214 tests unitaires ; 5 075 paires anglais/français et messages chinois. |
| Architecture et cartographie | Conformes ; 27 tests d'architecture réussis. Arête publique Chat → Agent alignée avec la revue déjà inscrite dans la décision 0083. |
| Lint backend et frontend | Conformes. |
| Skills | Quatre packages validés avec le validateur de skill-creator. |
| Restauration et upgrade/rollback | Réussis dans des environnements isolés. |
| Diff | `git diff --check` conforme ; changements préexistants préservés. |

## Ce qui requiert encore l'installation réelle

La sauvegarde de production à restaurer et la destination d'alertes n'ont pas été fournies.
Il n'existe pas de connecteur de supervision utilisable dans cette session. Aucune réception
d'alerte n'est donc attestée et aucun RTO sur le volume réel n'est annoncé. Les 48 secondes
mesurées concernent l'exercice synthétique local, hors détection et transfert distant.

Le corpus Lab est une base de validation publique du briefing, pas un jeu de réserve privé
ni une preuve de réussite d'exécution. La prochaine qualification doit employer des tâches
réelles autorisées, des artefacts/reçus vérifiés et des répétitions avec candidat et juge
explicitement choisis. Le guide se trouve dans `docs/fr/dev/lab-reference-corpus.md`.

Les journaux détaillés de cette session sont dans `/tmp/galaris-consolidation-*.log` ;
les traces navigateur sont conservées sous `artifacts/front-components/` et `artifacts/e2e/`.
