# Plan — Tool AgentAdmin

> **Statut :** `approved` — périmètre fonctionnel accepté ; implémentation non commencée.
>
> **Date :** 29 septembre 2026. Ce document prépare l'implémentation ; il ne décrit pas
> un Tool déjà disponible et n'autorise ni publication ni intervention en production.

## 1. Résultat attendu et périmètre

Un agent autorisé peut créer et administrer les agents, leurs avatars, leurs appartenances,
leurs connexions et leurs harnais avec un Tool intégré optionnel nommé **AgentAdmin**,
code `agent_admin`. Le catalogue comprend exactement les 34 fonctions ci-dessous.

`agent_list` et `agent_get` restent dans le Tool système `galaris`, sans duplication.
Aucune fonction de gestion de skills, y compris des skills appris, n'est ajoutée.
Les initialisations internes déjà réalisées à la création d'un agent restent inchangées.

La gestion porte sur les configurations propres aux agents et sur les référentiels de
civilités et groupes explicitement retenus. La création de modèles LLM, de fournisseurs,
de Tools ou d'entrées du catalogue des harnais, la modification des permissions globales
des Tools et les commandes d'arrêt des tâches ne font pas partie de ces 34 fonctions.

## 2. Contrats constatés dans le dépôt

| Surface | Fait à préserver / conséquence pour l'implémentation |
|---|---|
| [MCP Agent](../../back/app/agent/mcp.py) | `agent_list` et `agent_get` sont déjà standards. |
| [Schémas Agent](../../back/app/agent/schemas.py), [service](../../back/app/agent/agent_service.py), [routes](../../back/app/agent/router.py) | Responsable humain obligatoire ; code immuable ; suppression logique ; personnalité et fiche de poste en HTML éditorial. La création commence avec le harnais interne. |
| [Périmètre de gestion](../../back/app/agent/management_scope.py) | Le périmètre humain distingue les agents gérés et `AGENT_MANAGE_ALL`. Il ne constitue pas à lui seul une délégation MCP. |
| [Modèles Agent](../../back/app/agent/models.py), [appartenances](../../back/app/agent/team_router.py) | Le genre existant est `Title.gender` ; aucun champ sexe propre à Agent. `AgentGroup` désigne le modèle partagé de `core.team`. Les appartenances multiples sont distinctes du champ historique `group_id`. |
| [Connexions](../../back/app/connection/router.py), [façade](../../back/app/connection/facade.py) | Les routes portent une partie de l'orchestration et des protections ; la façade actuelle n'expose pas toutes les mutations requises. |
| [Harnais](../../back/app/harnesses/router.py), [façade](../../back/app/harnesses/facade.py) | Remplacement, retour à l'interne, blocages et actions ont leurs workflows. La façade actuelle doit être complétée pour l'administration. |
| [Image](../../back/app/image/image_service.py), [résolution LLM](../../back/app/llm/llm_service.py) | `generate_image_bytes` reçoit `agent_id` et `task_id` ; `get_image_llm` résout l'usage image du profil effectif. |
| [Catalogue intégré](../../back/app/tools/mandatory_tools.py), [chargeur MCP](../../back/app/tools/mcp_loader.py), [catalogue agent](../../back/app/tools/agent_registry.py) | Réutiliser la déclaration des Tools optionnels, le filtrage des fonctions et la vérification des autorisations courantes. |

Références : [cartographie](../../docs/fr/architecture/generated/project-map.md),
[exécution agentique](../../docs/fr/architecture/flows/agent-execution.md),
[états](../../docs/fr/architecture/state-machines.md),
[processus](../../docs/fr/architecture/flows/process.md),
[URI et médias](../../docs/fr/architecture/flows/media-resources.md),
[HTML éditorial](../../docs/fr/dev/editorial-html.md).

Ces constats proviennent de la lecture du code. Aucune recette runtime AgentAdmin n'a encore
été réalisée. Les limites des façades, de l'autorisation MCP et du filtrage par modèle image
doivent être traitées avant de déclarer le Tool opérationnel.

