<p align="right"><strong>Français</strong> · <a href="../../en/dev/memory-text-storage.md">English</a></p>

# Contenus textuels en base de données

Les textes natifs sont conservés directement dans les tables qui possèdent leur état
et leurs révisions. Contenu, métadonnées et historique sont enregistrés dans une même
transaction PostgreSQL ; les nouvelles écritures textuelles ne créent pas de fichier.

| Table et colonne | Contenu |
|---|---|
| `memory_items.content` | Souvenir privé courant |
| `documents.content` | Contenu courant d’un document |
| `memory_revisions.content` | Historique des souvenirs privés |
| `document_revisions.content` | Historique documentaire |
| `documents.summary_content` | Résumé partagé courant |
| `document_summary_revisions.content` | Historique des résumés partagés |

Les colonnes sont de type `TEXT`, sans normalisation des retours à la ligne. `NULL`
reste possible pour les ressources binaires ou fournies par un provider externe.
Les listes de métadonnées et les pages d’historique excluent les contenus complets.
URI, droits et conflits de modification conservent leurs règles actuelles.

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
