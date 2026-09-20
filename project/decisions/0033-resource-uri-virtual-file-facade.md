# ADR 0033 — URI de ressources comme façade de fichiers virtuelle

- Statut : Superseded by ADR 0046
- Date : 2026-08-12
- Amendé : 2026-08-20 — un seul stockage local est annoncé par run

## Contexte

Les opérations de fichier employaient simultanément des chemins de workspace, des couples
`tool_code + path`, des identifiants Messenger et des URLs propres aux providers. Un modèle devait
donc choisir une fonction et une grammaire différentes pour chaque origine, puis reconstruire une
référence lors d'un transfert. Ces formes ne pouvaient pas non plus alimenter proprement le
Working Set ou un historique de documents inter-Tasks.

## Décision

`app.file_share` devient la façade de fichiers virtuelle. Une ressource est désignée par
`<scheme>://<locator>` et toutes les opérations usuelles — découverte, liste, métadonnées,
recherche, écriture complète binaire ou texte, lecture/écriture texte, copie, move et suppression
— traversent ses contrats publics.
La surface MCP `file_*` est enregistrée exclusivement sous le Tool intégré `file_sharing`.
Le schéma `galaris://` est un provider de cette façade ; il ne rattache aucune fonction de fichier
au Tool `galaris`, réservé aux actions métier.
Un chemin relatif historique est normalisé en `workspace://` à l'entrée. Les résultats MCP sont
structurés et rendent toujours la référence canonique réutilisable.

Le schéma d'un provider externe est exactement le `code` du Tool connecté à l'agent lorsqu'il
porte la capability file-share ou Messenger.
Il respecte la grammaire d'un schéma URI en minuscules. Les protocoles Web/réseau usuels et les
schémas natifs Galaris sont réservés ; notamment `http` et `https` ne peuvent jamais être des codes
de Tool. `http://` est désactivé. `https://` est une source publique en lecture seule, protégée
contre les credentials, fragments, hôtes non publics et redirections SSRF.

Les schémas natifs restent gouvernés par leur domaine : `workspace://`, `console://`,
`memory://<uuid>` et `document://<uuid>`.
`workspace://` désigne toujours le stockage privé du runtime et `console://` le home de la
console SSH. Même lorsqu'une exécution interne possède les deux transports, aucun schéma ne devient
un alias de l'autre ; leur frontière est franchie exclusivement par `file_copy`.
Lorsque `console://` est disponible, les instructions agentiques l'utilisent pour les sources,
scripts, téléchargements, builds et autres fichiers destinés aux commandes `console_*`. Pour ne
pas imposer au modèle deux stockages locaux équivalents, `file_schemes` annonce alors uniquement
`console://` et les destinations automatiques des outils image, audio et navigateur l'utilisent.
`workspace://` reste disponible en interne pour le staging du runtime, les pièces jointes, les
anciennes références et les runtimes sans console, qui l'annoncent comme unique repli local.
`file_list` sans URI liste la racine locale annoncée ;
les chemins relatifs historiques continuent néanmoins de désigner le workspace pendant leur
période de compatibilité.
`galaris://` projette en JSON les Tasks, rounds texte, rounds vocaux, Goals, cycles de Goal et
Processes affectés via les collections `task/`, `text/`, `voice/`, `goal/`, `goal_cycle/` et
`process/`; la collection imbriquée
`goal/<uuid>/cycles/` conserve le contexte du Goal. Aucune mutation générique ne lui est attribuée.
Un Process est adressé par son `workflow_id` public, identique au catalogue `process_*`.
Les ACL de chaque domaine sont vérifiées par leurs façades publiques. Une suppression générique
n'efface jamais ces objets métier.

`file_copy` est l'unique primitive de copie persistante streamée entre providers. Les anciens
`file_upload`, `file_download`, `file_transfer` et `file_targets`, ainsi que les lecteurs MCP
dédiés couverts par une URI, ne sont plus exposés. Les capacités optionnelles des transports
empêchent la façade d'annoncer list, delete ou move lorsque le provider ne les implémente pas.
Nextcloud les implémente via WebDAV.

Les outils métier qui consomment un fichier acceptent la même URI canonique, quelle que soit sa
source. Quand une bibliothèque exige un `Path`, ils passent par `materialize_resource` avec une
limite explicite et un temporaire nettoyé à la fin de l'appel. Cela couvre notamment l'analyse et
la génération d'images, la transcription audio/vidéo et l'envoi Messenger. Une copie workspace
préalable n'est jamais requise ; `file_copy` n'est utilisé que si la copie doit survivre à l'appel.
Une copie vers une collection choisit le nom du `ResourceDescriptor` source avant de considérer le
locator, ce qui préserve le vrai nom des pièces jointes et des providers à identifiants opaques.
Les entrées fichier des Processes suivent ce contrat : le run garde l'URI source et ne révèle à
l'engine qu'une URL de téléchargement temporaire, laquelle matérialise la ressource via la façade.

Le Working Set et la capsule par interlocuteur conservent ces URI, sans recopier les octets. Une
livraison externe réussie produit un artefact final et un reçu source/destination ; move et delete
font expirer les références antérieures. Les queries HTTPS sont retirées des références durables.

Messenger et file-share sont des capabilities d'un Tool, pas des providers URI. Une pièce jointe
est donc rendue dans l'entrée chronologique du message qui la porte sous la forme
`<tool.code>://<room-locator-provider>/<file-uuid-local>`. Par exemple Talk et WebDAV partagent le
schéma `nextcloud://`, tandis qu'une connexion Telegram utilise `telegram://`. Pour un Tool qui
porte les deux capabilities, une room connue sélectionne Messenger et tout autre chemin sélectionne
file-share. Un message qui ne contient qu'un fichier n'est jamais écarté des projections de session
ou de runtime ; le nom visible ne sert pas d'identité.

## Conséquences

- Un LLM peut enchaîner `file_list`, `file_search`, `file_read` et `file_copy` sans convertir
  manuellement les références entre environnements.
- Un LLM peut passer toute URI lisible directement aux outils image, audio, Messenger et Process ; leur
  staging local est transparent, borné et éphémère.
- Une console active devient l'unique espace local visible et la destination automatique par
  défaut, sans supprimer le workspace privé requis en interne par les transports du runtime.
- Un fichier ne doit pas être conservé dans les deux espaces sans besoin explicite ; après copie,
  l'agent réutilise l'URI canonique retournée.
- `file_create` crée une ressource et renvoie son URI complète ; `file_write` remplace une
  ressource existante, en UTF-8 ou en base64 sous une limite serveur.
- `file_read` pagine le texte UTF-8 et renvoie les binaires d'au plus 1 Mio en base64 ; au-delà,
  le fichier doit être manipulé avec un logiciel via la console.
- `file_edit` remplace une plage inclusive de lignes dans les ressources textuelles.
- Une liste `document://` ou `<tool.code>://<room-locator-provider>/` devient un historique de ressources directement
  manipulables.
- Ajouter un provider consiste à enregistrer un transport et ses capacités, pas une nouvelle
  famille d'outils MCP.
- La compatibilité des chemins relatifs facilite la migration ; les sorties, Working Sets et
  prompts n'émettent que les URI canoniques.

## Preuves dans le code

`back/app/file_share/resource_uri.py`, `resource_contracts.py`, `resource_service.py`,
`galaris_provider.py`,
`web_transport.py`, `mcp.py`, `back/app/file_share/messenger_transport.py`,
`back/app/memory/file_facade.py`, `back/app/messenger/resource_reference.py`,
`back/bridge/nextcloud/file_share.py`,
`back/app/tools/resource_effects.py` et les tests associés.
