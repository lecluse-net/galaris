<p align="right"><strong>Français</strong> · <a href="../../en/dev/memory-text-storage.md">English</a></p>

# Contenus textuels en base de données

Les textes natifs sont conservés directement dans les tables qui possèdent leur état
et leurs révisions. Contenu, métadonnées et historique sont enregistrés dans une même
transaction PostgreSQL ; les nouvelles écritures textuelles ne créent pas de fichier.

| Table et colonne | Contenu |
|---|---|
| `memory_items.content` | Souvenir privé courant |
| `documents.content` | Contenu courant d’un document Texte ou Données |
| `memory_revisions.content` | Historique des souvenirs privés |
| `document_revisions.content` | Historique documentaire |
| `documents.summary_content` | Résumé partagé courant |
| `goals.description` | Description HTML courante d’un objectif, sans historique de texte |

Les résumés et mots-clés documentaires sont courants, sans historique propre.
Restaurer le contenu d'un document conserve ces métadonnées. Les anciennes versions
de résumés sont archivées avant le retrait de leur table, avec vérification d'empreinte
et conservation des références de fichiers. Voir les [contrats Données](datasets.md)
pour la migration des anciens Datasets et leur stockage commun avec les Textes.

Les colonnes sont de type `TEXT`, sans normalisation des retours à la ligne. `NULL`
reste possible pour les ressources binaires ou fournies par un provider externe.
Les listes de métadonnées et les pages d’historique excluent les contenus complets.
URI, droits et conflits de modification conservent leurs règles actuelles.

Les contacts font exception : `memory_items.content` et leurs
`memory_revisions.content` restent `NULL`. Chaque lecture reconstruit le JSON depuis
les métadonnées et identités canoniques du carnet privé, même lorsqu’une ancienne
révision Memory est demandée. Les index de recherche restent des projections ; ils
ne servent pas de contenu à la lecture. Le reconciler DbAdmin `app.memory.live_contacts`
retire les anciennes copies sans modifier les identités ni les souvenirs liés.

## Migration sans effacement des sources

`app.memory.content_migration` enregistre l’action DbAdmin
`app.memory.inline_text_contents`, déclenchée par l’ajout des colonnes. La première
bascule exige l’arrêt des anciens writers ; `make update` applique les changements
avant le démarrage de l’API. Ne pas transférer depuis un ancien backend encore actif.

La migration traite les lignes par lots de 100 et vérifie SHA-256 et les octets UTF-8.
Elle compare les valeurs SQL à une sauvegarde immuable dans
`galaris_migration.memory_text_contents`. Une source absente, une empreinte différente,
un texte invalide ou un caractère NUL arrête le traitement sans effacer la source.
Une erreur annule la transaction ; le rejeu conserve la sauvegarde et ne remplace pas
un contenu modifié légitimement après la bascule.

Aucun fichier de `/data/memory` n’est supprimé par cette migration. Les sources des
archives et des anciens jeux de données restent disponibles. Sauvegarder PostgreSQL
**avec `galaris_migration`** et les fichiers sources jusqu’à décision explicite de
retirer ces copies. Les pièces jointes conservent leur stockage de fichiers ; les
providers externes ne sont ni téléchargés ni réécrits.

Voir les [contenus riches](../user/rich-content.md) et la
[décision 0188](../../../project/decisions/0188-inline-memory-and-document-text.md).
