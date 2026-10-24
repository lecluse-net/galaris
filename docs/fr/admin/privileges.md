<p align="right"><strong>Français</strong> · <a href="../../en/admin/privileges.md">English</a></p>

# Déléguer les droits par fonction

Dans **Administrer → Rôles & autorisations** (`/authorize`), choisissez le rôle à modifier
et attribuez les privilèges utiles. L'affectation utilisateur/rôle détermine le rôle actif ;
les catégories servent uniquement à ranger les privilèges. Elles n'accordent aucun droit.
Vérifiez le rôle affiché dans le menu du compte avant d'examiner un refus d'accès.

## Séparer consultation, modification et périmètre

Les domaines suivants se délèguent indépendamment. Lorsqu'une route accepte son droit de
consultation **ou** son droit de modification, un opérateur peut lire ce qu'il modifie sans
recevoir implicitement un autre privilège. Les droits sur la ressource et le périmètre des
agents gérés restent nécessaires ; `AGENT_MANAGE_ALL` est une délégation distincte.

| Fonction | Consultation | Modification ou contrôle |
|---|---|---|
| Agents | `AGENT_ACCESS` | `AGENT_EDIT` |
| Contacts | `CONTACT_ACCESS` | `CONTACT_EDIT` |
| Souvenirs personnels | `MEMORY_ACCESS` | `MEMORY_EDIT`, administration `MEMORY_ADMIN` |
| Documents | `DOCUMENT_ACCESS` | `DOCUMENT_EDIT`, administration `DOCUMENT_ADMIN` |
| Jeux de données | `DATASET_READ` | `DATASET_EDIT`, administration `DATASET_ADMIN` |
| Fichiers | `FILE_ACCESS` | `FILE_EDIT` |
| Indexation des fichiers | `FILE_INDEX_ACCESS` | `FILE_INDEX_RUN` |
| Tableau de bord | `DASHBOARD_ACCESS` | — |
| Supervision Dream | `DREAM_ACCESS` | Réglages séparés ci-dessous |
| Permissions | `PERMISSION_ACCESS` | `PERMISSION_DECIDE`, `PERMISSION_REVOKE` |
| Fournisseurs IA | `LLM_PROVIDER_ACCESS` | `LLM_PROVIDER_EDIT` |
| Modèles configurés | `LLM_MODEL_ACCESS` | `LLM_MODEL_EDIT` |
| Profils LLM | `LLM_PROFILE_ACCESS` | `LLM_PROFILE_EDIT` |
| Appels LLM | `LLM_CALL_ACCESS` | `LLM_CALL_CONTROL`, purge `LLM_CALL_PURGE` |
| Tâches | `TASK_ACCESS` | `TASK_EDIT`, purge `TASK_PURGE` |
| Historique texte | `CONVERSATION_ACCESS` | `CONVERSATION_CONTROL` |
| Historique vocal | `VOICE_HISTORY_ACCESS` | `VOICE_HISTORY_CONTROL` |
| Configuration partagée des harnais | `HARNESS_CONFIG_ACCESS` | `HARNESS_CONFIG_EDIT` |
| Processus | `PROCESS_READ` | `PROCESS_EDIT`, lancement `PROCESS_LAUNCH`, administration `PROCESS_ADMIN` |
| Catalogue des outils | `TOOL_ACCESS` | `TOOL_EDIT` |
| Connexions | `CONNECTION_ACCESS` | `CONNECTION_EDIT` |
| Journal des mails | `MAIL_ACCESS` | `MAIL_EDIT` ; décisions d'envoi : aussi `PERMISSION_DECIDE` |
| Calendriers | `CALENDAR_ACCESS` | `CALENDAR_EDIT` |
| Compétences | `SKILL_ACCESS` | `SKILL_EDIT`, affectations `SKILL_ASSIGN` |

Oublier un contact avec ses souvenirs exige **à la fois** `CONTACT_EDIT` et `MEMORY_EDIT`.
La supervision Dream exige aussi la gestion globale des agents ; régler Dream n'ouvre pas
ses reçus. Les actions sur le runtime d'un agent utilisent les droits Agents et leur
périmètre ; certaines opérations globales sur les harnais exigent aussi une gestion globale.
Les commandes de déblocage d'une Task conservent leurs droits Tâches.

