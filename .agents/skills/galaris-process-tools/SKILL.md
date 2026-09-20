---
name: galaris-process-tools
description: Architecture Galaris des outils et exécutions longues — app.tools, app.mcp, connexions, file_share, ressources, app.process, callbacks et bridge n8n. À utiliser pour tracer, créer ou modifier un outil MCP, une connexion, un fichier, un process, une exécution n8n ou leur exposition aux agents.
---

# Maîtriser les outils et processus Galaris

## Charger le flux

Lire `docs/fr/architecture/flows/process.md`,
`docs/fr/architecture/flows/media-resources.md` et les contrats du module concerné. Consulter la
section MCP du guide `docs/fr/dev/README.md` avant de changer l’exposition d’un outil.

## Distinguer les responsabilités

| Domaine | Responsabilité |
|---|---|
| `app.tools` | Catalogue, sélection et règles d’exposition des outils |
| `app.mcp` | Contrats et serveur MCP Galaris |
| `app.connection` | Configuration et secrets référencés des intégrations |
| `app.file_share` | URI canoniques, providers et transferts streamés de ressources |
| `app.process` | État durable d’une exécution longue, progression, annulation et callbacks |
| `bridge.n8n` | Traduction entre workflows n8n et contrats Galaris |

Ne pas faire dépendre le catalogue d’outils d’un client concret. Un bridge externe traduit
vers `app.process` et les façades métier au lieu de posséder un second état canonique.

## Ajouter ou modifier un outil MCP

1. Définir un nom stable, une description actionnable et un schéma d’entrée borné.
2. Valider les paramètres avant l’accès réseau, disque ou base.
3. Résoudre les connexions et secrets côté serveur ; ne jamais les exposer au modèle.
4. Retourner une sortie structurée et concise, avec identifiants corrélables.
5. Pour une opération longue, créer un `Process` au lieu de bloquer l’appel.
6. Ajouter des tests du schéma, des autorisations, des erreurs et du résultat.
7. Régénérer la cartographie pour inventorier le nouvel outil.

## Gérer une exécution longue

- Appliquer uniquement les transitions autorisées de `app.process.process_service`.
- Considérer `success`, `error` et `cancelled` comme terminaux.
- Rendre callbacks et redeliveries idempotents.
- Corréler l’identifiant externe à un seul process Galaris.
- Distinguer demande d’annulation (`cancelling`) et confirmation (`cancelled`).
- Ne jamais remplacer un état terminal par un événement tardif.

Documenter toute nouvelle transition dans `docs/fr/architecture/state-machines.md` et la couvrir
par un test de matrice.

Les fichiers d'entrée d'un Process suivent exactement la même règle : chaque élément porte une
clé `uri` canonique et une description optionnelle. Le snapshot de run conserve l'URI source ;
l'URL machine temporaire matérialise cette ressource via `app.file_share` au moment où l'engine la
télécharge. Ne limiter ni le planner ni le process à un stockage local.

## Fichiers et ressources

Galaris, Conversation, Memory et File Sharing sont des services système obligatoires
(`can_disable=false`, propriété gérée par le logiciel). Lorsque les capacités nécessaires sont autorisées,
les documents `document://` sont le support canonique des contenus rédigés durables requis par
le résultat. Une Task ne nécessite pas à elle seule un document ; privilégier le document
pertinent existant et ne pas remplacer une ressource métier par un document.
Créer avec `file_create(path="document://", name=..., content=...)` où
`content` est un fragment HTML éditorial UTF-8. Réutiliser l'URI et les révisions plutôt que créer
des copies Markdown ou HTML ; lier les sources et pièces jointes. Partager avec `memory_sharing`
puis `document_share` avant de transmettre l'URI aux destinataires. Un lien ne donne pas accès.
La synchronisation réactive leurs connexions et ignore les anciens refus de fonctions ; seuls
les Tools optionnels conservent leurs désactivations explicites. Les API et l'interface refusent
les mutations des Tools système, de leurs connexions et de leurs autorisations.
Le choix d'un fichier pour un format explicitement demandé ou un artefact technique reste possible.
Voir `docs/fr/dev/editorial-html.md`, section « Documents comme pivot de l'information ».

Pour les documents éditoriaux, appliquer `docs/fr/dev/editorial-html.md` : les outils écrivent
des fragments HTML, les offsets sont des blocs HTML (même si un argument s'appelle
`start_line`), et toute mutation de contenu existant fournit `expected_revision` lu au préalable.
Les autres providers conservent leur format et leur unité d'offset. Adapter les exemples du
skill runtime Galaris et tester la conservation du contenu, les conflits de révision et les
refus de HTML hors profil ; ne pas figer un ancien bouton d'éditeur.

Les Datasets sont également des documents : créer avec
`file_create(path="document://", document_type="dataset", name=..., content=...)`.
Le JSON reste du JSON, avec le même partage et historique. Le type est immuable ; le paramètre
est réservé à la création dans `document://`. Les lectures JSON paginent en caractères et
`file_edit` travaille en lignes ; tout résultat écrit doit être un JSON complet valide.
Les mutations exigent `expected_revision`. Une copie de source `application/json` vers la
collection Documents crée un Dataset ; une destination existante conserve son type.

