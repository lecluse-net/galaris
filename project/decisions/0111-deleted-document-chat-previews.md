# 0111 — Aperçus des documents supprimés dans le chat

Statut : Accepted

L'oubli d'un document conserve désormais son dernier titre dans la ligne marquée supprimée.
Le contenu, les versions, les fichiers et les index suivent toujours la procédure d'effacement.
Les autres types de mémoire conservent leur titre de remplacement « Forgotten memory ».

Le port de métadonnées documentaires de Conversation peut résoudre les identifiants supprimés
avec un indicateur `deleted`. Ces métadonnées servent uniquement à présenter des références
historiques. Elles ne rétablissent aucun accès à la ressource. La liste de travail existante
ignore ces métadonnées supprimées lors de son enrichissement.

Après avoir autorisé la lecture d'un message, Chat complète ses aperçus manquants à partir
des seules références présentes dans ce message. Un document supprimé produit une carte
contenant son titre et l'indicateur de suppression, sans contenu, image ni téléchargement.
Un document inaccessible mais toujours actif et un identifiant inconnu restent omis.
L'interface traduit « Document supprimé », retire les actions et actualise la carte à la
notification de suppression comme à la réouverture du chat.

Les suppressions antérieures ont pu remplacer irréversiblement le titre par « Forgotten memory ».
Dans ce cas, l'interface utilise le libellé générique traduit « Document » ; aucun titre
historique n'est inventé ni reconstitué depuis le contenu effacé.

Les tests PostgreSQL vérifient la conservation du titre, la distinction avec un refus d'accès
et la disparition persistante du contenu. Les scénarios Chromium vérifient les cartes en
français et en anglais, les notifications, la réouverture et l'absence d'actions.