Les onglets Fournisseurs, Modèles disponibles et Modèles utilisés suivent respectivement
les droits fournisseur, modèle et profil. Les métadonnées nécessaires à un sélecteur sont
disponibles de manière ciblée : voir un nom de fournisseur depuis un modèle ne permet pas
d'en modifier les identifiants. Installer ou supprimer un modèle sur le serveur du
fournisseur reste une opération `LLM_PROVIDER_*`.

Dans **Superviser → Permissions**, décider une demande, autoriser une fonction ou rétablir
son héritage exige `PERMISSION_DECIDE`. Bloquer, remettre sur demande ou révoquer utilise
`PERMISSION_REVOKE`. L'identité de l'approbateur et la session web restent contrôlées.
La gestion des paramètres d'une connexion ne remplace aucun de ces droits.

Le Journal des mails conserve son contrôle du valideur désigné. Approuver ou rejeter un envoi
exige une session web et les droits `MAIL_EDIT` et `PERMISSION_DECIDE`. Les calendriers se
consultent et se configurent dans **Superviser → Calendriers** (`/connection/calendars`),
sur les connexions du périmètre géré ; créer la connexion reste une opération Connexions.

## Déléguer une rubrique de Préférences

L'API des paramètres applique une politique par clé. `PARAMS_ACCESS` et `PARAMS_EDIT`
concernent les paramètres système ; ils ne donnent pas un accès général à tous les réglages.
Pour chaque famille ci-dessous, le droit de modification permet aussi de consulter ses valeurs.

| Famille de réglages | Consultation | Modification |
|---|---|---|
| Système : inscriptions, limitation HTTP | `PARAMS_ACCESS` | `PARAMS_EDIT` |
| Langue et localisation | `LANGUAGE_CONFIG_ACCESS` | `LANGUAGE_CONFIG_EDIT` |
| Messagerie | `MESSAGING_CONFIG_ACCESS` | `MESSAGING_CONFIG_EDIT` |
| Mémoire et sessions | `MEMORY_CONFIG_ACCESS` | `MEMORY_CONFIG_EDIT` |
| Dream et prompts de classement/extraction | `DREAM_CONFIG_ACCESS` | `DREAM_EDIT` |
| Voix | `VOICE_CONFIG_ACCESS` | `VOICE_CONFIG_EDIT` |
| Audio | `AUDIO_CONFIG_ACCESS` | `AUDIO_CONFIG_EDIT` |
| Processus | `PROCESS_CONFIG_ACCESS` | `PROCESS_CONFIG_EDIT` |
| Tâches, planner et délai des appels LLM | `TASK_CONFIG_ACCESS` | `TASK_CONFIG_EDIT` |
| Harnais, manager et entrées binaires | `HARNESS_CONFIG_ACCESS` | `HARNESS_CONFIG_EDIT` |
| Recherche web | `SEARCH_CONFIG_ACCESS` | `SEARCH_CONFIG_EDIT` |
| Janus | `JANUS_CONFIG_ACCESS` | `JANUS_CONFIG_EDIT` |
| Instructions des exécuteurs | `INSTRUCTION_CONFIG_ACCESS` | `INSTRUCTION_CONFIG_EDIT` |
| Journalisation, rétention et token Logfire | `LOG_CONFIG_ACCESS` | `LOG_CONFIG_EDIT` |
| Navigateur | `BROWSER_CONFIG_ACCESS` | `BROWSER_CONFIG_EDIT` |
| Réglages des objectifs | `GOAL_CONFIG_ACCESS` | `GOAL_CONFIG_EDIT` |
| Profil LLM par défaut | `LLM_PROFILE_ACCESS` | `LLM_PROFILE_EDIT` |

Les secrets restent masqués et chiffrés. Les clés internes de signature et Web Push ne sont
pas exposées par cette API. La référence exécutable est
[`core.params.access`](../../../back/core/params/access.py) ; le frontend en dérive les
droits de chaque champ. Un refus via une route spécialisée ne peut pas être contourné par
une écriture sur l'API générique des paramètres.

## Autres fonctions et exceptions

