# ADR 0010 — Mémoire agentique gouvernée et commune aux drivers

- Statut : Accepted

> La sélection du modèle vectoriel décrite ici est remplacée par la
> [décision 0039](0039-exclusive-llm-profiles-and-agent-voice.md).
> Le résumé indépendant et sa contribution au classement sont supprimés par la
> [décision 0089](0089-memory-content-without-summary.md).
- Date : 2026-07-21
- Révisé : 2026-08-23

## Contexte

Galaris possédait un RAG documentaire, les historiques propres aux runtimes et le journal de
`app.messenger`, mais aucune mémoire durable commune aux agents. Hermès offre en outre une mémoire
de session et un `MemoryProvider` natif. L'utiliser comme autorité aurait rendu la continuité et les
connaissances dépendantes d'un driver, tandis qu'une injection différente pour le harnais interne
aurait produit deux comportements impossibles à comparer.

La mémoire doit rester disponible sans modèle ni embeddings sur le chemin critique, appliquer les
droits avant le classement, conserver sa provenance et permettre un oubli physique. Elle doit aussi
accepter des ressources autres que du texte sans imposer leur emplacement aux consommateurs.
Enfin, les interlocuteurs ordinaires arrivent par Messenger et n'ont généralement aucun accès à
l'interface Galaris. Une file de validation humaine y serait donc sans responsable légitime et
laisserait la mémoire dépendre d'une action qui ne peut pas avoir lieu.

Une première implémentation ajoutait des espaces personnels, partagés et globaux par-dessus le
propriétaire, la visibilité et les grants de chaque souvenir. Cette double hiérarchie rendait les
droits incompréhensibles, masquait le propriétaire réel et exposait une administration que les
outils agents n'utilisaient pas. Elle supposait en outre qu'un agent penserait spontanément à
choisir une portée ou des membres, alors qu'aucun contrat agentique ne le garantissait.

## Décision

`app.memory` est la façade métier unique. PostgreSQL conserve l'identité logique stable, le
propriétaire, les accès directs, les révisions, sources, liens, usages, le journal d'acquisition et
les travaux automatiques. Le contenu est confié à un petit contrat `ResourceStorage` dont le
`resource_id` est opaque. Le provider natif écrit atomiquement sous `/data/memory`; d'autres
providers pourront être enregistrés sans modifier la façade.

Il n'existe aucun `MemorySpace`, aucune adhésion à un espace et aucun `space_id`. Chaque souvenir
porte directement son `owner_agent_id`. Son propriétaire y accède toujours; un autre agent ne peut
le lire ou l'écrire que par un grant explicite sur ce souvenir, ou le lire si sa visibilité est
publique. Une acquisition automatique crée une mémoire privée. Le partage est donc une décision
explicite et localisée, jamais un comportement attendu spontanément d'un agent ni un effet de bord
sur toutes les mémoires d'un groupe.

Le chemin quotidien utilise le full-text search PostgreSQL avec pondération du titre, des
mots-clés et du contenu. Les ACL et dates de validité sont filtrées dans la
requête avant le ranking. Avant une exécution, un provider de contexte commun construit un
`MemoryBrief` déterministe : les mémoires `core` accessibles sont prioritaires, puis viennent les
résultats hybrides pertinents, dans des limites d'items et de caractères configurables. Une panne
du modèle vectoriel ou de son index replie ce rappel vers le lexical et reste fail-open.

La graine lexicale du brief est courte et déterministe : titre structuré du Goal, sinon libellé de
la Task sans suffixe de cycle, sinon extrait borné de l'objectif. L'objectif complet n'est jamais
transmis à `websearch_to_tsquery`, car ses termes formeraient une conjonction trop restrictive sur
les longues Tasks. Il est en revanche transmis, avec le libellé, à l'embedding de recherche dans
une limite de caractères configurable afin d'élargir le spectre sémantique sans détériorer la
branche lexicale. Le provider ajoute également une politique système commune : évaluer la
pertinence de la mémoire est obligatoire pour les travaux `high`, récurrents ou longs, tandis
qu'une recherche explicite reste conditionnelle à son impact matériel et à l'insuffisance du
brief.

