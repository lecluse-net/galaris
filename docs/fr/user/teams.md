<p align="right"><strong>Français</strong> · <a href="../../en/user/teams.md">English</a></p>

# Équipes et autorisations de dialogue

Une **équipe** réunit des utilisateurs humains et des agents. Chacun peut appartenir à
plusieurs équipes. Une équipe commune ouvre le dialogue humain-agent selon les droits du
canal. Les échanges entre agents suivent aussi la portée locale de leur connexion de messagerie.

## Composer une équipe

Les listes déroulantes d’agents présentent une section par équipe, dans l’ordre des équipes.
Un agent membre de plusieurs équipes apparaît dans chacune ; les agents sans appartenance
figurent dans **Sans équipe**. Ces sections conservent les agents autorisés pour l’action.

Le sélecteur **Agent** affiche sa recherche en haut de la liste déroulante. Saisissez un nom
pour filtrer les sections, sans tenir compte de la casse ni des accents. Le champ fermé
affiche l’agent choisi. Le sélecteur **Propriétaire** présente les équipes, puis les
sections **Agents** et **Utilisateurs** dans chacune. **Moi** figure parmi les utilisateurs
de ses équipes. La recherche porte sur les propriétaires disponibles ; la pagination est
indépendante pour chaque type dans chaque équipe. Les membres sans équipe ont leur section.

Ouvrez **Équipes**, ou l’onglet **Équipes** de la page **Agents**. La liste affiche les
effectifs humains et IA ; les petites équipes présentent aussi leurs membres avec avatars.
Déplacez les lignes par leur poignée pour réordonner les équipes : la position est
enregistrée dès le dépôt. La poignée fonctionne aussi au toucher et avec les flèches haut
et bas du clavier. Les nouvelles équipes sont ajoutées en fin de liste.
Cliquez sur le nom ou le bouton de modification pour ouvrir la fiche. La grande modale
présente les humains à gauche et les agents à droite, avec des sélecteurs à avatars pour
ajouter un membre. Sur mobile, les deux colonnes s’empilent. Les ajouts et retraits prennent
effet avec **Enregistrer** ; **Annuler** abandonne les changements non enregistrés.

Dans l’onglet **Agents**, le bouton **Ajouter des membres**, entre **Tout redémarrer**
et **Nouvel Agent**, ouvre cette même fiche pour les membres de l’équipe courante, sans
sélecteur d’équipe. Sélectionnez plusieurs humains ou agents, cliquez sur **Ajouter** dans
la colonne concernée, puis sur **Enregistrer**. Leurs autres appartenances sont conservées.
Ce bouton exige les droits de consultation des équipes et de modification de leurs membres ;
il est désactivé dans l’onglet **Sans équipe**.

Le manager conserve son accès à ses agents, et l’administrateur peut contacter tous les agents.
Partager une équipe ne permet pas d’administrer
un agent, de se faire passer pour lui ni de lire les conversations d’autres humains.

Les tâches sont administrées par leur agent, ses managers et les administrateurs globaux.
Un agent équipé d’une connexion active **Administration** peut intervenir sur les tâches des
agents de sa portée déléguée ; seule `all` ouvre la portée globale. Le demandeur d’une délégation peut en consulter le résultat sans obtenir
la gestion des autres tâches du destinataire.

Les sélecteurs proposent les agents autorisés pour l’action : agents administrables dans
les écrans de gestion, interlocuteurs autorisés dans le chat, catalogue des membres dans
la composition d’équipe. Leurs choix sont revérifiés à l’ouverture.

Les agents disposent d'un annuaire en lecture seule, sans délégation AgentAdmin :
`team_list(search="Recherche")` recherche les équipes par partie de leur nom et renvoie
leurs identifiants, une description abrégée et les effectifs humains et IA, y compris pour
les équipes vides. `team_members(team_id=…)` liste ensuite les humains actifs et les agents
non supprimés de l'équipe choisie. Le filtre `kind="user"` ou `kind="agent"` sélectionne
un type de membre ; `search` recherche une partie du nom. Un humain et un agent pouvant
avoir le même numéro, chaque identité comprend son type et son identifiant.
Les adresses de connexion et les données privées des comptes ne sont pas exposées.

Les deux fonctions sont disponibles en conversation et en tâche selon leur activation dans
Galaris. Suivez `next_offset` jusqu'à `null`, en conservant les filtres : une page peut être
plus courte que la limite demandée (50 par défaut, de 1 à 500). Les recherches ignorent la casse
et les espaces autour ; `%` et `_` restent des caractères ordinaires. Les équipes homonymes
restent distinctes par leur identifiant. Une équipe inconnue ou supprimée produit une erreur ;
une équipe vide renvoie une liste vide. Les appartenances sont relues à chaque appel ;
recommencez un inventaire si elles changent pendant sa lecture. La consultation ne donne aucun
droit supplémentaire de dialogue, de partage, d'accès aux documents ou d'administration.

Les agents peuvent aussi rechercher uniquement des collègues IA par équipe avec
`agent_list(team_name="Recherche")`, ou avec `team_id` s’ils connaissent son identifiant.
Le nom doit correspondre exactement, sans tenir compte des majuscules ni des espaces autour.
Si plusieurs équipes portent ce nom, leurs membres sont réunis sans doublons ; l’identifiant
permet de cibler une seule équipe. Le même filtre doit être conservé en suivant `next_offset`.
Une équipe inconnue ou supprimée ne renvoie aucun agent. Cette recherche ne donne aucun droit
supplémentaire de communication ou d’administration.

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
