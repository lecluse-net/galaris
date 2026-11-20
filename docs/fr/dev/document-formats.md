<p align="right"><strong>Français</strong> · <a href="../../en/dev/document-formats.md">English</a></p>

# Formats de document et contributions

Le **format de document** définit la représentation d'un contenu. Les formats intégrés
sont **Format Texte** (`text`, HTML éditorial), **Format Data** (`data`, JSON)
et **Carte mentale** (`mindmap`, JSON structuré). La carte possède son propre codec,
ses conversions et ses commandes de branches. La [décision 0301](../../../project/decisions/0301-native-mind-map-documents.md)
décrit son contrat.

Dans la source native de la carte, le champ facultatif `checked` d’un nœud vaut `true`
pour une case cochée ou `false` pour une case vide. Une valeur absente ou `null` signifie
que le nœud est sans case. Les révisions et la source `.mindmap` conservent cette valeur.
Le rendu PDF indique l’état de la case. La création d’une branche sœur depuis l’éditeur
reprend la présence de la case du nœud de départ et initialise la nouvelle case à `false`.
Dans une commande `edit`, omettre `checked` conserve l’état et `checked: null` retire la case.

Le champ facultatif `theme` contient un `id` stable et une `version` positive. L’éditeur
applique la palette Solaire si cette référence est absente ou inconnue. Le codec conserve
une référence inconnue pendant les éditions de branches. **Appliquer** enregistre le thème
dans la révision du document. Les jetons Solaire fournissent les deux variantes affichées
dans l’éditeur et le lecteur de carte.

Le champ facultatif `background_color` enregistre la couleur RGB du fond sous la forme
`#rrggbb`. L’éditeur et le lecteur affichent cette valeur en clair et en sombre. Les
clés Solaire des anciennes cartes suivent encore le mode de l’application. Une valeur
absente ou une clé inconnue utilise le fond de l’hôte. Le codec conserve le réglage pendant
les éditions de branches. Le plein écran utilise la mise en page du lecteur Texte et reste
un état de vue.

Le [contrat des références documentaires](document-references.md) décrit les modes proposés par type de ressource, les commandes par mode et la composition entre formats. Les formats équipés d’un lecteur complet déclarent `embed` dans leur contribution.

## Cartes mentales et agents

Le Service **Document** déclare les outils MCP suivants. Ils peuvent être montés dans
le Chat et dans une Task selon les fonctions autorisées, les droits sur la carte et les
règles du contexte d’exécution. La lecture est activée par défaut. La création et l’édition
sont déclarées **Sur demande**, avec la politique effective des connexions.

| Outil | Contrat |
|---|---|
| `mindmap_create` | Crée un document privé pour l’agent et renvoie son URI `document://`, sa révision et l’identifiant `root`. Accepte jusqu’à 100 branches initiales, les parents avant leurs enfants. |
| `mindmap_read` | Lit la révision enregistrée courante. La liste renvoie les identifiants stables, les parents et les résumés des nœuds. Suivre `next_offset` pour lire la suite. Avec `node_id`, l’outil renvoie le corps HTML du nœud par tranches. Suivre `next_body_offset` jusqu’à la fin. |
| `mindmap_add` | Ajoute 1 à 50 branches en une seule révision. Fournir `expected_revision` et la liste `branches`. |
| `mindmap_edit` | Applique un lot de 1 à 50 commandes `add`, `edit`, `move` ou `remove` en une seule révision. Fournir `expected_revision` et la liste `operations`. |

Un ajout fournit un nouvel identifiant, l’identifiant du parent et le titre. Placer les
parents avant leurs enfants dans le lot. Une commande `edit` cible un nœud présent et indique
au moins un champ à modifier. Une suppression emporte toute la sous-branche. Si une
commande est refusée avant l’écriture, le lot entier est rejeté. En cas de conflit de
révision, relire la carte et réconcilier les modifications.

L’agent peut choisir une carte mentale si le résultat à conserver s’organise naturellement en
branches, par exemple un arbre de décision, une enquête ou un plan par chantier. Il respecte
le format demandé et réutilise une carte pertinente à laquelle il a accès. Le choix du format
se distingue de l’autorisation d’exécuter l’écriture. Une carte créée reste privée jusqu’à
ce qu’un partage explicite accorde les droits voulus.

