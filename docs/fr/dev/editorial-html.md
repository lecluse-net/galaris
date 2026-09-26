<p align="right"><strong>Français</strong> · <a href="../../en/dev/editorial-html.md">English</a></p>

# Contrat des contenus HTML éditoriaux

La décision [0080](../../../project/decisions/0080-editorial-html.md) définit le périmètre.
Pour les contenus éditoriaux et les documents de type `html`, le corps autoritaire est un fragment UTF-8 `text/html`, `content_profile_version: 1`.
`rich-text` couvre les six catégories Memory, les objectifs et profils ; `document` ajoute
les images jointes, les formulaires, le CSS et le JavaScript des documents de travail ordinaires.
Un document Goal utilise `rich-text`, même
ouvert depuis la bibliothèque ou le Chat. Les ressources binaires/JSON/code et les skills
ne passent pas dans cette conversion.

## Documents comme pivot de l'information

Les profils d'agents sont des ressources virtuelles `galaris://agent/<id>`, sans document
ni dossier dans la bibliothèque. `agent_list`, `agent_get` et le champ API `resource_uri`
fournissent cette URI. `file_read` renvoie directement la personnalité et la fiche de poste
actuelles, en HTML `rich-text` dans leur enveloppe JSON, avec les droits d'accès existants.

Les documents possèdent un type immuable : `html` (défaut, y compris les documents existants)
ou `dataset`. Un Dataset est un document JSON, visible, filtrable et triable dans la même
bibliothèque, avec titre, icône, classement, partage et historique identiques. CodeEditor
en mode JSON remplace CKEditor. Le JSON UTF-8 est validé avant enregistrement, sans modifier
sa mise en forme ; une saisie invalide reste un brouillon. Il n'est jamais converti en HTML.
Le corps peut être toute valeur JSON valide ; NaN et Infinity sont refusés. La limite est
2 000 000 octets, sous réserve du quota de stockage. Voir la
[décision 0124](../../../project/decisions/0124-document-types-and-datasets.md).

L'API de création et `file_create` acceptent `document_type="dataset"` ; les mises à jour
refusent ce champ et les changements de MIME incompatibles. Exemple :
`file_create(path="document://", name="Scénarios", document_type="dataset", content='{"scenarios": []}')`.
Pour un Dataset, `file_read` pagine en caractères et `file_edit` édite des lignes ; le JSON
complet après modification doit être valide. `file_write`, `file_edit` et `file_append`
exigent la révision lue. Préférer remplacement ou édition à la concaténation de JSON.
Copier une source `application/json` vers `document://` crée un nouveau Dataset privé.
Les exports PDF/HTML restent propres aux documents HTML. Les autres types de documents
restent hors périmètre. Le [HTML interactif](document-apps.md) permet désormais
aux documents HTML de contenir des formulaires et d'accéder à des datasets déclarés via un
runtime isolé ; l'historique et les exports restent inertes.

Créer ou enrichir un document lorsque le résultat demandé appelle un contenu rédigé durable
à conserver, réviser ou partager. Une Task ne nécessite pas à elle seule un document : les réponses
autonomes et confirmations restent dans la conversation, l'état opérationnel dans la ressource
métier concernée. Ne pas ajouter un document uniquement pour consigner une action ou attester son
achèvement. Respecter le type de ressource demandé ; une opération indisponible appelle une
explication de la limite, pas la création d'un document de substitution.

Pour ces contenus durables, les documents Galaris sont le support canonique. Memory et File Sharing
sont des services système obligatoires, comme Galaris et Conversation. Leurs connexions et
fonctions restent actives et non modifiables. Le catalogue effectif conserve les restrictions
de contexte et les ACL des ressources ; les bridges optionnels peuvent toujours être désactivés.

Avec les fonctions nécessaires disponibles, rechercher et enrichir le document pertinent.
Créer un nouveau document seulement si le contenu nécessite un support distinct, avec
`file_create(path="document://", name="Titre", content="<p>Contenu HTML.</p>")`.
Son URI reste la référence entre recherche, rédaction, revue, Tasks et
conversations. Il conserve les sources et liens vers les documents associés ; les médias restent
des ressources canoniques ou des pièces jointes. Les conversations portent la discussion et une
transmission concise du résultat, sans entretenir une copie concurrente de son contenu.

