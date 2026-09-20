# URI de ressources et façade de fichiers

## Contrat canonique

`app.file_share` est le système de fichiers virtuel de Galaris. Toute référence durable ou
échangée entre tools utilise une URI canonique :

```text
<scheme>://<locator>
```

- Une URI explicite est obligatoire. Les chemins relatifs et tout ancien schéma local implicite
  sont refusés à l'entrée.
- Le schéma d'une intégration est exactement le `Tool.code` connecté à l'agent.
- Un code de Tool portant file-share ou Messenger est en minuscules et respecte
  `[a-z][a-z0-9+.-]*`.
- Les protocoles réseau/Web usuels (`http`, `https`, `file`, `ftp`, `sftp`, `ssh`, `ws`, etc.),
  les codes système et les schémas natifs ou futurs sont réservés et interdits comme codes de
  Tool externe.
- Les locators sont NFC, utilisent `/`, encodent les segments et refusent contrôles, `..`, query
  et fragment. Seules les URL Web peuvent porter une query ; elle n'est jamais persistée dans
  le Working Set.

## Schémas natifs

| Schéma | Forme | Propriétaire |
|---|---|---|
| `console://` | `console://path/file.ext` | home SSH de la console |
| `memory://` | `memory://uuid` | souvenir gouverné, lecture générique |
| `document://` | `document://uuid`, `document://uuid/attachments/`, `document://uuid/attachments/attachment-uuid` | document de travail révisé et ses pièces jointes |
| `https://` | URL publique sans credentials ni fragment | source Web en lecture seule |
| `galaris://` | `galaris://task/<uuid>`, `galaris://text/<uuid>`, `galaris://voice/<uuid>`, `galaris://goal/<uuid>`, `galaris://goal_cycle/<uuid>`, `galaris://process/<workflow-id>`, `galaris://skill/<skill-code>/<path>` | projections métier JSON en lecture seule ; fichiers de skills administrables sous autorisation |

Une collection finit par `/` ou n'a pas de locator, par exemple `document://` ou
`nextcloud://Shared/`. `http://` est parsé afin de produire une erreur explicite, mais son accès
est désactivé. Les URL HTTPS refusent les hôtes locaux, privés et non publics, y compris après
redirection.

La racine `console://` est toujours le home de l'utilisateur SSH. Un locator qui répète ce
home, avec ou sans slash initial, est rebasé avant accès afin de ne jamais produire
`/home/user/home/user/...`.
Lorsque `console://` est disponible, il est l'unique stockage local annoncé par `file_schemes` et
la destination locale par défaut des outils image et audio. Sans console, aucun stockage local ni
destination par défaut n'existe : l'appelant fournit l'URI exacte d'un provider writable. Les
matérialisations techniques sont des temporaires serveur nettoyés et ne deviennent jamais des URI.
Ne pas entretenir deux copies sans besoin explicite ; après un transfert, réutiliser l'URI rendue.
Le Tool intégré `console` porte `file_share_config.service = "console"` comme marqueur de
capacité. Ce provider reste natif : il est résolu vers la connexion SSH active et n'est pas ajouté
une seconde fois à la liste des providers connectés.

## Opérations MCP

Toutes ces fonctions sont enregistrées sous le Tool intégré `file_sharing`, quelle que soit l'URI
manipulée. `galaris://` reste un schéma/provider et n'attribue pas les fonctions au Tool
`galaris`.

`file_schemes` décrit les capacités effectives. `file_list`, `file_info`, `file_search`,
`file_read`, `file_create`, `file_write`, `file_append`, `file_edit`, `file_copy`, `file_move` et `file_delete`
acceptent des URI et rendent du JSON contenant les URI canoniques. Les limites de pagination,
lecture et écriture sont imposées par le serveur.

`file_create` crée une nouvelle ressource et renvoie son URI canonique complète. `file_write`
remplace une ressource existante ; son contenu est soit UTF-8, soit encodé en base64. `file_read`
détecte le texte et renvoie les petits binaires en base64 ; les gros binaires sont passés par URI à
un outil spécialisé ou copiés vers la console quand elle existe.
`file_edit` remplace une plage inclusive de lignes UTF-8 (blocs pour les documents HTML).
`file_create("document://", ..., document_type="dataset")` crée un document JSON ; le type
par défaut est `html` et reste immuable. Les datasets conservent les mêmes ACL, révisions et
pièces jointes. Leur contenu doit rester du JSON valide après chaque écriture, édition ou ajout.

