<p align="right"><strong>Français</strong> · <a href="../../en/dev/agent-admin.md">English</a></p>

# AgentAdmin

AgentAdmin (`agent_admin`) est un Tool intégré optionnel de 34 fonctions. Sa connexion
est créée inactive pour les agents ordinaires. L’assistant **Galaris** proposé par
l’installation la reçoit active dès sa création. Une synchronisation du catalogue ne
réactive jamais une connexion désactivée et ne modifie pas les agents déjà initialisés.
Un humain peut l’activer dans **Configurer → Outils & connexions → Connexions**.
`agent_list` et `agent_get` restent dans le service système Galaris.

## Délégation et droits

Chaque appel vérifie la connexion et l’autorisation effective de la fonction, puis les
droits actuels du responsable humain actif de l’appelant. Ce responsable définit le
périmètre des cibles ; `AGENT_MANAGE_ALL` l’étend à tous les agents. Aucune identité HTTP
n’est nécessaire et aucun rôle sélectionné dans une requête HTTP ne remplace cette délégation.

| Opérations | Droits du responsable, en plus de la connexion et de la fonction |
|---|---|
| Toutes | `AGENT_EDIT` |
| Tools et connexions | `CONNECTION_EDIT` |
| Lecture des équipes et groupes | `TEAM_ACCESS` |
| Appartenances | `TEAM_ACCESS`, `TEAM_MEMBERS_EDIT` |
| Création/modification/suppression des groupes | `TEAM_ACCESS`, `TEAM_EDIT`, `AGENT_MANAGE_ALL` |
| Création/modification/suppression des civilités | `AGENT_MANAGE_ALL` |
| Changement de responsable | `AGENT_MANAGE_ALL` |
| Blocages du harnais | `TASK_EDIT` |

L’appelant ne peut ni se supprimer ni changer son propre responsable. Les connexions
des services système sont protégées. Les connexions donnant des pouvoirs administratifs
sont modifiables uniquement par les humains : AgentAdmin ne peut pas s’auto-attribuer des
droits, déléguer AgentAdmin à un autre agent ou activer un autre Tool administratif.
La cible d’une connexion est résolue côté serveur. Une révocation bloque aussi les appels
sur un serveur MCP déjà monté ; la découverte se recalcule avec les droits courants.
La [décision 0148](../../../project/decisions/0148-agent-admin-delegation.md) fixe ce contrat.

## Catalogue

| Domaine | Fonctions |
|---|---|
| Agents | `agent_create`, `agent_update`, `agent_delete`, `agent_options` |
| Avatars | `agent_avatar_set`, `agent_avatar_delete`, `agent_avatar_generate` |
| Appartenances | `agent_team_list`, `agent_team_set` |
| Tools | `agent_tool_list` |
| Connexions | `agent_connection_list`, `agent_connection_get`, `agent_connection_create`, `agent_connection_update`, `agent_connection_delete`, `agent_connection_params_set`, `agent_connection_param_delete`, `agent_connection_function_list`, `agent_connection_function_set` |
| Harnais | `agent_harness_get`, `agent_harness_set`, `agent_harness_reset`, `agent_harness_status`, `agent_harness_action`, `agent_harness_logs`, `agent_harness_blockers` |
| Civilités | `agent_title_list`, `agent_title_create`, `agent_title_update`, `agent_title_delete` |
| Groupes partagés | `agent_group_list`, `agent_group_create`, `agent_group_update`, `agent_group_delete` |

Les listes ont `skip=0`, `limit=50`, avec un maximum de 500. La création exige explicitement
un responsable et commence avec le harnais interne. Le code permanent et le harnais ne
se modifient pas avec `agent_update`. Omission et valeur nulle sont distinctes ; les champs
éditoriaux restent du HTML. Les réponses décrivent l’effet persisté et les URI disponibles.
Les erreurs MCP incluent un objet `error` avec `kind` et une référence technique, sans secret.

Les paramètres utilisent le stockage chiffré existant ; les lectures masquent les secrets
et distinguent configuration locale, valeur héritée et valeur imposée. Les autorisations
de fonctions sont locales (`default`, `enabled`, `disabled`, `ask`) et ne modifient pas les règles
globales. Un couple agent/Tool ne possède qu’une connexion. La suppression des groupes
détache le groupe historique et révoque les accès associés ; une civilité référencée ne
peut pas être supprimée, y compris lorsqu’un agent archivé la référence encore.

Les harnais utilisent les workflows de sélection, de nettoyage et de blocage existants.
Une action n’est admissible que si le fournisseur et l’état courant la proposent.
Les résultats distinguent `completed`, `in_progress` et `error`. Les logs sont bornés
à 5 000 lignes, 2 000 caractères par ligne et 200 000 caractères au total, avec expurgation
des credentials et chemins. Les tâches bloquantes sont référencées par URI complète ;
aucune commande d’arrêt de tâche n’est fournie.

## Portrait généré

Seule `agent_avatar_generate` disparaît lorsque l’usage image du profil effectif de
l’appelant n’est pas configuré avec un modèle produisant des images, un fournisseur actif
et les credentials requis par son profil fournisseur. Ce contrôle local ne vérifie pas
la validité des credentials auprès du fournisseur.
Un profil hérité convient ; le modèle de chat ou celui de l’exécuteur ne sert jamais de repli.
La disponibilité est réévaluée à la découverte et à l’appel, même dans une session conservée.