Le rappel borné utilise une stratégie hybride unique. Elle conserve la branche lexicale, calcule
l'embedding de la requête avec l’usage Vectoriel du profil courant, effectue une
recherche cosinus exacte sur les chunks accessibles, puis rassemble les candidats des deux voies.
Il ne remplace donc jamais le FTS par une recherche vectorielle isolée.
Aucun contrat HTTP, Python, MCP ou `memory://` ne permet de forcer le chemin lexical local. Le
résultat indique le mode réellement utilisé et toute dégradation; absence de modèle, index vide,
timeout ou erreur du provider retombent automatiquement sur le résultat lexical. Cette surface
bornée est distincte de la liste d'administration paginée, qui reste lexicale. Le brief automatique
utilise le même hybride borné.

Le classement exploite aussi le graphe au lieu de le limiter à la visualisation. Après les rangs
lexicaux et vectoriels, il développe un seul saut par les liens confirmés de confiance au moins
`0,75`; leur contribution est pondérée puis modulée par leur confiance. Cette expansion réapplique
les ACL et le scope conversationnel. Le classement final `memory-weighted-diverse/v3` normalise et
combine pertinence sémantique, pertinence lexicale, voisinage graphique, nombre de provenances,
fraîcheur et centralité des liens accessibles. La centralité intègre aussi les associations de
co-usage apprises. Une sélection diversifiée pénalise la redondance et retire les quasi-doublons,
afin qu'un même fait paraphrasé trois fois n'occupe qu'une place. Chaque poids, la taille du vivier,
la longueur sémantique et la pénalité de diversité proviennent exclusivement des Params globaux de
la section Mémoire et ne sont pas surchargeables à l'appel. Le seuil de doublon est l'unique
`MEMORY_DUPLICATE_SIMILARITY_THRESHOLD`; il n'est jamais surchargeable par appel. La limite de
résultat vaut huit par défaut.

L'identité d'un interlocuteur est une barrière stricte portée
par la fiche contact canonique : les souvenirs de Jacques sont exclus du rappel de Paul même si
leur vecteur est très proche ou si une arête les relie. Le brief et le tool Memory reçoivent ce
scope depuis la Task ou le tour côté serveur, sans le confier au texte de la requête ni au modèle.
Les écritures effectuées dans ce contexte sont scellées au même UUID de contact avant de devenir
visibles au rappel et ne sont jamais dédupliquées avec le souvenir d'un autre interlocuteur.

L'observabilité distingue les présentations automatiques (`context`), les résultats d'une
recherche agentique (`search`) et les lectures complètes (`read`). Le résultat de Task expose le
nombre, la requête bornée, la troncature et les UUID du brief, mais jamais son contenu. Les appels
MCP restent des étapes séparées dans la trace. Des métriques Logfire et un endpoint diagnostique
local mesurent mode, dégradation, latence, résultats et taille du contexte avec des labels bornés,
sans requête, contenu, UUID ni identité conversationnelle.

Les embeddings de documents sont une projection reconstruisible appartenant à `app.memory`, pas
au RAG historique. Chaque chunk porte l'empreinte des champs sémantiques, la version du modèle et
sa dimension. Une écriture mémoire ne contacte jamais le provider : elle inscrit un job durable,
qui calcule les chunks hors transaction puis remplace atomiquement l'ancienne projection.
Sélectionner l’usage Vectoriel du profil courant constitue l'opt-in opérateur à transmettre ces chunks à ce provider;
le laisser vide maintient une mémoire exclusivement locale et lexicale.
L'empreinte courante est jointe dans la requête vectorielle, ce qui exclut immédiatement un index
devenu obsolète. Le démarrage, `make sync-db`, un changement du modèle Vectoriel courant et
`make rebuild-memory-index` réconcilient les projections manquantes. La recherche exacte est
retenue initialement afin de préserver le rappel sous filtres ACL; un index approximatif ne sera
ajouté qu'après mesure sur une volumétrie qui le justifie.

