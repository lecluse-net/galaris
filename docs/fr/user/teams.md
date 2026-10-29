<p align="right"><strong>Français</strong> · <a href="../../en/user/teams.md">English</a></p>

# Équipes et autorisations de dialogue

Une **équipe** réunit des utilisateurs humains et des agents. Chacun peut appartenir à
plusieurs équipes. Une équipe commune ouvre le dialogue humain-agent selon les droits du
canal. Les échanges entre agents suivent aussi la portée locale de leur connexion de messagerie.

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
Un agent équipé d’une connexion active **Galaris Admin** peut intervenir sur les tâches des
agents de sa portée déléguée ; seule `all` ouvre la portée globale. Le demandeur d’une délégation peut en consulter le résultat sans obtenir
la gestion des autres tâches du destinataire.

Les sélecteurs proposent les agents autorisés pour l’action : agents administrables dans
les écrans de gestion, interlocuteurs autorisés dans le chat, catalogue des membres dans
la composition d’équipe. Leurs choix sont revérifiés à l’ouverture.

## Qui peut communiquer ?

Le dialogue humain-agent repose sur une équipe commune, le manager de l’agent ou l’accès
administrateur (`AGENT_MANAGE_ALL`). Il n’y a aucun réglage « Hériter / Autoriser / Refuser »
pour les échanges hors équipe. Un accès ne se propage jamais par un troisième membre.
Pour les échanges entre agents, **Outils & connexions → Connexions → Communication inter-agents**
propose `none` (aucun), `team` (équipes communes, défaut) ou `all` (autres agents actifs).
Ce paramètre local `tools.management_scope`, réservé au gestionnaire humain global, est
revérifié à chaque échange. Les connexions de l'émetteur et du destinataire restent contrôlées.
Il ne modifie pas les droits de contact humain ni les droits documentaires.

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

Un contact humain externe sans identité Galaris autorisée est reçu dans un round textuel en pause,
visible dans le suivi d'activité avec les informations disponibles sur son identité. Le manager
reçoit une demande et autorise ou refuse les échanges dans `/permissions`.
L'accord est propre à cette personne sur cette connexion et reste révocable. Il ne crée pas de
compte Galaris et ne partage aucune ressource. Le Mail possède sa procédure distincte de Contacts et de
consentement avant admission, décrite dans le [Journal des mails](tasks.md).
L'identifiant d'utilisateur distant reste visible dans le détail des messages. L'association
facultative dans **Mon profil** indique seulement qu'un compte distant et un compte Galaris
appartiennent à la même personne. Pour Telegram, le [guide de configuration](../bridges/telegram-whatsapp.md)
prépare l'outil puis explique la connexion propre à chaque agent et son token BotFather.
Une permission n’active pas de nouveau canal : le Chat
natif reste humain ↔ agent. Les délégations de tâches entre agents respectent aussi ces droits.

## Privilèges

| Privilège | Permet de |
|---|---|
| `TEAM_ACCESS` | Voir les équipes et leurs membres |
| `TEAM_EDIT` | Créer, modifier et supprimer une équipe |
| `TEAM_MEMBERS_EDIT` | Ajouter et retirer des membres |

Modifier exige aussi le privilège de consultation correspondant. Le privilège du canal
utilisé, par exemple Chat ou l’API des agents, reste nécessaire.