## 3. Inventaire des 34 fonctions

Les arguments ci-dessous fixent l'intention ; les schémas typés définitifs seront alignés
sur les contrats des domaines au premier lot. Les listes sont paginées : 50 éléments par
défaut, limite maximale 500. Les filtres et la pagination restent propres à chaque collection.

| Nº | Fonction | Entrées / résultat attendu |
|---|---|---|
| 1 | `agent_create` | Configuration initiale, responsable et civilité ; retourne l'agent créé et son URI. |
| 2 | `agent_update` | `agent_id`, champs explicitement modifiés ; identité, poste, personnalité, fiche de poste, responsable, profil LLM, voix et groupe selon les droits. |
| 3 | `agent_delete` | `agent_id` ; suppression logique et résultat durable. |
| 4 | `agent_options` | Catégorie de choix et pagination ; responsables, profils LLM, voix et harnais sélectionnables, sans credentials. |
| 5 | `agent_avatar_set` | `agent_id`, URI canonique de fichier ; validation puis remplacement de l'avatar. |
| 6 | `agent_avatar_delete` | `agent_id` ; retrait de l'avatar. |
| 7 | `agent_avatar_generate` | `agent_id`, `instructions` facultatives ; portrait photographique généré et enregistré, ou suivi explicite d'une opération en cours. |
| 8 | `agent_team_list` | `agent_id`, pagination ; équipes visibles et appartenance de la cible. |
| 9 | `agent_team_set` | `agent_id`, `team_id`, `present` ; ajout/retrait idempotent d'une appartenance. |
| 10 | `agent_tool_list` | `agent_id`, filtres et pagination ; Tools configurables, schémas publics et caractère obligatoire. |
| 11 | `agent_connection_list` | `agent_id`, filtres et pagination ; connexions, y compris inactives. |
| 12 | `agent_connection_get` | `connection_id` ; configuration et paramètres avec secrets masqués. |
| 13 | `agent_connection_create` | `agent_id`, Tool, activation ; une seule connexion par couple agent/Tool. |
| 14 | `agent_connection_update` | `connection_id`, modifications autorisées dont activation ; ne pas autoriser un déplacement implicite vers une autre cible. |
| 15 | `agent_connection_delete` | `connection_id` ; suppression de la connexion et de ses paramètres selon le contrat existant. |
| 16 | `agent_connection_params_set` | `connection_id`, dictionnaire de paramètres ; validation, stockage protégé des secrets et retour expurgé. |
| 17 | `agent_connection_param_delete` | `connection_id`, nom du paramètre ; retrait de la surcharge locale. |
| 18 | `agent_connection_function_list` | `connection_id`, pagination ; fonctions, états locaux et autorisations effectives. |
| 19 | `agent_connection_function_set` | `connection_id`, fonction, état reconnu par le domaine ; autorisation locale uniquement. |
| 20 | `agent_harness_get` | `agent_id` ; sélection et configuration publique du harnais. |
| 21 | `agent_harness_set` | `agent_id`, `harness_id` ; sélection d'une entrée existante avec workflow de remplacement. |
| 22 | `agent_harness_reset` | `agent_id` ; retour au harnais interne via le workflow existant. |
| 23 | `agent_harness_status` | `agent_id` ; état courant du runtime. |
| 24 | `agent_harness_action` | `agent_id`, action autorisée par le fournisseur et l'état courant ; résultat accepté/en cours/terminé distinct. |
| 25 | `agent_harness_logs` | `agent_id`, bornes de lecture ; logs bornés et expurgés. |
| 26 | `agent_harness_blockers` | `agent_id` ; tâches bloquantes référencées par URI complète, sans les arrêter. |
| 27 | `agent_title_list` | Pagination ; civilités, libellés et genres existants. |
| 28 | `agent_title_create` | Libellé et genre ; nouvelle civilité. |
| 29 | `agent_title_update` | Identifiant et modifications ; civilité actualisée. |
| 30 | `agent_title_delete` | Identifiant ; suppression selon les contraintes de référence du domaine. |
| 31 | `agent_group_list` | Pagination ; groupes/équipes partagés existants. |
| 32 | `agent_group_create` | Nom et ordre ; nouveau groupe partagé. |
| 33 | `agent_group_update` | Identifiant, nom et/ou ordre ; groupe actualisé. |
| 34 | `agent_group_delete` | Identifiant ; suppression et traitement des appartenances selon le contrat partagé des équipes. |