Un nouveau document est privé. `memory_sharing` résout le destinataire humain, agent ou équipe
et sa version de droits ; `document_share` accorde `read` ou `edit` avant transmission. Un lien
ou `document_show` ne donne aucun droit. Une livraison externe est une opération distincte dont
le succès doit être confirmé par le transport.

Les fichiers Markdown/HTML autonomes restent appropriés pour un format explicitement demandé,
du code ou une page interactive. Les réponses conversationnelles courtes restent dans le chat ;
les faits durables concis relèvent de `memory_remember`. Les artefacts techniques produits par
les outils, dont les transcriptions et `.summary.md`, gardent leur contrat ; une synthèse rédigée
à partir de ces sources privilégie le document. Une panne temporaire ne vaut pas désactivation
et ne justifie pas un remplacement silencieux du document par un fichier.

Cette politique guide les agents ; elle ne convertit pas les anciens fichiers et ne modifie pas
les ACL des ressources existantes. `document_show` reste indépendant de la connexion Memory.
Voir la [décision 0104](../../../project/decisions/0104-documents-information-hub.md).

## Entrées et normalisation

Les écritures HTTP éditoriales annoncent `X-Editorial-Profile-Version: 1`. Un client ancien
reçoit 409 et doit conserver son brouillon puis charger la nouvelle application. Les services
et outils internes utilisent leurs contrats HTML explicites ; Memory refuse une rétrogradation
HTML vers Markdown. Une conversion d’import appelle `convert_to_html` avec le MIME source.
Une mise à jour du MIME sans le nouveau corps est refusée.

`core.util.rich_text` valide les structures avant nh3 et sérialise de manière déterministe.
Les limites sont 2 000 000 octets HTML, 500 000 caractères visibles, 50 000 éléments, profondeur
64. Le suivi Goal limite sa sortie agentique à 120 000 caractères sérialisés et 30 000 visibles.
Les couleurs acceptent les valeurs hexadécimales, RGB/HSL et une liste de noms CSS ; les
alignements sont left/center/right/justify. Les styles sont limités à la typographie, aux
couleurs, dimensions et propriétés de tableaux. Les dimensions CSS sont bornées à 1 600 unités
ou 100 %, les dimensions naturelles des images à 16 000 pixels. Les liens
acceptent HTTP(S), mailto et les références internes reconnues. Le profil `rich-text` refuse
scripts, événements DOM, SVG et styles arbitraires. Les documents ordinaires les acceptent,
ainsi que les formulaires, pour un rendu isolé ; voir [HTML interactif](document-apps.md).
Les iframes et images distantes restent refusées. Les API valident avant toute révision.

CKEditor 5 est l’arbre d’édition temporaire. `getData()` traverse le filtre frontend avant émission,
puis la validation backend reste autoritaire. Aucun aller-retour vers Markdown. Les lecteurs
historiques utilisent le MIME de la révision ; les artefacts HTML actifs restent séparés du
lecteur éditorial. Les fichiers Markdown et leur lecteur existant sont conservés pour les skills.

`RichTextEditor` expose deux modes via `profile` : `rich-text`, mode simple par défaut pour
les champs multilignes enrichis, et `document`, mode complet avec page, images, pièces jointes
et exports. Les usages métier hors documents conservent le mode simple. Le groupe Lecture
est commun aux deux modes : Source et Plein écran sont toujours présents ; Pleine largeur
est réservé au mode document, qui possède un affichage en page. La contribution `editorVoice.ts`
du module actif `app.llm` fournit automatiquement la dictée et la lecture vocale aux deux modes,
via le contrat `EditorVoiceProvider` de `core.util`. Aucun branchement n’est nécessaire dans
les écrans. Changer de présentation n’émet aucune modification du contenu. Une nouvelle valeur
externe, une recréation ou la fermeture de l’éditeur arrête les requêtes et libère l’audio.

