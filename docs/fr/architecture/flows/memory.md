<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/memory.md">English</a></p>

# Flux de mémoire

La mémoire durable est un domaine gouverné de Galaris. Un driver ou un bridge ne lit jamais
directement son stockage et ne décide pas seul de la portée d'une session.

Les objets mémoire et documents ne possèdent pas de champ `summary` indépendant.
La recherche et les embeddings utilisent le titre, les mots-clés et le contenu courant.
Dream et le Lab produisent et échangent le contenu sans résumé parallèle. Les aperçus
sont des extraits calculés, jamais une seconde version éditable du contenu. L'index
sémantique v3 est reconstruit en arrière-plan après synchronisation DbAdmin.

Les modifications et acquisitions ne portent aucun commentaire libre `reason`.
L'historique conserve les contenus, versions, auteurs, tâches et dates. Les relances
d'ajout de document sont reconnues par un marqueur interne `document_append` ; DbAdmin
convertit les anciennes révisions avant de supprimer les motifs. Le critère de
conservation `retention_reason` de Dream reste appliqué.

## Lecture avant une exécution

```text
journal app.messenger ──► snapshot de session borné ──┐
                                                       ├─► AgentRunContext
PostgreSQL Memory ── ACL/validité ── hybride ──► brief ─────────┘         │
                                                                ├─► Pydantic AI history + context
                                                                └─► Hermès MemoryProvider + history
```

Le snapshot de session est indexé par connexion et salon. Le journal est autoritatif dès qu'il
contient des lignes; `Task.messages` et l'historique d'un runtime servent uniquement de repli.

Le brief durable ne déclenche aucun modèle. La requête filtre d'abord le propriétaire, les accès
directs, la visibilité publique et les dates de validité. Les mémoires `core` passent par le même
rappel que les autres types et par la même portée de contact ; aucune place ni score artificiel ne
leur est réservé. La projection de la fiche Agent reste exclue du brief, puisque l'identité et la
personnalité viennent déjà du profil canonique dans le prompt système, mais elle reste disponible à
la recherche explicite. Avant le reranking, un candidat doit porter une preuve lexicale directe ou
une similarité sémantique atteignant à la fois le plancher `0,35` et une marge de `0,20` sous le
meilleur candidat. Le résultat peut donc être vide. Le budget final en items et caractères reste
strict, et chaque extrait porte l'identifiant logique ainsi que ses sources.

Le Topic est un prior de classement, jamais une frontière d'accès implicite. Avec un Topic
canonique courant, ses souvenirs reçoivent le signal thématique maximal. Sans Topic courant, le
vecteur de la requête présélectionne le Topic public le plus proche parmi ceux qui contiennent une
mémoire accessible à l'agent, uniquement si sa similarité atteint `0,55` ; sa similarité borne la force du prior. Dans les deux cas, la voie
globale autorisée reste fusionnée afin qu'une erreur de classement thématique ne masque pas un
souvenir réellement pertinent.

La requête lexicale n'est jamais l'objectif complet de la Task. Elle est dérivée de façon
déterministe et bornée : titre structuré du Goal lorsqu'il existe, sinon libellé de la Task, puis
court extrait de l'objectif en dernier recours. Pour un round conversationnel, les préfixes
techniques d'expéditeur et le code Agent sont retirés ; la graine sémantique ajoute au plus les deux
messages canoniques immédiatement précédents afin de résoudre « réessaye », « ça » et les autres
références au tour précédent. Pour une Task Messenger humaine, l'UUID canonique
du contact borne la recherche ; son nom affiché, son identifiant natif et le code du bridge ne sont
donc pas répétés dans la graine sémantique. Les suffixes de cycle sont retirés afin qu'un
nouveau cycle puisse retrouver les précédents. Cette réduction évite qu'un long prompt devienne
une conjonction FTS impossible à satisfaire.
La génération de candidats lexicaux relie les termes significatifs par `OR`, puis les classe par
couverture FTS. Lorsque le fournisseur vectoriel est indisponible, le repli peut ainsi proposer
les meilleurs souvenirs partiellement concordants au lieu d'exiger tous les mots de la requête.

Il n'existe aucun espace mémoire. Chaque souvenir appartient directement à un agent, qui y accède
toujours. Un autre agent ne le voit que par un grant posé sur ce souvenir ou parce que celui-ci est
explicitement public. Les acquisitions automatiques restent privées : le partage n'est jamais
laissé à une initiative supposée du modèle et ne se propage pas à un conteneur entier.

### Portée des souvenirs conversationnels

Un Topic possède une projection `MemoryItem` publique et globale. Chaque interlocuteur observé
possède séparément un nœud `MemoryItem(social)` privé, déterministe pour
`(agent, bridge, identifiant distant)`. Toute extraction automatique attend d'abord un Topic. Dès
son extraction, un souvenir conversationnel est scellé au contact par `MemoryContactItem` et
`MemoryTopicContactScope + MemoryTopicContactItem` enregistre l'appartenance exacte.
Les acquisitions gouvernées et les tools d'écriture reprennent ce scope serveur dès la création :
deux interlocuteurs donnant le même fait obtiennent deux souvenirs distincts, chacun scellé à sa
fiche contact, sans fenêtre d'exposition en attendant Dream.