`agent_update` distingue omission et valeur nulle pour permettre les effacements autorisés.
Il ne change ni le code permanent ni le harnais. Les mutations retournent une projection
structurée suffisante pour vérifier l'effet sans ajouter un second `agent_get` administratif.
Les identifiants techniques restent typés ; les résultats incluent les URI canoniques
disponibles, notamment `galaris://agent/<id>` et `galaris://task/<uuid>`.

## 4. Autorisation, exposition et frontières

### Délégation administrative

- Déclarer AgentAdmin comme Tool optionnel, désactivé par défaut pour les agents ordinaires.
  La synchronisation du catalogue ne doit pas activer rétroactivement ses connexions.
- Exiger la connexion active et la fonction autorisée de l'appelant à chaque invocation,
  y compris sur un serveur MCP déjà monté. Revalider avant un effet différé.
- Au lot 1, arrêter et tester la matrice entre l'identité MCP, le responsable humain,
  les privilèges existants (`AGENT_EDIT`, `AGENT_MANAGE_ALL`, droits connexions et équipes)
  et la cible. Ne pas supposer qu'un contexte humain est présent dans un worker.
- Décision à formaliser avant les mutations : la délégation donne-t-elle une portée globale
  explicite, comme certains Tools administratifs existants, ou une portée issue du responsable ?
  La portée doit être visible dans la configuration/documentation et cohérente sur les 34 fonctions.
  Aucun fallback ne transforme une absence d'identité ou de droits en accès global.
- Résoudre la cible réelle d'une connexion côté serveur et contrôler cette cible. Ne pas se
  fier à un `agent_id` fourni séparément par le modèle pour autoriser un `connection_id`.
- Couvrir les modifications de responsable et l'attribution d'AgentAdmin à un autre agent :
  aucune auto-attribution ni extension de portée ne doit contourner la délégation effective.
- Conserver les protections des Tools système, de leurs connexions et fonctions. Les règles
  partagées des équipes et civilités restent applicables aux mutations de référentiels.

### Implémentation par domaines

Conserver les points d'entrée MCP dans les domaines propriétaires, tous rattachés au même
code `agent_admin`, plutôt que créer un nouveau module métier pour le seul catalogue.
Les opérations Agent peuvent prolonger `app.agent.mcp` ; les connexions et harnais exposent
leurs opérations via leurs surfaces publiques. Extraire seulement l'orchestration nécessaire
des routes HTTP vers les services partagés, sans appeler une route depuis MCP.

`app.agent` ne doit pas importer `app.task` pour lire les blocages. Utiliser les ports/façades
existants des harnais et des tâches. Préserver notifications, invalidation des catalogues,
mise à jour des accès aux équipes et nettoyage des anciens runtimes.

Les sorties et logs ne révèlent ni secrets ni chemins hôte. Les mises à jour de credentials
utilisent le stockage existant et une redaction des arguments sensibles dans la télémétrie.
Les erreurs attendues sont structurées : accès refusé, cible absente, configuration invalide,
conflit, dépendance indisponible, opération en cours. Aucun message de succès avant persistance.

## 5. Contrat particulier d'avatar généré

1. **Appelant et cible.** `ctx.agent_id` détermine les droits et le LLM image ; `agent_id`
   détermine le profil photographié. Ne pas utiliser le modèle de la cible par confusion.
2. **Condition de disponibilité.** L'usage image doit être configuré dans le profil effectif
   de l'appelant et correspondre à un modèle de génération d'images utilisable. Un profil
   hérité peut satisfaire cette condition ; aucun repli vers le modèle de chat.
