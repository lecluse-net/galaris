# 0274 — Capacités et protocoles des Tools fournisseurs

Statut : accepté, implémenté.

Complétée par [0278 — Agendas personnels](0278-personal-agendas-and-goal-boundaries.md) :
les sources externes restent optionnelles, avec un agenda personnel natif par défaut.

## Décision

Un Tool représente un service ou fournisseur, par exemple Ionos. MCP, API, partage,
messagerie, Listener, Mail et Calendrier sont ses capacités fonctionnelles. Un protocole
est la déclinaison technique d'une capacité : HTTP/SSE/stdio pour MCP, REST pour API,
AFFiNE/Nextcloud/Samba pour le partage, IMAP & SMTP pour Mail et iCal pour Calendrier.
Un Tool peut cumuler des capacités différentes, mais sélectionne un seul protocole par
capacité. Le catalogue propose plusieurs protocoles pour une même capacité.

Les capacités sont des codes chaînes ouverts, sans enum. Chaque protocole du catalogue
expose sa chaîne `capability`. Les sélections du Tool sont conservées dans `capabilities`
sous forme d'identifiants `protocole.capacité`, par exemple `http.mcp` ou `imap_smtp.mail`.
Les configurations typées existantes conservent les réglages d'exécution ; la liste et les
configurations doivent être cohérentes. Les anciens clients qui omettent cette liste restent
acceptés. Les identifiants externes restent conservés lors des modifications et exports.
Les libellés standards du catalogue sont des clés i18n ; les libellés et identifiants externes
sont affichés littéralement. Une chaîne inconnue ne crée pas à elle seule un adapter d'exécution.
La liste des Tools montre uniquement leurs capacités en badges Quasar, avec fond transparent,
texte et bordure d'une même couleur. Les onglets distinguent leur origine sans badge redondant. Dans le
formulaire, un bouton complet « Ajouter un protocole » est affiché en l'absence d'onglet ;
il devient « + » après le premier choix. Il ouvre un menu déroulant de protocoles groupés
par capacité, ancré au bouton. Le choix ajoute et active l'onglet de configuration.
Les autres protocoles de la même capacité sont alors indisponibles. Le terme « capacité »
n'apparaît pas dans le formulaire : les groupes servent d'en-têtes visuellement distincts.
Chaque option affiche son protocole sans répéter le nom du groupe.
La saisie libre de protocole n'est pas proposée ; les futurs plugins alimenteront ce catalogue.
Mail et Calendrier quittent les définitions intégrées et deviennent deux configurations
optionnelles `mail_config` et `calendar_config`. Leur présence active le protocole ; leurs
champs fixes sont dans `settings` et les références aux paramètres de connexion dans
`param_map`, comme pour OneBot. Les mots de passe restent dans les paramètres de connexion
chiffrés. IMAP et SMTP constituent une seule entrée Mail, présentée en deux sections.
Le catalogue fournit les champs fixes et les rôles à associer. L'éditeur standard crée un
paramètre uniquement sur demande explicite et propose des noms génériques : `email`, `login`,
`password`, `folders`, `user_id`. Plusieurs champs ou protocoles peuvent réutiliser le même
paramètre. Les identifiants IMAP et SMTP peuvent ainsi être communs ou différents.
Les dossiers autorisés utilisent un paramètre à choix multiples dont l'arborescence est
chargée depuis une connexion IMAP enregistrée et authentifiée. Les configurations historiques
vides conservent la lecture des anciens paramètres globaux et locaux.
Une erreur conserve le formulaire, sans création partielle ni seconde modale de configuration.

iCal suit le même mécanisme : URL privée de type `password`, identifiant HTTP et mot de passe
référencent les paramètres standards `url`, `login` et `password`. Les options propres à
la source (libellé et propriétaire) peuvent également y être liées.
Aucun formulaire dédié de source n’est nécessaire. `CalendarFeed` conserve l’identité durable
et l’historique de synchronisation, projetés depuis les paramètres au premier usage ou au CRON.
Un mapping reprend le premier feed historique ; les feeds supplémentaires restent conservés.
Les autorisations des fonctions MCP contrôlent lecture et mutations, sans mode d’accès parallèle.
Seules les notifications VALARM créent une tâche contenant les informations de l’événement.
Le début d’un événement ne déclenche aucune tâche et Calendar ne lance plus de Process directement.
Une tâche peut lancer le Process pertinent par ses outils habituels. Les anciens réglages de
déclenchement, d’action, de workflow et d’instructions sont retirés ; leur stockage historique
est conservé sans effet d’exécution.
La supervision consulte les sources, teste la synchronisation et liste chaque occurrence de rappel
avec sa tâche et son état réel. Un reçu de création réussi ne vaut pas traitement : seule la phase
Task `SUCCESS` marque la relance comme traitée. Les occurrences récurrentes ont des suivis distincts.

