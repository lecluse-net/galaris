# Navigation File Share par les harnais : comparaison MCP et système de fichiers

- Statut : `design`
- Date : 2026-10-11.
- Demande : mesurer si une arborescence personnelle facilite l'accès aux ressources pour
  les harnais et les petits modèles, puis décider de l'intérêt d'une projection FUSE.
- Condition de poursuite : aucun développement FUSE avant une comparaison avec un vrai
  harnais et un vrai modèle montrant un gain utile. Sans amélioration, abandonner cette piste.
- État : premier essai réalisé, comparaison non concluante ; hypothèse à confirmer,
  chantier FUSE non engagé.

## Garantie recherchée

Un agent trouve et lit les mêmes ressources plus facilement, avec une réussite vérifiée
et un coût raisonnable. L'intuition liée à l'apprentissage des commandes shell est une
hypothèse à tester, pas une preuve de nécessité. Les outils File Share actuels restent
disponibles, avec leurs URI canoniques, recherches et limites de sortie pour le modèle.

La cible éventuelle est un répertoire **par agent**, par exemple `~/file_share/` dans
son environnement d'exécution. Son emplacement exact dépend du home et du workspace du
harnais ; `/media` partagé entre agents n'est pas la cible. L'agent est propriétaire de
toute sa projection. Aucun système d'utilisateurs ou d'ACL POSIX multiples n'est requis.

Les ressources sans accès sont absentes ; la lecture et l'écriture reflètent les droits
effectifs de l'agent et les capacités du provider. Les contrôles existants restent côté
serveur. Le mode d'un fichier ne suffit pas à autoriser une opération métier.

## Socle actuel et limites à instruire

Sources principales : [flux des ressources](../../docs/fr/architecture/flows/media-resources.md),
[contrats](../../back/app/file_share/resource_contracts.py),
[façade](../../back/app/file_share/resource_service.py),
[transports](../../back/app/file_share/transport.py),
[outils MCP](../../back/app/file_share/mcp.py) et
[catalogue des tests](../../docs/fr/dev/functional-tests.md).

- `ResourceListing` porte `truncated` et `next_cursor`. Une page bornée ne garantit pas
  que le provider évite de charger le répertoire entier en amont.
- Les transports proposent le téléchargement vers un fichier et, facultativement,
  `iter_bytes(offset=...)`. Tous les providers n'offrent pas une lecture aléatoire native.
- Les lectures MCP ont des unités propres au contenu : caractères, blocs éditoriaux ou
  binaire encodé. Ces contrats ne sont pas des lectures POSIX en octets.
- Des budgets de transfert existent aussi hors MCP, notamment un téléchargement par
  défaut de 512 Mio. Installer FUSE ne supprime pas automatiquement ces limites.
- Le descripteur distingue désormais `name`, libellé ou nom source, et `entry_name`, clé
  issue de l'URI. Ce socle ne constitue ni un montage ni une preuve d'unicité de toute
  arborescence future : vérifier la projection complète et tous les providers.
- Les harnais ont déjà un workspace et une intégration MCP. Le gestionnaire de harnais
  ne fournit pas aujourd'hui ce montage personnel.

L'indexation File Share existante reste acquise ; ce plan ne la remplace pas et ne
recrée pas le programme clos par la [décision 0155](../decisions/0155-durable-file-indexing.md).

## Phase 0 — expérience avant FUSE

### Conclusion provisoire du premier essai — 2026-10-11

**Hypothèse à confirmer : une navigation par le système de fichiers pourrait faciliter
le travail des harnais, mais le gain sur les outils File Share MCP n'est pas démontré.
On ne lance pas un chantier FUSE sur la base de cette incertitude.**

Le premier scénario, exécuté avec DSH et DeepSeek v4 Flash, a donné une réponse correcte
via le répertoire local. La variante MCP s'est arrêtée sur un chargement de skill dont
le runtime n'a pas confirmé l'issue ; elle n'a pas permis d'évaluer la navigation File
Share. Les validations humaines, reprises d'exécution et écarts entre coûts de Task
et coûts fournisseur empêchent une comparaison fiable de vitesse et de coût. Ce résultat
ne prouve ni la supériorité du répertoire ni une difficulté intrinsèque des outils MCP.