```text
Topic public ───── topic_contains ────► souvenir privé
      └──── topic_involves_contact ───► contact privé
contact privé ─── contact_contains ──► souvenir privé
```

Le rappel de nouveauté filtre sur le couple Topic/contact. Un souvenir déjà lié à un contact ne
peut pas être rattaché à un autre.
Les liens `topic_contains`, `contact_contains` et `topic_involves_contact` sont des projections de
graphe utiles à la navigation. Le dernier rend directement visible le couple structurel, mais une
jointure sur ces liens ne remplace jamais le scope exact.
Une source conversationnelle sans contact prouvé reste inéligible. L'absence de Topic bloque les
trois extracteurs automatiques Task, round texte et tour Voice, sans modifier les écritures
explicites par tool ni le contrat distinct d’apprentissage.

Un `MemoryItem` possède aussi une nature orthogonale à son rôle cognitif : `memory` pour un
souvenir ordinaire, `document` pour un document Markdown de travail. Un document reste de type
`working`, privé à sa création, mutable et non dédupliqué. Il utilise les mêmes UUID, ACL,
ressources opaques, révisions et projections de recherche que les autres nœuds, mais il est exclu
des acquisitions Dream et de l'oubli automatique par inactivité. Seul son propriétaire peut
l'oublier ou modifier ses collaborateurs.

## Documents de travail collaboratifs

```text
file_create(path="document://") ──► MemoryItem(document, working, privé)
       │
       ├─► file_read(document://uuid, offset) ──► passage borné
       ├─► file_edit(start_line, end_line, content) ──► révision atomique
       ├─► file_append(document://uuid, content) ──► révision atomique
       └─► document_share(agent_id, read|edit|none) ──► grant direct
                                                        │
                                                        └─► autre agent
                                                             ├─ file_search(document://)
                                                             ├─ file_read(document://uuid)
                                                             └─ edit/append si autorisé
```

La surface MCP reste volontairement petite. `file_search` assure la découverte des URI
`memory://` et `document://`; `memory_forget` assure la suppression explicite par le propriétaire.
`file_read` ne renvoie jamais un document entier par défaut : il accepte un offset pour
poursuivre. `file_edit` remplace une plage inclusive de lignes, numérotées à partir de 1.
Une plage absente ou une révision concurrente échoue sans modification et demande une relecture.
Les révisions conservent l'agent et la Task auteurs.

Avant une délégation, le propriétaire partage explicitement le document puis place son UUID dans
l'objectif de la Task enfant. Les agents conservent les notes provisoires dans le document et
promeuvent séparément les conclusions réellement durables avec `memory_remember`.

Le registre de contexte d'`app.agent` est fail-open. Il prépare une seule valeur commune. Hermès
reçoit cette valeur exacte via le provider projeté et ne la recalcule pas; le harnais interne la
reçoit dans l'`AgentRunRequest`.

Lorsque le provider Galaris est actif, la configuration générée désactive par défaut
`MEMORY.md`, `USER.md` et le tool natif `memory`. Cette politique est une valeur par défaut, pas
un verrou : `hermes.default.config`, puis la configuration Hermès propre à l'agent, peuvent
explicitement réactiver l'un des deux magasins ou conserver le toolset désactivé. L'override par
agent est toujours prioritaire.

Le même provider ajoute une politique système commune aux drivers. Le modèle doit examiner le
brief, puis appeler `file_search(memory://)` seulement lorsqu'un contexte durable peut matériellement
modifier le travail et que le brief ne suffit pas. Une Task `high` ou récurrente impose cette
évaluation, jamais l'appel lui-même. Les états transactionnels restent lus avec les tools de leur
domaine. Une recherche explicite utilise une requête courte et l'unique stratégie hybride.

Le brief injecté s'annonce comme déjà récupéré et demande au modèle de le consulter avant toute
nouvelle recherche Memory. Sans modifier cette politique sélective, les descriptions de
`file_search` et `memory_remember` rendent plus saillants deux recours volontaires : rechercher
explicitement un contexte durable absent ou insuffisant, et mémoriser spontanément une information
durable susceptible d'aider une conversation future.

## Rappel hybride unique à deux voies

```text
API /memory/browse (administration) ─────► ACL/validité ──► FTS ─────────► page exhaustive

API /memory/search + page Mémoire + MCP/voix/brief + toute recherche file_search(memory://)
       ├─► voie thématique ──► FTS + cosinus exact ─┐
       └─► voie globale ─────► FTS + cosinus exact ─┼─► classement pondéré ─► diversité ─► résultats
                 liens confirmés forts ──► reranking┤
                 sources + centralité des liens ────┤
                                                     │
              modèle/index/provider indisponible ───┘
                                      repli lexical à deux voies signalé
```

