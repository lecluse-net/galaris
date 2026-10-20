<p align="right"><strong>Français</strong> · <a href="../../en/dev/file-storage.md">English</a></p>

# Fichiers internes et migration du stockage

Les fichiers internes ont une identité `file://<uuid>` et un registre `files` dans
`core.storage`. File Sharing expose leurs lectures, copies, uploads indépendants et
miniatures. Chat et Documents conservent leurs rattachements et leurs droits. Les
Datasets restent, pour cette livraison, des documents ; `app.dataset` et `data://`
appartiennent à une étape ultérieure.

## Stockage

Les contenus textuels courants et historiques de Memory et Documents sont désormais
stockés dans leurs colonnes PostgreSQL `content`. Le transfert conserve les sources
de `/data/memory` et une sauvegarde SQL vérifiée. Voir le
[stockage textuel en base](memory-text-storage.md).

Le seul driver livré est `disk`. Il stocke les octets sous
`/data/files/<2 premiers caractères hexadécimaux>/<2 suivants>/<uuid canonique>`, sans
extension. `files` porte le nom officiel, le nom original, le MIME, la taille réelle,
SHA-256, le backend, la clé de stockage et l'audit. Le nom ne sert jamais de chemin.
Le protocole de driver permet une évolution ultérieure ; aucun driver S3/SMB ni SDK
associé n'est ajouté.

`file_aliases` relie les fichiers aux références métier historiques. Une lecture
`file://` exige un propriétaire indépendant (`file_owners`) ou une référence Document/
Chat autorisée au moment de l'accès. Connaître l'UUID ne donne aucun droit. Les URI
`file:///etc/...`, chemins Windows, hôtes et traversées sont refusés par le parseur.

`file_create(path="file://", name=..., content=...)` crée un fichier indépendant privé
pour l'agent et retourne son URI. `file_copy` accepte cette collection comme destination
explicite. Les octets sont immuables ; créer un autre fichier pour un autre contenu.
Les uploads HTTP sont streamés et limités par `MEMORY_RESOURCE_MAX_BYTES`. La façade MCP
conserve ses bornes de contenu existantes.

L'API `/file-share/files` permet l'upload multipart pour un agent géré. Les routes
`/{uuid}/content`, `/{uuid}/thumbnail` et le renommage `PATCH /{uuid}` appliquent RBAC,
périmètre de gestion et droits du fichier. Le propriétaire d’un fichier indépendant ou
un éditeur du Document parent peut le renommer. Tout renommage d’un fichier interne modifie
uniquement `files.name`. Documents, Datasets, Chat, Process et Fichiers relisent ce même nom,
y compris dans les aperçus, téléchargements et exports. Les noms historiques d’import ne
servent pas de libellés modifiables. Le renommage ne crée aucune révision du corps du Document.
Le nom original, le MIME,
l’UUID, les octets et leurs empreintes restent inchangés. Le navigateur
reçoit des téléchargements HTTP autorisés, jamais un accès au disque local.

Le moteur `core.preview.thumbnails`, sa racine `/data/thumbnails` et ses rendus restent
inchangés. La nouvelle façade emploie `file://<uuid>` comme référence de cache. Les
routes et caches historiques des PJ continuent de fonctionner.

## Pièces jointes de code source

Documents et Discussion acceptent les fichiers de code source, notamment JavaScript,
TypeScript, Python et shell, y compris les scripts avec shebang. Leurs octets restent
inchangés. L'aperçu commun utilise `CodeEditor` en lecture seule avec coloration syntaxique,
copie et téléchargement ; ouvrir une source ne l'exécute jamais. Un nom de fichier source
reconnu reste du code même si son type MIME indique HTML ou un média.

Les routes de lecture des pièces jointes et fichiers sources répondent en `text/plain`,
avec téléchargement forcé, `nosniff` et une CSP sans scripts ni accès réseau. Les règles
d'accès et les limites de taille restent applicables. Les fichiers HTML et SVG conservent
leurs lecteurs isolés existants.

## Migration DbAdmin

La composition `file_storage_composition` déclare un transfert `AFTER_EXPAND` et un
retrait des sources `AFTER_CONTRACT`, déclenchés par l'ajout de `files`/`file_aliases`.
DbAdmin journalise les obligations **avant** Atlas : un arrêt après création des tables
ne fait pas perdre la migration. Les phases disposent de transactions distinctes.

