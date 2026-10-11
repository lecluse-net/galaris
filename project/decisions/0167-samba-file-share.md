# 0167 — Samba via la façade de fichiers canonique

Statut : accepté. Date : 2026-10-11.

`bridge.samba` traduit SMB 2/3 vers les contrats publics de `app.file_share` avec
`smbprotocol`. Il n'ajoute ni modèle, ni route, ni outil MCP dédié. Le formulaire
de Tool existant découvre le bridge ; la connexion de chaque agent possède les
identifiants, et le code du Tool reste le schéma de ses URI.

Chaque opération synchrone possède une connexion signée et un pool privé, exécutés
hors de la boucle asyncio. Les réponses SMB et la durée cumulée sont bornées.
L'annulation attend la fin de l'opération avant de libérer ses temporaires et sa
connexion. La racine configurée est un serveur, un partage ou un sous-dossier existant.
Une racine serveur énumère ses partages via SRVSVC/NDR32 sur le pipe SMB authentifié
`IPC$/srvsvc`, avec réponses fragmentées, reprise serveur et limites de taille.
Les seuls partages disque accessibles deviennent des collections sous `<code>://` ;
l’agent parcourt leurs URI sans connaître le protocole, l’hôte ou les identifiants.
Une racine de partage conserve son confinement initial. DFS et les points de reparse SMB sont refusés ; les liens
POSIX côté serveur restent soumis à sa configuration, notamment `wide links = no`.

La lecture et l'écriture vérifient les métadonnées depuis le handle verrouillé.
Une création réserve le nom avec l'ouverture exclusive SMB ; une précondition de
version est vérifiée avant toute écriture. Le remplacement écrit dans le handle
verrouillé plutôt que d'annoncer une substitution conditionnelle atomique que SMB
ne fournit pas ici. Un échec réseau peut laisser un remplacement partiel ; aucun
rejeu automatique ni succès fictif n'est permis. Une création échouée tente sa
suppression depuis le même handle. Les dossiers ne sont jamais supprimés ou déplacés.

Les providers qui ne portent que des fichiers ne sont pas annoncés comme des fonctions
MCP réservées aux Tasks. Ils restent accessibles par les fonctions génériques
autorisées de `file_sharing`, en conversation comme en Task.

Un move entre partages est une copie bornée suivie d’une suppression conditionnelle
de la source ; un refus indique explicitement que seule la copie a réussi.

Les curseurs sont liés au serveur, au partage, à la racine, au compte et au mode
de parcours. L'empreinte de chaque dossier refuse une continuation périmée.
Le bridge participe aux modes d'indexation existants et ne possède pas de worker.

`make tests-samba` utilise exclusivement un serveur Samba et PostgreSQL éphémères,
des comptes synthétiques, sans port hôte ni volume durable. Les tests traversent
la façade et le vrai SDK pour les parcours fichiers, les conflits et les refus.
