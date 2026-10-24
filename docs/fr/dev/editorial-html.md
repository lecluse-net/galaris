<p align="right"><strong>Français</strong> · <a href="../../en/dev/editorial-html.md">English</a></p>

# Contrat des contenus HTML éditoriaux

Une citation de processus interne utilise un lien titré vers
`galaris://processes/<code>` ou `galaris://processes/runs/<uuid>`. Pour afficher le
diagramme dans un document, conserver ce lien dans
`<blockquote class="galaris-link-card galaris-process-diagram"><p><a href="URI">Titre</a></p></blockquote>`.
Le canvas, les contrôles de zoom et les miniatures sont fournis au rendu, jamais
enregistrés dans le HTML. Process conserve la définition, les runs et leurs droits.
Les citations sont enregistrées dans le HTML, sans manifeste de PJ ni copie de la cible.
La liste des PJ et la collection documentaire de fichiers n'exposent que les fichiers
téléversés. Les anciens manifestes internes restent lisibles par leurs API de compatibilité.
Une carte d'agent conserve `galaris://agent/<id>`, son nom et son poste dans
`blockquote.galaris-link-card.galaris-agent-card`. Son avatar est chargé au rendu avec
les droits du lecteur, sans blob enregistré ni nouvelle PJ. L'ouverture en modale et
la possibilité d'afficher une carte sont deux capacités indépendantes des contributions.

La décision [0080](../../../project/decisions/0080-editorial-html.md) définit le périmètre.
Pour les contenus éditoriaux et les documents de type `html`, le corps autoritaire est un fragment UTF-8 `text/html`, `content_profile_version: 1`.
`rich-text` couvre les six catégories Memory, les objectifs et profils ; `document` ajoute
les images jointes, les formulaires, le CSS et le JavaScript des documents de travail ordinaires.
Un document Goal utilise `rich-text`, même
ouvert depuis la bibliothèque ou le Chat. Les ressources binaires/JSON/code et les compétences
ne passent pas dans cette conversion.

## Documents comme pivot de l'information

Les profils d'agents sont des ressources virtuelles `galaris://agent/<id>`, sans document
ni dossier dans la bibliothèque. `agent_list`, `agent_get` et le champ API `resource_uri`
fournissent cette URI. `file_read` renvoie directement la personnalité et la fiche de poste
actuelles, en HTML `rich-text` dans leur enveloppe JSON, avec les droits d'accès existants.

Memory possède les documents éditoriaux HTML `document://`. Dataset possède les ressources
JSON indépendantes `data://`, leurs droits et leur historique, dans **Connaissances → Jeux de données**.
Une création native de Dataset ne crée pas de Document dans Memory. Les anciens liens
documentaires ne fonctionnent comme alias que pour les Datasets migrés et vérifiés.
Le JSON UTF-8 est validé avant enregistrement, sans modifier sa mise en forme ; une saisie
invalide reste un brouillon et n'est jamais convertie en HTML. Toute racine JSON valide est
admise ; NaN et Infinity sont refusés. La limite est 2 000 000 octets, sous réserve du quota
de stockage. Voir la [décision 0187](../../../project/decisions/0187-dataset-domain-and-typed-contracts.md)
et le [contrat Dataset](datasets.md).

Créer directement avec
`file_create(path="data://", name="Scénarios", content='{"scenarios": []}')`.
Le champ `content` doit contenir le JSON complet ; une omission ou un contenu vide est refusé
avant création. L'ancienne option `document_type="dataset"` sur `document://` reste un
adaptateur et renvoie aussi `data://`, jamais un nouveau Dataset documentaire.
Pour un Dataset, `file_read` pagine en caractères et `file_edit` édite des lignes ; le JSON
complet après modification doit être valide. `file_write`, `file_edit` et `file_append`
exigent la révision lue. Préférer remplacement ou édition à la concaténation de JSON.
Copier une source `application/json` vers `data://` crée un nouveau Dataset privé.
Les exports PDF/HTML restent propres aux documents HTML. Les autres types de documents
restent hors périmètre. Le [HTML interactif](document-apps.md) permet désormais
aux documents HTML de contenir des formulaires et d'accéder à des datasets déclarés via un
runtime isolé ; l'historique et les exports restent inertes.

