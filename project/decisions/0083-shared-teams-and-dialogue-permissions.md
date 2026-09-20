# 0083 — Équipes communes et autorisations de dialogue

Statut : accepté. Date : 10 septembre 2026. Simplifié le 11 septembre 2026 sur demande utilisateur.

## Modèle

`core.team` possède une notion unique d’équipe, son catalogue, les appartenances humaines
et le journal des changements. `app.agent` possède les appartenances des agents et les
résolution du droit de contact. Le modèle d’appartenance `AgentTeam` réside dans `models.py`.
Les quatre modèles de règles de dialogue et leurs écrans sont supprimés.
Un humain ou un agent peut appartenir à plusieurs équipes, sans
imbrication. Les équipes ne deviennent pas des rôles RBAC.

La table historique `agent_groups` conserve ses identifiants et ses références. L’action
DbAdmin `app.agent.team_memberships` reprend les appartenances `agents.group_id` dans
`agent_teams` de façon idempotente. Le champ historique reste compatible avec les anciens
clients ; les nouvelles interfaces utilisent les appartenances multiples. Aucun humain
n’est ajouté automatiquement à une équipe lors de cette reprise.

## Résolution

Pour un humain actif : management global (`AGENT_MANAGE_ALL`, dont dispose l’administrateur),
manager de l’agent ou équipe commune. Sans l’un de ces trois cas, le dialogue est refusé.
Aucune exception individuelle, liaison entre équipes ou règle héritée n’est conservée.

Pour deux agents : une équipe commune permet le dialogue dans les deux sens.
Les accès ne sont jamais transitifs. Le retrait de la dernière équipe commune révoque le contact.
Les documents conservent leur politique distincte de partage individuel/par équipe et de
lecture/modification ; cette simplification ne modifie pas leurs ACL.

Le droit de dialogue ne donne ni management, ni impersonation, ni accès aux conversations
d’autres humains. Les privilèges du canal restent requis. Il permet de solliciter les capacités
configurées de l’agent ; il ne cloisonne pas à lui seul sa mémoire ou ses outils par interlocuteur.

## Points de contrôle

La résolution est partagée par le Chat texte, les API compatibles OpenAI et Janus,
les notifications, les émissions de la façade Messenger et la délégation MCP `task_run`.
Les messages entrants utilisent les liens humains/agents de l’identité canonique persistée,
avec la connexion du serveur comme source de l’agent destinataire. Une identité externe
non rattachée ou absente ne peut pas engager un dialogue avec l’agent. Cette règle concerne
aussi les messages humains reçus par un canal asynchrone.

Une révocation interdit les nouveaux envois et délégations, filtre les émissions websocket,
annule la notification push avant envoi et termine le flux API avant son prochain fragment.
Les appels audio dépendent uniquement de `CHAT_CALL`, vérifié au plus toutes les secondes
pendant les échanges. L’accès reste limité à la conversation personnelle interne de l’appelant.
Les événements vocaux suivent ce privilège, sans accorder les événements de chat texte.
Une tâche déjà admise poursuit son cycle ; l’historique personnel est conservé en lecture
seule pour le dialogue. Les préférences personnelles et les opérations documentaires
restent soumises à leurs privilèges propres. Les identifiants de session API sont isolés par
utilisateur, même si deux clients envoient le même `conversation_id`.

Une autorisation ne crée pas un nouveau transport. Les échanges utilisent les capacités
des canaux configurés ; notamment le Chat natif reste un canal humain ↔ agent.

## Administration et revue des dépendances

`TEAM_ACCESS`, `TEAM_EDIT` et `TEAM_MEMBERS_EDIT` séparent lecture du catalogue, édition
et composition. Les anciens privilèges `AGENT_AUTHORIZATION_ACCESS` et
`AGENT_AUTHORIZATION_EDIT` sont retirés. Toute mutation exige aussi le privilège de lecture.
Les changements d’équipe et d’appartenance enregistrent leur avant/après avec
l’acteur et l’horodatage dans `team_audit`.

Le frontend compose les écrans d’équipe et les onglets utilisateur par contributions des
modules actifs. La fiche équipe présente uniquement ses membres humains et agents. Les
anciens onglets d’autorisations des agents et des utilisateurs sont supprimés.
La liste présente les effectifs humains et agents et les avatars des petites équipes.
La création et la modification regroupent les membres dans une grande modale à deux
colonnes ; les changements d’appartenance restent locaux jusqu’à l’enregistrement.
L’ordre des équipes se règle par déplacement dans la liste et se persiste par une opération
dédiée, atomique et protégée par `TEAM_EDIT`. Le formulaire ne transmet plus de position :
une modification de nom ou de membres ne rétablit pas un ordre périmé. Une nouvelle équipe
est ajoutée en fin de liste. La poignée est utilisable à la souris, au toucher et au clavier.
`AgentSelect` et `AgentAvatar` acceptent les métadonnées du catalogue sans charger la
configuration des agents. Le droit de lecture du catalogue permet aussi de lire leurs
avatars, sans conférer le management de l’agent.

