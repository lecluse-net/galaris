<p align="right"><strong>Français</strong> · <a href="../../en/user/calendar.md">English</a></p>

# Agenda et lancements de tâches

Un événement peut être associé à un contact Galaris de l’agent, de manière facultative.
Le champ **Contact associé** permet de rechercher et choisir ce contact dans l’éditeur ;
le détail du rendez-vous permet d’ouvrir sa fiche. Les agents peuvent aussi renseigner
`contact_id` avec leurs outils d’agenda, ou retirer le lien avec `clear_contact=True`.
Pour un événement récurrent, le contact concerne toute la série. Le lien reste local à
Galaris : il ne crée aucune invitation et n’est pas envoyé au calendrier externe.

Ouvrez **Connaissances → Agenda** (`/calendar`). Chaque agent possède un agenda personnel
sans compte externe. Ses agendas CalDAV et abonnements iCalendar peuvent être affichés avec
le même calendrier. Les connexions externes se configurent dans **Outils & connexions**,
avec les paramètres standards du protocole.
Chaque agent dispose d’un unique agenda interne par défaut, créé automatiquement. Les réglages
permettent de le renommer et de choisir sa couleur, mais pas de le supprimer, le désactiver ou
créer d’autres agendas internes. Les agendas externes viennent en complément. Les éventuels
anciens agendas internes supplémentaires restent accessibles pour conserver leurs événements.

Lorsque la lecture des agendas est activée pour l’agent, son contexte contient les rendez-vous
en cours et des dix jours à venir, triés chronologiquement et limités à dix occurrences au total par défaut.
Dans **Préférences → Mémoire → Contexte temporel des agents**, réglez séparément l’horizon
en jours et le nombre maximal d’événements. Les deux limites s’appliquent ensemble.
Ce résumé est actualisé à chaque construction du contexte ; les sources obsolètes et la présence
d’autres rendez-vous sont signalées. Les fonctions bloquées ou sur demande ne sont pas lues
automatiquement. L’agent peut utiliser ses outils autorisés pour consulter d’autres dates,
vérifier une disponibilité ou se poser un rappel dans le cadre du travail confié.

L’agenda est le pense-bête daté de l’agent, utilisable depuis une conversation comme depuis
une tâche : rendez-vous, échéances et choses à se rappeler à un moment donné. Une demande
telle que « rappelle-moi vers 15 h que je dois partir » doit créer un événement dans son agenda
personnel lorsque la fonction est autorisée.

La source **Mémoire**, sélectionnable dans la liste des agendas, affiche les souvenirs datés de
l’agent sur la période consultée. Un clic ouvre leur contenu d’origine. Les dates partielles
gardent leur précision et leur récurrence, dans le fuseau global de Galaris : une date sans
heure couvre la journée, un mois seul couvre ce mois. Les souvenirs restent dans Memory.
Cette source figure aussi dans le contexte temporel de l’agent, avec un lien vers le souvenir,
sans deuxième injection dans le brief Memory. Elle respecte les droits et le contact de la
conversation ; les gestionnaires doivent disposer de l’accès Mémoire pour la consulter.
Ces occurrences sont informatives : aucune tâche, aucun réveil automatique, aucune réservation
de disponibilité ni export vers un agenda externe. Les masquer dans l’IHM ne modifie pas
le contexte de l’agent. Les objectifs conservent leur propre fonctionnement.

## Se repérer

Chaque agenda occupe sa propre ligne, avec sa source en sous-libellé. Les agendas locaux,
**Objectifs** et **Mémoire** portent la mention **Galaris**. Les agendas externes affichent
le libellé du Tool d’origine, plutôt que le nom de son protocole.
Une étoile identifie l’agenda par défaut. La case à cocher affiche ou masque ses
événements ; le clic gauche sur le nom ou le reste de la ligne ouvre sa modale de réglages
sans changer la sélection. La ligne s’ouvre aussi au clavier avec Entrée.
Dans **Mes agendas**, le bouton **…** et le clic droit sur une ligne ouvrent le même menu :
copier la référence, afficher ou masquer l’agenda, ouvrir ses réglages et, pour un agenda
externe avec le droit de modification, lancer sa synchronisation avec son suivi.
Chaque agenda possède une URL stable `galaris://calendar/<identifiant>`. Collez-la dans
une discussion ou ajoutez-la comme pièce jointe de ressource : elle ouvre une fiche sans
miniature, puis l’agenda concerné. Le renommage conserve le lien ; celui-ci ne donne aucun
droit supplémentaire. Les couches **Objectifs** et **Mémoire** conservent leurs objets d’origine.
Le nom proposé par défaut est **Agenda personnel** et suit la langue de l’interface ; les noms
personnalisés sont conservés. Dans la modale de réglages d’un agenda, choisissez l’une des
onze couleurs Solaire puis enregistrez, pour ses cases et ses événements en clair comme en sombre.
La modale porte le nom de l’agenda, suivi d’un badge **Galaris** ou du libellé de son Tool.
Ses onglets reprennent la présentation de la modale des objectifs : **Réglages** et, pour
les agendas externes seulement, **Synchronisation**. L’agenda interne, **Objectifs** et
**Mémoire** n’affichent aucune information ni action de synchronisation.
**Mémoire** utilise le jaune par défaut. Ces choix sont conservés par utilisateur dans le
navigateur utilisé, y compris pour **Objectifs** et **Mémoire**.