Le mode hybride est l'unique stratégie des surfaces de recherche bornées (`/memory/search`, brief
automatique, tools MCP et voix). `/memory/recall` est un alias HTTP déprécié du même contrat.
Il fusionne les candidats lexicaux et sémantiques, retourne le chunk sémantique le plus pertinent
comme extrait et indique `mode`, `degraded` et `degradation_reason`. Aucun appelant ne peut le
dégrader volontairement en lexical : cette voie est exclusivement un repli automatique lorsque
le modèle, le fournisseur ou l'index sémantique est indisponible. Pour `memory://`, le paramètre
générique `mode` de `file_search` ne change donc pas cette stratégie. La liste
d'administration `/memory/browse` reste lexicale et paginée. Le rappel borné n'annonce ni total exact ni pagination
exhaustive, puisque son rôle est de rappeler quelques éléments pertinents.

La version `memory-topic-evidence-diverse/v7` fusionne quatre signaux de présélection : FTS et pgvector
dans le Topic courant lorsqu'il existe, puis FTS et pgvector dans la portée globale autorisée.
Elle classe ensuite les candidats selon les Params globaux pour le sémantique, le lexical, les liens
confirmés, le nombre de sources, la fraîcheur et la centralité. Cette dernière tient compte des
liens accessibles autour du candidat, y compris hors du seul top-k. Les injections automatiques ne
créent aucune association de co-usage : être présenté ensemble ne prouve pas une relation métier.
Le vivier vaut 48 candidats et le résultat contient au plus huit items par défaut; le vivier,
les poids et la diversité sont exclusivement configurés par les Params globaux de la section
Mémoire. Une sélection de diversité pénalise les résultats
trop proches et ne conserve qu'un représentant des quasi-doublons. Son seuil est l'unique
`MEMORY_DUPLICATE_SIMILARITY_THRESHOLD`, partagé avec l'acquisition, les signalements et les
fusions automatiques; il n'est pas surchargeable par appel. Le résultat détaillé interne
expose les sources de chaque hit et les nombres de candidats
et résultats thématiques/globaux. Un contact exact borne aussi la voie globale : elle accepte les
souvenirs de ce contact dans d'autres Topics et les souvenirs autonomes non conversationnels,
mais exclut toute mémoire scellée par un autre interlocuteur. Sans contact, la voie globale
conserve le rappel ACL ordinaire.

Après ces rangs textuels et vectoriels, le rappel inspecte au plus un saut depuis leurs candidats
à travers les `MemoryLink` confirmés (`suggested=false`) dont la confiance atteint `0,75`. Cette
voie `graph_link`, pondérée à `1,1` puis modulée par la confiance du lien, ne peut reranker qu'un
souvenir possédant déjà une preuve lexicale ou vectorielle directe. Le repli lexical ignore les
formules conversationnelles sans terme informatif et exige un recouvrement direct avec plusieurs
termes pour une requête longue. Elle repasse toujours par
les mêmes ACL, dates, types et surtout par le même filtre de contact. Un lien, même de confiance `1,0`, ne peut donc jamais
faire entrer un souvenir scellé à Paul dans le rappel courant de Jacques.

Une proposition positive `topic_membership_candidate` ne crée pas de candidat et ne définit pas
l'appartenance canonique à un Topic. Lorsqu'un souvenir est déjà candidat par une voie autorisée,
elle ajoute cependant la source `suggested_topic_link` et contribue au signal graphique à hauteur
de sa confiance multipliée par `MEMORY_RECALL_SUGGESTED_LINK_WEIGHT` (`0,25` par défaut). Les
signaux d'anomalie, de fusion ou de séparation restent exclus du classement : leur sens n'est pas
univoquement positif pour la pertinence d'un souvenir.

Le brief commun et `file_search(memory://)` résolvent côté serveur le Topic et la fiche contact de
la Task ou du tour conversationnel. Pour le brief automatique, la fiche contact constitue à elle
seule la frontière d'identité et son libellé ne pollue pas la requête thématique. Une recherche
explicite peut toujours employer un nom comme terme lexical, sans en faire une frontière : celle-ci
reste l'UUID exact du contact et son appartenance persistée.

Les projections publiques `memory_role=topic` et les fiches structurelles de contacts ne sont
jamais rendues comme souvenirs factuels par cette surface. Leurs embeddings restent disponibles
pour le classement et la navigation.

La branche vectorielle applique propriétaire, grants, visibilité, dates et types dans la
requête SQL avant la distance. Elle ne considère que les chunks dont `model_key`, dimension et
`source_fingerprint` correspondent au modèle et au souvenir courants. La recherche pgvector reste
exacte. Le brief conserve une requête lexicale courte mais transmet l'objectif complet, borné par
Param, à l'embedding. Le benchmark exécutable accepte des requêtes sémantiques et viviers
différents afin de comparer qualité et latence p95 entre une portée concise et une portée élargie.
Il couvre aussi préférence, contact, procédure, correction, expiration,
oubli, ACL inter-agent et repli lexical ; sa baseline atteint le seuil `recall@5 >= 90 %` sans
fuite. Un index ANN sous filtres ACL ne sera donc introduit qu'après une dégradation mesurée sur
une volumétrie représentative.