## Vue du code source

La vue « Code source » de CKEditor utilise une police à chasse fixe de 12 px. Le plugin
`GalarisSourceEditing` colore le HTML et les portions JavaScript/CSS intégrées avec highlight.js,
en utilisant la palette Solaire dans les deux thèmes. La coloration est une couche visuelle
séparée du champ natif : elle ne modifie ni la sélection, ni l’historique de saisie, ni le HTML
enregistré. Le texte source est échappé par le moteur de coloration et n’est jamais exécuté
dans cette vue.

## Blocs de code dans les documents

Les blocs de code et le code en ligne utilisent une police à chasse fixe de 12 px. Les blocs
sont colorés avec la palette Solaire en édition, en lecture et à l’impression. Le langage
du bloc guide highlight.js ; les blocs sans langage ou en texte brut utilisent une détection
automatique limitée aux langages courants. Les langages inconnus et les blocs de plus de
50 000 caractères restent affichés sans coloration.

`GalarisCodeHighlight` utilise des marqueurs CKEditor temporaires, uniquement convertis vers
la vue d’édition, sans effet sur les données ni l’historique d’annulation. Seuls les blocs
modifiés sont recolorés. Le lecteur et l’impression colorent une copie du HTML filtré ;
les classes de coloration ne sont jamais enregistrées dans le document.

Un clic dans un bloc affiche une barre flottante : langage, numéros de ligne, retour à la
ligne et copie. Le changement de langage cible explicitement ce bloc sans en créer ni en
fusionner d’autres. `Alt+F10` place le focus dans la barre et `Échap` la ferme. En lecture
seule, la copie reste disponible et les options du document sont désactivées.

Les options sont conservées sur `<code>` par `data-code-lines="true"` et
`data-code-nowrap="true"`, validés par les deux filtres HTML. Les numéros sont des éléments
visuels temporaires, exclus du texte copié, des données enregistrées et de l’index sémantique.
Ils suivent les lignes logiques, y compris lorsqu’une ligne longue revient à la ligne à l’écran.

## Révisions et lecture agentique

Le partage MCP passe par `memory_sharing` pour découvrir les destinataires et leur
`lock_version`, puis `document_share` ou `memory_share` avec exactement un `agent_id`,
`user_id` ou `team_id`. L’accès vaut `read`, `edit` ou `none` pour retirer ce grant précis.
Les équipes comprennent leurs membres humains et IA actuels. Cette mutation ne change ni
le HTML ni sa révision : `expected_lock_version` protège les ACL, `expected_revision`
protège les écritures de contenu. Le skill système Galaris fournit les exemples complets.

`file_read` retourne le HTML, le profil, la révision, `offset_unit: block`, les blocs numérotés
et `next_offset`. Les offsets sont des positions de blocs, les numéros commencent à 1 et sont
valables pour la révision observée. La limite par défaut reste 20 000 caractères. Un bloc
indivisible trop grand produit sa taille requise : un appel explicite peut aller jusqu’à
2 000 000 caractères. Aucun fragment de balise coupée n’est présenté comme HTML.

`file_edit` utilise `start_line`/`end_line` comme numéros de blocs uniquement pour document://.
`expected_revision` y est obligatoire, ainsi que pour remplacement et ajout. Le remplacement
textuel documentaire cible une occurrence unique dans un nœud textuel, jamais les attributs.
Les ajouts répétés immédiatement par le même auteur et la même tâche sont idempotents.
Une sauvegarde sans changement canonique ne crée pas de révision supplémentaire.

Les révisions contiennent leur format et un manifeste `content_images`. Retirer une image du
corps ne retire pas son attachement. Supprimer un attachement le masque mais retient ses octets
jusqu’à l’oubli définitif du document. Une restauration crée une nouvelle version compatible,
sans restaurer les ACL historiques. Les URL temporaires sont créées en mémoire et révoquées
au démontage ; les réponses de téléchargement interdisent les caches partagés.

