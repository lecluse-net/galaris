# Amélioration des skills système livrés avec Galaris

Date : 29 octobre 2026. Périmètre : les trois packages de `back/app/skill/system_skills/`.
Les corrections sont appliquées dans les sources de développement.

## Résultat

| Skill | Améliorations |
|---|---|
| `galaris` | Choix des outils par intention ; distinction autorisé/présent/exécuté ; stockage `file://` sans Console ; permissions des services système ; portées administratives ; propriété BPMN ; types Dataset ; analyse PDF et politique réseau du navigateur. |
| `galaris-knowledge` | Choix Conversation/Task/Goal/Document/Dataset/Process/fichier ; prérequis des intégrations ; accès documentaire ; explications des droits et des capacités réellement montées. |
| `galaris-lab` | Distinction évaluations de mécanismes/campagnes Process ; procédure dédiée aux exécutions réelles, avec données synthétiques, droits, pagination, idempotence, coûts et annulation. |

La procédure détaillée des campagnes Process est dans
[references/process-campaigns.md](../../back/app/skill/system_skills/galaris-lab/references/process-campaigns.md),
liée depuis le point d'entrée du skill Lab. Les mécanismes ordinaires conservent leur procédure.
Les signatures MCP courantes restent l'autorité ; les exemples du guide ne constituent pas un second schéma.

## Contrats réconciliés

- Les connexions système restent actives, tandis que leurs fonctions conservent les modes
  Actif/Bloqué/Sur demande, les ACL et les restrictions de contexte.
- Les délégations ToolAdmin, Goal et Process sont bornées par leur portée effective.
  Une connexion active ne signifie pas une administration globale.
- Process possède directement le BPMN, ses révisions et ses droits. Le guide ne demande plus
  un Document support et ne présente plus les données de run comme un Dataset indépendant.
- Le provider `file://` permet de créer ou copier un fichier géré sans Console. Son URI opaque
  n'est pas un chemin ; ses octets sont immuables et les capacités annoncées restent déterminantes.
- Le navigateur distingue activation, permissions de fonctions et autorisations réseau.
- Une analyse de PDF suit le contenu natif disponible ou `document_analyze`, avec lecture du
  résultat et de sa couverture.
- Les campagnes Process Lab produisent de vrais runs et peuvent effectuer de vraies opérations
  externes. Les paramètres de budget et de pagination des mécanismes ne leur sont pas attribués.
- Les skills guident l'usage des capacités déjà exposées. Leur chargement ne monte aucun outil
  absent et n'accorde aucun droit.

Les guides conservent les procédures sur URI canoniques, HTML éditorial, révisions, partage,
déduplication, effets incertains et reçus de livraison. Le chargement progressif existant est
préservé. Aucun comportement du moteur d'exécution n'est modifié par ces corrections éditoriales.

## Sources vérifiées

Les descriptions ont été confrontées notamment aux déclarations MCP et à leurs tests :
[services et defaults](../../back/app/tools/mandatory_tools.py),
[permissions système](../../back/app/tools/tests/test_system_tools.py),
[portées administratives](../../back/app/tools/management_scope.py),
[accès Goal](../../back/app/goal/access.py),
[stockage Process](../../back/app/process/models.py),
[test de propriété du BPMN](../../back/app/process/tests/test_definition_storage.py),
[fichiers gérés](../../back/app/file_share/managed_files.py),
[politique réseau](../../back/app/browser/network.py),
[accès documentaire](../../back/app/tools/admin_access.py),
[fonctions Lab](../../back/app/lab/mcp.py) et
[campagnes Process](../../back/app/lab/process_evaluation.py).

## Vérifications

- `quick_validate.py` : les trois skills modifiés sont valides.
- Tests existants ciblés : **54 réussites sur 55** dans les suites de stockage des skills,
  chargement du harnais et MCP Lab. La couverture existante confirme notamment les noms des
  fonctions natives dans les guides système et la conservation des procédures de pièces jointes.
- Le test `test_mounted_lab_action_waits_for_one_exact_human_agreement` échoue parce que
  `answer_action` retourne faux pour l'accord du compte synthétique. Son workflow concerne
  l'autorisation d'une création Lab ; les corrections livrées ne modifient ni ce code ni ses
  fixtures. Cet échec reste signalé, sans affirmer que toute la suite est validée.
- Les deux premières exécutions de `make docs-prepare` ont vérifié corpus, cartographie et
  contrats d'architecture dans leurs instantanés, puis refusé la publication après modification
  des sources pendant les contrôles. Aucun fichier généré n'a été publié par ces tentatives.
- La troisième exécution a vérifié le corpus documentaire, puis échoué sur les frontières
  d'architecture des changements Dataset/Document présents dans le worktree : dépendances de
  `app.document` et imports privés `app.document.data.*`. Ces sources Python ne sont pas
  modifiées par le présent lot ; la préparation documentaire globale reste non validée.
- Références locales des packages système : quatre fichiers Markdown contrôlés, aucun lien cassé.
- `git diff --check` : aucune anomalie lors du contrôle du diff courant.

Les tests de comportement avec un modèle réel et les opérations externes ne sont pas exécutés.
Aucun commit ni déploiement n'est effectué. Les nouvelles instructions seront consommées lors
de leur distribution normale et de la construction des contextes qui y sont autorisés.