La politique commune aux exécuteurs Task, conversation et voix invite les agents à envisager
un Dataset pour les données structurées réutilisables entre documents, calculs ou Tasks :
fiche d'entreprise avec capital et devise, catalogue de produits ou chiffres comparables.
Privilégier un Dataset pertinent existant et relire ses données avant de rédiger un contenu
qui en dépend. Conserver unités, dates, sources et incertitudes, sans inventer les valeurs
manquantes ni remplacer une ressource métier autoritaire. Ce choix reste proportionné à
l'usage : aucune recherche ou écriture systématique n'est exigée pour un fait isolé ou une
réponse autonome. La politique d'action du contexte et les droits restent applicables ;
un lien vers un Dataset n'actualise pas automatiquement la prose déjà enregistrée.

Créer ou réviser un document lorsque le résultat demandé appelle un contenu rédigé durable
à conserver, réviser ou partager. Une Task ne nécessite pas à elle seule un document : les réponses
autonomes et confirmations restent dans la conversation, l'état opérationnel dans la ressource
métier concernée. Ne pas ajouter un document uniquement pour consigner une action ou attester son
achèvement. Respecter le type de ressource demandé ; une opération indisponible appelle une
explication de la limite, pas la création d'un document de substitution.

Pour ces contenus durables, les documents Galaris sont le support canonique. Document, Memory et File Sharing
sont des services système obligatoires, comme Galaris et Conversation. Leurs définitions et
connexions restent protégées et actives. Leurs fonctions gardent les modes Actif, Bloqué,
Sur demande et l’héritage global/local, configurables par un humain. Le catalogue effectif
conserve les restrictions de contexte et les ACL des ressources ; les bridges optionnels
peuvent toujours être désactivés.

Avec les fonctions nécessaires disponibles, rechercher et réviser le document pertinent.
Créer un nouveau document seulement si le contenu nécessite un support distinct, avec
`file_create(path="document://", name="Titre", content="<p>Contenu HTML.</p>")`.
Son URI reste la référence entre recherche, rédaction, revue, Tasks et
conversations. Il conserve les sources et liens vers les documents associés ; les médias restent
des ressources canoniques ou des pièces jointes. Les conversations portent la discussion et une
transmission concise du résultat, sans entretenir une copie concurrente de son contenu.

Pour les mises à jour de prose, respecter le périmètre demandé, intégrer les corrections et fusionner
les répétitions. Conserver les faits utiles, les sources, les nuances, les questions ouvertes,
les raisons des décisions et le sens des contributions. Ajouter les informations distinctes ;
conserver la chronologie lorsqu'elle sert le document, notamment un journal, un compte rendu ou
un audit. Les révisions gardent les versions antérieures : le corps n'a pas à recopier son
historique d'édition. Le suivi opérationnel reste dans les Tasks ou Goals, sauf s'il fait partie
du document demandé. Privilégier une édition ciblée avec `file_edit` ; un remplacement complet
avec `file_write` suppose d'avoir lu tout le contenu nécessaire à sa conservation. La concision
s'adapte à l'usage, sans réduction de longueur ni réécriture globale systématique. Cette règle
éditoriale ne demande pas de condenser les entrées Dataset ou le code.

Un nouveau document est privé. `document_sharing` résout le destinataire humain, agent ou équipe
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

Tiptap est l’arbre d’édition temporaire. Son HTML traverse le filtre frontend avant émission,
puis la validation backend reste autoritaire. Aucun aller-retour vers Markdown. Les lecteurs
historiques utilisent le MIME de la révision ; les artefacts HTML actifs restent séparés du
lecteur éditorial. Les fichiers Markdown et leur lecteur existant sont conservés pour les compétences.

Les lecteurs partagent les styles de tableaux `galaris-table-{blue,iris,green,orange,salmon,gray}` et
`galaris-table-{contrast,striped,minimal}` avec l’éditeur et les exports PDF/HTML. Ces classes
sont explicitement autorisées dans les deux filtres ; les couleurs viennent des variables
Solaire incluses dans les documents autonomes. Les préréglages ne remplacent ni les attributs
de colonnes, ni les fusions, ni les styles personnalisés des cellules.

