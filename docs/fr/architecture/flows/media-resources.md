<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/media-resources.md">English</a></p>

# Flux des médias et ressources

Galaris sépare l'identité canonique d'une ressource, son transfert borné et les temporaires
strictement techniques requis par certaines bibliothèques.

Les miniatures des documents et des discussions partagent `core.preview.thumbnails`.
Une URL/URI canonique donne une seule clé SHA-256 et un fichier PNG à la racine de
`GALARIS_THUMBNAIL_ROOT`, avec des métadonnées de page JSON sous la même clé si disponibles.
Le rendu tient dans 520 × 320, conserve proportions et transparence, sans bandes ajoutées.
Les captures HTML passent par le navigateur partagé ; les raccourcis `.url` réutilisent
directement l'aperçu de leur URL cible. Chaque domaine contrôle les droits avant d'accéder
au cache. Supprimer un raccourci ne supprime pas l'aperçu de sa cible.

## Recherche de sources

`search_web` appelle SearXNG par HTTP asynchrone, avec un client possédé par l'appel :
attente réseau et annulation ne bloquent pas la boucle des autres conversations. La réponse
normalisée conserve les sources utiles et les limites de couverture indiquées par le provider.
Des moteurs indisponibles ou des entrées illisibles donnent une recherche dégradée, avec
conservation des résultats partiels ; ils ne prouvent pas l'absence de sources pertinentes.
Une enveloppe invalide, un délai dépassé ou un refus HTTP est un échec de recherche distinct.
Les diagnostics ne recopient ni requête, ni corps de réponse, ni exception brute.

La requête, l'ordre des résultats et `SEARCH_DEFAULT_LANGUAGE` sont préservés. La langue du
diagnostic ne modifie pas implicitement celle du moteur. Aucun filtre lexical de pertinence
n'est appliqué. `SearchClient.search()` garde sa liste pour les consommateurs synchrones ;
`search_response()` et `asearch_response()` exposent également les limites de couverture.
La recherche, Browser et le transport HTTPS de fichiers restent des capacités distinctes.

## Sessions Browser et autorisation des outils

Les codes d'erreur de l'exécuteur sont limités au protocole public. Une enveloppe invalide
ou un code inconnu devient `executor_failed`, sans recopier de message externe ni d'URL
signée. Une session expirée reste un échec explicite ; l'action n'est pas rejouée dans une
nouvelle session. Une nouvelle navigation demeure possible à la demande de l'agent.

Tout appel natif relit la projection d'autorisation courante avant son effet, même si son
serveur MCP a été construit avant une révocation. Une réactivation permet de rappeler une
fonction déjà montée ; elle ne monte pas implicitement de nouvelles fonctions dans le run.

## Pièce jointe entrante

```text
Attachment canonique
  → <tool.code>://<room-locator-provider>/<attachment-uuid-local>
  → prompt et outils avec cette URI exacte
  → matérialisation temporaire bornée seulement si un consommateur exige des octets
  → suppression du temporaire
```

Le staging d'entrée ne change jamais l'identité présentée au modèle. Le harnais interne peut
télécharger une image, un audio, une vidéo ou un PDF dans un fichier temporaire afin de construire une entrée
multimodale, mais ce chemin n'est ni adressable par l'agent, ni durable, ni inscrit dans le Working
Set. Les médias non transmis nativement restent chez le provider et sont consommés par leur URI.

`console://` existe uniquement lorsqu'une console est attachée au run et désigne son home. Sans
console, aucun système de fichiers local n'est annoncé : l'agent ne peut manipuler que les
ressources du Messenger courant et les providers compatibles file-share retournés par
`file_schemes`. Une création exige alors une destination provider explicite.

Pour Hermès, le bridge diffuse les binaires sur le canal `raw` du harness manager générique vers
le volume de l’instance de cet agent. Il n’utilise jamais `/api/files`, dont la limite Hermès de
100 Mio ne fait pas partie du contrat Galaris. Les limites du canal de messagerie ou du domaine
média restent applicables ; le transport interne du runtime n’ajoute pas de plafond fixe.

## Pièce jointe sortante

`MessengerFileTransport` résout une room ou un destinataire direct, puis délègue au
`Messenger`. Une recherche de pièce jointe est bornée à l’historique récent. Les bridges qui
supportent de gros fichiers surchargent l’upload/download afin de streamer les octets.

Pour une demande conversationnelle de renvoi, le serveur résout d'abord le `local_id` canonique de
la pièce jointe dans la session autorisée, récupère ses octets par la façade Messenger, vérifie la
taille annoncée et réelle, puis les téléverse dans la même room. Le fichier n'est ni régénéré ni
converti et aucune Task de production n'est admise pour cette opération.

