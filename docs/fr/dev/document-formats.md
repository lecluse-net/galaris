<p align="right"><strong>Français</strong> · <a href="../../en/dev/document-formats.md">English</a></p>

# Formats de document et contributions

Le **format de document** définit la représentation d'un contenu. Les formats intégrés
sont **Format Texte** (`text`, HTML éditorial) et **Format Data** (`data`, JSON).
Un format structuré, comme une future carte mentale, possède son propre codec ; utiliser
JSON pour son stockage ne le transforme pas en Format Data.

## Façade et responsabilités

Le package public `app.document` et sa façade exportent `DocumentFormatDefinition`,
`register_document_format`, `document_formats`, `document_format_definition`,
`document_format_catalogue`, `document_source`, `extract_document_content` et
`remap_document_references`. Un module natif ou un futur plugin utilise ce même contrat.
L'enregistrement refuse collisions, codes historiques réservés et versions incompatibles.
Il s'effectue lors de la composition d'une génération ; aucun installateur de plugins
ni chargement arbitraire de code à chaud n'est ajouté.

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
pas une certification. La bibliothèque propose **Formats de document**, avec les
capacités composées backend/frontend et une nouvelle tentative après erreur.
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

Ce contrat prépare les contributions de plugins. Installation, signature, génération
effective, isolation de code non fiable et publication de certifications restent dans
le [chantier plugins](../../../project/plans/infrastructure-plugins-galaris.md).
Les migrations entre versions de formats et les snapshots multifichiers cohérents
nécessitent une politique spécifique ; aucune conversion silencieuse n'est autorisée.