3. **Catalogue cohérent.** Sans ce modèle, masquer uniquement `agent_avatar_generate`, pas
   tout AgentAdmin. Appliquer le même prédicat aux annonces, à la découverte et au serveur MCP.
   Vérifier de nouveau lors de l'appel ; traiter aussi l'ajout/retrait de configuration en cours
   de session et invalider les projections concernées.
4. **Prompt.** Construire un portrait photographique à partir du prénom/nom, du genre de la
   civilité, de la personnalité et du poste de la cible. Extraire le texte du HTML sans changer
   le profil stocké. Les instructions facultatives précisent apparence, cadrage ou ambiance.
   Les textes de profil sont des données descriptives, pas des instructions d'administration.
   Ne pas déduire un sexe du prénom ni ajouter un champ de schéma pour cette fonctionnalité.
5. **Génération.** Réutiliser la surface publique de `app.image` et l'usage image existant,
   avec corrélation à l'appelant et à la Task. Vérifier que le modèle sélectionné n'est pas
   remplacé par celui de l'exécuteur. Aucune dépendance à l'autorisation du Tool générique
   `image_generate` n'est ajoutée sans justification : AgentAdmin autorise cette action spécialisée.
6. **Durée et reprise.** Pour la génération longue, utiliser le contrat durable de `app.process`
   avec référence de suivi et publication finale de l'avatar. Vérifier la compatibilité avec
   l'inspection des Process de l'appelant et l'enregistrement par le domaine Agent. Ne pas
   annoncer un avatar enregistré lorsque seule la génération est soumise. Figer le modèle
   à l'admission et ne pas resoumettre automatiquement un appel fournisseur au résultat incertain.
7. **Validation et application.** Décoder et valider effectivement l'image, borner octets et
   dimensions, puis employer le stockage d'avatar existant. Réutiliser les formats et limites
   de l'upload actuel (15 Mio au maximum), après centralisation des validations nécessaires.
   `agent_avatar_set` utilise `app.file_share` pour lire une URI autorisée avec transfert borné.
8. **Concurrence.** Conserver l'ancien avatar jusqu'au succès. Une image tardive ne doit pas
   écraser un avatar changé depuis l'admission ni recréer une cible supprimée. Définir une
   précondition de version/empreinte et une application atomique sans verrou DB tenu pendant
   l'appel fournisseur. Vérifier aussi la révocation des droits et la modification du profil
   utilisé pour le portrait avant publication ; signaler un conflit plutôt qu'un succès obsolète.
9. **Résultat.** Retourner cible, état et référence de suivi éventuelle ; confirmer explicitement
   l'enregistrement effectif. Nettoyer les temporaires et ne pas retourner de base64 au modèle.

La disponibilité conditionnelle, la reprise durable et la précondition d'application sont
des travaux à réaliser, pas des garanties déjà apportées par le service image actuel.

## 6. Lots d'implémentation et preuves attendues

| Lot | Travail | Critère de sortie |
|---|---|---|
| 1 — Contrats et droits | Fixer les schémas, la matrice de délégation, les règles des référentiels, les résultats différés et les surfaces publiques nécessaires. Inventorier les consommateurs HTTP/MCP/runtime. Formaliser les choix structurants dans une décision. | Matrice appelant × cible × fonction × droit, scénarios synthétiques autorisés/refusés et aucune ambiguïté de portée restante. |
| 2 — Parcours vertical | Déclarer AgentAdmin et son catalogue ; réaliser création, options, modification, suppression. Intégrer les contrôles d'accès sans modifier les standards `agent_list`/`agent_get`. | Un agent autorisé crée une cible synthétique, la retrouve avec les standards, la modifie puis la supprime ; le même parcours est refusé sans délégation. |
| 3 — Référentiels et équipes | Civilités, groupes et appartenances avec règles partagées ; préserver la cohérence entre `group_id` et appartenances multiples. | Création/renommage/retrait correctement reflétés dans l'API et l'UI ; références utilisées et suppressions traitées sans perte d'accès accidentelle. |
| 4 — Tools et connexions | Catalogue, connexions, paramètres et permissions locales ; secrets, unicité, protections système, rafraîchissement des capacités. | Une connexion ajoutée/configurée est utilisable, puis sa révocation bloque un appel sur un serveur déjà monté ; aucun secret dans sorties et erreurs. |
| 5 — Harnais | Sélection, retour interne, état, actions, logs et blocages par les workflows existants. | Remplacement autorisé correctement suivi ; concurrence et tâches bloquantes refusées sans contourner les transitions ou laisser deux runtimes actifs. |
| 6 — Avatars | Upload par URI, suppression, génération conditionnelle, suivi durable et application atomique. | Modèle absent : fonction indisponible et appel direct refusé. Modèle présent : portrait enregistré ; erreur, révocation ou résultat tardif préservent l'état courant. |
| 7 — Recette et documentation | Parcours assemblé, FR/EN, cartographie, contrôles et revue des modes d'échec. | Les 34 fonctions sont découvertes selon les droits et capacités ; preuves automatisées et recette réelle rapportées séparément. |