`access_count` et `last_accessed_at` mesurent uniquement une mémoire effectivement présentée à un
LLM, par le contexte commun ou par `file_search` et `file_read`. Les recherches,
consultations et tris de l'API d'administration ou de l'IHM sont toujours neutres, sans option
permettant au client de modifier cette règle. Ces écritures d'usage sont atomiques et ne changent
jamais `updated_at`. Pour un `MemoryItem`, `updated_at` désigne exclusivement la dernière
modification effective du payload ou des mots-clés; propriétaire, titre, visibilité, grants,
provenance et autres métadonnées n'y participent pas. Les rappels internes utilisés par Dream
pour éviter les doublons ne comptent jamais comme des accès utiles.

`created_at` représente la date d'origine du souvenir lorsqu'un producteur fiable la fournit.
Dream lui transmet la date de création de la Task source, même lorsque cette Task historique est
analysée plus tard. Les enregistrements d'acquisition, sources et révisions gardent leur propre
date d'écriture pour préserver l'audit. Lors d'une fusion, l'item conserve la plus ancienne date
d'origine connue.

Les usages distinguent `context`, `search` et `read`. Le résultat d'exécution conserve en outre
uniquement la requête courte, les nombres récupéré et réellement injecté, la troncature et les
UUID des items injectés ; le texte injecté
n'est jamais recopié dans ces métadonnées. L'interface présente ainsi le brief automatique
séparément des appels explicites `memory_*`.

## Acquisition, Dream et extraction automatique

`memory_sources` est l'association de provenance entre un souvenir et son activité canonique.
Chaque ligne conserve l'identité extensible `source_kind + source_ref` et porte, selon le cas, une
clé étrangère typée vers `tasks` ou `conversation_rounds`. Ces deux
relations sont n↔n : une activité peut produire plusieurs souvenirs et un souvenir réutilisé ou
fusionné peut être confirmé par plusieurs activités. Une création, une mise à jour ou une fusion
ajoute toujours la nouvelle source sans réécrire le contenu lors d'une simple fusion. Les tools
Memory appelés depuis un round texte ou vocal utilisent le round persistant injecté côté serveur ;
ils ne retombent sur `agent:manual` qu'en l'absence de toute Task ou de tout round canonique.

Les FKs utilisent `ON DELETE CASCADE` sur la seule ligne de provenance : supprimer physiquement
une activité retire son association, jamais le `MemoryItem`. Les écritures courantes renseignent
directement la FK typée lorsque la source canonique existe.

```text
producteur explicite
(page Mémoire, tool mémoire, écriture Hermès)
  → journal d'acquisition idempotent
  → filtre de sécurité + décision déterministe
       ├─ create      → nouvel item + source
       ├─ update      → nouvelle révision + source
       ├─ link        → relation explicite
       ├─ contradict  → nouvel item + lien de contradiction
       └─ skip/unsafe → rejet automatique audité
```

Une acquisition admissible est appliquée immédiatement. Il n'existe ni boîte de validation ni
question humaine dans Galaris : les interlocuteurs des canaux de messagerie ne sont généralement
pas des utilisateurs de l'interface et ne pourraient pas répondre à une telle demande. Le journal
interne apporte l'idempotence, la provenance et la reprise après interruption; un état technique
transitoire est repris par le worker et n'est jamais exposé comme décision à prendre.

La déduplication exacte par contenu conserve une identité seulement lorsque les deux bornes
`valid_from` et `valid_until` sont identiques, y compris leur absence. Un fait confirmé à nouveau
avec une autre période de validité ne réutilise donc pas un ancien souvenir expiré. Celui-ci
conserve ses dates et sa provenance ; le rappel continue de l'exclure.

### Apprentissage procédural séparé

L'analyse des résultats de Tasks réutilise certaines preuves observables de Memory, mais elle
n'appartient pas à ce domaine. Le mécanisme Dream `skill.learn_task_outcome` crée et renforce des
procédures dans les tables dédiées d'`app.skill`. Il ne crée aucun `MemoryItem`, et les expériences
historiques ne sont plus rappelées. Son score, ses seuils d'injection et son audit sont décrits dans
le [flux Dream](dream.md) et l'ADR 0047.

La recherche de souvenirs dans les Tasks est entièrement détachée de leur terminaison. Le
mécanisme `memory.extract_task` d'`app.dream` prend une Task racine réussie non scannée par
cycle, rattachée à un agent et à un topic, hors Goal, Voice et refus explicite de capture,
présente au petit modèle un rappel hybride borné des souvenirs déjà connus, l'identité exacte de
l'expéditeur humain lorsqu'elle est disponible et, lorsqu'il existe,
l'objectif du tour suivant de la même conversation comme indice sur le résultat réel. Il
ne conserve comme candidats de doublon que les correspondances qui atteignent l'unique
`MEMORY_DUPLICATE_SIMILARITY_THRESHOLD`. Il checkpoint une décision structurée unique
puis applique chaque opération avec une identité stable.
Cette décision crée un fait absent (`CREATE`), ajoute la source à un souvenir candidat sans le
réécrire (`LINK`) ou s'abstient avec une liste vide (`IGNORE`). Le serveur refuse toute cible qui
ne faisait pas partie du rappel, exclut les projections Topic/Contact et ne propose comme cible de
`LINK` qu'un souvenir possédé par l'agent courant. Le modèle doit encore vérifier l'identité du fait :
un thème, une décision liée ou un recouvrement partiel ne suffit jamais. Un rattachement conversationnel peut compléter
le contact et le Topic d'un souvenir global du même agent, mais ne peut jamais franchir la frontière
d'un autre contact. Lors de l'application, `app.memory` recalcule la corrélation depuis le contenu
exact de chaque fait proposé : sous le seuil il crée un nouvel item; au seuil ou au-dessus il
conserve l'item existant et ajoute seulement la nouvelle `MemorySource`. Une décision `CREATE`
ainsi fusionnée est auditée comme l'effet `LINK` réellement appliqué.

