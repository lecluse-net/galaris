# 0092 — Événements WebSocket limités aux consommateurs actifs

Statut : accepté.

## Constat

Les composants retirent déjà leurs écouteurs à la fermeture, mais le serveur continue
d'envoyer tous les événements autorisés à chaque socket. Appels LLM, tâches, objectifs,
documents, processus, traces agentiques et événements du chat mobilisent donc la base
et le réseau même lorsqu'aucun consommateur du navigateur ne les utilise.

| Événements | Consommateurs à préserver |
|---|---|
| `llm_call.*` | Activité du tableau de bord, suivi LLM, détails et traces d'exécution |
| `task.*` | Tableau de bord, suivi des tâches, tâches du chat et suivi des objectifs |
| `goal.*`, `goal_settings.update` | Page Objectifs via son store |
| `memory.*` | Bibliothèque et éditeur de documents, aperçus et documents du chat |
| `process_run.*` | Suivi des processus et panneau des processus du chat |
| `voice_conversation.*` | Historique des appels téléphoniques |
| `agent_run.event` | Consommateurs du suivi d'activité d'une tâche |
| `chat.message` | Inbox du shell et conversation ouverte |
| `chat.activity`, `chat.runtime`, `chat.call`, `chat.voice_transcription` | Store de la page Chat, libéré à sa sortie |
| `dream.update` | Page Dream, déjà soumise au filtre de page affichée |

## Décision

Le client partagé déclare les noms `sujet.action` réellement écoutés dans le handshake
et remplace cette liste avec `events.subscribe` au premier ou dernier consommateur.
Plusieurs composants peuvent partager un même événement. Le dernier état est réémis à
la reconnexion ; une fermeture hors ligne est prise en compte. Aucun intervalle de
rafraîchissement des abonnements n'est ajouté.

Le serveur borne et valide cette liste, puis filtre les destinataires avant d'ouvrir
la session DB. Il revérifie l'abonnement avant l'envoi après les contrôles asynchrones.
Une déclaration d'intérêt ne confère aucun droit : session, rôle et accès à la ressource
restent vérifiés sur les destinataires. Le filtre de page Dream reste complémentaire.

L'inbox authentifiée conserve `chat.message` hors de la page Chat, pour les non-lus et
les notifications. Les événements de streaming ne restent demandés que tant que leurs
consommateurs sont montés. Les composants encore montés dans un onglet en arrière-plan
conservent leurs abonnements : cette décision ne change pas la politique de visibilité.

Les anciens clients, sans champ `events` dans le handshake, conservent leur diffusion
autorisée jusqu'au rechargement. Cela évite d'interrompre une session ouverte pendant une
mise à jour du serveur. Les nouveaux clients déclarent explicitement une liste vide
lorsqu'ils n'écoutent aucun événement.

## Garanties

Tests sans consommateur, écoute partagée, réouverture, réponse tardive, reconnexion,
déconnexion, changement de session, validation du protocole et refus selon les droits.
Les parcours navigateur vérifient les abonnements de chaque groupe de pages et le
streaming du chat, dont la notification finale après avoir quitté la conversation.
Les chargements tardifs des objectifs et de l'éditeur documentaire ne doivent pas
installer d'écouteur après leur démontage, y compris avec des documents préexistants.
