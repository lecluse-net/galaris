<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/calendar.md">English</a></p>

# Agenda local, fournisseurs et exécution des actions

`app.calendar` possède le modèle canonique des agendas internes et externes. Chaque agent
possède un unique **Agenda** système (`calendar`) créé automatiquement, sans compte
externe ; il ne peut pas être désactivé ou supprimé. Les anciens agendas internes supplémentaires
restent accessibles, sans possibilité d'en créer de nouveaux. `bridge.calendar` traduit
CalDAV, Google Agenda, Microsoft 365 / Outlook, iCloud et les abonnements iCalendar ;
la représentation canonique des événements reste **iCalendar** (`VEVENT`,
récurrences, exceptions et `VALARM`). Un abonnement à un fichier iCalendar est en lecture seule.

## Configuration et droits

DbAdmin renomme `agenda` en `calendar` sur la ligne existante. Un ancien fournisseur qui
occupe ce code reçoit un code `calendar-provider` disponible et conserve ses connexions.

La capacité fournisseur est `caldav.calendar`. `calendar_config.settings` porte le type de
source (`caldav`, par défaut, `ical`, `google`, `microsoft` ou `icloud`), le fuseau et les préférences de créneaux.
`calendar_config.param_map` référence les paramètres de connexion standards pour `url`,
`username`, `password`, et éventuellement le libellé et le propriétaire. L'URL privée et le
mot de passe utilisent des paramètres chiffrés de type `password` ; les valeurs suivent
l'héritage et les valeurs imposées des connexions. Aucun formulaire parallèle de secrets
n'appartient à l'Agenda. Les agendas externes sont matérialisés depuis ces paramètres et
la découverte fournisseur. L'API refuse la création d'agendas internes supplémentaires.
Le rôle `sync_interval_hours` référence un paramètre entier de connexion, commun à tous
ses agendas, avec héritage global/local : deux heures par défaut, de 1 à 8760 heures.
Google et Microsoft utilisent le consentement OAuth du compte ; iCloud un mot de passe
d'application. La configuration détaillée est décrite dans le [parcours Agenda](../../user/calendar.md).

`CALENDAR_ACCESS` ou `CALENDAR_EDIT` autorise la consultation dans le périmètre de gestion
de l'agent. `CALENDAR_EDIT` autorise les commandes ; les capacités distantes restent
contraignantes. Les fonctions MCP gardent leurs politiques globales/locales et leur connexion
active. Un calendrier explicite est recoupé avec son agent et sa connexion, avant l'exécution.
Une désactivation exclut la source et ses actions des workers. Le détail d'une Task conserve
ses droits propres. Lire une ressource ne donne pas ses droits d'écriture.

Les URL, identifiants, contenus et instantanés sont chiffrés au repos. Seules les métadonnées
nécessaires aux index, dont les bornes temporelles et les identités, sont directement interrogeables.
Le bridge conserve HTTPS, validation/épinglage d'une adresse publique à chaque requête et
redirection, limites de réponse et absence de transfert d'identifiants vers une autre origine.

## Modèle et historique

- `calendar_feeds` : agenda, connexion, fuseau, capacités, curseur de synchronisation et bail.
- `calendar_events` : événement unique ou maître d'une série, composant iCalendar chiffré,
  révision, correspondance distante et ETag. Une table `remote_object` n'est pas nécessaire.
- `calendar_event_exceptions` : composants d'exception associés à leur identité d'origine.
- `calendar_event_revisions` : instantanés immuables de chaque révision, suppression comprise.
- `calendar_occurrences` et `calendar_projection_windows` : projections locales reconstruisibles,
  indexées par agenda et plage temporelle. Les longs textes ne sont pas dupliqués par occurrence.
- `calendar_actions` : consigne locale, ancrage début/fin, décalage signé, portée et retard maximal.
- `calendar_triggers` : exécution d'une action pour une occurrence, échéance et lien vers sa Task.
- `calendar_sync_operations` : outbox des écritures/suppressions, état, version et essais.
- `calendar_sync_runs` : journal durable des passages, étapes et échecs, y compris les lectures.

Agendas et événements utilisent `HistoryMixin` et la suppression logique. Les exceptions sont
incluses dans les instantanés de l'événement. Les projections se reconstruisent et se purgent,
sans suppression des événements, révisions, reçus ou Tasks. DbAdmin fait converger le schéma et
les données système ; la synchronisation des rendez-vous reste une opération métier.
Aucune migration de données d'agenda n'est requise : cette refonte précède leur première utilisation.

## Consultation locale par période

L'API et les outils ne contactent jamais le fournisseur pour lire, créer ou modifier un rendez-vous.
`GET /calendars/events` accepte l'agent et les agendas sélectionnés, avec `period=month`, `week`,
`day` ou `next30`. `month=YYYY-MM` choisit un autre mois ; des bornes `start`/`end` explicites
permettent la navigation. Les bornes sont calculées dans le fuseau d'affichage, en tenant compte
des changements d'heure. La période est limitée à un mois ; tous ses événements sont renvoyés,
avec `total`, `complete` et les sources périmées, sans pagination ni troncature silencieuse.
Une limite de protection de 10 000 occurrences demande une plage plus courte en cas de dépassement.
La lecture utilise une recherche d'événement par clé primaire pour chaque occurrence et déduit
le total de la réponse complète, sans comptage séparé. Elle évite ainsi une jointure sur tout
l'historique lorsque les statistiques PostgreSQL sont encore incomplètes après un import massif.