Avant toute décision de poursuite, refaire une comparaison bornée avec les instructions
préchargées, des autorisations de lecture comparables, les commandes Bash de lecture
autorisées pour la variante répertoire et une comptabilité vérifiée. Répéter les mêmes
missions avec le même modèle, puis un modèle plus petit. Une copie locale suffit pour
cette étape ; aucun driver FUSE n'est nécessaire pour tester l'hypothèse. Les critères
de décision ci-dessous restent applicables : sans gain utile établi, conserver les
outils actuels et ne pas engager le chantier.

### Comparaison minimale

Choisir un harnais déjà fonctionnel, parmi DSH, Hermes, Codex ou Claude Agent, selon sa
compatibilité réelle avec le modèle retenu. Commencer avec un modèle peu coûteux susceptible
de rencontrer les difficultés évoquées. Un modèle de référence plus puissant est une
extension ; ne pas changer de harnais pour comparer les deux modes d'accès d'un même modèle.

| Variante | Accès au corpus | Objet de la mesure |
|---|---|---|
| A — MCP actuel | Véritables `file_schemes`, `file_list`, `file_info`, `file_search`, `file_read`, via la façade et les providers du jeu de test. | Référence actuelle, avec ses consignes normales et ses limites. |
| B — Répertoire | Même corpus immuable matérialisé dans un répertoire temporaire du harnais ; commandes et lecteurs de fichiers habituels. | Effet du mode d'accès, sans écrire de driver FUSE. |

La matérialisation est une fixture jetable de campagne, pas un nouveau stockage durable.
Les deux variantes disposent du shell ; seule B peut y lire le corpus. Chaque exécution
part d'une session propre, sans mémoire ni artefact d'un essai précédent. Les URI attendues
restent identifiables dans les deux variantes ; le mapping de vérification et les réponses
attendues restent hors de portée du candidat.

Isoler le canal d'accès : A utilise MCP pour ce corpus, B le répertoire. Les autres outils
nécessaires restent identiques. Une variante combinant répertoire et MCP peut être testée
ensuite pour qualifier l'usage cible, où les tools File Share sont conservés.

Figer la version du harnais et son image, le modèle exact, les paramètres disponibles,
l'effort, les budgets, les outils annexes, le corpus, ses droits et l'horloge. Fournir la
même demande, avec seulement les instructions nécessaires pour accéder à chaque surface.
Conserver les plafonds normaux de sortie du shell : un montage ne doit pas donner au
modèle des sorties illimitées. Alterner ou randomiser l'ordre A/B de chaque paire.

Ne pas embellir simultanément l'arborescence de B et laisser A face à une collection
désordonnée. Les mêmes groupes et informations doivent être accessibles aux deux variantes.
Tester séparément, ensuite, l'apport des regroupements par date ou statut.

Une copie locale donne une latence optimiste par rapport à FUSE sur un provider distant.
Elle peut réfuter le bénéfice ergonomique ; un résultat positif reste à confirmer avec
les latences, erreurs et coûts du futur transport.

### Corpus synthétique et vérification

Préparer au moins douze cas couvrant les familles ci-dessous, avec plusieurs difficultés
et des réponses attendues vérifiables. Réserver des cas distincts pour confirmer un résultat
après calibration. Aucun contenu de production n'entre dans les fixtures.

| Famille | Mission et preuve attendue |
|---|---|
| Découverte | Retrouver un fichier dans plusieurs niveaux, avec distracteurs ; URI exacte et valeur attendue. |
| Noms | Espaces, Unicode, titres proches, mêmes noms de PJ dans des parents distincts ; aucune confusion d'identité. |
| Lecture | Extraire une donnée au-delà de la première page de lecture et poursuivre sans omission. |
| Croisement | Réconcilier plusieurs sources et relever une divergence ; valeurs et références exactes. |
| Pagination | Retrouver une entrée au-delà de 500 éléments ; ne pas confondre page et collection complète. |
| Ressources métier | Identifier une Task récente parmi un historique, puis lire son état ; UUID et données exactes. |
| Mail et Messenger | Trouver la bonne PJ parmi des messages et pièces homonymes ; parent et ressource exacts. |
| Binaire borné | Identifier un format ou vérifier un petit contenu binaire avec des capacités comparables. |
| Échecs | Page interrompue ou ressource indisponible ; résultat incomplet signalé, sans faux succès. |