La continuité conversationnelle appartient à `app.messenger`. Elle est reconstruite depuis son
journal par `(connection_id, room_id)`, bornée en messages et caractères, et n'ajoute aucun second
modèle de session. Si le journal contient des messages, les caches d'un runtime ne sont pas
fusionnés avec lui ; ils servent seulement de repli lorsque le journal est vide.

`app.agent` assemble ces contributions avant la sélection du driver et expose des observers de
résultat terminal. Le harnais interne traduit la session canonique en historique natif Pydantic AI.
Le bridge Hermès projette un plugin `MemoryProvider` qui récupère exactement le brief déjà classé
pour la Task active. Il n'effectue ni second ranking ni seconde injection. Les opérations complètes
restent les tools MCP `memory_*`. La mémoire fichier native et son tool sont désactivés par défaut
afin que Galaris soit l'unique autorité durable. Le YAML global `hermes.default.config`, puis celui
de l'agent, peuvent réactiver explicitement ce mécanisme pour un besoin de compatibilité ; dans ce
cas seulement, une écriture native devient une acquisition gouvernée appliquée immédiatement.

L'acquisition depuis les Tasks n'est plus inscrite sur leur chemin terminal. Le mécanisme
opportuniste `app.dream` parcourt progressivement les Tasks racines réussies, rattachées à un
agent et à un topic, hors Goal, Voice et refus explicite de capture. Les enfants de plan, erreurs
et résultats déjà couverts par une source métier spécialisée ne sont pas des sources ordinaires.
Un témoin versionné est conservé même lorsqu'aucun souvenir n'est extrait.
Son petit modèle dédié utilise une sortie structurée promptée, sans outil, driver ni MCP. Chaque
fait proposé, qu'il vienne de Dream, d'un tool ou de la création manuelle dans l'interface, est
vérifié contre les mémoires ordinaires du même propriétaire et de la même portée.
Le serveur applique l'unique `MEMORY_DUPLICATE_SIMILARITY_THRESHOLD` : sous le seuil il crée le
souvenir; au seuil ou au-dessus il conserve l'UUID existant et lie la nouvelle provenance. Les
faits sociaux ne franchissent jamais la frontière du contact exact. La décision puis son effet
réel `CREATE` ou `LINK` sont checkpointés avant l'application idempotente par la façade gouvernée.

La fusion conserve l'UUID, le contenu et la révision existants, ajoute seulement la provenance de
la nouvelle source et n'est pas comptée comme une création. Des propositions d'une même source
peuvent cibler une proposition antérieure, ce qui évite aussi les paraphrases produites dans un
seul lot. La sélection est fondée sur l'utilité future, pas sur la taille de la source : chaque
proposition doit porter un motif de rétention fermé et une utilité élevée, tous deux contrôlés par
le serveur. Les faits publics de dossier ou de recherche, résumés de livrable et détails ponctuels
sont rejetés. En l'absence d'index vectoriel, la capture reste fail-open pour la déduplication mais
conserve ce filtre d'utilité. `MEMORY_CAPTURE_ENABLED` gouverne les extractions Task et Voice sans
arrêter les projections et entretiens Dream non génératifs.

La provenance `MemorySource` constitue aussi l'association n↔n canonique avec les activités qui
peuvent produire un souvenir. Elle conserve son vocabulaire ouvert `source_kind + source_ref`, mais
porte des FKs typées vers la Task, le round conversationnel texte ou le tour vocal lorsqu'une telle
source existe. Une fusion, une mise à jour ou une déduplication exacte ajoute la nouvelle
association à l'UUID retenu. Les écritures courantes renseignent directement la FK typée lorsqu’une
source canonique existe ; une source disparue reste une provenance textuelle sans inventer de cible.

