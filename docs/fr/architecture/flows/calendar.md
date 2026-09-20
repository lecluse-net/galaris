<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/calendar.md">English</a></p>

# Tool Calendar et iCalendar

`bridge.calendar` adapte des ressources iCalendar HTTPS au catalogue `app.tools`, aux
connexions d’agents, aux Tasks et aux Process de Galaris. Le Tool intégré `calendar` est toujours
présent dans le catalogue, mais il n’est jamais connecté automatiquement : un administrateur crée
explicitement une connexion Calendar pour l’agent depuis l’écran **Outils > Connexions**.

## Connexion et calendriers

Une connexion Calendar possède les préférences générales de recherche de créneaux : fuseau IANA,
début et fin de journée de travail et pas de recherche. La même modale permet ensuite d’ajouter une
ou plusieurs ressources `CalendarFeed`. Chaque ressource indique son propriétaire humain, son mode
`read` ou `write`, les déclencheurs actifs et l’action Task ou Process choisie.

Chaque `CalendarFeed` référence réellement sa `Connection`. Supprimer la connexion supprime donc sa
configuration calendrier ; désactiver la connexion retire immédiatement les fonctions MCP et exclut
ses calendriers du CRON. L’URL complète, les identifiants HTTP et le snapshot iCalendar sont chiffrés
au repos. Les API ne restituent que le nom d’hôte et des indicateurs de présence des secrets.

Les accès réseau acceptent uniquement HTTPS. Le bridge résout et épingle une adresse publique à
chaque requête et redirection afin de refuser les réseaux privés. Les réponses sont bornées à 5 Mio.
Une écriture remplace une ressource `.ics` avec `PUT` et `If-Match` lorsque le serveur fournit un ETag.

Le bouton **Tester la synchronisation** télécharge et développe le flux sans déclencher d’action. Il
présente les trois prochaines occurrences et, pour un calendrier en écriture, la capacité annoncée
par le serveur.

## Synchronisation et déclenchement

Le scheduler durable d’`app.task` héberge `calendar-sync` avec un intervalle de 900 secondes :

1. il sélectionne uniquement les calendriers actifs de connexions actives ;
2. `recurring-ical-events` développe les récurrences RFC 5545 et les alarmes `VALARM` ;
3. les débuts d’événement et notifications dans la fenêtre depuis le contrôle précédent produisent
   une empreinte stable ;
4. la contrainte unique `(calendar_id, fingerprint)` crée un seul `CalendarTrigger` ;
5. le bridge soumet une Task via la façade publique d’`app.agent`, ou lance le Process affecté à
   l’agent via `app.process` avec une clé d’idempotence dérivée de l’empreinte.

La reprise après indisponibilité relit au plus sept jours. Le texte du calendrier est toujours marqué
comme contenu externe non fiable dans les Tasks et les outils MCP.

## Fonctions MCP

Une connexion active expose à son agent les fonctions natives suivantes :

- `calendar_list` et `calendar_events` pour découvrir les calendriers et leurs occurrences ;
- `calendar_is_available` pour vérifier une plage exacte et obtenir les conflits ;
- `calendar_find_free_slots` pour chercher des créneaux selon les préférences de connexion ;
- `calendar_create_event`, `calendar_update_event` et `calendar_delete_event` pour les ressources
  déclarées en écriture.

Les identifiants de calendriers optionnels sont toujours recoupés avec la connexion active de
l’agent. Les événements annulés ou transparents ne bloquent pas une plage de disponibilité.