La réussite est jugée par des vérificateurs déterministes : identifiants, valeurs,
exhaustivité et, lorsque pertinent, empreinte du résultat. La déclaration du modèle
« j'ai lu le fichier » et un jugement LLM seul ne constituent pas cette preuve.

Les très gros fichiers et une vidéo longue font l'objet d'une **recette de capacité
distincte** : lecture séquentielle, reprise, accès à des positions éloignées et `ffprobe`.
Comparer au parcours MCP réellement disponible, y compris transfert ou outils spécialisés,
et documenter les différences de capacité. Un cas impossible avec la référence ne doit
pas gonfler le score de facilité de navigation. La durée d'une vidéo ne détermine pas sa taille.

### Mesures et règle de décision

Mesure principale : proportion de missions entièrement réussies, au total et par famille.
Mesures secondaires : coût par réussite vérifiée, tokens d'entrée/sortie, nombre d'appels,
reprises, erreurs d'arguments ou d'URI, omissions, durée et volumes transférés. Inclure les
échecs dans le coût ; séparer temps modèle, outils et préparation du corpus.

Faire d'abord un pilote de deux cas pour valider l'instrumentation. Figer ensuite les
cas, le budget et le nombre de répétitions avant la campagne de décision. Une base de
départ est cinq répétitions par cas et par variante ; ajuster l'effectif à la variabilité
du pilote, sans annoncer que cet effectif suffit à prouver un petit gain. Les répétitions
d'un même cas ne sont pas autant de missions indépendantes. Rapporter l'incertitude des
différences appariées en tenant compte des cas.

Seuils proposés, à figer avant les runs de décision :

- poursuivre si B apporte au moins **10 points** de réussite supplémentaires sur le
  modèle prioritaire, ou au moins **20 %** de réduction du coût par réussite vérifiée ;
- pour le critère de coût, établir une non-dégradation de réussite avec une marge maximale
  de **5 points** ; l'intervalle de la différence de réussite doit exclure une perte
  supérieure à cette marge ;
- utiliser des intervalles appariés à 95 % : l'estimation doit franchir le seuil retenu
  et l'intervalle du gain doit exclure zéro. Un résultat ponctuel favorable ne suffit pas ;
- aucune régression d'accès, confusion de fichiers ou lecture silencieusement tronquée
  n'est acceptable. Rapporter les familles qui régressent, même si la moyenne progresse.

Un résultat sans amélioration conduit à arrêter la piste FUSE et conserver MCP. Un
résultat incertain ne vaut pas accord de développement : au plus une seconde campagne
bornée, prévue avant analyse, puis décision explicite. Ne pas poursuivre jusqu'à trouver
un sous-ensemble favorable. Un gain limité à une famille justifie un périmètre limité.

### Infrastructure et livrables

Réutiliser ce qui convient dans le [Lab](../../docs/fr/architecture/ai-lab-evaluation.md)
et les pratiques du [benchmark mémoire](../../back/scripts/memory_benchmark/README.md).
Vérifier d'abord si leur contrat permet réellement l'exécution complète du harnais et
de ses outils : l'enregistrement d'appels sans effet ne remplace pas cette expérience.
Une campagne technique n'est pas un processus métier à envelopper dans `app.process`.

La [qualification des runtimes](../../bin/test-harness-runtimes.sh) vérifie les SDK et
binaires avec des réponses déterministes ; elle ne mesure pas l'aisance d'un LLM réel.
En reprendre les images et garanties d'isolation adaptées, sans présenter ce test comme
la campagne A/B. Exécuter les outils de préparation dans Docker, via une cible Make dédiée
si nécessaire. L'accès réseau est limité aux services de test et au fournisseur choisi.