L'inventaire couvre :

- les PJ Documents, images importées et cartes de liens, y compris les PJ retenues ;
- les manifests des révisions et l'archive de séparation Document/Memory si elle existe ;
- les octets des fichiers appartenant au Tool Chat interne, uploads et notes vocales inclus.

Un simple pointeur de description laissé par un document déjà oublié n'est pas une
source : l'ancien stockage peut avoir légitimement effacé ses octets. Les références
encore portées par un manifeste, une révision ou l'archive restent à migrer et vérifier.

Les références externes, par exemple Nextcloud, ne sont ni ouvertes, ni téléchargées,
ni déplacées. Les corps de documents, synthèses et révisions Memory ne sont pas
indistinctement traités comme des PJ. Les HTML, JSON, messages et reçus existants ne sont
pas réécrits et aucun événement métier n'est réémis.

Le manifest durable `/data/files/.migration/internal-files.json` précède le premier
transfert. Il contient les sources, UUID, noms, alias, tailles et empreintes. Une
modification d'inventaire ou de source pendant une reprise arrête le traitement.
Les destinations sont publiées atomiquement après vérification et fsync. Une collision
d'UUID avec des octets différents bloque sans écrasement. Les sources restent présentes
jusqu'au commit du registre et à la vérification complète de toutes les destinations.
Le nettoyage retire ensuite chaque source explicitement identifiée et vérifiée.
Une interruption à ce stade laisse des destinations déjà durables ; la reprise tolère
les seules sources déjà retirées et toujours vérifiables par le manifest.

## Exploitation

Le chemin conteneur reste `/data/files`. Un montage additionnel dans l'override permet
un HDD ou volume dédié, indépendant de PostgreSQL et des miniatures :

```yaml
services:
  backend:
    volumes:
      - type: bind
        source: /mnt/galaris-files
        target: /data/files
        bind:
          create_host_path: false
```

Préparer le répertoire hôte et monter le disque final **avant la première migration**.
L'initialisation du volume règle les droits du répertoire pour l'utilisateur applicatif.
Tout worker futur manipulant ces octets doit recevoir le même montage et les droits utiles.
Le fichier caché `.store-uuid` est lié à la table `file_stores` et vérifié à chaque
synchronisation. Ne pas le supprimer ni en fabriquer un autre pour contourner un refus.

Arrêter les anciens writers avant la migration. `make update` recrée le backend et
exécute DbAdmin avant l'API ; ne pas migrer un ancien backend encore actif avec une
synchronisation en ligne. Prévoir l'espace du transfert vérifié et une fenêtre adaptée
au volume : le déplacement entre disques copie et vérifie avant le retrait des sources.
Une anomalie bloque le démarrage et conserve les sources disponibles ; réparer le
montage ou la source puis relancer le même chemin DbAdmin, sans supprimer son journal.

Sauvegarder ensemble PostgreSQL, `/data/files` **avec ses fichiers cachés**, `/data/memory`
et les données restantes de `/data/chat`. Restaurer cet ensemble à la même date logique.
Le nettoyage Chat ne parcourt jamais le registre partagé pour y supprimer des fichiers
d'autres domaines. Une PJ détachée reste lisible lorsqu'un document ou son historique
la conserve. Supprimer le document retire ses références dans la même transaction.
Seuls les fichiers sans autre référence sont marqués supprimés ; après commit,
leurs octets sont vérifiés puis effacés. Une référence Chat, un propriétaire indépendant
ou l'archive Document/Memory protège toujours le fichier. Les réservations internes
`agent-file://` et `archive-file://` ne donnent aucun droit de lecture.
Le tombstone conservé dans `files` interdit de réutiliser l'UUID. `purged_at` constate
la fin de l'effacement ; le reconciler DbAdmin reprend les purges interrompues,
y compris après unlink et avant commit. Aucun balayage des fichiers actifs n'est effectué.

Les tests synthétiques de stockage, migration, accès et non-régression sont dans
`core/storage/tests`, `core/dbadmin/tests`, `app/memory/tests/test_managed_files.py`,
`app/chat/tests` et `app/file_share/tests`.
Le scénario de suppression d'un document dans `app/memory/tests/test_service.py`
doit également passer : il protège l'effacement physique des PJ devenues inutiles.
