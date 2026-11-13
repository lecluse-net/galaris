# 0278 — Agendas personnels par défaut et frontière avec Goal

Statut : accepté, implémenté.

Le stockage, la synchronisation et l'ordonnancement décrits ci-dessous sont remplacés par
la [décision 0279](0279-local-agendas-and-caldav-synchronization.md). Le défaut personnel et
la frontière avec Goal restent applicables.

## Décision

`app.calendar` devient le domaine canonique des agendas, sources et reçus de rappels.
Le service système `agenda`, connecté et actif par défaut, donne à chaque agent un agenda
personnel sans compte externe. L’ancien Tool externe `calendar` n’est pas recréé : le bridge
iCalendar reste un protocole optionnel de fournisseur.

Les tables `calendar_feeds` et `calendar_triggers` conservent leurs identités. Une source native
porte `source_kind=internal` et un contenu iCalendar chiffré distinct du cache distant.
Une contrainte partielle impose un agenda natif par connexion ; les mutations prennent un
verrou de ligne. `bridge.calendar` enregistre le transport HTTPS dans un port public du domaine.
Les fonctions `calendar_*` et le journal des tâches restent communs aux deux sources.

Le défaut de sélection est l’agenda personnel. Un calendrier ou une connexion explicite reste
lié à sa source réelle, avec vérification d’appartenance avant autorisation et exécution.
Les mutations personnelles commencent autorisées, via des valeurs initiales qui préservent les
décisions explicites ultérieures. Les protocoles externes conservent leurs propres permissions.

Une notification VALARM crée une tâche avec les informations de l’événement. Sans notification,
aucune tâche n’est créée. Le natif est vérifié chaque minute et HTTPS toutes les quinze minutes.
La même empreinte et le même reçu assurent la reprise idempotente et le suivi par occurrence.

L’agenda porte les engagements datés et rappels ponctuels. Goal porte un résultat durable et
ses revues planifiées. Les consignes encouragent les rendez-vous utiles, mais interdisent de
recopier un prochain cycle Goal dans l’agenda. Un rendez-vous lié à un Goal doit représenter
un engagement distinct. Les tâches de rappel ne reçoivent aucun `goal_id` implicite et ne
modifient pas le calendrier d’exécution des objectifs.

## Vérification

Les tests couvrent le défaut sans réseau, les permissions initiales, la coexistence d’une
source HTTPS, l’isolation des agents, le déplacement ou retrait des alarmes et l’admission
d’une seule tâche suivie. Les tests iCal existants restent appliqués au domaine canonique.
Le schéma et les données permanentes convergent par DbAdmin, sans migration destructive.