Chaque création doit déclarer une utilité future
élevée et un motif de rétention fermé : préférence explicite, fait personnel stable, décision ou
engagement, contrainte récurrente, procédure réutilisable, correction explicite ou relation
durable. Le serveur élimine toute proposition sans ces deux signaux. Le prompt exclut les faits
publics de dossier ou de recherche, les résumés de livrable et les détails ponctuels. Chaque
réponse doit être un unique objet JSON complet. Une première réponse invalide déclenche une reprise
corrective bornée ; une seconde réponse invalide fait échouer la préparation et ne peut jamais
produire un reçu réussi. Chaque création ou rattachement appliqué reste un effet du reçu, mais les
résultats serveur checkpointent aussi, pour chaque opération, l'UUID du souvenir et le statut
`stored` ou `merged`. Une opération rejetée, une source devenue indisponible ou une preuve
incomplète fait échouer l'application et conserve le reçu rejouable : une proposition seule ne
peut plus être comptée comme une écriture. Les anciens reçus réussis qui portent des opérations
sans cette preuve redeviennent automatiquement éligibles et sont réappliqués avec leurs clés
d'idempotence stables. Les totaux de l'interface séparent les nouveaux souvenirs des sources
rattachées et ne lisent que les preuves d'application. Les autres effets
Dream, notamment l'association d'un Topic, ne sont jamais comptés comme souvenirs. Une liste vide laisse
un témoin de scan réussi. Le
mécanisme n'expose aucun outil au modèle local, s'interrompt dès qu'une conversation Voice démarre
et n'est disponible que si `MEMORY_CAPTURE_ENABLED` est actif.

`memory.extract_task` ne devient éligible qu'après la fin du reçu `topic.classify_task`. Le même
sujet n'apparaît donc pas simultanément comme classification en cours et extraction restante ; le
compteur des Tasks non scannées reprend directement les états du mécanisme d'extraction au lieu de
soustraire tous les reçus à toutes les Tasks terminales.

La langue des contenus générés suit la source durable : `Task.data.language`, détectée par le
dispatcher à partir de la conversation, ou `VoiceConversationSession.language` pour la voix.
Les prompts structurés imposent cette langue aux titres, descriptions, contenus et mots-clés des
dossiers et souvenirs ordinaires. Les rubriques déterministes utilisent le
même code et l’item final conserve `metadata.language`. `DEFAULT_LANGUAGE`, déjà stocké dans les
paramètres PostgreSQL, ne sert que de repli lorsqu’aucune langue de source exploitable n’existe.
Ce comportement ne retraduit pas implicitement les souvenirs historiques, afin de ne pas réécrire
une mémoire durable sans nouvelle provenance.

Le scheduler Dream ne réclame qu'une opération à la fois et fait tourner le point de départ entre
les mécanismes disponibles. Après la fin complète de chaque opération, il attend
`DREAM_POLL_SECONDS` avant d'en démarrer une autre. Un appel LLM long ne réduit donc pas cette
respiration ; la même durée sert d'intervalle de vérification lorsqu'aucun sujet n'est disponible.

`app.memory.link_reconciliation` ne fait aucune inférence. Il relit chaque provenance de Task,
round ou tour Voice classé, puis rattache le souvenir au Topic canonique. Une source
conversationnelle utilise en plus le contact exact et le scope Topic/contact autoritatif. Le même
service en projette l'arête directe `topic_involves_contact` et reconstruit `cycle_of` et
`result_of`. Il compare un état désiré aux seuls liens portant sa `projection_key`, de sorte qu'une
relance crée, met à jour ou retire les projections obsolètes sans toucher aux liens explicites ni
aux ACL du souvenir.

Le mode ciblé accepte l'UUID d'un `MemoryItem` et traite ses arêtes entrantes et sortantes. Chaque
opération Dream réussie peut inscrire ces nœuds dans le worker durable Memory. Le paramètre
`MEMORY_LINK_RECONCILIATION_TRIGGER_MODE` choisit entre manuel uniquement, après Dream, planifié ou
les deux. Le mode global planifié respecte
`MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS` et n'est inscrit que lorsque ni Task ni conversation
Voice n'est active ; si la charge revient avant son exécution, le job est différé. Les routes
`GET|POST /api/memory/link-reconciliation` exposent son calendrier et son dernier état ; le `POST`
exécute immédiatement un sweep global dans la requête courante, sans job durable ni garde
d'inactivité. Le verrou transactionnel du réconciliateur sérialise ce lancement avec un éventuel
sweep planifié concurrent. La commande
`make rebuild-memory-links ARGS='--item-id <uuid>'` expose le même contrat aux opérateurs.

