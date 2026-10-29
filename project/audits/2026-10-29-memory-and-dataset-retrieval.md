# Mémoire et recherche Dataset — qualification du 29 octobre 2026

## Périmètre

La comparaison utilise exclusivement des données synthétiques créées pour les tests.
Elle distingue recherche, assemblage du contexte et réponse finale. Elle ne mesure ni la
fréquence des calendriers chargés en usage réel, ni l'adoption des consignes par des agents
autonomes. Les changements sont décrits dans la [décision 0249](../decisions/0249-memory-evidence-and-dataset-retrieval.md).

## Contexte mémoire : comparaison appariée

Le corpus existant fournit 396 scénarios, 360 souvenirs, trois mondes et 33 familles,
avec variantes françaises/anglaises et reformulations. Les variantes d'une famille ne
constituent pas des situations indépendantes. Les deux bras utilisent les mêmes données,
droits, horloges et budgets (8 items, 12 000 caractères), avec ordre alterné et sources
initiales figées. Le moteur utilise le repli lexical réel. Tous les cas saturent volontairement
le calendrier. Les 348 questions répondables portent le dénominateur des scores de rappel.

| Mesure | Avant | Après |
|---|---:|---:|
| Faits attendus retrouvés, rappel@8 | 84,6 % | 84,6 % |
| Faits attendus présents dans le contexte | 43,2 % | 76,4 % |
| Questions ayant toutes leurs preuves dans le contexte | 31,9 % | 68,4 % |
| Questions avec résultat interdit | 0 | 0 |

Le gain provient de l'allocation du contexte, pas d'un meilleur moteur de recherche.
Le calendrier reste présent ; plusieurs faits ordinaires complémentaires survivent à sa
saturation. La source et les paramètres sont empreintés par le runner, qui refuse les
modifications pendant la campagne. Aucune amélioration de latence n'est revendiquée : d'autres
contrôles tournaient sur la machine pendant ces mesures.

## Réponses du modèle configuré

Un premier contrôle porte sur dix questions FR/EN, avec une génération par bras : les
huit faits simples sont correctement restitués et les deux questions sans preuve conduisent
à une abstention, dans les deux versions. Il ne démontre aucun gain sur ces questions simples.

Le contrôle suivant ajoute quatre formulations FR/EN exigeant chacune deux preuves :
28 réponses, soit 14 questions × deux bras, avec le même modèle de conversation configuré.
Les quatre questions à deux preuves passent de zéro réponse complète à quatre réponses
complètes, accompagnées des deux références attendues. Les deux questions sans preuve gardent
leur abstention dans les deux bras. Les formes de réponse peuvent ajouter l'unité présente
dans la source ou le mot « format » : l'égalité stricte de chaînes est conservée séparément
de la vérification des faits et des références, sans assimilation à une erreur factuelle.

Le coût enregistré pour ce second contrôle est d'environ 0,0065 USD, avec variation de cache.
Il ne démontre pas une baisse de coût par tâche. Ce petit contrôle ne qualifie ni les parcours
Task autonomes, ni le déclenchement effectif d'une recherche par un agent, ni d'autres modèles.

## Dataset : découverte textuelle et calculs

La campagne ciblée comprend huit jeux synthétiques et 80 requêtes, dont 64 répondables,
huit recherches inconnues et huit recherches par un autre agent sans accès. Les familles
portent sur un terme, deux termes séparés/inversés, une clé et une valeur, le titre, une
absence et un refus d'accès. Les 56 cas d'extraits placent la preuve après une longue zone
sans rapport. La référence est le provider natif initial ; les empreintes des sources
courantes sont contrôlées avant et après la campagne finale.

| Mesure | Avant | Après |
|---|---:|---:|
| Découverte des 64 ressources attendues | 37,5 % | 100 % |
| Présence de la preuve dans les 56 extraits attendus | 0 % | 100 % |
| Résultats interdits | 0 | 0 |

Ce corpus isole les limites de la recherche de sous-chaîne et des extraits pris au début
du JSON. Il ne constitue pas une mesure de qualité sémantique ou de recherche en langage
naturel général. Une requête agrégée sur 500 lignes renvoie 295 octets, contre 209 500 octets
pour le JSON source ; la somme utilise les littéraux décimaux, sans calcul dans le modèle.

## Garanties et limites

Les reproductions échouaient avant correction pour les termes Dataset séparés, les preuves
complémentaires écartées par le calendrier, les en-têtes de grands tableaux et le rappel
artificiellement augmenté par les questions sans réponse. Les tests couvrent les révisions,
droits retirés, réponses tardives, index partiels, publication obsolète, pagination, calculs
décimaux, budgets et schémas MCP des deux runtimes. Une réadmission finale vérifie la page
entière après l'hydratation de ses descriptions.

La correction explicite peut conserver les deux preuves avec un lien de contradiction.
La révision cible est contrôlée à nouveau lors de l'acquisition ; une nouvelle lecture permet
de réessayer sans rester bloqué sur la proposition périmée. Les tests couvrent ce changement
intercalé entre admission et application, ainsi que le refus des souvenirs d'un autre agent.

Le fournisseur vectoriel configuré n'a pas pu être joint, y compris pour un unique texte
synthétique. Les tests avec vecteurs prescrits qualifient les mécanismes et le repli ; ils
ne qualifient pas la pertinence des embeddings réels. Le reranking appris et la contextualisation
LLM supplémentaire restent des expériences à comparer avant activation. Aucune approximation
vectorielle ni nouvelle infrastructure de recherche n'est introduite sans mesure de charge.

Une sélection élargie a obtenu 230 succès et 12 échecs dans les fixtures historiques Dataset :
création de Datasets par un contrat Document désormais refusé et anciens champs de révision
documentaire. Ces tests et les contrats correspondants n'ont pas été modifiés ici. Les sélections
ciblant les contrats courants ont obtenu 204 succès, puis 31 succès après les dernières gardes.
Ces résultats ne représentent pas une validation complète de l'application.

Les mesures détaillées, références et journaux locaux restent dans le répertoire d'artefacts
du benchmark, hors sources versionnées. Ce compte rendu conserve uniquement les agrégats et
conclusions techniques. Aucun commit ou déploiement n'est effectué par la qualification.
