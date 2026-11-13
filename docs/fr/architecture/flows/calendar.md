<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/calendar.md">English</a></p>

# Agenda local, CalDAV et exécution des actions

`app.calendar` possède le modèle canonique des agendas internes et externes. Chaque agent
possède un **Agenda personnel** système (`agenda`) sans compte externe, auquel peuvent
s'ajouter d'autres agendas internes et des sources externes. `bridge.calendar` traduit le
protocole **CalDAV** ; les événements échangés restent au format **iCalendar** (`VEVENT`,
récurrences, exceptions et `VALARM`). Un abonnement à un fichier iCalendar est en lecture seule.

## Configuration et droits

La capacité fournisseur est `caldav.calendar`. `calendar_config.settings` porte le type de
source (`caldav`, par défaut, ou `ical`), le fuseau et les préférences de créneaux.
`calendar_config.param_map` référence les paramètres de connexion standards pour `url`,
`username`, `password`, et éventuellement le libellé et le propriétaire. L'URL privée et le
mot de passe utilisent des paramètres chiffrés de type `password` ; les valeurs suivent
l'héritage et les valeurs imposées des connexions. Aucun formulaire parallèle de secrets
n'appartient à l'Agenda. Les agendas externes sont matérialisés depuis ces paramètres et
la découverte CalDAV ; l'API de création d'agenda crée uniquement des agendas internes.

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

Les mutations contrôlent `expected_revision`. Le choix `series`, `occurrence` ou `following`
précise leur portée ; une occurrence conserve son `recurrence_key` d'origine après déplacement.
Un changement de règle à partir d'une occurrence scinde la série et conserve les exceptions
futures. Les journées entières conservent leurs dates et une fin exclusive ; les rendez-vous
horaires et récurrences utilisent des fuseaux explicites. Les séries excessives échouent
explicitement dans un calcul isolé, sans résultat partiel présenté comme complet.

## Synchronisation CalDAV

Une modification locale et son opération d'outbox sont enregistrées dans la même transaction.
Le reçu `sync_state=pending` indique une intention locale, jamais une confirmation distante.

Le worker externe est examiné chaque minute. Une source saine est relevée toutes les cinq
minutes ; une écriture en attente ou une demande explicite réveille sa synchronisation. Les
sources sont traitées avec une concurrence bornée et une session indépendante par branche.
Un bail et une révision de configuration empêchent l'application d'une réponse périmée.

CalDAV fournit la découverte, `sync-token` et `sync-collection`. Les contenus modifiés sont lus
par lots avec `calendar-multiget`. Les continuations d'une réponse tronquée sont consommées
avant de valider le passage. Un jeton expiré entraîne une lecture complète de réconciliation.
Un abonnement iCalendar utilise une lecture conditionnelle par ETag lorsque possible.
Une réponse incomplète ou invalide n'avance jamais le curseur et ne justifie aucune suppression.

Chaque ressource CalDAV possède une adresse stable et un ETag. Une création utilise
`If-None-Match: *`, une modification/suppression `If-Match` avec un ETag fort. Après perte
d'accusé de réception, le worker relit le résultat et retrouve l'opération au lieu de créer
un doublon. Une version distante concurrente conserve les deux contenus et bloque l'écriture ;
sa résolution explicite est elle-même contrôlée par révision. Les erreurs conservent l'outbox,
un recul progressif des tentatives, et une trace locale structurée : agenda, passage,
opération, étape, catégorie, statut HTTP et emplacement de code, sans URL ni contenu privé.

## Actions et Tasks

Une action n'est pas une notification d'interface : son échéance admet une Task par la façade
publique `app.agent`. Elle peut agir avant le début, au début ou après la fin. Plusieurs actions
peuvent partager une heure tout en conservant des identités distinctes. Un calendrier externe
requiert une activation explicite des actions ; une source en lecture seule peut porter des
consignes locales. Les données importées ne deviennent jamais des instructions autorisées.

Le worker local examine les échéances toutes les dix secondes, indépendamment du réseau et
des vues ouvertes. Il vérifie activation, révision, occurrence et politique de retard ; une
échéance trop tardive est marquée `skipped`. L'admission utilise une clé stable. Une Task déjà
créée dont le reçu a été perdu est retrouvée avant modification, reprise ou relance, sans
nouvelle admission. Le contexte complet est figé à l'admission, puis reste dans Task et le reçu.
Le reçu `submitted` signifie uniquement que la Task existe ; seul `Task.SUCCESS` signifie que
l'action est traitée. Une Task absente/inaccessible reste indisponible.

Le journal se filtre par événement et occurrence et expose `galaris://task/<uuid>`. Une relance
manuelle possède sa propre clé et un nouveau numéro de lancement ; elle ne rouvre pas la Task
terminale précédente. Un événement annulé ne produit pas de nouvelle action.

L'Agenda porte les engagements datés et rappels. Goal possède les résultats durables et leurs
revues : ne pas recopier une prochaine revue de Goal dans l'Agenda. Les Tasks de rappel ne
reçoivent aucun `goal_id` implicite. Une Task peut ensuite lancer un Process sous ses droits
ordinaires ; aucun Process ne sert à envelopper la synchronisation ou le rappel technique.