Les conversations Messenger et les Tasks de Goal peuvent ainsi être examinées sans promotion
automatique de leur résumé complet : seul un élément satisfaisant le contrat de durabilité devient
un souvenir. Les projections déterministes de Goal restent l'autorité structurée de leurs cycles.
Les appels explicites à `memory_remember` ou `memory_summarize` restent immédiats.

`memory.extract_conversation_round` applique le même contrat aux rounds textuels et vocaux
classés. Il sépare le round courant d'au plus cinq messages canoniques antérieurs. Toutes les
acquisitions gardent la provenance `conversation_round:<uuid>`. Les rounds audio realtime sans
transcript sont ignorés, car leur promotion durable reste explicite via les tools Memory.

## Dossiers thématiques et administration manuelle

`app.topic` classe les Tasks et sessions Voice dans des dossiers globaux, puis projette chaque
dossier sous la forme d'un `MemoryItem` public, ownerless et source-managed. Les souvenirs privés
restent privés : l'arête `topic_contains` n'accorde aucun accès au voisin. La lecture des dossiers
utilise `TOPIC_ACCESS`; leur création, modification, suppression, fusion et scission utilisent le
privilège administratif distinct `TOPIC_EDIT`.

Les mécanismes de classement essaient d'abord un
réemploi dans une sortie structurée qui ne permet aucune création. La liste de candidats est
ordonnée par fusion RRF de la pertinence lexicale, de la proximité avec les seules projections
publiques pgvector et de dossiers populaires servant d'ancres. Une absence de modèle ou d'index
conserve le classement lexical et populaire. La distance ne choisit jamais le dossier. Une
seconde inférence ne propose un nouveau dossier qu'après l'échec de ce
passage ; un filtre déterministe de similarité et un verrou transactionnel empêchent ensuite les
quasi-doublons et doublons concurrents.

La famille `memory.topic_maintenance` du réconciliateur traite le snapshot courant de l'index.
Sans LLM et sans contenu publié, elle produit au plus 100 signaux par catégorie : rattachement
d'une mémoire orpheline, membre éloigné de l'ancre, Topics publics proches et groupes privés
stables suffisamment séparés pour suggérer une scission. Les groupes privés sont calculés par
propriétaire et ne forment jamais un centroïde public ou inter-agent. Les relations réservées
`topic_*_candidate` et `topic_membership_anomaly` portent `suggested=true`, le modèle, la version et
les preuves bornées. Une réconciliation remplace uniquement ces suggestions générées ; elle ne
crée, déplace ni supprime jamais un `topic_contains` canonique.

`DREAM_TOPIC_CREATION_MODE` contrôle l'effet d'une proposition restante. `forbid` laisse
l'activité non classée, `auto` crée immédiatement, et `propose` — valeur par défaut — ouvre une
interaction Messenger persistante. L'utilisateur d'origine choisit de créer, de réutiliser l'un
des UUID checkpointés ou de ne pas classer l'activité. Une proposition sans route humaine reste
non classée ; sa clé liée au reçu Dream évite tout envoi en double lors d'une reprise.

Une fusion déplace toutes les arêtes `topic_contains` vers la cible, réaffecte les Tasks et sessions
Voice, puis oublie la projection source. Une scission est une partition manuelle : l'administrateur
crée le nouveau dossier et choisit explicitement les souvenirs dont l'arête doit être déplacée;
les autres restent dans le dossier source. Le contenu, l'UUID, le propriétaire, la visibilité et
les grants des souvenirs ne changent jamais. La projection publique est le seul `MemoryItem` qui
porte le `topic_id` canonique, avec `ON DELETE CASCADE`; les deux extrémités de `memory_links`
cascadent à leur tour vers les seules arêtes. Le nœud mémoire situé à l'autre extrémité ne dépend
jamais du lien et survit. Tous les autres `topic_id` — Tasks, sessions et tours Voice, journal
Messenger et rounds — utilisent `ON DELETE SET NULL`. Comme l'API historise le Topic au lieu de le
supprimer physiquement, son service applique explicitement la même politique : il purge la
projection dérivée et ses arêtes, conserve les souvenirs liés et remet toutes les références à
`NULL`.

## Projections des données canoniques

```text
Agent ───────────────► Markdown core ───────────────┐
Goal ────────────────► Markdown working/episodic ──┼─► MemoryItem privé et source-managed
GoalCycle + Task ────► compte rendu episodic ──────┤          │
expéditeur Messenger ► fiche social ───────────────┤          ├─ UUID conservé sur Agent/Goal/Cycle
Process assigné/réussi ► procédure/résultat ───────┘          │
                                                              └─ identité source hashée pour le contact
```

`Agent`, `Goal` et `GoalCycle` restent les sources de vérité de leurs données structurées. Memory
en construit des pages Markdown pour rendre leurs informations utiles au rappel commun des
drivers, sans déplacer ni dupliquer la saisie métier. Les mots-clés sont entièrement
déterministes : type de source,
identifiants, agent propriétaire, statut, numéro de cycle et verdict. La fiche Agent contient
l'identité, la personnalité et la fiche de poste, mais jamais les clés, tokens, mots de passe,
configuration Hermès ou autres secrets techniques. Le Goal contient sa description et son suivi
canonique. Chaque cycle contient son compte rendu, les preuves, le verdict et le résultat de sa
Task, y compris lorsque cette Task a ensuite été historisée. Pour qu'un Goal possédant des milliers
de cycles ne provoque jamais un chargement non borné, seules les 100 projections de cycles les plus
récentes sont conservées. La fenêtre est calculée par `sequence`; lorsqu'elle avance, la projection
sortante est oubliée et son `goal_cycles.memory_item_id` redevient nul.