Livrer sous `artifacts/file-share-navigation/<campagne>/` : manifeste, empreintes du corpus,
configuration expurgée, résultats par cas, mesures et erreurs. Garder les secrets hors traces.
Le compte rendu durable contient les agrégats, limites et décision : poursuivre, arrêter
ou confirmer. Publier aussi les échecs et les exclusions. Aucune commande de campagne
n'est encore implémentée par ce plan.

## Phase 1 — conception seulement si le gain est confirmé

### Arborescence personnelle et identité

Retenir un répertoire stable dans le home effectif du harnais, annoncé dans ses consignes.
Exemples de branches à qualifier : `nextcloud/`, un code de Tool connecté, `document/`,
`memory/` et `task/`. Les noms des Tools réels déterminent les schémas externes ; ne pas
inventer un second registre de résolution. Définir les conflits entre noms réservés et
codes de Tools avant d'adopter des raccourcis pour `galaris://`.

La console reste le système de fichiers de travail du harnais : aucune branche `console/`
sous File Share. Les URI `console://` existantes restent valides pour les tools.
Les chemins montés projettent des URI et ne remplacent pas leur identité dans les contrats
métier, livraisons, Documents ou pièces jointes.

Garantir un nom unique par parent, stable entre pages et indépendamment des titres
modifiables. Préserver le nom source pour l'affichage et la copie. Étudier un libellé lisible
avec identifiant stable pour les collections métier ; tester cet effet séparément du
mode d'accès. Définir encodage, séparateurs, `.`, `..`, longueurs et collisions ; refuser
une collision sans écrasement. Ne jamais aplatir les parents de PJ homonymes.

### Inventaire des providers

| Surface actuelle | Écart à traiter après la décision de poursuite |
|---|---|
| Collections `galaris://` | Curseurs présents, mais projections et coût des requêtes à mesurer. Ajouter les vues pertinentes par les façades propriétaires des domaines. |
| Documents et Memory | Collections paginées ; préparer l'exposition du contenu exact, des révisions et des PJ. Vérifier les listes de PJ chargées avant découpage. |
| Nextcloud | `resource_list_page` existe ; chaque page refait un `PROPFIND Depth: 1` et trie tous les enfants. Le curseur ne suffit donc pas aux immenses dossiers. Qualifier une stratégie côté bridge et les lectures par plages. |
| Samba | Pagination exposée, mais l'énumération actuelle est bornée à 10 000 entrées et 8 Mio de métadonnées. Étudier une vraie continuation avant de promettre de très grands dossiers. |
| Mail | File Share expose aujourd'hui les PJ d'un message, pas toute l'arborescence IMAP. Ajouter dossiers, messages et PJ via le bridge, avec identité stable, continuation et métadonnées sans lecture de tous les corps. |
| Messenger | La découverte des PJ examine un historique borné, sans continuation générale. Concevoir une liste paginée depuis les façades Messenger et ses locators canoniques. |
| AFFiNE | Lecture/création existantes sans liste générale de pages. Extension facultative si le bridge est conservé ; son éventuelle suppression n'est pas un préalable et ne fait pas partie de ce plan. |
| HTTPS et autres Tools | Pas de racine listable garantie. Annoncer seulement les capacités réelles et les ressources connues ; ne pas fabriquer une collection complète. |

Pour Mail, qualifier notamment UID/UIDVALIDITY et les références publiques déjà utilisées
par le bridge, plutôt qu'un numéro de séquence instable. Tester plusieurs milliers de
messages, noms de dossiers et pièces jointes ; ni mot de passe IMAP ni lecture directe
du protocole dans le driver. Les extensions de Nextcloud et Messenger restent dans leurs
adapters et contrats publics, communes aux consommateurs lorsque c'est pertinent.

### Vues métier, notamment Tasks

Éviter de faire de `ls task/` une liste exhaustive d'objets historiques. Comparer une
racine de répertoires de navigation : `today/`, `by-date/YYYY-MM-DD/`, éventuellement
`active/` ou une archive. Les contenus proviennent toujours des ressources Task canoniques.
Les actions de lancement, transition ou suppression restent des actions métier.