Sélectionnez l’agent, puis cochez les agendas à afficher. La navigation propose **Mois**,
**Semaine**, **Jour** et **Planning**. Utilisez **Aujourd’hui**, les flèches ou le petit
calendrier pour changer de période. Cliquez sur un jour pour ouvrir son détail ; le bouton
« autres » donne accès aux rendez-vous supplémentaires d’une journée chargée.
La vue Mois affiche le numéro ISO de chaque semaine à gauche de sa ligne. En vue Semaine,
ce numéro apparaît dans le titre de la période. Les semaines commencent le lundi.

Le fuseau d’affichage est distinct du fuseau enregistré avec chaque
événement. Les événements sur plusieurs jours conservent leurs dates de journée entière.
Sur mobile, le Planning est proposé par défaut et les filtres d’agendas se déplient avec
le bouton de filtre.

## Créer et modifier un événement

Utilisez **Créer un événement** ou cliquez dans l’espace vide d’une journée pour ouvrir un
nouveau rendez-vous sur la journée entière. En vue Semaine ou Jour, maintenez le bouton de
la souris sur l’heure de début et relâchez-le sur l’heure de fin : la plage est surlignée,
puis le formulaire reprend les deux heures choisies. Par exemple, une sélection de 9 h à
11 h prépare un rendez-vous de deux heures. Un clic simple sur un créneau prépare une heure ;
Échap annule une sélection en cours. Le numéro du jour ouvre toujours la vue Journée et le
clic sur un événement existant ouvre son détail.
Renseignez le titre, les dates, le lieu et les instructions éventuelles. La date de fin d’un
événement sur la journée entière inclut le dernier jour choisi.

Une répétition peut être quotidienne, hebdomadaire, mensuelle, annuelle ou exprimée par une
règle personnalisée. Vous pouvez choisir un intervalle, les jours de semaine et une fin par
date ou nombre d’occurrences. Une règle existante plus complexe reste conservée comme règle
personnalisée.

Ouvrez un événement pour le modifier ou le supprimer. Pour une série, choisissez explicitement
**cet événement**, **cet événement et les suivants** ou **tous les événements de la série**.
Un déplacement par glisser-déposer conserve la durée et demande confirmation du périmètre.
Une modification concurrente bloque l’écriture et conserve le brouillon : rechargez la
version actuelle avant de reprendre. Les abonnements iCalendar restent en lecture seule.

## Remplacer une notification par une tâche

Chaque événement planifie automatiquement une tâche pour son début : aucune case ni second
enregistrement n’est nécessaire. Le titre et la description précisent le travail attendu.
Les lancements sont activés par défaut sur les nouveaux agendas internes et synchronisés,
y compris ceux découverts automatiquement. Une désactivation explicite dans les réglages
reste conservée lors des synchronisations suivantes.
La tâche reçoit aussi les dates, le fuseau, le lieu et le contexte complet de l’événement,
avec les dernières modifications disponibles au lancement. Chaque occurrence répétée possède
sa propre exécution, sans doublon lors d’une nouvelle lecture ou d’une reprise.

Les rappels VALARM et les lancements déjà configurés conservent leurs horaires et leurs
instructions ; ils remplacent le lancement par défaut pour l’occurrence concernée.
Si un lancement anticipé a été manqué au-delà de son délai de rattrapage, il est reporté au
début de l’événement, avec le même identifiant pour éviter une double admission. Un lancement
déjà admis n’est pas redémarré au début de l’événement.
Les réglages d’activation de l’agenda, de la connexion et des exécutions restent applicables, ainsi que la
politique de retard maximal. Les tâches utilisent l’agent de la connexion et ses autorisations.