Revue de dépendance du 11 septembre : `core/team` consomme les nouveaux exports publics
`UserSelect` et `UserAvatar` de `core/user`. Cette unique arête d’infrastructure est ajoutée
à la baseline frontend ; elle ne crée aucun cycle ni import de domaine applicatif depuis
`core`. La contribution des agents reste fournie par `app/agent`.

Revue explicite des six nouvelles dépendances frontend : `app/agent` consomme
les contrats publics de `core/team` et `core/user` pour ses contributions ; `core/team`
consomme les surfaces publiques de `core/api`, `core/authorize`, `core/navigation` et
`core/util`. Ces dépendances d’infrastructure ne créent ni cycle ni import métier depuis
`core`. Leur ajout à la baseline est limité à ces six arêtes ; aucune dette d’import privé
n’est ajoutée.

Après simplification du 11 septembre, la contribution utilisateur des agents disparaît :
`app/agent → core/user` est retirée de la baseline. Les cinq autres dépendances restent utiles.

Les tests d’exception et de priorité sont abandonnés avec ce contrat. Les garanties conservées
couvrent équipe commune, manager, accès global, non-transitivité, persistance, reprise
idempotente, refus HTTP, historique privé après révocation, refus avant transport et
admission, interruption de streaming et délégation, ainsi que les interactions des écrans.

## Partage documentaire et mémoire par les agents

Les ACL fines s’appliquent également aux outils MCP : `document_share` conserve son appel
historique par agent et accepte maintenant un humain ou une équipe ; `memory_share` expose
la même mutation pour les items mémoire. `memory_sharing` fournit les droits courants, le
verrou et un catalogue filtrable/paginé des destinataires. Une mutation cible exactement un
destinataire et conserve les autres droits, sans créer de révision du contenu HTML.

Le propriétaire agent est vérifié directement, sans prendre l’identité de son manager.
Un droit d’écriture reçu ne permet pas de repartager ; les objets immuables ou gérés par
une source restent protégés. Les équipes utilisent les mêmes grants et appartenances
vivantes que l’interface, pour leurs membres humains comme IA. Les managers humains restent
des destinataires valides : `Agent.user_id` n’est pas un compte de service à exclure.

Le skill système et les descriptions MCP distinguent les fragments HTML éditoriaux
(documents, contenus Memory, objectifs Task, description/suivi Goal, profils Agent) des
titres, messages de transport, fichiers Markdown, skills et ressources JSON/binaires.

## Gestion des tâches et sélection commune des agents

Précision du 11 septembre : une équipe commune donne le dialogue, pas la gestion des
tâches. Les routes humaines réservent cette gestion aux managers de l’agent et aux
administrateurs globaux. Les outils d’un agent ne gèrent que ses propres tâches ; une
connexion **active** `galaris_admin` ouvre le périmètre global des tâches, y compris leur
lecture, recherche, arrêt et délégation. Cette autorité est relue à chaque opération.
Les garde-fous du workflow (états terminaux, arrêt de sa propre exécution, etc.) restent
applicables. Le demandeur d’une délégation conserve sa lecture pour en suivre le résultat,
sans acquérir la gestion de toutes les tâches du destinataire. Une création HTTP vérifie
aussi le périmètre du parent, de la source, du demandeur et de l’objectif référencés.

`AgentSelect` filtre systématiquement les options de ses consommateurs avec le catalogue
minimal `/agents/selection`. Le périmètre explicite est `management` par défaut,
`dialogue` pour le chat ou `teams` pour composer une équipe. Ces catalogues utilisent les
mêmes résolveurs serveur que les opérations ; ils ne renvoient pas la configuration des
agents. Les changements de session, de privilèges ou de périmètre et l’ouverture du menu
rafraîchissent les droits. Un refus retire les options et la sélection obsolètes ; une
réponse ancienne ne peut pas rétablir les choix d’un autre contexte. Les filtres métier
des pages, leurs options neutres et les avatars propres au transport sont conservés.

Revue de dépendance : `app/chat → app/agent` est ajoutée pour réutiliser l’export public
`AgentSelect` dans la création de conversation. Aucun import privé ni cycle n’est ajouté.
L’invalidation de session utilise l’événement public de `core/api`, déjà consommé par
`app/agent`, sans introduire de dépendance supplémentaire vers `core/user`.