Les Objectifs et Sujets ont leurs paires `GOAL_ACCESS`/`GOAL_EDIT` et `TOPIC_ACCESS`/`TOPIC_EDIT`.
Les Équipes distinguent consultation, modification et composition (`TEAM_ACCESS`, `TEAM_EDIT`,
`TEAM_MEMBERS_EDIT`) ; modifier une équipe conserve aussi son droit de consultation.
Chaque rubrique du Laboratoire possède sa propre paire lecture/écriture, indépendante des
contenus Task, Process ou Conversation utilisés pour les évaluations. Les incidents
utilisent `INCIDENT_ACCESS`/`INCIDENT_EDIT`, avec `INCIDENT_PURGE` distinct.

Le Chat distingue lecture, envoi, gestion, appel et changement de locuteur. Les utilisateurs
conservent leurs quatre droits CRUD ; rôles, privilèges et affectations ont chacun leur
paire de consultation/gestion. L’IDE (`CODE_ACCESS`) et les accès API sont des capacités
d’exécution ; ils ne promettent pas une interface de code en lecture seule. Les fonctions
du compte personnel restent réservées au propriétaire authentifié.

Mail (`MAIL_ACCESS`/`MAIL_EDIT`) et calendriers (`CALENDAR_ACCESS`/`CALENDAR_EDIT`) sont
indépendants des Connexions. Dans une vue Sujets, voir les objectifs Task, historiques,
souvenirs, Documents ou Datasets exige aussi les droits du domaine source. Les opérations
globales de classement déplacent les liens de sujet sans ouvrir ni modifier leur contenu.

## Distinguer accès aux fichiers et accès à leur source

L'explorateur est un transport commun : il applique les droits du domaine de l'URI demandée
et ceux du provider. `FILE_ACCESS` n'ouvre ni les Documents ni les Datasets. Consulter une
pièce jointe autorisée d'un Document n'exige pas un accès global aux Fichiers. Les liens
médias revérifient la session, le rôle, l'agent et la source à chaque lecture, y compris
partielle. Un lien partagé ne donne jamais les droits manquants.

Les autorisations de fonction MCP et les portées locales `tools.management_scope` constituent
encore des contrôles distincts. Voir [l'administration des outils](tool-administration.md)
et [le partage des ressources](../dev/sharing.md).

## Organiser les catégories et mettre à jour les rôles

Les catégories initiales sont traduites tant que leur libellé reste celui fourni par le
logiciel. Un renommage devient du texte libre. Avec `MANAGE_PRIVILEGE`, déplacer un privilège
ou supprimer une catégorie modifie son classement, sans retirer les droits des rôles.
Les synchronisations suivantes conservent renommages, déplacements, désaffectations et
catégories supprimées : l'initialisation est enregistrée une seule fois par catégorie.

La séparation des anciens droits larges dispose d'une reprise ponctuelle des rôles existants,
décrite dans la [décision 0233](../../../project/decisions/0233-functional-domain-privileges.md)
et implémentée dans
[`domain_projection.py`](../../../back/core/authorize/domain_projection.py).
Elle ne constitue pas une équivalence permanente entre les anciens et les nouveaux droits.
Les nouveaux rôles doivent être configurés explicitement ; un droit révoqué n'est pas
réattribué à la synchronisation suivante. Les droits de réglages supplémentaires doivent
être vérifiés dans chaque rôle personnalisé. L'administrateur conserve tous les privilèges
déclarés ; aucun périmètre global supplémentaire n'est déduit pour les autres rôles.

La reprise des réglages, de Mail et des calendriers est décrite dans la
[décision 0235](../../../project/decisions/0235-functional-settings-and-source-authorization.md).
Un ancien approbateur Mail en lecture seule doit recevoir explicitement `MAIL_EDIT` et
`PERMISSION_DECIDE` pour décider depuis le journal. Les réglages globaux des objectifs
conservent aussi `AGENT_MANAGE_ALL` ; leur API générique ne permet pas de contourner cette portée.

En développement, `make sync-db` synchronise les déclarations. Pour un déploiement, utilisez
`make update`. Après mise à jour, vérifiez un rôle de consultation et un rôle opérateur dans
les parcours réellement délégués. La [cartographie générée](../architecture/generated/project-map.md)
recense le catalogue courant sans figer son nombre dans les guides.