Les événements uniques possèdent une projection permanente ; les séries sont développées
uniquement sur les fenêtres utiles, puis mises en cache. Les projections expirées sont purgées
quotidiennement après trente jours, sous verrou d'événement pour préserver les reconstructions
concurrentes. Consulter un mois ancien ne programme aucune action et ne retire aucune échéance.
Les vues renvoient les métadonnées compactes ; le détail charge le texte complet et les exceptions.
Une disponibilité issue d'une source périmée ou indisponible reste inconnue.

La connexion système Agenda porte `services.management_scope`. Les modes `personal`, `team` et
`all` définissent les agendas que les outils MCP peuvent consulter et gérer. Les appels visant
l’agenda d’un autre agent utilisent la permission de fonction de la connexion Agenda de l’appelant.
Cette portée et l’appartenance aux équipes sont relues à chaque appel. Les agendas externes de
l’appelant conservent leur propre connexion pour l’autorisation. Les écritures et rappels utilisent
le propriétaire de l’agenda et la connexion de la source. Le contexte automatique conserve les
agendas de l’agent et les accès humains restent soumis au RBAC de l’API.

Les mutations contrôlent `expected_revision`. Le choix `series`, `occurrence` ou `following`
précise leur portée ; une occurrence conserve son `recurrence_key` d'origine après déplacement.
Un changement de règle à partir d'une occurrence scinde la série et conserve les exceptions
futures. Les journées entières conservent leurs dates et une fin exclusive ; les rendez-vous
horaires et récurrences utilisent des fuseaux explicites. Les séries excessives échouent
explicitement dans un calcul isolé, sans résultat partiel présenté comme complet.

## Synchronisation CalDAV

Une modification locale et son opération d'outbox sont enregistrées dans la même transaction.
Le reçu `sync_state=pending` indique une intention locale, jamais une confirmation distante.

Le worker externe est examiné chaque minute et applique l'intervalle de la connexion,
y compris après une erreur ou une interruption. Les agendas sont traités un à un ; une
demande manuelle possède son suivi dans `calendar_sync_runs`.
Un bail et une révision de configuration empêchent l'application d'une réponse périmée.

CalDAV fournit la découverte, `sync-token` et `sync-collection`. Les contenus modifiés sont lus
par lots avec `calendar-multiget`. Les continuations d'une réponse tronquée sont consommées
avant de valider le passage. Un jeton expiré entraîne une lecture complète de réconciliation.
Un abonnement iCalendar utilise une lecture conditionnelle par ETag lorsque possible.
Une réponse incomplète ou invalide n'avance jamais le curseur et ne justifie aucune suppression.

Google et Microsoft utilisent un snapshot complet paginé sans limite de dates. Les séries
et exceptions sont importées, mais seules les écritures d'événements simples et la suppression
d'une série entière sont exposées ; les autres mutations récurrentes échouent avant écriture
locale. CalDAV conserve l'édition des récurrences.

Chaque ressource CalDAV possède une adresse stable et un ETag. Une création utilise
`If-None-Match: *`, une modification/suppression `If-Match` avec un ETag fort. Après perte
d'accusé de réception, le worker relit le résultat et retrouve l'opération au lieu de créer
un doublon. Une version distante concurrente conserve les deux contenus et bloque l'écriture ;
sa résolution explicite est elle-même contrôlée par révision. Les erreurs conservent l'outbox,
un recul progressif des tentatives, et une trace locale structurée : agenda, passage,
opération, étape, catégorie, statut HTTP et emplacement de code, sans URL ni contenu privé.

## Actions, Tasks et Process

Une action peut se déclencher avant le début, au début ou après la fin de l'événement. Plusieurs
actions peuvent partager une heure tout en conservant des identités distinctes. Les alarmes et
actions configurées remplacent l'échéance au début de l'événement. Le choix facultatif d'un Process
est une donnée locale de l'événement et de sa série. À l'échéance, l'Agenda admet ce Process via
`app.process.facade` ou une Task via `app.agent` si le choix est vide. Les nouveaux agendas internes et synchronisés activent les actions par défaut,
en conservant les désactivations explicites. Une source en lecture seule peut porter des
consignes locales. Les Tasks restent soumises aux droits et politiques de leurs outils.

Le worker local examine les échéances toutes les dix secondes, indépendamment du réseau et
des vues ouvertes. Il vérifie activation, révision, occurrence et politique de retard ; une
échéance trop tardive est marquée `skipped`. L'admission utilise une clé stable. Une Task déjà
créée dont le reçu a été perdu est retrouvée avant modification, reprise ou relance, sans
nouvelle admission. Le contexte complet est figé à l'admission pour la Task et le reçu.
L'admission d'un Process enregistre l'exécution, sa demande de démarrage et le reçu de l'Agenda
dans une transaction. Les droits de l'agent sont vérifiés au déclenchement et au démarrage du
Process. Un refus est conservé comme échec du lancement. L'état `submitted` indique que la Task
ou le Process a été admis. L'action est traitée lorsque cette exécution réussit.

Le journal se filtre par événement et occurrence et expose la référence de la Task ou du Process
exécuté. Une relance manuelle possède sa propre clé et un nouveau numéro de lancement. Un
événement annulé ne produit pas de nouvelle action.

L'Agenda porte les engagements datés et rappels. Goal possède les résultats durables et leurs
cycles : ne pas recopier un prochain cycle de Goal dans l'Agenda. Les Tasks de rappel ne
reçoivent aucun `goal_id` implicite. Une Task peut ensuite lancer un Process sous ses droits
ordinaires ; aucun Process ne sert à envelopper la synchronisation ou le rappel technique.