Les fonctions MCP conservent leurs noms publics `mail_*` et `calendar_*`. Leur famille est
résolue à partir du protocole, indépendamment du code du fournisseur. Une sélection explicite
`connection_id` lie autorisation et exécution à la même connexion active de l'agent ; une
ambiguïté est refusée. Les ressources Mail utilisent le code du Tool. Si le Tool possède aussi
un partage de fichiers, le préfixe `mail/` réserve son espace Mail. Les curseurs du polling Mail
et de la messagerie sont séparés lorsqu'ils partagent une connexion.

La navigation dans les URI d'un fournisseur personnalisé conserve les contrôles Fichiers
existants, auxquels s'ajoute le contrôle Mail du transport. Les anciennes URI `mail://`
conservent leur contrôle Mail. Ce changement ne redéfinit pas les privilèges transversaux
de la bibliothèque de fichiers.

## Migration

### Plusieurs comptes Mail par fournisseur

Un Tool Mail peut avoir plusieurs connexions pour un même agent. L'unicité des autres Tools
reste garantie en base par `(tool_id, agent_id, singleton_key)` : la clé interne vaut zéro
par défaut, et `NULL` pour les nouvelles connexions Mail. Les connexions existantes sont
conservées. Les créations restent sérialisées par le verrou du Tool. Retirer Mail avec des
doublons est refusé ; sans doublon, les connexions retrouvent la clé d'unicité zéro.
Les opérations qui ne reçoivent que le couple agent/Tool refusent une sélection ambiguë.
Les ressources Mail nouvelles portent `account/<connection_id>/` dans le locator. À la racine
du fournisseur, plusieurs comptes sont présentés comme des répertoires distincts ; la
résolution vérifie chaque fois l'agent, le Tool et l'activation de la connexion.

L'action DbAdmin `app.tools.mail_calendar_protocols` est déclenchée par l'ajout des nouvelles
colonnes. Elle transforme les anciennes lignes `mail` et `calendar` en Tools personnalisés
en conservant leurs clés, libellés, connexions, activations, valeurs globales, secrets,
autorisations, reçus Mail et ressources CalendarFeed. Les anciennes configurations de transport
Mail deviennent des capacités dérivées du protocole. Aucun déplacement de connexion ni nouvelle
activation n'est nécessaire. Les libellés peuvent ensuite identifier le fournisseur.

Les installations neuves ne créent plus ces anciennes lignes. Les datasets ne les possèdent
plus et ne les recréent pas après suppression. Une synchronisation ordinaire ne rejoue pas
la migration et ne rétablit pas un protocole désactivé par l'administrateur.

L'action `app.tools.capability_selections`, après les datasets, initialise la liste depuis
les configurations existantes à l'ajout de la colonne `tools.capabilities`. Elle ne réécrit
aucun accès, secret ou paramètre. Les doublons de capacité et les incohérences entre liste
et configuration sont refusés à l'écriture.

## Vérification

### Diagnostics et autorisations d’une connexion

Le catalogue Tools possède un port de sonde par protocole, enregistré par son domaine
propriétaire. Le test administratif résout les paramètres enregistrés côté serveur,
borne chaque sonde et ne modifie ni activation ni règles de permission. Un protocole
sans sonde renvoie un résultat non vérifié, jamais une réussite implicite. Les erreurs
externes ne sont pas renvoyées brutes. L’éditeur réutilise la projection et le tableau
de la page Permissions ; un filtre serveur limite la découverte à la connexion choisie,
y compris inactive, sans élargir les droits de gestion de l’agent.

Les tests de protocoles couvrent la composition Mail/Calendrier, les connexions et secrets
indépendants, les refus de sélection ambiguë ou étrangère et la conservation des identités
et données lors de la migration idempotente. Les scénarios de composants vérifient création,
paramètres partagés, réouverture et désactivation indépendante des protocoles.