Les formulaires et scripts restent du HTML ordinaire dans les documents :
`file_create`/`file_write`/`file_edit` acceptent directement `form`, `style` et `script`.
Lire `docs/fr/dev/document-apps.md` pour les attributs Dataset et le SDK. Aucune fonction MCP
d'exécution JavaScript n'est créée ; l'exécution isolée appartient au navigateur du lecteur.
Partager page et datasets séparément ; le code n'hérite jamais des droits de son auteur.

Lire [le contrat des URI de ressources](references/resource-uris.md) avant de modifier un Tool
file-share, une opération de fichier ou sa projection dans le Working Set. `app.file_share` est la
façade de fichiers virtuelle : ne pas recréer une résolution de schéma dans `app.tools`, un bridge
ou un runtime.

Le Tool intégré `file_sharing` possède et expose l'unique surface MCP générique :
`file_schemes`, `file_list`, `file_info`,
`file_search`, `file_read`, `file_create`, `file_write`, `file_append`, `file_edit`, `file_copy`,
`file_move` et `file_delete`. Ne pas réintroduire un lecteur ou un transfert dédié lorsqu'une URI couvre déjà
l'intention. Les actions métier qui portent une sémantique supplémentaire restent dans leur
domaine et dans leur propre Tool. En particulier, `galaris://` est un schéma pris en charge par
`app.file_share`, pas une raison de rattacher les fonctions `file_*` au Tool `galaris`.

Les pièces jointes d'un document passent par la collection
`document://<document-uuid>/attachments/`. `file_list` les énumère ; leur URI exacte peut être
passée à `file_info`, `file_read`, `file_copy` ou à un outil spécialisé. `file_create` avec un
`name`, ou `file_copy` vers la collection, ajoute une pièce jointe immuable ; `file_delete` sur
l'URI exacte la supprime. La lecture suit le droit de lecture du document parent, les mutations
exigent son droit d'écriture, et ni l'ajout ni la suppression ne créent de révision du contenu.

Toute fonction métier qui reçoit ou rend un fichier échange une URI canonique de `app.file_share`,
jamais un chemin hôte ni un chemin implicitement propre à son domaine. Lorsqu'un outil spécialisé
doit donner les octets à une bibliothèque locale (`image_read`, génération avec pièces jointes,
transcription audio/vidéo, livraison Messenger, etc.), il appelle `materialize_resource` dans un
répertoire temporaire borné et automatiquement nettoyé. L'appelant passe donc directement une URI
`nextcloud://`, `console://`, HTTPS, Mail ou Messenger : il ne prépare pas une copie locale.
`file_copy` reste réservé à la création intentionnelle d'une copie persistante dans un
autre provider.

Le provider natif `galaris://` projette en lecture seule les collections `task/`, `text/`, `voice/`,
`goal/` et `goal_cycle/`. Sa couche provider route l'URI, mais chaque domaine possède la requête, les ACL
et la sérialisation de sa projection publique. La collection `skill/` est une exception administrée :
elle expose les fichiers des packages uniquement à un agent dont la connexion `skill_management` est
active. Les skills système y restent en lecture seule. Les autres opérations génériques de mutation
sur `galaris://` sont refusées ; `file_copy` peut exporter un snapshot JSON vers un autre schéma.

Valider taille, type, nom, URI et destination. Une destination collection conserve par défaut le
nom exposé par les métadonnées de la source, y compris lorsque son locator est un identifiant opaque.
Le runtime ou la bibliothèque locale ne reçoit qu'un temporaire serveur borné, jamais une
référence durable ni un chemin arbitraire de l’hôte. Sans console active, aucun stockage local
n'est annoncé : l'agent conserve l'URI Messenger courante ou écrit vers un provider compatible
file-share. Les transferts sont streamés, bornés et nettoyés. Vérifier
l’isolation entre agents, la connexion active, les ACL du domaine et l'overwrite explicite lors de
chaque nouveau transport. Un nouveau provider expose ses capacités par protocoles optionnels ; il
ne prétend pas supporter list, move ou delete sans implémentation réelle.

Les neuf fonctions de contrôle `conversation_*` appartiennent au Tool `conversation` et restent
limitées au contrôleur conversationnel. `conversation_round_get`, `voice_turn_get`, `llm_call` et
`llm_calls` appartiennent à `galaris_admin`, optionnel, avec vérification de sa connexion active
à chaque appel. Ne pas exposer les inspections LLM dans le service système `galaris`.

## Sécurité et observabilité

- Masquer tokens, credentials, entêtes d’authentification et contenu sensible.
- Ajouter timeouts, limites de taille et gestion explicite des erreurs externes.
- Journaliser les transitions avec process, outil, connexion et trace, sans payload secret.
- Pour une instrumentation Logfire, charger le skill `logfire-instrumentation`.

## Valider

Exécuter les tests ciblés, les tests d’idempotence et d’annulation, puis `make typecheck`,
`make project-context` et `make architecture-check`.