Le téléversement vérifie PNG/JPEG/WebP/GIF par Pillow, avec les quotas documentaires existants,
40 millions de pixels et 16 000 pixels par dimension. L’annulation avant publication nettoie
la ressource non référencée ; un attachement publié mais pas encore inséré reste disponible
pour réessayer. Ne jamais purger un fichier à partir de sa seule absence dans le corps courant.

## Export PDF

`POST /memory/documents/{document_id}/export-pdf` vérifie les droits de lecture et le profil
`document`, puis transmet à `core.preview.render_html_pdf` une copie statique du contenu en
cours. Le frontend partage les styles d’impression et intègre les images autorisées en data
URI ; cet export ne sauvegarde pas le document. Chromium, dans `browser-executor`, imprime
une page temporaire sans JavaScript ni accès réseau, puis ferme son contexte. Les limites
sont 12 Mio de HTML avec images, 16 Mio de PDF, 30 secondes de rendu et deux exports simultanés.
Le service de rendu doit être reconstruit lors d’une modification de son code.

## Pièces jointes, cartouches et export portable

Le profil documentaire accepte les formulaires et scripts dans un contexte isolé, avec la
barre d'outils et le texte éditable habituels. Leur code n'apparaît que dans Source ; les
historiques et exports restent inertes. La restauration conserve la source. Le mode Source
permet toujours de saisir explicitement du HTML interactif.

Coller une page HTML ou du contenu copié depuis une page dans le corps importe directement
des blocs éditables, sans dialogue ni bloc de page isolé. Les titres, paragraphes, listes,
liens et tableaux sont conservés ; les styles présents dans le presse-papiers sont convertis
en mise en forme éditoriale autorisée. Scripts, contrôles interactifs et feuilles de style
externes ne sont pas importés. Dans un bloc de code, le collage reste littéral.
Le Markdown collé est également converti en HTML éditable : titres, listes, citations,
tableaux, emphase, liens et blocs de code. Le HTML déjà mis en forme garde la priorité ;
les enveloppes de texte brut copiées depuis un éditeur de source ne bloquent pas cette
conversion. Le texte ordinaire, le code en ligne, les blocs de code et la saisie dans Source
gardent leur comportement littéral. Les images Markdown suivent le même import en PJ.
Les images raster intégrées en base64 passent par l’upload des pièces jointes. Les images
HTTPS publiques passent par `POST /memory/documents/{document_id}/import-image` : vérification
du périmètre utilisateur et du droit d’écriture avant téléchargement, port
`core.preview.read_web_image`, transport File Share protégé contre les adresses privées et
redirections internes, limite de 10 Mo et 15 secondes, puis validation et stockage comme PJ.
Chaque source n’est importée qu’une fois par collage (50 sources maximum), et le corps conserve
uniquement son URI canonique `document://…/attachments/…`. Une image inaccessible conserve
sa description et déclenche un avertissement sans perdre le texte. L’annulation ou le changement
de document empêche une réponse tardive de modifier le corps ; une PJ déjà créée reste disponible.

Les fichiers HTML sont autorisés comme pièces jointes et ouverts par la visionneuse HTML
existante, isolée de l'origine applicative. Les liens canoniques de pièces jointes sont
acceptés dans `<a href>` ; leur navigation résout le document et la pièce jointe concernés.
`GET /memory/documents/{document_id}/attachments/{attachment_id}/info` permet aussi d'ouvrir
un fichier retiré de la liste mais retenu pour le texte ou l'historique, sous les ACL actuelles.

`POST /memory/documents/{document_id}/link-card` exige un agent dans le périmètre utilisateur
et le droit d'écriture avant tout accès réseau. `app.file_share.web_metadata` partage avec
Messenger l'extraction Open Graph et YouTube oEmbed via le transport HTTPS public protégé
contre les adresses privées et redirections internes. Memory passe par le port
`core.preview.preview_web_link`, enregistré par File Share au chargement, pour éviter une
dépendance circulaire entre les deux domaines. Pages : 1 Mio et 15 secondes ; images :
5 Mio, 40 millions de pixels, redimensionnement maximal 640 × 360 et conversion JPEG.
Le résultat est un `blockquote.galaris-link-card` statique avec une miniature en pièce jointe.
L'insertion dans le corps est une édition CKEditor normale ; seule elle crée une révision.
Une miniature déjà publiée reste réutilisable si l'insertion est annulée.