Dans une Task, chaque fichier produit est inscrit avec l'URI exacte du provider qui le possède.
Une livraison réussie conserve la source, l'artefact final chez le provider de destination et un
reçu (outil, destination et source). L'envoi Messenger est une copie sortante et ne supprime jamais
la source. Les labels et noms de fichiers
restent des données non fiables ; seuls les identifiants et références validés par le serveur sont
réinjectés aux étapes suivantes.

## URI de ressources

Lors d'une copie avec staging, un échec du téléchargement source précède tout upload :
il est signalé au harnais comme un refus sans effet sur la destination. L'agent peut corriger
la source et continuer. Après le début de l'upload, ou pendant un transfert direct en streaming,
une erreur conserve un résultat incertain et interdit un rejeu aveugle. Le temporaire de staging
est supprimé dans les deux cas.

La référence échangée entre tools, Tasks et providers est canonique : `console://path`,
`<code-tool>://room-provider/attachment-uuid`, `memory://uuid`, `document://uuid`,
`document://uuid/attachments/attachment-uuid`,
`galaris://process/workflow-id`, `galaris://skill/skill-code/SKILL.md`, `https://host/path` ou
`<code-tool>://locator`. `file_schemes`
et les autres fonctions `file_*` appartiennent au Tool intégré `file_sharing`, même pour le
provider `galaris://`. `file_schemes` annonce les capacités effectives, `file_write` écrit un
contenu complet UTF-8 ou binaire encodé en
base64 et `file_copy` streame entre deux schémas. Les chemins relatifs et les anciens schémas locaux implicites sont
refusés : aucune conversion implicite ne choisit un stockage à la place de l'agent.
Le provider `galaris://` expose uniquement la recherche par nom et par texte ; la recherche
sémantique appartient à `memory://`. Une copie depuis `galaris://`, `memory://` ou `document://`
utilise la limite binaire générale du fichier et non la limite d'une écriture texte unitaire.

Une destination collection de `file_copy` ou `file_move` conserve le nom de la source. Les
métadonnées du provider permettent de reconnaître un répertoire existant même lorsque l'appelant
omet le `/` final. Un espace provider tel qu'un workspace AFFiNE ou une room Messenger est lui
aussi complété avec le nom source ; le `/` reste nécessaire pour déclarer sans ambiguïté une
collection qui n'existe pas encore. Un move refuse avant la copie toute source que la façade
générique ne peut pas supprimer, afin de ne jamais produire un déplacement partiel présenté comme
un échec.

Le nom conservé est celui du `ResourceDescriptor` source, pas nécessairement le dernier segment du
locator : une pièce jointe adressée par UUID garde ainsi son véritable nom. Les outils spécialisés
image, audio et Messenger reçoivent eux aussi des URI canoniques. S'ils exigent un chemin local,
ils appellent `materialize_resource` vers un temporaire borné qu'ils détruisent après l'appel. Une
URI `nextcloud://`, `console://`, HTTPS, Mail ou Messenger est donc consommée directement. Les
sorties sont écrites par `resource_create`/`resource_write`
et exposent l'URI canonique créée ou livrée.

`console://` désigne toujours le home de l'utilisateur SSH. Les formes `~/path`, le chemin
absolu du home et sa forme sans slash après parsing URI sont rebasées sur ce home ; elles ne sont
jamais concaténées une seconde fois au chemin racine. Aucun segment virtuel `main/` n'est ajouté :
`console://mon_fichier` lit ou écrit exactement `~/mon_fichier`.
Les agents ne gèrent qu'un stockage local annoncé : `console://` lorsqu'il est disponible. Le
staging multimodal et les matérialisations spécialisées restent des temporaires serveur nettoyés,
sans URI et sans persistance après l'appel.

Les noms de fichiers ne portent aucune identité. Une pièce jointe est résolue par son UUID dans la
room autorisée ; un document par son UUID et ses ACL ; un provider externe par une connexion active
de l'agent. Les URL HTTPS sont en lecture seule et leur destination réseau est revalidée à chaque
redirection. `http://` n'est jamais téléchargé.

Les pièces jointes d'un document forment la collection
`document://<document-uuid>/attachments/`. `file_list`, `file_info`, `file_read` et les outils
spécialisés qui matérialisent une URI exigent le droit de lecture du document parent. `file_create`,
`file_copy` vers cette collection et `file_delete` exigent son droit d'écriture. Une pièce jointe
documentaire est immuable : la remplacer consiste à en créer une nouvelle puis, si nécessaire, à
supprimer l'ancienne. Ces mutations ne créent aucune révision de contenu du document.