Une seconde projection, volontairement plus petite, représente chaque expéditeur humain observé
par Messenger sous la forme d'une mémoire `social`. Son adresse est exactement
`(messaging_id, user_id)` : code canonique du bridge et identifiant natif sensible à la casse.
`owner_agent_id` isole la fiche privée, sans devenir une propriété de l'humain. La clé de source est
le SHA-256 d'un JSON canonique versionné contenant ces trois valeurs ; elle n'expose donc pas
l'identifiant natif dans la contrainte ou les erreurs techniques. Le contenu ne conserve que le
nom affiché, la messagerie et l'identifiant, jamais la connexion, la room ou le texte d'un message.
Un nom non vide nouveau révise la même fiche; un nom vide ne remplace jamais un nom déjà connu.
Une observation identique ne crée aucune révision.

`memory.project_process` projette sans LLM chaque `ProcessDefinition` affectée en mémoire
procédurale et la sortie de chaque `ProcessRun` réussi en mémoire épisodique privée. L'entrée,
le snapshot brut, les tokens et callbacks ne sont jamais copiés. La sortie repasse par le
sanitizer récursif Process, puis est bornée à 12 000 caractères. Un résultat est relié à sa
définition par `result_of`; seules les 20 dernières réussites par agent et processus sont
conservées. Une suppression ou une sortie de fenêtre oublie la projection, pas la source
canonique.

Une projection porte `source_managed=true`, reste privée, en lecture seule et sans grant. Ni un
agent, ni un administrateur, ni l'IHM ne peut la modifier, la partager, la relier
manuellement ou l'oublier. Une modification de la source inscrit un job durable qui recalcule la
page et crée une révision seulement si son contenu ou ses métadonnées ont changé. La suppression de
la source appelle le chemin interne d'oubli. La reconstruction réconcilie également les projections
orphelines si cet événement n'a pas pu être traité. Les cycles sont reliés à leur Goal par
`cycle_of`.

Les UUID logiques sont stockés dans `agents.memory_item_id`, `goals.memory_item_id` et
`goal_cycles.memory_item_id`. L'identité déterministe `(managed_source_kind, managed_source_ref)`
permet de rattacher un item existant si ce pointeur manque, sans créer de doublon. La synchronisation
du dataset remplit les liens manquants et le worker les réconcilie au démarrage. Les contacts n'ajoutent pas de
colonne source : leur identité source déterministe les rattache directement, et le journal
Messenger sert au rejeu. La procédure explicite est :

```bash
make rebuild-source-memory                         # UUID manquants seulement
make rebuild-source-memory ARGS='--all'            # rafraîchir toutes les projections
make rebuild-source-memory ARGS='--recreate --provider native'
                                                    # recréer avec un fournisseur choisi
make rebuild-messenger-contacts                     # rejouer les expéditeurs humains
make rebuild-memory-index                           # index sémantique manquant
make rebuild-memory-index ARGS='--all'              # recalcul complet en arrière-plan
make rebuild-memory-links                           # liens déterministes depuis leurs sources
```

`rebuild-memory-links` refuse de créer une arête tant qu'une Task ou session Voice portant déjà une
provenance mémoire n'a pas de dossier thématique. Il remet en attente les classifications épuisées,
puis doit être relancé lorsque Dream a terminé cette phase. Après cette barrière globale, il
reconstruit les arêtes `cycle_of`, `result_of`, `topic_contains`, `contact_contains` et
`topic_involves_contact` depuis les Goals, Process, Tasks, sessions Voice, Topics et scopes
Topic/contact canoniques. Les liens saisis manuellement et les relations issues d'une décision de
consolidation ne sont pas déductibles de ces sources et ne peuvent pas être recréés après une
suppression SQL intégrale.

Les tools MCP de Goal restent nécessaires aux lectures exactes, commandes, états courants et
contrôles d'appartenance. La mémoire est une projection de rappel et de recherche, pas une API
transactionnelle de remplacement.

Les messages Messenger, connexions, rooms, identifiants d'authentification, configurations de
LLM/outils et diagnostics Lab ne sont jamais projetés automatiquement. La fiche sociale minimale
des expéditeurs humains ne contient aucun texte de conversation. Les Tasks et tours Voice
transcrits terminaux sont examinés progressivement par Dream. Process constitue l'autre exception
bornée et déterministe décrite ci-dessus.

## Stockage et oubli

`MemoryItem.id` est l'identité logique stable. Chaque révision pointe vers un couple
`(provider_code, resource_id)` opaque. Le provider `native` écrit atomiquement dans le répertoire
fixe `/data/memory` ; la base ne déduit jamais un chemin de `resource_id`.

