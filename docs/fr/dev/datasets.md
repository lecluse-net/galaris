<p align="right"><strong>Français</strong> · <a href="../../en/dev/datasets.md">English</a></p>

# Documents Données et contrats JSON

`app.document` possède l'identité, le contenu courant, les métadonnées, le partage,
le classement et les révisions de tous les documents. `app.document.text` fournit
le comportement HTML ; `app.document.data` fournit le comportement JSON. Le registre
`app.document.type_registry` décrit les types disponibles et leur validation.
La façade JSON publique est `app.document.data.facade`. Les anciens imports
`app.dataset` et `app.dataset.facade` délèguent à cette implémentation ; ils ne
possèdent plus une seconde copie du contenu.

## Persistance et historique

Les types publics sont `text` et `data`. Les anciens contenus HTML deviennent des
Textes. Données accepte toutes les racines JSON, sans schéma associé, et conserve
le texte UTF-8 exact, y compris indentation et fins de lignes. Chaque écriture
vérifie les droits courants et `expected_revision`. Un JSON invalide ne remplace
jamais la dernière version enregistrée.

`documents` et `document_revisions` sont communs. Le stockage `text` conserve le
contenu en base ; le stockage `file` référence un fichier immuable de `core.storage`
sous `/data/files`. Une révision protège son fichier même si le contenu courant
change. Les miniatures sont des dérivés régénérables. Titre, propriétaire, sujet,
partage, résumé et mots-clés sont courants ; les modifier ne crée pas de version
de contenu. Une restauration crée une nouvelle version sans restaurer ces métadonnées.
Le format du résumé est explicite : les anciennes descriptions JSON en texte brut
restent du texte brut, sans être interprétées comme du HTML.

## Bibliothèque et interfaces

La bibliothèque Documents liste Texte et Données, filtre le type avant pagination
et conserve les droits dans les compteurs. Le bouton de création ouvre le menu des
types ; les menus contextuels offrent les mêmes créations. L'enveloppe de l'éditeur
est commune. La contribution Texte utilise l'éditeur HTML ; Données utilise
`CodeEditor` JSON, y compris pour l'aperçu historique. L'autosauvegarde conserve un
brouillon invalide et bloque le départ tant qu'il n'est pas enregistré ou abandonné.

`POST /documents` accepte `document_type="text"` ou `"data"`. Les routes `/datasets`
et les URI `data://` restent compatibles et accèdent aux mêmes enregistrements.
Les anciens liens `/dataset/:id` ouvrent le document dans `/documents`.
Un lien entre documents ne transmet aucun droit. Les applications HTML gardent
leur consentement personnel lié à la révision de la page et leur quota d'écriture.

## Codec et requêtes

Le codec de variables conserve `{type, value}` avec `int`, `float`, `string`, `bool`,
`Agent`, `User`, `File`, `Document`, `Dataset`, `array` et `object`. Les imports
historiques `app.process.values` gardent le profil BPMN v2 figé. Process possède les
déclarations de ses variables et ses définitions exécutables ; celles-ci ne deviennent
pas des Documents. Le typage d'une référence ne donne jamais accès à sa cible.

Les entiers du codec sont transportables sans perte en JavaScript. Les nombres
non finis, clés JSON dupliquées et charges excessives sont refusés. La source JSON
d'un document conserve néanmoins ses nombres exacts ; aucune normalisation du codec
Process ne lui est imposée.

`dataset_query` interroge un `data://` autorisé par pointeurs JSON RFC 6901 : filtres
combinés par AND, projection, tri, pagination et agrégats. `expected_revision`
protège la lecture entre pages. Les résultats distinguent valeurs absentes et nulles ;
les agrégats numériques utilisent des chaînes décimales. Les unités, expressions et
conversions de date implicites ne sont pas déduites. Les pages ont 50 éléments par
défaut et acceptent 500, avec un budget de contenu borné. La recherche sémantique dépend
du modèle vectoriel configuré et de l'indexation Dream ; sa couverture incomplète reste visible.

## Migration et compatibilité

La décision [0252](../../../project/decisions/0252-typed-documents.md) décrit la transition.
DbAdmin archive les sources, transfère les contenus exacts, les versions, les auteurs,
les droits et les métadonnées, puis vérifie les copies avant de finaliser les types.
Les anciennes projections documentaires de même identité sont rapprochées ; une
collision avec un document indépendant bloque le transfert.

Le classement Dataset courant fait autorité pour ses documents. Les anciens placements
des projections documentaires sont archivés et remplacés pour éviter de réintroduire
un héritage de partage obsolète. Les dossiers et apparences personnels sont conservés.
Les rôles Dataset reçoivent les capacités Document correspondantes pour la bibliothèque
commune. Les marqueurs durables empêchent un rejeu de restaurer des droits révoqués ou
d'écraser des modifications ultérieures.

Les tables `datasets` et `dataset_revisions` restent des sources de récupération.
Leur retrait appartient à une livraison ultérieure ; aucune suppression de ces sources
n'accompagne cette migration. Les alias vérifiés, pièces jointes, consentements et
budgets conservent leurs identités et leurs contrôles. La migration se vérifie via les
tests PostgreSQL réels de `app/document/tests/test_typed_document_upgrade.py`.