Le chat et les Tasks internes partagent la préparation native des pièces jointes : messages
courants puis historique récent, avec déduplication par URI. Chaque média reste associé à son
message d'origine ; les médias d'une ancienne réponse IA sont présentés immédiatement après
celle-ci avec leur provenance. Les droits et métadonnées sont relus via `app.file_share` à chaque
nouvelle exécution. Les temporaires disparaissent avant l'inférence, y compris après erreur ou
annulation. Un checkpoint reprend son historique multimodal sans rajouter les mêmes fichiers.

L'admission croise les drapeaux `input_*` du modèle et les formats du transport. Les images
PNG/JPEG/WebP/GIF et PDF utilisent le SDK ; l'audio WAV/MP3 utilise Chat Completions. Le bridge
OpenRouter déclare en plus AIFF/AAC/OGG/FLAC/M4A et les vidéos MP4/MPEG/MOV/WebM. La vidéo des autres
transports, les formats inconnus et les fichiers inaccessibles restent des références explicites.
Hermès conserve son transport texte/image et ses replis propres.

À la découverte des modèles, une modalité absente reste inconnue jusqu'à l'enrichissement
par le catalogue. Un défaut de conversation ne doit pas fabriquer un refus d'image, de fichier,
d'audio ou de vidéo : les valeurs explicites du fournisseur restent prioritaires. L'API expose
les modalités connues séparément des booléens complétés par défaut.

Les modèles déjà enregistrés ne sont pas modifiés par une consultation du catalogue. Dans leur
fiche, « Actualiser les capacités » recharge les métadonnées et présente les différences ;
« Appliquer au formulaire » puis l'enregistrement rendent ces choix effectifs. Les modalités
inconnues conservent leur valeur enregistrée. Les tarifs, le contexte et les autres réglages ne
sont pas actualisés par cette action. Les modèles créés ensuite utilisent directement les
capacités découvertes. Aucun changement de schéma ni migration automatique n'est nécessaire.

`PYDANTIC_AI_BINARY_INPUT_MAX_BYTES` borne le total des octets natifs uniques préparés pour un run
(20 000 000 par défaut). La priorité va aux messages courants. Un dépassement ou une incompatibilité
produit un avis explicite dans le contexte ; l'agent peut appeler `image_read`, `audio_read`,
`video_read`, `audio_transcribe` ou un lecteur adapté. Ces outils restent disponibles et gardent
leurs effets, notamment la description Memory de `image_read`. Une URI seule n'est jamais présentée
comme du contenu déjà vu. La transcription automatique n'est évitée que pour un audio dont le
format et la taille annoncée permettent l'entrée native. Le comptage préalable ne traite pas le
base64 comme du texte : il réserve approximativement 4096 tokens par média ; seuls les usages
renvoyés par le fournisseur font foi pour la consommation réelle.

Dans l'historique, une pièce jointe reste imbriquée dans le message qui l'a transportée et expose
son URI construite avec le code exact du Tool, le locator provider de la room et l'UUID local du
fichier. La projection remise aux runtimes préfixe le message avec son horodatage de post, son
émetteur et sa nature humaine ou IA ; cette règle vaut pour les exécutions conversationnelles,
les Tasks et l'historique des tours audio. Messenger et file-share sont des capabilities et ne
créent aucun schéma. Les messages fichier seul ne sont pas éliminés par les projections de session
ou de runtime.

## Notes vocales

La normalisation commune :

1. vérifie la taille de la source ;
2. exige une piste audio ;
3. limite la durée à la fois par métadonnée et par nombre d’échantillons décodés ;
4. transcode en OGG/Opus mono 48 kHz ;
5. vérifie la taille de sortie ;
6. supprime toujours le fichier temporaire.

La limite de taille commune vient de `MESSENGER_CONTENT_MAX_MB`, exprimé en mégaoctets décimaux
(1 Mo = 1 000 000 octets), vaut 1 000 Mo par défaut et ne peut pas dépasser cette valeur. Elle
s'applique aux pièces jointes comme aux notes vocales. La durée
des notes vocales reste bornée séparément, en minutes, par
`MESSENGER_VOICE_MAX_DURATION_MINUTES`.

## Invariants de sécurité

- Refuser `..`, séparateurs injectés et chemins sortant de la racine.
- Borner taille, durée, historique et nombre d’entrées listées.
- Ne pas déduire la sécurité d’une extension de fichier seule.
- Ne pas journaliser secrets ni contenu binaire.
- Nettoyer les temporaires dans un `finally` ou après échec du stream.
- Tester l’isolation entre deux agents et les liens symboliques/path traversal.

Points d’entrée : `back/app/file_share/resource_uri.py`, `resource_service.py`,
`messenger_transport.py` et `back/app/messenger/media.py`.