Au moment de l’envoi dans le Chat interne, le contexte peut transmettre l’URI de la carte
ouverte et sa révision affichée. Le contrat d’attention ne contient ni l’identifiant du
nœud actif ni la sélection multiple. Pour une demande comme « ajoute un enfant à cette
branche », l’agent identifie la cible à partir du message et de `mindmap_read`. Si la cible
reste ambiguë, il demande son titre ou son chemin avant d’écrire. Le contexte d’affichage
n’accorde aucun droit et les outils vérifient la révision et les permissions.

## Façade et responsabilités

Le package public `app.document` et sa façade exportent `DocumentFormatDefinition`,
`register_document_format`, `document_formats`, `document_format_definition`,
`document_format_catalogue`, `document_source`, `extract_document_content` et
`remap_document_references`. Les modules natifs et les plugins signés utilisent ce contrat.
L'enregistrement refuse collisions, codes historiques réservés et versions incompatibles.
Le chargement des formats d'archives est réservé aux signatures d'éditeurs autorisés
selon le [contrat des bundles](plugin-bundles.md).

Documents conserve identité, propriétaires, ACL, classement, révisions, conflits et
publication des contenus. Les Process restent propriétaires de leurs définitions BPMN
et Memory de ses souvenirs privés. Un format n'introduit aucune bibliothèque parallèle.

Le descripteur déclare code stable, fournisseur, version du format, version du contrat,
MIME, stockage, valeur initiale, validation et extraction. Les contenus textuels utilisent
`documents.content` ; les contenus binaires utilisent des fichiers immuables `core.storage`.
Le validateur binaire et les octets initiaux sont requis pour un format de stockage `file`.
Les révisions retiennent les fichiers historiques et leur version de format.
Une sauvegarde binaire explicite publie immédiatement son checkpoint ; les sauvegardes
textuelles conservent leur regroupement après la période de calme. Les échecs de
publication nettoient les octets non publiés sans supprimer une source déjà enregistrée.

Un format textuel expose ses références avec `references` et les réécrit avec
`remap_references`. La copie passe par ces opérations pour publier ses propres assets.
Une référence externe conserve ses droits indépendants ; l'extraction ne doit pas
résoudre ni copier le contenu d'une ressource liée.

## Catalogue et frontend

`GET /api/documents/formats` expose le catalogue et les capacités déclarées : éditeur,
aperçu, intégration, miniature, PDF, export natif et import. Chaque capacité distingue
`native`, `fallback` et `unavailable`. `capability_complete` décrit cette déclaration,
pas une certification. Le catalogue reste disponible par l'API ; la bibliothèque ne
propose plus de bouton **Formats de document**. La création et le filtre de format
restent accessibles dans les commandes ordinaires de Documents.
`file_schemes` expose aussi `document_formats` pour les agents.
Les outils fichiers lisent et remplacent aussi les formats binaires, avec contrôle de
révision. Leurs pages base64 sont décodables indépendamment ; les offsets sont en octets.

Le package public frontend `@/app/document` exporte `registerDocumentFormat`,
`findDocumentFormat`, le catalogue et les contrats des contributions. Le fournisseur,
le code et la version des contributions doivent correspondre au catalogue backend.
Les composants lourds peuvent être chargés à la demande. Le format fournit son éditeur,
la validation du brouillon, son instantané statique et, facultativement, un lecteur
historique inerte et un composant intégré. La sauvegarde ordinaire reste celle de l'hôte.

Un éditeur binaire reçoit un `DocumentContentSource` : clé de contexte, révision,
lecture seule, lecture autorisée et sauvegarde sous contrôle de révision. Il conserve
son brouillon lors d'un refus, d'un conflit ou d'une interruption. Les métadonnées
locales sont sauvegardées avant publication binaire ; une réponse tardive n'actualise
pas un autre document. Son lecteur historique ne reçoit aucun droit de sauvegarde.
Le sixième argument de `snapshot` fournit aussi une source autorisée en lecture seule,
figée sur la révision demandée : PDF et miniatures peuvent ainsi lire un format binaire.
L'éditeur expose `DocumentFormatEditorHandle.flush` et `discardDraft` pour participer
aux contrôles de fermeture ; `flush` doit refuser de perdre un brouillon non sauvegardé.

Tout format peut être référencé dans Texte. Un rendu spécialisé utilise le même bloc
de ressource et les mêmes commandes d'ouverture ; le repli est une carte/miniature.
Les intégrations imbriquées détectent les visites répétées et bornent la profondeur.
Le partage du document hôte n'accorde aucun droit sur une ressource intégrée.
Les contraintes d'entrée des Process comparent le code du format réel, même lorsque
plusieurs formats partagent un MIME, et conservent les contrôles d'accès aux ressources.