Décisions à prendre : date de création ou d'activité, fuseau de l'agent, passage à minuit,
tâche ancienne encore active, visibilité de l'historique et accès direct à un UUID connu.
Le regroupement ne doit pas rendre inaccessible une Task autorisée. Si plusieurs vues
renvoient au même objet, définir leur identité et leurs alias sans créer de copies divergentes.
Appliquer les filtres et droits dans `app.task`, pas par une requête sur ses tables privées
depuis FUSE. Étudier séparément Goal, conversations et processus selon leur volume et usage.

### Octets, fichiers volumineux et limites

Créer, si nécessaire, un contrat de lecture en octets dans la façade File Share, distinct
des lectures MCP. Conserver les limites de caractères/blocs et de sortie pour MCP ; ne pas
les augmenter globalement pour satisfaire FUSE. Le contenu binaire traverse le transport
comme des octets, sans enveloppe base64 destinée au LLM.

Spécifier lecture séquentielle et `read(offset, length)`, taille exacte lorsqu'elle est
connue, fin de fichier réelle et reprise. Pour HTML, JSON et projections métier, servir
une sérialisation définie et une révision cohérente par ouverture. Un décalage de caractères
ou de blocs ne peut pas être réinterprété comme un décalage d'octets.

Pour un provider sans plages, choisir explicitement flux séquentiel ou cache disque
progressif permettant les seeks, avec budgets et erreurs déclarés. Les formats vidéo
peuvent demander des lectures éloignées : un simple flux ne garantit pas tous les usages.
Distinguer taille totale autorisée, taille d'un bloc, mémoire, disque cache, concurrence
et délais. Une limite de ressource doit produire une erreur, jamais une fausse fin de fichier.
Ne pas télécharger systématiquement une vidéo entière à l'ouverture ou au `stat`.

### Pagination, cohérence et fiabilité FUSE

FUSE fournit `opendir`, un handle et des offsets de continuation pour `readdir` ; il ne
transforme pas automatiquement les pages du provider. Associer les cookies POSIX aux
curseurs sur la durée du handle. Définir reprise, retour à un offset déjà émis et mutations
concurrentes, sans omission ou duplication silencieuse. Selon le provider, retenir une
itération stable ou un index/snapshot temporaire sur disque, avec ressources bornées.

Un million d'entrées est un scénario de charge à qualifier, pas une interdiction intrinsèque
de FUSE. Mesurer le temps de première page, les requêtes et la mémoire ; distinguer les coûts
du driver de ceux du tri et de la sortie de `ls`. Éviter un `stat` distant par entrée ;
qualifier métadonnées groupées et `readdirplus` sans cache illimité.

Définir fraîcheur des noms, attributs et contenus : TTL, invalidations d'entrée/inode,
révision ou ETag, suppression et retrait de droits. FUSE propose ces mécanismes mais ne
garantit pas la cohérence du backend. Prévenir le mélange de versions pendant une lecture.
Éviter le writeback générique sur des sources modifiables à l'extérieur.

Prévoir interruption, délais, reconnexion, redémarrage du service, démontage et nettoyage
des caches/handles. Une panne ne doit pas devenir un dossier vide. Les accès déjà ouverts
après révocation nécessitent une règle explicite et un cache conforme à cette règle.
Mesurer erreurs et latences sans journaliser les contenus ni les secrets.

### Installation et périmètre de privilèges

Qualifier Linux, FUSE/libfuse et la présence de `/dev/fuse` sur chaque hôte d'exécution.
Étudier un service de montage dédié, livré et versionné avec le gestionnaire de harnais,
lié à une seule identité d'agent, plutôt que donner des privilèges étendus aux harnais.
Les mécanismes de montage exigent des droits à qualifier ; éviter le mode `privileged` global.

Définir ordre de démarrage, disponibilité du mount, propagation des montages Docker,
redémarrage et retrait lors de la suppression d'un agent. Un volume partagé ordinaire
ne garantit pas la visibilité d'un montage créé ensuite : qualifier les bind mounts
et leur propagation sur l'hôte. Prévoir diagnostic et retour aux tools MCP en cas d'échec.