Le portrait utilise le prénom, le nom, le genre de la civilité et la personnalité
de la cible. Le HTML est lu comme texte descriptif et reste inchangé en base. Les instructions
facultatives, au plus 4 000 caractères, précisent apparence, cadrage ou ambiance.

`agent_avatar_generate` appelle directement le service utilisé par `image_generate`,
attend l'image et l'enregistre. La réponse contient `status="success"`, `registered=true`,
l'URI de la cible et sa révision d'avatar. Aucun Process ni job de processus n'est créé.
Avant enregistrement, les droits, le responsable, le profil et la révision de l'avatar
sont revérifiés. Une erreur fournisseur, une révocation ou une modification concurrente
conserve l'état courant ; la fonction ne resoumet pas automatiquement la génération.
DbAdmin purge les anciennes définitions `agent_admin:<agent>:avatar` et leurs exécutions,
jobs et événements, après résolution de leurs éventuelles Tasks d'attente.

`agent_avatar_set` lit une URI canonique autorisée avec `app.file_share` dans un temporaire
borné, ensuite nettoyé. Upload, URI et génération partagent le décodage réel JPEG/PNG/GIF/WebP,
la limite de 15 Mio et les limites de dimensions (16 millions de pixels, 8 192 par côté).
Avant chaque enregistrement, le module Agent applique l’orientation EXIF puis convertit
l’image en JPEG optimisé (qualité 85), avec un maximum de 500 × 500 pixels, proportions
conservées, sans recadrage ni agrandissement. La transparence devient un fond blanc,
les animations utilisent leur première image et les métadonnées EXIF sont retirées.
Cette conversion s’applique au POST HTTP, aux URI et aux portraits générés.
Une révision monotone protège aussi contre un avatar remplacé puis restauré. Les lecteurs UI
utilisent cette révision pour charger le nouvel avatar à la réouverture.
Une réponse d'un ancien chargement de la liste ne peut pas retirer un portrait courant ;
son URL temporaire est libérée.

## Vérification

`back/app/agent/tests/test_agent_admin.py` vérifie le parcours CRUD sans contexte HTTP,
le périmètre, les protections des connexions, les 34 fonctions, la révocation et la disponibilité
image sur un serveur monté, ainsi que la génération directe sans Process et ses issues d’échec.
Il exerce aussi le transfert URI réel derrière une frontière fournisseur synthétique,
le nettoyage des temporaires et le parcours MCP des harnais avec tâches bloquantes.
`e2e/specs/agent-admin.spec.mjs` exerce l’API et l’UI assemblées avec un fournisseur synthétique :
création, génération, remplacement, réouverture par navigation Vue sans rechargement,
civilité renommée et refus après révocation.
Ces tests ne mesurent pas la qualité photographique d’un fournisseur réel.

Commandes : `make tests ARGS='app/agent/tests app/connection/tests app/harnesses/tests app/tools/tests app/image/tests app/process/tests core/team/tests'`,
`make tests-e2e ARGS='agent-admin.spec.mjs --project=chromium'`, `make typecheck`,
`make docs-prepare`, `make architecture-check`. Le changement de schéma est la colonne
`agents.avatar_revision`, synchronisée par DbAdmin avec `make sync-db` en développement.

### Recette avec un fournisseur réel

Recette réalisée en développement le 2 octobre 2026 avec OpenRouter authentifié et
`google/gemini-3.1-flash-image`, via le serveur MCP HTTP réel et les réponses humaines
à l'API d'autorisation. Deux portraits photographiques fictifs ont été générés et enregistrés
en 10,797 s puis 10,317 s, en JPEG de 500 × 500 pixels sans métadonnées EXIF.
Les cheveux argentés, les lunettes et la veste verte de la cible sont visibles ; ses champs
HTML sont conservés et le modèle utilisé est celui de l'appelant.
Le remplacement et la réouverture par navigation Vue sont vérifiés sur ordinateur et mobile,
avec comparaison de l'empreinte du portrait affiché à celle du JPEG enregistré.

YOLO était désactivé : aucun appel fournisseur avant accord ni après refus, et aucun
appel supplémentaire au rejeu des continuations terminées. Le compte fictif a été désactivé,
ses agents archivés et ses jetons révoqués après recette. Un message
`WebSocket closed without opened.` est observé pendant la connexion ; aucun échec API ni
erreur navigateur n'est observé sur le parcours du portrait. Cette recette qualifie le
fournisseur image derrière MCP ; elle ne qualifie pas les quatre SDK de harnais avec
leurs propres modèles distants et ne constitue pas un déploiement.

Pour renouveler la recette après configuration humaine des credentials image de l'appelant :

1. Utiliser un appelant et une cible entièrement fictifs ; activer AgentAdmin pour l'appelant
   et vérifier que la génération est disponible.
2. Donner à la cible une civilité et un profil HTML descriptif distincts de ceux de l'appelant,
   puis demander un portrait photographique avec `agent_avatar_generate`.
3. Attendre la réponse `registered=true` ; vérifier le modèle image de l'appelant,
   les traits décrits de la cible et la conservation de ses champs HTML.
4. Vérifier le portrait dans l'UI après navigation et réouverture, puis son remplacement
   par une deuxième génération réussie.
5. Ne pas resoumettre automatiquement un appel interrompu ; publier uniquement
   les conclusions techniques et mesures agrégées, sans profil réel ni capture individuelle.

Réception : portrait photographique exploitable, persisté par un fournisseur authentifié
et visible à la réouverture. Les garanties synthétiques de suivi, remplacement, conflits
tardifs et révocation ne prouvent pas la qualité photographique du fournisseur.