`RichTextEditor` expose deux modes via `profile` : `rich-text`, mode simple par défaut pour
les champs multilignes enrichis, et `document`, mode complet avec page, images, pièces jointes
et exports. Les usages métier hors documents conservent le mode simple. Le groupe Lecture
est commun aux deux modes : Plein écran reste présent, Source est réservé à `rich-text` ; Pleine largeur
est réservé au mode document, qui possède un affichage en page. La contribution `editorVoice.ts`
du module actif `app.llm` fournit automatiquement la dictée et la lecture vocale aux deux modes,
via le contrat `EditorVoiceProvider` de `core.util`. Aucun branchement n’est nécessaire dans
les écrans. Changer de présentation n’émet aucune modification du contenu. Une nouvelle valeur
externe, une recréation ou la fermeture de l’éditeur arrête les requêtes et libère l’audio.

## Vue du code source

La vue « Code source », disponible uniquement pour `rich-text`, utilise une police à chasse fixe de 12 px.
Les documents n’exposent ni cette commande ni ce mode, y compris sur mobile et en lecture seule.
`EditorialSource` colore le HTML et les portions JavaScript/CSS intégrées avec highlight.js,
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

`tiptapContent` utilise des décorations ProseMirror temporaires, uniquement converties vers
la vue d’édition, sans effet sur les données ni l’historique d’annulation. Seuls les blocs
modifiés sont recolorés. Le lecteur et l’impression colorent une copie du HTML filtré ;
les classes de coloration ne sont jamais enregistrées dans le document.

En édition, le menu au clic droit d’un bloc propose langage, numéros de ligne, retour à la
ligne et copie. Le changement de langage cible explicitement ce bloc sans en créer ni en
fusionner d’autres. `Maj+F10` ouvre le menu au clavier et `Échap` le ferme. En lecture
seule, aucune barre contextuelle ni aucun menu au clic droit n’est affiché, y compris sur
le texte. La copie reste disponible au clavier et via le bouton dédié du bloc.

Les options sont conservées sur `<code>` par `data-code-lines="true"` et
`data-code-nowrap="true"`, validés par les deux filtres HTML. Les numéros sont des éléments
visuels temporaires, exclus du texte copié, des données enregistrées et de l’index sémantique.
Ils suivent les lignes logiques, y compris lorsqu’une ligne longue revient à la ligne à l’écran.

## Révisions et lecture agentique

Le partage MCP passe par `document_sharing` pour découvrir les destinataires et leur
`lock_version`, puis `document_share` avec exactement un `agent_id`,
`user_id` ou `team_id`. L’accès vaut `read`, `edit` ou `none` pour retirer ce grant précis.
Les équipes comprennent leurs membres humains et IA actuels. Cette mutation ne change ni
le HTML ni sa révision : `expected_lock_version` protège les ACL, `expected_revision`
protège les écritures de contenu. La compétence système Galaris fournit les exemples complets.

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

`POST /documents/{document_id}/export-pdf` vérifie les droits de lecture et le profil
`document`, puis transmet à `core.preview.render_html_pdf` une copie statique du contenu en
cours. Le frontend partage les styles d’impression et intègre les images autorisées en data
URI ; cet export ne sauvegarde pas le document. Chromium, dans `browser-executor`, imprime
une page temporaire sans JavaScript ni accès réseau, puis ferme son contexte. Les limites
sont 12 Mio de HTML avec images, 16 Mio de PDF, 30 secondes de rendu et deux exports simultanés.
Le service de rendu doit être reconstruit lors d’une modification de son code.

## Pièces jointes, cartouches et export portable

Le profil documentaire accepte les formulaires et scripts dans un contexte isolé, avec la
barre d'outils et le texte éditable habituels, sans vue Source. Les historiques et exports
restent inertes. La restauration et les modifications du texte environnant conservent le
HTML/CSS/JavaScript enregistré, notamment les contenus fournis par les outils et les agents.

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
HTTPS publiques passent par `POST /documents/{document_id}/import-image` : vérification
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
`GET /documents/{document_id}/attachments/{attachment_id}/info` permet aussi d'ouvrir
un fichier retiré de la liste mais retenu pour le texte ou l'historique, sous les ACL actuelles.