Ne pas ajouter de migration ou dépendance par anticipation. Si la concurrence ou le suivi
durable nécessite un changement de modèle, le justifier au lot concerné et employer DbAdmin
avec les skills `database` et `core-dbadmin` selon la nature du changement.

## 7. Validation

Partir des garanties existantes dans le [catalogue fonctionnel](../../docs/fr/dev/functional-tests.md)
et étendre les scénarios pertinents plutôt que multiplier les tests par fonction :

- `app/agent/tests/test_agents.py`, `test_management_scope.py`, `test_tools.py` : CRUD,
  responsable, code immuable, HTML, suppression et absence de régression des standards.
- `app/tools/tests/test_mcp_loader.py`, `test_live_authorization.py`, `test_agent_registry.py`,
  `test_mandatory_tools.py` : catalogue, délégation, révocation, services système et publicité
  conditionnelle de la génération dans tous les runtimes consommateurs.
- Tests de `app.connection` : unicité concurrente, paramètres invalides, secrets, héritage,
  permissions locales et rafraîchissement des capacités sans réactivation involontaire.
- Tests des équipes et de `app.harnesses` : appartenances, référentiels utilisés, transitions,
  blocages, demandes concurrentes, interruption et nettoyage.
- Tests de `app.image`, `app.llm` et `app.process` : résolution du modèle de l'appelant,
  absence de fallback chat, prompt issu de la cible, image invalide, échec fournisseur,
  timeout ambigu, callbacks/reprises dupliqués et application tardive refusée.

Les workflows de persistance se testent avec la DB isolée, en remplaçant uniquement les
frontières externes. Tous les profils, prompts et images de fixtures sont synthétiques.
Un mock fournisseur prouve le contrat, pas la qualité photographique : prévoir séparément
un essai réel borné avec un modèle configuré, puis vérifier le portrait affiché dans l'UI.

Exécuter les suites ciblées via `make tests ARGS='…'`, puis `make typecheck`,
`make architecture-check` et les suites transversales proportionnées aux domaines touchés.
La recette assemblée vérifie création, réouverture, visibilité du nouvel avatar, changement
de contexte, révocation et erreurs, ainsi que les requêtes échouées et erreurs navigateur.

À l'implémentation, mettre à jour les parcours FR/EN des agents, Tools, connexions et harnais,
le catalogue fonctionnel et la documentation du Tool. La documentation du skill système
Galaris peut être ajustée pour expliquer AgentAdmin ; cela n'ajoute aucune gestion de skills.
Régénérer les cartes avec `make project-context`, exécuter `make docs-prepare` et propager
les sources par `make docs-update` dans le cadre de la livraison en développement.
Ne pas documenter le Tool comme disponible avant son implémentation.

Avant publication, exécuter `make validate` sur le snapshot final et lire son résumé complet.
Terminer par revue du diff et `git diff --check`. Rapporter distinctement les contrôles
automatiques, les parcours réellement exercés, les essais fournisseur et les limites restantes.
Un plan terminé est retiré de cet index après transfert des contrats durables vers les
décisions, la documentation et les tests.