## Contexte du Chat et révisions

L'éditeur peut exposer `DocumentFormatEditorHandle.captureFocus()`. Il renvoie un
`DocumentFocusAnchor` (`point` ou `rectangle`) ou `null`. Les coordonnées sont des
entiers dans l'espace du document, avec l'origine à zéro. Dessin rapporte des pixels de
l'image sauvegardée. L'hôte associe le repère à la révision courante après `flush`, ou
transmet la révision chargée dans l'historique. Le repère ne confère aucun droit.

Le codec peut ajouter `compare_revisions(before, after, region)`. Galaris vérifie les
droits actuels et fournit les octets de deux révisions sauvegardées compatibles avec
la version du codec. Le résultat doit être un objet JSON d'au plus 12 000 caractères
sérialisés. Dessin indique le nombre de pixels modifiés et le rectangle qui les contient.
En l'absence de codec compatible, le résultat indique si les empreintes diffèrent.
L'agent utilise `document_revision_list`, `file_read(revision=…)` et
`document_revision_compare`. Une tâche d'analyse avec un modèle visuel peut utiliser
`document_analyze(revision=…)` sur une version historique en image.

## Barre d'outils

Utiliser `DocumentToolbar` pour la barre principale du format. Le composant applique la
présentation de la référence graphique, les groupes, les infobulles et la navigation
au clavier. La barre déclarative reste en haut de la zone d'édition pendant le
défilement. Un éditeur natif l'importe depuis `@/app/document`. Un module compilé pour
un ZIP utilise le même composant fourni par `host.DocumentToolbar` dans
`createFormat(host)`.

Le format passe des groupes réactifs de type `DocumentToolbarGroup[]`. Chaque groupe
possède un `id` et un `label`. Chaque commande possède un `id` unique dans la barre et
un `label` déjà traduit. Le composant émet `command(id, value?)`. Le format exécute
l'action puis publie son nouvel état dans les groupes.

| Type de commande | Propriétés |
|---|---|
| `button` | `icon` du catalogue de la référence graphique et facultativement `showLabel`, `primary` ou `busy` |
| `toggle` | Les propriétés du bouton et la valeur contrôlée `pressed` |
| `color` | `value`, une couleur CSS hexadécimale compatible avec une entrée couleur |
| `range` | `value`, `min`, `max` et éventuellement `step` |

Un bouton ou une bascule marqué `secondary` passe dans **Autres outils** en dessous
de 1024 px. Les commandes secondaires ont aussi une icône et un libellé. Les
champs couleur et curseur restent dans leurs groupes. Utiliser `disabled` pour une
commande momentanément indisponible. Passer `readonly` quand le contenu est en lecture
seule. Une commande qui reste utilisable, comme Copier, déclare `readOnly: true`.
Le lecteur historique affiche sa propre vue de lecture.

```vue
<DocumentToolbar
  :label="t('editor.tools')"
  :groups="toolbarGroups"
  :readonly="source.readonly"
  @command="runCommand"
/>
```

Dans Dessin, les actions du canevas et l'état des outils suivent ce contrat. Les
révisions et la sauvegarde suivent toujours `DocumentContentSource`. Texte et Carte
mentale réutilisent la même enveloppe pour leurs commandes spécialisées. Données
utilise la barre déclarative pour la copie JSON.
[Contrats TypeScript](../../../front/core/util/documentToolbar.ts)
· Exemple dans `plugins/sample/drawing/DrawingEditor.vue`

## Pièces jointes, conversion et export

Les lecteurs de fichiers sont indépendants des formats documentaires. Le contrat public
`registerResourceViewer` de `@/core/util` reçoit un code, un fournisseur, une version,
une priorité, une détection MIME/nom et un composant. Il s'applique à la surface partagée
`ResourceAttachments`. Le lecteur reçoit une source autorisée, pas un chemin serveur.
Il nettoie ses requêtes et ressources au changement de contexte.

Les convertisseurs serveur réutilisent `core.preview.PreviewConverter` : sélection
déterministe, version, source préservée et dérivé temporaire nettoyé à la sortie.
Les aperçus de PJ (`preview=true`) et leur génération de miniatures utilisent ce port.
Un téléchargement ordinaire conserve les octets originaux. Les miniatures sont des
dérivés dispensables, soumis aux ACL de leur source.

Les formats déclarent leurs extensions d'import et MIME. Un contenu textuel natif
est validé par son codec ; un format binaire conserve ses octets. Les conversions
bureautiques/PDF et imports avec médias réutilisent la publication existante, avec
conservation de l'original et nettoyage des ressources non publiées après échec.