Les écritures explicites `memory_remember` et `memory_summarize` restent immédiatement appliquées.
Les relations structurelles certaines sont des projections de `MemorySource`, des Topics, des
contacts, des Goals et des Process. `app.memory.link_reconciliation` les reconstruit globalement ou
autour d'un nœud, sans LLM, et ne possède jamais un lien explicite. Le scope Topic/contact
autoritatif produit aussi une arête directe `topic_involves_contact`. Dans la visualisation,
l'agent sélectionné reste implicite puisqu'il borne déjà le graphe par ses ACL ; sa projection
n'est donc ni un nœud ni une source d'arêtes affichées. L'ancien graphe de Tasks et de rooms n'est
plus produit.

Toute acquisition admissible est appliquée immédiatement. Le journal d'acquisition durable sert à
l'idempotence, à l'audit et à la reprise après interruption, jamais à une validation humaine. Une
décision `create`, `update`, `link` ou `contradict` produit immédiatement l'item, la révision ou le
lien correspondant; une décision `skip` ou un contenu interdit est rejeté automatiquement. Aucun
endpoint ni écran d'acceptation/rejet n'est exposé. L'interface permet seulement de consulter,
corriger et oublier. Les secrets détectables sont rejetés ou expurgés avant l'entrée en
mémoire. Les mises à jour utilisent une révision attendue, et l'oubli efface toutes les ressources,
révisions, sources, ACL, liens et traces d'usage en ne gardant qu'un tombstone sans contenu.
La route d'administration `GET /memory/duplicates/preview` expose uniquement une prévisualisation
bornée des paires vectoriellement proches ; elle ne fusionne ni ne supprime les souvenirs
historiques.

Les données métier déjà structurées ne deviennent pas une seconde autorité dans Memory. Galaris
projette `Agent`, `Goal` et `GoalCycle` en Markdown déterministe : profil professionnel
sans secret, description et suivi du Goal, puis compte rendu et résultat de chaque cycle. Les UUID
des `MemoryItem` sont conservés directement sur les trois lignes sources. Chaque item porte aussi
une identité de source unique, afin qu'une reconstruction rattache un item existant lorsqu'un UUID
manque au lieu de le dupliquer.

Ces items sont `source_managed`, privés et en lecture seule. Cette protection ne dépend ni du rôle
administrateur ni de l'IHM : les opérations publiques de modification, oubli, grant,
ajout de source et création de lien les refusent. Seul l'adapter interne de projection peut créer
une révision ou les oublier à la suppression de la source. Pour maîtriser une volumétrie de cycles
potentiellement illimitée, `GoalCycle` constitue l'unique exception de rétention : seules ses 100
projections les plus récentes par Goal sont conservées, sans supprimer les lignes métier. Un
observer fail-open inscrit les
recalculs dans le worker durable ; `make sync-db`, la réconciliation de démarrage et la commande
`make rebuild-source-memory` réparent les sources sans UUID. L'option `--recreate --provider`
permet de repeupler un autre `ResourceStorage` à partir des données canoniques.

Une exception sociale minimale s'applique aux expéditeurs humains effectivement observés par
Messenger. Chaque agent reçoit une fiche `social`, privée, source-managed et en lecture seule,
identifiée par le condensat versionné de `(owner_agent_id, messaging_id, user_id)`.
`messaging_id` est le code canonique du bridge et `user_id` reste l'identifiant natif exact ; la
connexion, la room et le message ne participent ni à la clé ni au contenu. Un nouveau nom affiché
révise la fiche, tandis qu'une observation identique ou un nom vide après un nom connu ne la
modifie pas. Messenger appelle la façade Memory après résolution de l'identité IA et avant les
interactions, avec un repli fail-open. Son journal permet un backfill idempotent sans nouvelle
table ni colonne. Aucune fusion cross-canal ou extraction du texte des conversations n'est
effectuée.

Les documents de travail deviennent une seconde nature de `MemoryItem`, orthogonale aux types
cognitifs : `node_kind=document` avec `memory_type=working`. Ils conservent le modèle de
propriétaire, grants, ressources opaques, révisions, recherche et graphe existant, sans créer
d'espace documentaire ni d'ACL parallèle. Ils sont privés, mutables, non dédupliqués, exclus de
l'acquisition automatique et de la rétention par inactivité. Seul le propriétaire peut les
oublier ou gérer leurs grants ; un collaborateur `edit` peut créer une nouvelle révision.