Les tâches lancées par les agendas sont des travaux d’arrière-plan, comme les cycles
d’objectifs. Les demandes issues des discussions passent avant elles dans la file, même
si un lancement d’agenda attend depuis plus longtemps. Cette priorité ne force pas l’arrêt
d’un travail déjà en cours.

Les cartes du calendrier affichent le dernier état de chaque action, pour l’occurrence
concernée. Le détail affiche tous les lancements, leurs échéances, erreurs et liens vers les
Tasks accessibles. Pour une série, le bouton **Toute la série** élargit cet historique. Les
états se rafraîchissent automatiquement ; le bouton Actualiser permet une lecture immédiate.

**Lancer à nouveau** crée une nouvelle exécution après une tâche terminée ou un lancement
échoué, annulé ou ignoré. L’ancienne tâche garde son résultat. Une tâche active ne peut pas
être relancée. Les retries de sauvegarde d’une même action et de relance utilisent une clé
stable pour éviter les doublons.

## Synchronisation et droits

Dans le protocole Agenda du Tool, choisissez **CalDAV**, **Google Agenda**, **Microsoft 365 /
Outlook**, **Apple iCloud** ou **iCalendar privé**. Nextcloud utilise CalDAV. L’URL racine
CalDAV commune à une instance se définit dans les paramètres globaux du Tool, avec héritage
imposé si nécessaire. Un lien ICS privé appartient à la connexion du compte. Google,
Microsoft et iCloud utilisent leurs adresses de service prédéfinies.

Pour Google et Microsoft, référencez les paramètres standards `client_id` et `client_secret`
de l’application enregistrée chez le fournisseur, puis définissez leurs valeurs globales
dans le Tool. Enregistrez l’URL de retour affichée par Galaris dans cette application.
Microsoft accepte `common` pour les comptes personnels et professionnels, ou l’annuaire
de l’entreprise. Dans chaque connexion, **Autorisation du compte agenda → Connecter le
compte** ouvre le consentement du fournisseur. Les jetons sont chiffrés et renouvelés
automatiquement ; une révocation exige une nouvelle autorisation. Les accès MCP éventuels
restent indépendants. Les règles de consentement de l’entreprise continuent de s’appliquer.

CalDAV accepte un mot de passe d’application ou OAuth avec les adresses d’autorisation,
de jetons et les scopes configurés dans le Tool. iCloud utilise l’identifiant Apple et un
mot de passe spécifique à l’application. Les abonnements ICS, y compris les liens Google
ou Outlook privés, restent en lecture seule.

Les événements simples Google/Microsoft se créent, se modifient et se suppriment depuis
Galaris. Leurs séries, exceptions et annulations sont importées ; créez ou modifiez les
répétitions chez le fournisseur. Ces écritures sont refusées avant modification locale.
La suppression d’une série entière reste possible. CalDAV conserve l’édition des récurrences.
Google/Microsoft utilisent actuellement un snapshot paginé complet, sans limite de dates ;
une réponse incomplète interrompt la synchronisation sans supprimer les événements locaux.

La fréquence de synchronisation appartient à la **connexion** et s’applique à tous les
agendas issus du même compte, Nextcloud compris. Dans la définition du Tool, associez le
rôle **Intervalle de synchronisation (heures)** à un paramètre entier standard, par exemple
`sync_interval_hours`. Sa valeur se gère ensuite dans les paramètres de la connexion :
de 1 à 8760 heures, 2 par défaut, avec l’héritage global/local habituel. Aucun paramètre
n’est créé sans action explicite. Les anciens réglages de l’agenda principal servent de
repli tant que le rôle n’est pas configuré. La connexion ne contient aucune liste d’agendas
ni écran de suivi ; ces informations restent sur la page Agenda.

Le contrôle des échéances a lieu chaque minute et traite les agendas un à un. Les erreurs,
interruptions et modifications locales respectent le délai de la connexion. **Actualiser**
relit la copie locale ; les agendas internes ne contactent aucun serveur externe.

