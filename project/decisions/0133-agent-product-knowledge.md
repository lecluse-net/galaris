# 0133 — Connaissance du produit attribuable aux agents

Statut : accepté. Date : 2026-09-25.

## Garantie

Tout agent autorisé peut découvrir, rechercher et lire la documentation de sa version de
Galaris, sans devenir un agent spécialisé ni recevoir implicitement une autre mission.
La capacité documentaire peut être utilisée avec les inspections administratives désactivées.

## Décision

`galaris_admin` expose `documentation_catalog` et `documentation_search`. L'autorisation
effective du catalogue porte le droit documentaire, y compris les URI directes. La recherche
exige en plus sa propre autorisation. Chaque opération revalide les droits ; l'index n'accorde
jamais d'accès. Les autorisations existantes des inspections sont conservées.

Le module `app.documentation` possède le corpus et une projection PostgreSQL/pgvector
reconstructible. Il ne dépend d'aucun autre domaine. Les adaptateurs `app.tools` et
`app.file_share` vérifient les droits avant d'appeler sa façade. `app.tools` compose l'accès au
modèle vectoriel par la façade LLM publique, sans introduire de cycle documentaire.

Les sources `docs/`, `project/decisions/` et `project/plans/` sont embarquées par des contextes
de build explicites. Leur liste, leurs empreintes et la version de build forment un manifeste
calculé au chargement. Seuls les passages du corpus courant sont éligibles, même si la base
contient des projections anciennes. Les sources restent natives, bornées, en lecture seule et
distinctes des documents éditoriaux et de la mémoire des agents.

La recherche combine plein texte, correspondances exactes et embeddings. Les embeddings sont
mutualisés par empreinte de passage et identité du modèle. Un job périodique travaille par lots ;
une couverture incomplète ou une panne sémantique n'empêche pas la lecture ni la recherche
textuelle. Les lignes retirées sont éliminées après une période de grâce de sept jours.

L'indexation valide les nouveaux passages textuels dans une transaction courte avant
d'appeler le fournisseur : une recherche concurrente ne doit pas attendre les embeddings
sur un conflit d'insertion. Le verrou transactionnel PostgreSQL reste limité à l'indexation
de fond entre workers ; il conserve une connexion pendant cet appel, sans verrou d'écriture
sur les passages. Aucun verrou ou quota global n'est ajouté aux appels LLM ou aux recherches.
Les lots contiennent au plus huit passages ; le fournisseur dispose de 60 secondes, dans
un job limité à 90 secondes. Les erreurs d'embeddings déclenchent un avertissement et une
échéance de reprise progressive de 60 à 600 secondes, locale au processus, sans attente
active ni transaction ouverte pendant ce délai. Un succès réinitialise cette échéance ;
un redémarrage la réinitialise également. Les erreurs inattendues et annulations continuent
à remonter au scheduler. Les lots déjà validés, les droits vivants et le repli textuel
restent les garanties à préserver.

Le skill système `galaris-knowledge` fournit le modèle conceptuel et la méthode d'assistance.
Les règles d'attribution de skills restent applicables, complétées par le droit documentaire.
Les instructions déjà chargées ne sont pas effacées rétroactivement ; les outils restent
soumis à leur contrôle vivant. La connaissance du produit ne prouve pas les droits humains
ni la configuration effective d'une installation.

Le chargement dépend d'une configuration de compétence, jamais de l'identité de l'agent.
Un fichier facultatif `runtime.yaml` contenant `loading: eager` demande au harnais interne
de charger une compétence effectivement attribuée dès la première requête en Task,
conversation texte et voix par tours. Sans ce fichier, avec `loading: deferred`, ou avec
une configuration invalide, les Tasks conservent le chargement à la demande et les
conversations ne chargent pas cette compétence par ce mécanisme. Le fichier ne modifie
aucune autorisation ni connexion. Il est borné à 4096 octets et accepte uniquement `loading`.

`galaris-knowledge` fournit cette configuration ; son défaut global reste désactivé et son
attribution exige toujours le droit documentaire. La proposition Galaris reçoit cette
attribution à sa création ; tout autre agent explicitement autorisé peut en bénéficier.
Les autres compétences conservent leur défaut. Les harnais externes ne sont pas modifiés.
Les tests du SDK vérifient la présence du guide dès la première requête, ceux des contrôleurs
sa transmission, et les tests DB l'indépendance de l'identité et les révocations. Des compétences
synthétiques couvrent les configurations absentes, valides et invalides. Ces preuves ne
mesurent pas la justesse sémantique d'un modèle réel.

La connaissance de l’interface s’appuie sur un guide de parcours FR/EN et une carte de menus
générée depuis les modules frontend actifs, leurs traductions et leur fusion réelle.
`make project-context` et son contrôle de fraîcheur couvrent cette carte. Les conditions
dynamiques ne sont pas exécutées pendant la génération : les droits, menus et identifiants
propres à une session ou à un catalogue serveur ne peuvent pas être déduits de la doc.
Le catalogue documentaire expose ces sources comme points d’entrée du guidage utilisateur.

## Validation

`make docs-update` orchestre en développement la génération, les contrôles documentaires,
la comparaison du corpus source avec le conteneur actif et la synchronisation de l’index
textuel. `docs-prepare` prépare les sources sans instance active ; `docs-check` ne les modifie pas.
`make update` depuis les sources lance automatiquement `docs-prepare` avant le build :
une carte périmée est régénérée sans exiger une commande manuelle préalable.
Les mises à jour depuis les sources ou depuis un paquet d’images qualifié synchronisent
l’index textuel puis contrôlent le résultat dans le backend démarré avant de signaler leur
réussite. Les paquets qualifiés conservent leurs sources documentaires embarquées immuables.
La comparaison utilise
une empreinte du contenu indépendante du libellé de build ; les paquets se comparent à
l’image candidate exacte, pas au worktree local. Un corpus absent, incomplet ou différent,
ou un échec de recherche/lecture, fait échouer ce contrôle. Il n’accorde aucun droit aux agents
et ne dépend pas d’un fournisseur d’embeddings. Les tests des images incluent le même contrôle.
La rédaction des guides, la qualité des traductions et une éventuelle restauration après
échec de déploiement restent des opérations explicites.

Les scénarios synthétiques couvrent recherche en langue naturelle, identifiants exacts,
provenance, distinction des plans, exclusions du corpus, remplacement des sources, indexation
incrémentale, changement de modèle, lecture paginée et révocation par connexion ou fonction.
Les tests de montage MCP vérifient l'accès documentaire avec les inspections désactivées.