L'impression et le PDF reproduisent uniquement le corps du document.
`POST /memory/documents/{document_id}/export-bundle` exige la lecture du document, retourne
un ZIP borné à 64 Mio de données d'entrée (dont 12 Mio pour l'instantané), et n'écrit aucune
révision. Les noms de fichiers sont préfixés par leur UUID ; les liens du HTML deviennent
relatifs et encodés. Les fichiers retirés mais encore référencés sont inclus. Les dépendances
externes des fichiers HTML ou 3D ne sont pas incorporées automatiquement.

## Migration et exploitation

```bash
# Lecture seule : formats actuels, conversion simulée d’un échantillon, exceptions.
docker compose exec backend python -m app.memory.html_migration
# Développement : actions DbAdmin et réconciliation, sans restart.
make sync-db
# Production : nouvelle application et convergence avant disponibilité.
make update
```

Les actions sont `app.memory.editorial_html`, `app.agent.editorial_html`,
`app.task.editorial_html`. Elles sont déclenchées par leurs deltas de colonne, traitent au plus
500 objets par lot et restent différées tant que leur postcondition n’est pas satisfaite.
Répéter la synchronisation pour les ensembles plus grands. Les sources Memory restent dans
les révisions immuables ; `profile_legacy_source` et `objective_legacy_source` conservent les
champs antérieurs d’Agent et Task. Les liens anciens invalides perdent leur caractère cliquable,
avec avertissement et destination conservée dans la source historique. Les images non migrables
restent signalées et empêchent la convergence du lot concerné.

Les projections agent/Goal ont leur propre version de reconstruction. Les embeddings restent
une projection asynchrone : leur empreinte dépend du texte visible, pas des styles HTML.
Observer `scanned`, `queued`, `current` pour suivre la reconstruction ; aucun LLM n’intervient
dans la conversion. Suspendre les anciens workers pendant un déploiement de cette transition.
Le rollback doit conserver le lecteur HTML, les nouvelles écritures et les images ; utiliser
les anciennes sources pour une restauration ciblée, jamais pour écraser tout le stockage.

## Vérification

```bash
make tests ARGS='core/util/tests/test_rich_text.py app/memory/tests/test_editorial_html.py app/memory/tests/test_html_migration.py app/agent/tests/test_prompt_tree.py'
make tests-front-components ARGS='rich-text.spec.mjs galaris-links.spec.mjs memory.spec.mjs skills.spec.mjs'
make typecheck
make architecture-check
make project-context-check
```

La recette navigateur utilise les vrais composants CKEditor/Quasar et des API simulées explicites.
Elle complète les tests DB de persistance, d’accès, de restauration et de concurrence ; elle
ne remplace pas une qualification d’un fournisseur externe. Vérifier aussi les petits écrans,
les deux thèmes, le clavier et les fichiers de référence avant une nouvelle version du schéma.

La recette de bout en bout utilise `make tests-e2e ARGS='editorial-html.spec.mjs'` : PostgreSQL
éphémère, vraie API et frontend compilé. Elle vérifie les six catégories, le refus d’un ancien
client et la persistance d’un document après édition de tableau et rechargement. Les tests
unitaires de prompt couvrent les transports simulés et Hermès ; ils ne prétendent pas exécuter
un fournisseur externe réel.

Qualification CKEditor du 9 septembre 2026 : 44 tests backend du contrat HTML et des documents,
27 tests Chromium éditeur/liens Galaris/Memory et le parcours API complet sous Chromium, Firefox et WebKit
validés ; typage, lint et traductions contrôlés. La migration de développement a convergé avec
523 corps Memory HTML, aucun corps éditorial restant à convertir et aucune exception.
La reconstruction vectorielle suit sa file asynchrone habituelle.