`POST /documents/{document_id}/link-card` exige un agent dans le périmètre utilisateur
et le droit d'écriture avant tout accès réseau. `app.file_share.web_metadata` partage avec
Messenger l'extraction Open Graph et YouTube oEmbed via le transport HTTPS public protégé
contre les adresses privées et redirections internes. Documents passe par le port
`core.preview.preview_web_link`, dont l'adaptateur Browser réutilise ce transport et
le cache de captures partagé. Pages : 1 Mio et 15 secondes ; images :
5 Mio et 40 millions de pixels.
Le résultat est un `blockquote.galaris-link-card.galaris-web-card` avec les textes et
l'URL source, sans image persistée dans le corps ni pièce jointe technique. La miniature
WebP (320 × 320 au maximum) reste dans le cache partagé `core.preview.thumbnails`.
`POST /documents/link-card/thumbnail` exige un droit d'accès documentaire et vérifie
le périmètre de l'agent demandé avant de lire le cache ou de régénérer l'aperçu public.
Le rendu ajoute l'image temporairement ; impression, PDF et ZIP l'intègrent à leur
instantané. Une absence ou un échec d'aperçu conserve la carte textuelle.
L'insertion dans le corps est une édition normale ; seule elle crée une révision.
Les anciennes cartes avec une image en PJ restent lisibles sans modification de leur historique.

L'impression et le PDF reproduisent uniquement le corps du document.
`POST /documents/{document_id}/export-bundle` exige la lecture du document, retourne
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

La recette navigateur utilise les vrais composants Tiptap/Quasar et des API simulées explicites.
Elle complète les tests DB de persistance, d’accès, de restauration et de concurrence ; elle
ne remplace pas une qualification d’un fournisseur externe. Vérifier aussi les petits écrans,
les deux thèmes, le clavier et les fichiers de référence avant une nouvelle version du schéma.

La recette de bout en bout utilise `make tests-e2e ARGS='editorial-html.spec.mjs'` : PostgreSQL
éphémère, vraie API et frontend compilé. Elle vérifie les six catégories, le refus d’un ancien
client et la persistance d’un document après édition de tableau et rechargement. Les tests
unitaires de prompt couvrent les transports simulés et Hermès ; ils ne prétendent pas exécuter
un fournisseur externe réel.

La qualification du remplacement par Tiptap s’appuie sur `tiptap-preservation.spec.mjs`,
les parcours existants d’édition, de pièces jointes, de voix, d’historique et d’export,
et `make tests-e2e ARGS='editorial-html.spec.mjs document-apps.spec.mjs'` pour Chromium,
Firefox et WebKit avec stockage réel. Les comptes rendus sous `artifacts/` portent les
résultats exécutés ; une ancienne recette CKEditor ne qualifie pas le nouvel éditeur.
Le remplacement ne demande aucune réécriture des documents ou des révisions en base.

## Références aux objets métier

Les tâches, objectifs, sujets, discussions, rounds texte, appels et tours vocaux peuvent
être copiés depuis leurs menus contextuels ou fiches, puis collés comme liens titrés.
Le sélecteur **Lien Galaris → Objets Galaris** les recherche également. Les URI et les
URL de cette installation sont normalisées avant insertion. Le menu contextuel et la
barre d'outils basculent entre lien et carte en édition. En lecture seule ou visualisation,
le clic gauche sur un lien ou le fond d’une carte ouvre sa cible ; le clic droit est bloqué
et les barres contextuelles sont absentes. Ces références ouvrent leur fiche en modale avec les droits actuels du
lecteur, sans changer le document consulté.

Les cartes sont des instantanés HTML portables des métadonnées essentielles : titre,
agent, date, état et canal selon le type. Les tâches, rounds et tours vocaux n'y enregistrent
ni résumé, ni objectif, ni transcription, ni réponse. Un sujet peut afficher sa description
et ses mots-clés. L'état enregistré n'est pas actualisé automatiquement ; la modale relit
la ressource actuelle. Une référence ne crée aucune pièce jointe et ne donne aucun droit
supplémentaire. Les identités de navigation `galaris://topic/<uuid>`, `galaris://room/<uuid>`
et `galaris://voice_session/<uuid>` ne déclarent aucune nouvelle capacité du provider
fichier. Voir la [décision 0209](../../../project/decisions/0209-business-document-references.md).
