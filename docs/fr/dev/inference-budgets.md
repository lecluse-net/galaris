<p align="right"><strong>Français</strong> · <a href="../../en/dev/inference-budgets.md">English</a></p>

# Limites d’utilisation de l’inférence par utilisateur

Dans **Superviser → Consommation**, le bloc **Mes limites d’utilisation** affiche les
plafonds de votre compte. Le tableau présente les membres de vos équipes quand vous en êtes
chef, ou les autres comptes actifs avec le droit global. Chaque compte figure sur une ligne
avec trois colonnes fixes. Chaque cellule plafonnée indique le
montant avec le symbole `$` et une jauge. Une cellule vide indique une utilisation illimitée.
Le chef d’équipe accède aux demandes en attente depuis la ligne du compte concerné.
Les jauges personnelles apparaissent aussi au-dessus de **Configurer**.
L’infobulle donne le montant consommé, le plafond et son renouvellement. La barre est verte
sous 50 %, bleue dès 50 %, orange dès 80 % et rouge dès 95 %. Un clic ouvre la page de consommation.

| Limite d’utilisation | Début | Renouvellement |
|---|---|---|
| 5 heures | Premier appel admis après une période inactive | Après cinq heures, le plafond se renouvelle et le prochain appel démarre une fenêtre. |
| Hebdomadaire | Le lundi à 00 h UTC par défaut | Toutes les 168 heures, indépendamment de l’activité. Les horaires déjà attribués sont conservés pour préserver les crédits associés. |
| Mensuelle | Premier jour du mois civil à 00 h UTC | Premier jour du mois civil suivant. |

La fenêtre de cinq heures et le renouvellement hebdomadaire reprennent les règles temporelles
documentées par [Anthropic](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work).
Galaris mesure une valeur en dollars avec ses propres tarifs et traces.

<a id="request-credit"></a>
## Demander des crédits

Pour déposer une demande, suivre sa décision ou traiter celle d’un membre de votre équipe, consultez le [parcours Consommation et crédits](../user/usage.md#request-credit).

## Configurer les plafonds et accorder des crédits

L’utilisation est illimitée par défaut sur les trois périodes. Tous les comptes connectés peuvent consulter
leur consommation.

| Droit | Action |
|---|---|
| `LLM_BUDGET_EDIT_OWN` | **Modifier mes plafonds** dans **Mes limites d’utilisation**, même si l’utilisation est illimitée. Le bouton règle les montants de son compte. |
| `LLM_BUDGET_ADMIN` | Le tableau liste tous les autres comptes actifs. Cliquer sur la ligne ou sur **Modifier les plafonds**. Ce droit permet aussi de modifier ses propres plafonds. Le rôle système Administrateur le reçoit automatiquement. |
| Chef d’équipe actif | Modifier les plafonds des autres membres humains des équipes qu’il dirige, accorder du crédit et traiter leurs demandes. L’appartenance à plusieurs équipes dirigées par la même personne produit une seule ligne. |

Un montant vide rend l’utilisation illimitée pour la période. Zéro suspend les nouvelles inférences.
Le renouvellement est automatique et la date du prochain renouvellement s’affiche dans
l’infobulle de la jauge.

Un utilisateur peut demander un montant pour une limite d’utilisation. Une seule demande par
période peut rester en attente. Chaque chef d’équipe du demandeur peut l’accepter, la refuser ou octroyer directement
un montant. Le crédit augmente exclusivement le plafond choisi pour la période en cours et
expire à la fin de celle-ci. Pour la limite de cinq heures, la fenêtre doit être ouverte au
moment de l’octroi. Une demande peut rester en attente jusqu’à son démarrage. Un autre
plafond atteint continue de bloquer les appels.

La désignation se fait dans la [fiche de l’équipe ou de l’utilisateur](../user/teams.md).
Seul un autre chef d’équipe actif peut traiter une demande ou octroyer du crédit. Une fois
traitée, une demande ne peut plus donner lieu à un nouvel octroi. Un changement d’équipe ou
de chef prend effet dès l’enregistrement. L’accès aux plafonds de son propre compte dépend
toujours de `LLM_BUDGET_EDIT_OWN` ou `LLM_BUDGET_ADMIN`.

## Comptabilité et admission

L’imputation suit [la provenance de llm_calls.user_id](llm-attribution.md). Chaque appel
physique est compté une fois à sa date de départ. Les traces archivées et les échecs ayant
consommé du budget restent inclus. La valeur d’inférence est utilisée, avec le montant facturé
comme repli historique. Elle inclut la valeur connue sous abonnement. Une trace sans montant
connu ne fournit aucune valeur à additionner.

Une limite d’utilisation atteinte suffit à refuser l’appel avant le départ fournisseur. Les API
d’inférence renvoient HTTP 429 ou une erreur terminale de budget pour une exécution déjà
admise. Pour un compte plafonné, un seul appel physique peut être en cours à la fois. Le
verrou PostgreSQL par compte sérialise la vérification et l’admission, sans bloquer les
autres utilisateurs. Quand le fournisseur ne communique le coût final qu’après l’appel,
le dernier appel admis peut dépasser le solde. Les appels suivants sont refusés dès que
l’épuisement est établi. Une conversation partagée sans demandeur unique est refusée
si l’une de ses entrées appartient à un compte plafonné.

Les cycles de Goal, leur jugement, les tâches automatiques attribuées, les activités LLM
natives, Dream et certains travaux différés vérifient aussi le budget avant de démarrer.
La file conserve le travail en attente. Un renouvellement ou un octroi le rend à nouveau
éligible sans nouvelle demande. Le contrôle central couvre les départs fournisseurs qui
écrivent dans `llm_calls`. Une nouvelle session vocale attribuée à un compte plafonné utilise
l’inférence et la transcription par lot plutôt que les modes temps réel non comptabilisés.
La synthèse vocale personnelle vérifie le budget avant l’appel. Les embeddings internes
et la synthèse vocale hors journal restent hors du calcul en dollars. Les appels sans compte imputable
appartiennent à la consommation système.

## Contrat de données et accès

| Table | Rôle |
|---|---|
| `agent_groups`, `team_users` | Un chef humain par équipe (`manager_user_id`) et les appartenances humaines qui définissent son périmètre. |
| `llm_user_budgets` | Un budget par utilisateur, avec plafonds décimaux, heure hebdomadaire et début de fenêtre de cinq heures. L’ancienne colonne `referrer_user_id` reste en base pour conserver les données historiques. |
| `llm_credit_requests` | Demandes uniques en attente par compte et période, décision et identité du chef d’équipe ayant traité la demande. |
| `llm_credit_grants` | Journal durable des montants octroyés, de leur auteur, de la période et de la demande associée. |

Toutes les routes `/api/llm-budget` exigent un jeton de connexion lié à une session web active.
Les actions utilisent la session en cours et le serveur contrôle le privilège de configuration,
les appartenances aux équipes dirigées par le compte actif et l’interdiction d’auto-octroi. La déconnexion révoque la session.
Les jetons API utilisateur, les jetons de harnais et les outils MCP n’autorisent aucun accès.
Le verrou par compte et les identifiants uniques empêchent une double attribution après une
répétition de requête ou deux traitements simultanés. Les écritures de budget qui dépendent
des équipes relisent leur périmètre sous le même verrou de coordination que les changements
d’appartenance et de chef.
