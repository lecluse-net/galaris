<p align="right"><strong>Français</strong> · <a href="../../en/user/teams.md">English</a></p>

# Équipes et autorisations de dialogue

Une **équipe** réunit des utilisateurs humains et des agents. Chacun peut appartenir à
plusieurs équipes. Deux membres partageant une équipe peuvent dialoguer via les canaux
disponibles, sans règle supplémentaire.

## Composer une équipe

Ouvrez **Équipes**, ou l’onglet **Équipes** de la page **Agents**. La liste affiche les
effectifs humains et IA ; les petites équipes présentent aussi leurs membres avec avatars.
Déplacez les lignes par leur poignée pour réordonner les équipes : la position est
enregistrée dès le dépôt. La poignée fonctionne aussi au toucher et avec les flèches haut
et bas du clavier. Les nouvelles équipes sont ajoutées en fin de liste.
Cliquez sur le nom ou le bouton de modification pour ouvrir la fiche. La grande modale
présente les humains à gauche et les agents à droite, avec des sélecteurs à avatars pour
ajouter un membre. Sur mobile, les deux colonnes s’empilent. Les ajouts et retraits prennent
effet avec **Enregistrer** ; **Annuler** abandonne les changements non enregistrés.

Le manager conserve son accès à ses agents, et l’administrateur peut contacter tous les agents.
Partager une équipe ne permet pas d’administrer
un agent, de se faire passer pour lui ni de lire les conversations d’autres humains.

Les tâches sont administrées par leur agent, ses managers et les administrateurs globaux.
Un agent équipé d’une connexion active **Galaris Admin** peut intervenir sur les tâches de
tous les agents. Le demandeur d’une délégation peut en consulter le résultat sans obtenir
la gestion des autres tâches du destinataire.

Les sélecteurs proposent les agents autorisés pour l’action : agents administrables dans
les écrans de gestion, interlocuteurs autorisés dans le chat, catalogue des membres dans
la composition d’équipe. Leurs choix sont revérifiés à l’ouverture.

## Qui peut communiquer ?

Le chat repose uniquement sur une équipe commune, le manager de l’agent ou l’accès
administrateur (`AGENT_MANAGE_ALL`). Il n’y a aucun réglage « Hériter / Autoriser / Refuser »
pour les échanges hors équipe. Un accès ne se propage jamais par un troisième membre.
Deux agents doivent partager une équipe pour communiquer entre eux.

Les documents conservent leur partage plus fin : accès individuels ou par équipe,
avec distinction entre lecture et modification. Partager une équipe pour le chat ne
rend pas automatiquement tous les documents accessibles.

## Retrait d’un droit

Le retrait bloque les nouveaux échanges, les notifications à venir et les nouveaux fragments
d’une réponse en streaming. Les appels vocaux dépendent uniquement du privilège `CHAT_CALL`,
dans une conversation personnelle ; ils ne dépendent pas des équipes. Ce privilège est
revérifié pendant l’appel et son retrait coupe l’audio.
L’historique personnel reste disponible ; une tâche déjà admise n’est pas annulée.
Les préférences personnelles et les documents conservent leurs règles d’accès propres.

Un contact externe doit être rattaché à une identité Galaris vérifiée pour solliciter un agent,
y compris par message asynchrone. Une permission n’active pas de nouveau canal : le Chat
natif reste humain ↔ agent. Les délégations de tâches entre agents respectent aussi ces droits.

## Privilèges

| Privilège | Permet de |
|---|---|
| `TEAM_ACCESS` | Voir les équipes et leurs membres |
| `TEAM_EDIT` | Créer, modifier et supprimer une équipe |
| `TEAM_MEMBERS_EDIT` | Ajouter et retirer des membres |

Modifier exige aussi le privilège de consultation correspondant. Le privilège du canal
utilisé, par exemple Chat ou l’API des agents, reste nécessaire.