La surface agentique est volontairement réduite à créer, lire un passage borné, remplacer un texte
exact unique, ajouter du contenu et régler l'accès d'un agent à `read`, `edit` ou `none`.
La façade Python publique `search_memory(texte, agent_id=..., **options)`, l'API
`POST /memory/search`, la page Mémoire et les recherches agentiques renvoient une liste déjà
classée sans exposer les scores internes. La consultation exhaustive reste distincte sous
`POST /memory/browse`; `memory_forget` reste la
suppression explicite. Les
conflits, snapshots, indexation et révisions attendues sont gérés côté serveur. Le prompt commun et
le skill Galaris demandent de rechercher un document existant, de le partager avant `task_run` et
de transmettre son UUID à l'agent délégué.

La projection ne remplace pas les tools MCP des domaines sources. En particulier, les tools Goal
restent la surface exacte et transactionnelle pour lire un état courant ou exécuter une commande;
Memory sert au rappel transversal. Les projections déterministes de Goal restent l'autorité
structurée de leurs cycles ; le mécanisme Dream peut néanmoins examiner leur Task et ne doit
produire un souvenir que si son contrat de durabilité le justifie. Les messages, credentials,
configurations de runtime, LLM ou outils et diagnostics spécialisés ne sont pas projetés. Les
contacts Messenger humains constituent l'exception bornée décrite ci-dessus. Une seconde exception
déterministe projette les définitions Process affectées et uniquement les sorties réussies,
assainies et bornées. Ces items restent privés et source-managed, avec une fenêtre de 20 résultats
par agent et processus; les entrées, snapshots bruts et erreurs ne sont jamais projetés.

## Conséquences

- Le comportement de rappel et la mémoire de session sont identiques quel que soit le driver.
- Une Task, un Goal, le planner et les drivers restent fonctionnels si Memory est désactivée ou en
  panne.
- PostgreSQL et le volume mémoire natif doivent être sauvegardés de façon cohérente.
- Le RAG historique et son chemin d'import ont été retirés après l'import de ses documents ;
  `app.memory` est l'unique façade de mémoire.
- Aucune acquisition ne dépend de la présence d'un humain dans Galaris. Les erreurs et refus restent
  observables dans les traces techniques, tandis que les corrections passent par les opérations
  normales de mémoire.
- La suppression des espaces retire une couche d'ACL et les tables associées sans supprimer les
  souvenirs existants; leur propriétaire demeure l'autorité par défaut.
- Le partage inter-agent des souvenirs ordinaires reste administratif. Celui des documents de
  travail est agentique mais explicite, local au document, révisionné et limité au propriétaire ;
  aucune appartenance implicite à un groupe ou un espace n'est introduite.
- Les profils Agent et les suivis Goal deviennent retrouvables par les drivers sans changer la
  persistance ni les commandes de leurs domaines sources.
- Les expéditeurs humains observés deviennent retrouvables dans la mémoire privée de l'agent sans
  introduire de carnet d'adresses, de route préférée ou de rapprochement d'identités.
- Le contenu projeté est volontairement dupliqué dans le fournisseur mémoire, mais jamais saisi
  deux fois : il est régénérable, versionné et supprimé avec sa source, ou lorsqu'un cycle sort de
  la fenêtre de projection bornée.
- Un changement de fournisseur mémoire ne nécessite pas d'export propriétaire ; les projections
  sont repeuplées depuis PostgreSQL et reçoivent de nouveaux UUID si la recréation le demande.
- Obsidian, AFFiNE, la compaction de session et la maintenance avancée restent des extensions
  optionnelles, pas des dépendances du rappel courant.

## Preuves dans le code

`back/app/memory/`, `back/app/agent/context.py`, `back/app/agent/observers.py`,
`back/app/messenger/session.py`, `back/app/messenger/contact_memory.py`,
`back/app/harness/executor.py`,
`back/bridge/hermes/default-agent/data/plugins/memory/galaris/`, `front/app/memory/` et leurs tests.