`file_list` borne une page à 500 entrées. Les collections `galaris://` renvoient un
`next_cursor` lorsqu'une page suivante existe ; le client le repasse sans l'interpréter dans le
paramètre `cursor`. Les requêtes domaine utilisent cet offset avant leur `LIMIT`, afin de ne jamais
charger toute une collection de Tasks ou de rounds en mémoire.

`file_copy` est l'unique primitive de copie persistante inter-provider. Une destination collection
conserve le nom fourni par `file_info` sur la source, même lorsque le locator source est un UUID ou
un identifiant provider opaque. Une collection existante est reconnue par les métadonnées du
provider même si l'appelant a omis le `/` final ; un espace provider tel qu'un workspace AFFiNE ou
une room Messenger complète pareillement la destination avec le nom source. Le `/` final reste
nécessaire pour déclarer sans ambiguïté une collection qui n'existe pas encore. Un move
inter-provider est une copie suivie d'une suppression autorisée ; si la
suppression échoue, l'erreur indique explicitement que seule la copie a réussi.

Les consommateurs spécialisés de fichiers utilisent la même façade. `image_read`, les attachments
de `image_generate`, `audio_transcribe` et les envois de fichiers Messenger acceptent directement
toute URI lisible annoncée par `file_schemes`. Ils matérialisent les octets dans un temporaire borné,
valident le type utile, puis suppriment toujours ce temporaire. Une copie locale préalable est
donc une erreur de protocole sauf si une seconde ressource persistante est explicitement demandée.
Leurs destinations acceptent pareillement une URI writable et leurs résultats exposent l'URI
canonique effectivement créée ou livrée.

`galaris://` expose les collections `task/`, `text/`, `voice/`, `goal/`, `goal_cycle/` et
`process/`. Il expose aussi `skill/` uniquement lorsque la connexion intégrée
`skill_management` de l'agent est active. `galaris://skill/<skill-code>/` liste le package et
`galaris://skill/<skill-code>/<path>` adresse un fichier, par exemple `SKILL.md`.
`text/` et `voice/` sont deux vues filtrées des `ConversationRound` canoniques ; une même UUID
n'est exposée que dans la collection correspondant à son média.
`galaris://goal/<uuid>/cycles/` fournit aussi les cycles d'un Goal. `file_list`, `file_search`,
`file_info` et `file_read` appliquent les ACL du domaine ; `file_copy` permet d'exporter une
projection JSON. `process/` expose uniquement les workflows affectés à l'agent et les adresse par
leur `workflow_id`, identique à celui des outils `process_*`. Les fichiers d'un skill utilisateur
supportent create, write, append, edit, copy, move et delete dans les limites génériques ;
`SKILL.md` reste obligatoire, validé et non supprimable, et les skills système ne sont jamais
modifiables. Hors de `skill/`, write, append, move et delete sont toujours refusés sur ce schéma
avec une erreur qui renvoie vers le domaine propriétaire.

Les opérations génériques ne suppriment jamais un souvenir, un document ou une pièce jointe de
messagerie. Une pièce jointe documentaire peut être supprimée par son URI lorsque l'agent possède
le droit d'écriture sur le document parent. Copier un texte vers `document://` crée un document ;
copier vers `document://<uuid>` exige `overwrite=true` et une autorisation d'édition. Copier vers
`document://<uuid>/attachments/` crée une pièce jointe immuable en conservant le nom de la source.
La collection et ses éléments sont lisibles dès que le document parent l'est ; création et
suppression exigent son droit d'écriture.

Messenger et file-share sont des capabilities d'un Tool, jamais des schémas. Une pièce jointe
utilise `<tool.code>://<room-locator>/<file-uuid>`, par exemple
`nextcloud://talk-token/<file-uuid>` ou `telegram://-10042/<file-uuid>`. Le locator de room est
celui du provider et l'UUID du fichier reste l'identité durable locale. Un Tool qui porte les deux
capabilities, comme Nextcloud, sélectionne Messenger lorsque le premier segment désigne une room
connue de cette connexion ; les autres chemins utilisent son transport file-share.

## Working Set et sécurité

Le Working Set conserve les URI, pas les octets. Une écriture/copie réussie inscrit la ressource ;
un move rend la source obsolète ; un delete la marque `stale`. Une copie vers un provider externe
inscrit l'artefact final et un reçu de livraison avec source et destination canoniques.

Ne jamais résoudre soi-même une URI en chemin hôte ou URL avec credentials. Traverser la façade
publique `app.file_share`, qui applique ACL du domaine, connexion active de l'agent, normalisation,
stream borné, politique d'overwrite et validation SSRF.
