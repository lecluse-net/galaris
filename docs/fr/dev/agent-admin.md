<p align="right"><strong>Français</strong> · <a href="../../en/dev/agent-admin.md">English</a></p>

# AgentAdmin

AgentAdmin (`agent_admin`) est un Tool intégré optionnel de 34 fonctions. Sa connexion
est créée inactive ; une synchronisation du catalogue ne réactive jamais une connexion
désactivée. Un humain l’active dans **Configurer → Outils & connexions → Connexions**.
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
de fonctions sont locales (`default`, `enabled`, `disabled`) et ne modifient pas les règles
globales. Un couple agent/Tool ne possède qu’une connexion. La suppression des groupes
détache le groupe historique et révoque les accès associés ; une civilité référencée ne
peut pas être supprimée, y compris lorsqu’un agent archivé la référence encore.

Les harnais utilisent les workflows de sélection, de nettoyage et de blocage existants.
Une action n’est admissible que si le fournisseur et l’état courant la proposent.
Les résultats distinguent `completed`, `in_progress` et `error`. Les logs sont bornés
à 5 000 lignes, 2 000 caractères par ligne et 200 000 caractères au total, avec expurgation
des credentials et chemins. Les tâches bloquantes sont référencées par URI complète ;
aucune commande d’arrêt de tâche n’est fournie.

## Portrait généré et suivi

Seule `agent_avatar_generate` disparaît lorsque l’usage image du profil effectif de
l’appelant n’est pas configuré avec un modèle produisant des images, un fournisseur actif
et les credentials requis par son profil fournisseur. Ce contrôle local ne vérifie pas
la validité des credentials auprès du fournisseur.
Un profil hérité convient ; le modèle de chat ou celui de l’exécuteur ne sert jamais de repli.
La disponibilité est réévaluée à la découverte et à l’appel, même dans une session conservée.

Le portrait utilise le prénom, le nom, le genre de la civilité, la personnalité et le poste
de la cible. Le HTML est lu comme texte descriptif et reste inchangé en base. Les instructions
facultatives, au plus 4 000 caractères, précisent apparence, cadrage ou ambiance.

La réponse initiale contient `registered=false`, `status`, `run_id`, l’URI du workflow et
un `follow_up` indiquant `process_get_run`. Le service système Galaris permet donc le suivi
sans attribuer ProcessAdmin. Le succès final contient `registered=true` et l’URI de la cible.
Ces workflows techniques restent absents du catalogue des processus métier.

Un Process fige le modèle image de l’appelant, l’empreinte de sa configuration fournisseur,
le responsable, la description de la cible et sa révision d’avatar. Une marque durable précède
l’appel fournisseur : une interruption au résultat incertain devient `unknown` sans nouvelle
soumission automatique. Avant publication, les droits, la cible et les empreintes sont revérifiés.
L’image, son reçu et le succès du Process sont persistés ensemble. Un résultat tardif, une
révocation, une suppression ou une modification du profil produit un échec et conserve l’état courant.

`agent_avatar_set` lit une URI canonique autorisée avec `app.file_share` dans un temporaire
borné, ensuite nettoyé. Upload, URI et génération partagent le décodage réel JPEG/PNG/GIF/WebP,
la limite de 15 Mio et les limites de dimensions (16 millions de pixels, 8 192 par côté).
Avant chaque enregistrement, le module Agent applique l’orientation EXIF puis convertit
l’image en JPEG optimisé (qualité 85), avec un maximum de 512 × 512 pixels, proportions
conservées, sans recadrage ni agrandissement. La transparence devient un fond blanc,
les animations utilisent leur première image et les métadonnées EXIF sont retirées.
Cette conversion s’applique au POST HTTP, aux URI et aux portraits générés.
Une révision monotone protège aussi contre un avatar remplacé puis restauré. Les lecteurs UI
utilisent cette révision pour charger le nouvel avatar à la réouverture.

## Vérification

`back/app/agent/tests/test_agent_admin.py` vérifie le parcours CRUD sans contexte HTTP,
le périmètre, les protections des connexions, les 34 fonctions, la révocation et la disponibilité
image sur un serveur monté, ainsi que la publication durable et ses issues d’échec.
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