Dans la modale d’un agenda externe, l’onglet **Synchronisation** affiche uniquement
l’historique des 50 dernières tentatives, sans pagination. **Nouvelle synchronisation**,
en pied de modale, ajoute la tentative en tête et l’ouvre
automatiquement. Son état, les étapes horodatées, les éléments traités, les volumes
reçus/envoyés en ko et le statut HTTP évoluent en direct dans cette ligne. Les tentatives
récentes restent consultables ; rouvrir la modale retrouve le journal.
Les étapes détaillées et les phases réseau sont temporaires : elles disparaissent à la fin
et ne sont pas enregistrées dans le bilan historique. Le résultat, la durée, les compteurs
et une éventuelle erreur restent consultables.
La modale reste ouverte après une synchronisation manuelle, y compris en cas d’erreur.
Le calendrier n’est rafraîchi à la fin que si des changements réels ont été enregistrés :
événements, état de synchronisation, conflits ou agendas découverts. Relire des événements
identiques ne provoque pas de rafraîchissement. Une erreur après des modifications déjà
enregistrées conserve leur prise en compte.
Les échecs conservent leur étape, leur catégorie et leurs compteurs. Les conflits non résolus
se comparent et se règlent dans les détails de la tentative la plus récente.
Le bouton **Paramètres de connexion** reste dans le pied de la modale, sans quitter Agenda.
**Enregistrer** reste également en pied de l’onglet **Réglages**. La croix du titre permet
de fermer la modale.

Les connexions CalDAV et iCalendar acceptent les serveurs HTTPS publics et les serveurs
du réseau privé de l’entreprise (IPv4 privée et IPv6 locale unique). Le serveur doit être
joignable depuis le backend Galaris et présenter un certificat valide. Les adresses de
boucle locale et de liaison locale restent exclues.

Les boutons **Ouvrir la tâche**, **Ouvrir la revue** et **Ouvrir l’objectif** affichent leur
modale de détail au-dessus de l’agenda. Leur fermeture retrouve l’événement et conserve la
période, la vue et les filtres de l’agenda.
Pour un agenda synchronisé, **Paramètres de connexion** ouvre directement la modale de sa
connexion, avec les paramètres standards et sans quitter l’agenda.

Les lectures et modifications utilisent la copie locale. **Synchronisation en attente**
indique une sauvegarde locale, pas encore une confirmation du fournisseur. Les réglages d’un
agenda donnent accès à l’historique et aux erreurs de chaque tentative. En cas de conflit,
comparez les versions puis choisissez explicitement la version locale ou distante.

`CALENDAR_ACCESS` permet la consultation ; `CALENDAR_EDIT` permet les mutations. La modification
d’événements exige aussi un agenda inscriptible. Les actions locales restent configurables
sur un abonnement en lecture seule, avec le droit d’édition Agenda. Ouvrir une Task demande
les droits Task correspondants. Les paramètres de connexion gardent leurs droits distincts.

## Objectifs dans l’agenda

Avec les droits Objectifs, cochez **Objectifs** dans la liste des agendas. Dans le formulaire
d’un objectif, **À dates fixes dans l’agenda** configure un premier passage, son fuseau,
une répétition quotidienne, hebdomadaire, mensuelle ou annuelle, et le retard maximal admis.
Les plages autorisées et la disponibilité de l’agent restent applicables : la date prévue
n’est pas une réservation ni une promesse de démarrage exact.

Les passages futurs sont prévisionnels. À leur échéance, ils deviennent des événements
individuels conservés, en attente puis liés à leur cycle et à sa Task exacte. Ouvrir le
passage de lundi donne accès à la Task de lundi, même si elle a commencé plus tard.
Le détail distingue la date prévue, le démarrage réel et la fin du travail ; la revue
éventuelle reste accessible séparément avec les droits Task.

Modifier la récurrence ou le titre ne change que le futur. Le passé, les passages déjà
arrivés à échéance et les cycles en cours conservent leur date, leur titre et leurs liens.
Une pause ou une clôture retire les passages futurs ; la reprise repart de son instant
d’activation. Un passage trop ancien est conservé comme **Ignoré**, sans créer de Task.
Les dates mensuelles inexistantes et les heures sautées au changement d’heure sont omises.

Les Goals existants gardent leurs cycles et leur mode par délai ou par objectif parent.
Le mode par délai montre seulement son prochain passage connu. Les anciens cycles sont
affichés à leur date réelle de création, sans reconstruire une planification historique.
Leur libellé disponible lors de la reprise est conservé pour les futurs renommages.
Un lancement manuel produit un passage distinct. La couche Objectifs n’ajoute jamais un
rappel Agenda qui lancerait une seconde Task pour le même cycle.