Il n'existe plus d'archive produit. L'oubli supprime toutes les ressources, projections
vectorielles et traces liées, puis seul un tombstone sans contenu demeure. Un oubli explicite
conserve dans le journal d'acquisition une empreinte irréversible du contenu et sa source : la
même information ne peut pas être réapprise automatiquement depuis cette source, tandis qu'une
correction différente reste admissible.

La maintenance légère ne supprime plus un souvenir selon son inactivité. `app.memory` possède les
politiques et les `MemoryFinding` de type `duplicate`, `contradiction` ou `aging`; le mécanisme
`memory.maintain_findings` les détecte et les traite séquentiellement dans Dream pendant
l'inactivité. Memory pilote, Dream exécute. Chaque politique possède les modes `off`, `manual` et
`automatic`; l'automatique appelle exactement le même service que l'action manuelle de l'IHM.
Ce mécanisme n'utilise aucun LLM génératif et reste exclu des jauges Dream. Les doublons lisent
l'index d'embeddings courant et appliquent le même
`MEMORY_DUPLICATE_SIMILARITY_THRESHOLD` que l'acquisition et le rappel. Les contradictions exigent
en plus un marqueur textuel explicable.

Un vieillissement appliqué renseigne `old_at`/`old_reason`. Il ne supprime pas l'item et ne le
retire pas du RAG. La date de référence est la dernière modification significative, jamais
`last_accessed_at`, afin qu'une recherche ne rajeunisse pas elle-même les souvenirs rappelés.
Une modification significative ou une nouvelle provenance efface ce marquage.

`GET /memory/retention/preview?days=<n>` compte en lecture seule les expirations et inactivités,
par type et date la plus ancienne. Cette prévisualisation n'active aucune suppression et ne
modifie jamais `activity_at`; la valeur livrée de la politique reste donc `0` tant qu'un opérateur
n'a pas choisi une durée à partir des données observées.

Une mémoire issue d'une source ne suit pas ces commandes publiques. Pour Agent, Goal et GoalCycle,
sa suppression est déclenchée exclusivement par la suppression de la donnée canonique. Une fiche
de contact persiste même si sa connexion est supprimée, puisque cette route ne participe pas à
l'identité humaine. Lors d'un changement de fournisseur, la procédure `--recreate` oublie les
anciennes ressources, libère leur identité de source, crée de nouveaux items puis remet leurs UUID
dans les tables canoniques.

## Surfaces

- Façade Python et services : `search_memory(texte, agent_id=..., **options)` depuis `app.memory`
  renvoie une simple liste classée de `MemorySearchItem`, sans scores; `back/app/memory/` contient
  le moteur détaillé.
- API d'administration : `/api/memory` avec RBAC `MEMORY_ACCESS`,
  `MEMORY_EDIT` et `MEMORY_ADMIN`; `/memory/search` renvoie la liste classée sans score et
  `/memory/browse` porte la consultation lexicale paginée. Les options absentes de
  `/memory/search` viennent des Params courants; `/memory/recall` reste un alias déprécié.
  `/memory/metrics` expose le miroir local sans contenu des
  compteurs/histogrammes, `/memory/retention/preview` estime une politique avant activation et
  `/memory/duplicates/preview` liste sans mutation les paires ordinaires au-dessus du seuil global
  de fusion cosinus, éventuellement pour un agent, et retourne cette valeur dans sa réponse.
  `/memory/findings` expose les détections persistantes et
  ses actions `apply`/`dismiss` avec les mêmes contrôles de révision que le mode automatique.
- MCP agent : façade `file_search`, `file_info`, `file_read`, `file_create`, `file_write`,
  `file_append`, `file_edit` sur `memory://` et `document://`; commandes métier
  `memory_remember`, `memory_forget`, `memory_summarize` et `document_share`.
- Interface : sous `/memory`, l’onglet **Liste** conserve la recherche, le propriétaire, le
  contenu, les révisions, la provenance, les accès directs et les liens. L’onglet **Graphe**
  charge un sous-graphe léger par curseurs, puis les voisins à la demande ; il ne charge jamais
  tout le corpus ni les payloads en mémoire. L'agent sélectionné détermine déjà le périmètre ACL et
  reste donc implicite : sa projection n'est pas affichée. Un Topic public n'entre dans ce graphe
  que s'il contient un souvenir possédé par l'agent ou un item qui lui est directement partagé ;
  les dossiers des autres agents ne sont pas affichés par le seul effet de leur visibilité publique.
  Les Topics, contacts et documents sont
  exposés avec un rôle visuel propre ; les relations Topic–mémoire/document, Contact–mémoire et
  Contact–Topic sont renforcées, tandis que les suggestions restent fines et discontinues. La
  récence combine dernier accès et dernière modification dans une colonne calculée indexée. Les
  réglages restent sous **Préférences → Mémoire**. L’interface sert à auditer, corriger ou oublier,
  pas à accepter ou rejeter des acquisitions.

Les métriques Logfire et le miroir local mesurent le nombre, le mode, la dégradation, la latence,
le nombre de résultats et les caractères réellement injectés. Les labels sont bornés et ne
contiennent jamais requête, texte, UUID de mémoire, salon ou interlocuteur.
