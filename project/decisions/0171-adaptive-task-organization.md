# 0171 — Organisation adaptée au travail demandé

Statut : accepté. Date : 2026-10-11.

## Décision

Le Dispatcher choisit l'organisation dans la même inférence que la route et l'effort :
`direct` pour une action bornée avec vérification simple, `tracked` pour une mission longue
ou complexe qui demande préparation et continuité, `clarify` quand une intention manquante
laisse des périmètres ou profondeurs sensiblement différents. Une inconnue technique
résoluble par inspection autorisée relève de la préparation. Le modèle natif de décision
ajoute un choix fermé ; le modèle texte peut fournir jusqu'à trois questions ciblées.
Le premier utilise une question localisée sur le périmètre et la profondeur attendus.

L'organisation ne remplace ni l'effort ni la coordination : un livrable cohérent conserve
un exécutant responsable, avec suivi si nécessaire ; plusieurs résultats indépendamment
vérifiables et reprenables utilisent le Planner et ses collections. Le schéma de chaque
étape transmet `direct` ou `tracked` aux feuilles. Les anciens plans restent directs par défaut.
Il n'y a ni nouvelle phase de briefing, ni nouvelle inférence préparatoire systématique,
ni nouvelle colonne de base de données. La décision 0143 reste applicable.

## Clarification et reprise

Une clarification d'organisation réutilise l'interaction durable du Planner et suspend
la Task en `PLAN`. La réponse enregistre les consignes, applique `REASSESS_ORGANIZATION`
vers `CREATE`, puis réévalue le choix avec la réponse. Le contexte d'exécution reçoit aussi
les réponses humaines pour appliquer le périmètre précisé. L'exécution en ligne respecte aussi
cette suspension. Sans canal permettant de poser la question, ou à expiration sans réponse,
la Task échoue explicitement avec `ORGANIZATION_CLARIFICATION_REQUIRED` ; le silence ne
déclenche pas les actions. Une relance explicite d'une clarification échouée repasse par
`RETRY_ROUTING`, sans invoquer directement l'exécuteur.

Précision du 12 novembre 2026 : après une réponse, si le Dispatcher conserve `clarify`,
la même Task pose une nouvelle question et se suspend à nouveau. Chaque nouvelle série
exige une réponse non vide aux séries précédentes ; une question en attente ou expirée
ne déclenche pas de question supplémentaire. Les réponses restent cumulées et chaque
interaction est corrélée à sa série pour refuser les anciens retours, même pendant
l'envoi suivant. Une réponse reçue pendant l'envoi clôt l'attente sans la recréer.
La limite d'une série reste propre au cadrage d'un plan déjà choisi. Une clarification
d'organisation impossible ou expirée porte un échec sans retry automatique ; le scheduler
respecte cette politique dès `CREATE`, avant les gardes propres à l'exécution.

Le défaut provenait du partage de la garde d'une seule série entre organisation et plan :
une réponse humaine pouvait être suivie d'un échec de clarification, puis de retries
sans information nouvelle. Les tests validaient la réponse mais pas le routage suivant.
Le scénario PostgreSQL couvre désormais deux séries, les retours tardifs et la reprise,
et les tests du scheduler vérifient la clôture sans retry dans chaque phase concernée.

Le suivi d'un exécutant est un objet `galaris.work-plan/v1` dans les données de sa Task :
au plus vingt jalons, critères d'acceptation, résultats observés, URI et prochaine action,
avec un budget de contexte borné. `task_work_update` ne modifie que la Task active de
l'exécutant ; la commande recharge et verrouille la ligne, contrôle `expected_revision`,
préserve les autres données et refuse les Tasks suspendues ou terminales. Un même contenu
est idempotent ; modifier un jalon achevé demande une raison explicite. `task_get` fournit
la révision et le suivi. Les mises à jour utilisent les événements Task existants.

Le suivi dispose de `work_plan_revision` dans les données de la Task, initialisé à zéro
pour un suivi absent ou historique. `expected_revision` compare ce compteur, incrémenté
uniquement lorsque les jalons changent. La révision globale de Task conserve son rôle de
concurrence ORM et HTTP ; les checkpoints et l'activité ne périment plus une lecture du suivi.
Le verrou de ligne continue de sérialiser les écrivains et les commandes de suspension ou d'arrêt.
Un conflit de suivi est refusé avant mutation avec une consigne explicite de relecture.

Les consignes de reprise demandent de contrôler les ressources et effets conservés avant
de répéter une action. Un jalon coché est une déclaration du modèle, jamais une preuve de
réussite terminale. Le contrat de résultat et les reçus d'effets restent les autorités.
Un outil indisponible ne doit pas être présenté comme un checkpoint persistant.

Précision du 26 octobre 2026 : après relecture des attentes et du suivi persistés par
les outils, un jalon explicitement `blocked` interdit la clôture de la Task en succès.
Sans attente durable d'entrée, d'autorisation ou d'enfants, la clôture conserve le bilan,
les coûts et les effets acquis, mais termine en erreur sans retry automatique. Elle
ne crée aucune attente humaine. Un suivi absent, historique invalide ou simplement
non actualisé (`pending`/`doing`) ne suffit pas à invalider un résultat du harnais.
Le suivi ne prouve toujours pas un succès ; cette garde empêche seulement de contredire
un blocage déclaré. Les tâches déjà terminales ne sont pas réécrites.

## Validation et limites

Précision du 7 novembre 2026 : chaque jalon distingue `required=true` (défaut conservateur
pour les suivis existants) et `required=false`. Les compléments facultatifs restent séparés
du livrable demandé. Un état `skipped` exige un jalon facultatif et une observation ;
un complément facultatif `blocked` reste lui aussi une omission non bloquante à la clôture.
La progression exclut ces omissions des jalons applicables et expose leur nombre `skipped`,
sans les compter comme des réalisations. Les critères de succès du résultat restent inchangés.
Un jalon obligatoire `blocked` conserve la garde d'échec ; changer le caractère obligatoire
ou rouvrir un jalon `done`/`skipped` exige une raison explicite. Aucun de ces champs ne modifie
le périmètre d'exécution ou les ACL, et aucun terminal historique n'est réécrit.

Le défaut initial venait de la fusion d'une réponse obligatoire et d'une note conditionnelle
dans un même jalon bloqué après refus d'écriture. Le contrat et les tests ne représentaient
que la présence d'un blocage, sans son caractère obligatoire. La couverture existante est
étendue avec une réponse conservée malgré une note facultative refusée, les suivis historiques,
les attentes prioritaires et la persistance des omissions motivées, sur données synthétiques.

Les scénarios synthétiques couvrent le choix, l'attente, l'expiration, la réponse tardive,
la persistance PostgreSQL, les écritures concurrentes, les droits de l'exécutant et la
préservation des checkpoints. Le corpus Lab `task-organization` complète les frontières
de routage existantes ; ses critères évaluent l'organisation séparément de la route.
Les contrats d'inférence figés `active/v4` gardent leur ancien schéma ; les nouveaux appels
texte utilisent `active/v5`. Les campagnes Lab existantes gardent leur rubrique figée.

Une comparaison avec le modèle réel a détecté que le suivi faisait manquer une collection
au routage natif. Les critères du choix natif explicitent désormais la coordination des
éléments indépendants. Ce défaut échappait aux tests avec modèle simulé : la qualification
doit vérifier les anciennes frontières avec les nouvelles décisions, pas seulement la
validité du schéma et des transitions. Les mesures de routage ne certifient pas l'exécution
complète d'une mission ni tous les modèles disponibles. La production ne change qu'après
un déploiement explicitement demandé.