Distinguer console interne gérée et exécuteur SSH externe : le montage doit être visible
sur la machine qui exécute effectivement le shell. Documenter les prérequis et la livraison
sur cet hôte ; aucun changement de production n'est autorisé par cette conception.
L'UID local représente l'agent propriétaire ; il ne crée pas un système multi-utilisateurs
dans le partage. Le contexte d'exécution et les restrictions des Tools restent applicables.

## Ordre de travail conditionnel et réception

| Étape | Livrable | Condition pour passer à la suivante |
|---|---|---|
| 0.1 | Harnais/modèle choisis, fixtures, vérificateurs et pilote fonctionnels. | Accès réel aux deux surfaces et mesures fiables. |
| 0.2 | Campagne appariée, compte rendu et décision. | Gain utile établi selon les critères figés ; sinon arrêt. |
| 1 | Contrats d'octets, noms, vues métier, pagination et installation ; décision d'architecture acceptée. | Périmètre minimal faisable, coût et limites documentés. |
| 2 | Premier montage en lecture seule sur les providers retenus. | Gain reproduit avec le transport réel, isolation et fiabilité vérifiées. |
| 3 | Extensions de providers et gros fichiers. | Qualification propre à chaque capacité ; pas de promesse uniforme prématurée. |
| 4 | Écriture éventuelle. | Sémantique explicite de flush/close, conflits de versions et issue réseau ambiguë. |

L'étape en lecture seule est un périmètre initial ; la cible de droits conserve les
capacités d'écriture des sources. Ne pas les annoncer dans le montage tant que les mutations
correspondantes ne sont pas réellement supportées et qualifiées.

Réception technique après poursuite : mêmes droits et URI que MCP, aucun nom en collision
dans un parent, pagination complète et stable, lecture exacte des octets, erreurs explicites,
cache borné, interruption/nettoyage, redémarrage et isolement entre deux agents. Vérifier
les consommateurs MCP existants, notamment copies conservant le nom source et lectures
éditoriales avec révisions. Réutiliser les suites actuelles ; ajouter les garanties nouvelles
au niveau du contrat, avec services réels et frontières externes synthétiques.

Générer les jeux volumineux à la demande, sans gros blobs versionnés. Après le résultat
positif seulement, qualifier un fichier dépassant les budgets actuels et une très grande
collection, puis mesurer mémoire, disque et requêtes. La comparaison initiale ne vaut
ni qualification de tous les harnais ni validation d'un montage réseau en production.

## Références techniques pour la conception éventuelle

- [libfuse : opérations bas niveau](https://libfuse.github.io/doxygen/structfuse__lowlevel__ops.html),
  notamment `opendir`, `readdir` et les cookies de continuation.
- [libfuse : invalidations](https://libfuse.github.io/doxygen/fuse__lowlevel_8h.html) et
  [configuration des caches](https://libfuse.github.io/doxygen/structfuse__config.html).
- [Noyau Linux : FUSE](https://docs.kernel.org/filesystems/fuse/fuse.html) et
  [modes d'I/O](https://docs.kernel.org/filesystems/fuse/fuse-io.html).
- [Docker : propagation des bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)
  et [accès FUSE depuis un conteneur](https://docs.docker.com/engine/containers/run/).
- [Nextcloud : WebDAV SEARCH](https://docs.nextcloud.com/server/stable/developer_manual/client_apis/WebDAV/search.html) :
  option à qualifier ; ne pas supposer une pagination par offset non documentée.
- [FFmpeg : protocoles](https://ffmpeg.org/ffmpeg-protocols.html), pour distinguer accès
  séquentiel, seek et cache lors de la recette vidéo.
- Décisions [0033](../decisions/0033-resource-uri-virtual-file-facade.md),
  [0046](../decisions/0046-remove-implicit-local-resource-storage.md),
  [0147](../decisions/0147-nextcloud-file-consistency.md),
  [0153](../decisions/0153-common-action-authorizations.md) et
  [0167](../decisions/0167-samba-file-share.md).
- Gestion des harnais : [0038](../decisions/0038-generic-harness-manager.md),
  [0117](../decisions/0117-harness-manager-distribution-and-updates.md).