Le PDF utilise un instantané statique et le moteur Chromium isolé existant. Le rendu
ne rejoue pas les scripts ; il ne remplace pas l'original. Les formats peuvent fournir
un instantané spécialisé ; un repli littéral ne promet aucune fidélité graphique.
Le téléchargement de source reste disponible sans plugin, sous les ACL courantes,
avec `GET /api/documents/{uuid}/source` et une révision facultative.
Une contribution frontend peut déclarer `nativeExtension` pour proposer un nom
de fichier adapté au téléchargement depuis l'éditeur.

La carte mentale construit son instantané graphique à partir de l'arbre complet en
mémoire. `prepareMindMapGraphic` réutilise l'instantané éditorial portable pour assainir
les contenus des nœuds et résoudre les images dans le contexte de lecture courant.
Le diagramme partage les styles de connexion de l'éditeur et reprend le thème et le fond.
L'export raster borne la définition du PNG. L'impression ajuste le diagramme sur une page
A4 en paysage et utilise le même cadre sans scripts que le document Texte. Les objets
interactifs utilisent le titre et le texte de leur référence. Le PDF existant conserve
sa projection textuelle de l'arborescence.

L'archive ZIP réutilise le diagramme graphique et l'inventaire des pièces jointes.
L'API d'export commune conserve ses contrôles d'accès et réécrit les liens vers les
fichiers inclus dans l'archive. Le partage PDF sur mobile utilise le même dialogue
que Texte avec la projection hiérarchique de la carte comme source du PDF.

L'éditeur conserve un historique borné en mémoire. Toute opération sur la carte publie
la source via le canal d'autosauvegarde habituel. Annuler et rétablir publient à leur
tour une source valide. La saisie d'une session de texte riche forme un groupe dans
l'historique de la carte et conserve l'historique local de l'éditeur. Le remplacement
global valide tous les nœuds modifiés avant publication, à partir des textes et des
plages HTML qui conservent les attributs et la structure.

## Qualification d'un format

`qualify_document_format` exécute des `FormatExample` synthétiques avec résultats
attendus indépendants : validation, extraction, références, remappage et source invalide.
Il accepte également des exemples binaires. Les erreurs sont rapportées sans contenu.
Ce TCK de codec ne prétend pas vérifier les droits ni l'interface.

`document_format_conformance` agrège des `FormatSuiteEvidence` pour le code, le fournisseur,
la version et le SHA-256 exact de l'implémentation. Les suites requises sont : codec,
cycle documentaire, permissions, concurrence, assets, import, aperçu, intégration,
miniature, PDF, source native, navigateur et absence du plugin. Une suite manquante,
vide, échouée, dupliquée ou d'une autre implémentation ne passe pas. Les capacités
déclarées et les preuves de qualification restent distinctes ; le catalogue courant
n'annonce pas automatiquement les rapports locaux comme certification installée.

`make tests-document-formats` exécute la batterie documentaire backend dans une base
éphémère, puis les parcours navigateur ciblés. Les sorties réelles font foi : un arrêt
ou une erreur n'est jamais un succès. Les contributions de test `example.outline`,
`example.binary` et `example.note` vérifient l'extension sans ajouter de format produit.
Un futur plugin devra fournir ses exemples, ses tests de rendu et les preuves des
autres suites ; cette batterie du dépôt ne certifie pas du code tiers inconnu.

## Migration et limites

`document_format` est l'unique nom dans le code, les API et la base. Les anciens champs,
imports et la route `/documents/types` sont supprimés. DbAdmin copie la colonne historique
`document_type` vers `document_format`, vérifie le transfert, puis retire la source.
Les anciens codes `html` et `form` deviennent `text` ; les contenus et leurs versions,
propriétaires, droits et identités sont conservés. Une action Process migre les contraintes
dans le BPMN, ses révisions et les graphes figés des runs, sans modifier leurs états ni
les valeurs utilisateur. Une interruption conserve les sources et permet la reprise.
Les URI `document://` et `data://` restent stables. Un format/version absent n'est jamais
réinterprété comme du HTML ; source, métadonnées, droits et révisions restent récupérables.

L'isolation de code non fiable et la publication de certifications restent dans le
[chantier plugins](../../../project/plans/infrastructure-plugins-galaris.md).
Les migrations entre versions de formats et les snapshots multifichiers cohérents
nécessitent une politique spécifique ; aucune conversion silencieuse n'est autorisée.
