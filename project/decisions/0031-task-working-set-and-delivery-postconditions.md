# ADR 0031 — Working Set de Task et postconditions de livraison

- Statut : Accepted
- Date : 2026-08-10

## Contexte

Une exécution planifiée peut produire successivement un document mémoire, un fichier chez un provider
et une livraison Messenger. Jusqu'ici, chaque étape ne recevait que le texte des étapes précédentes
et devait redécouvrir les ressources. Des sous-tâches ont ainsi recréé plusieurs brouillons de même
nom, travaillé sur un fichier différent du document demandé, écrasé le fichier final par un
placeholder, puis terminé le plan sans preuve que le livrable avait été remis. Une reprise
conversationnelle pouvait en plus perdre son historique lorsqu'elle recevait l'UUID local d'une
room mais le comparait seulement à l'identifiant externe du message.

## Décision

`app.task` possède un Working Set versionné stocké dans les données de la Task racine. Il contient
des références typées et bornées, jamais leur contenu : rôle, type, référence, révision, état,
producteur et métadonnées techniques. Toutes les feuilles du plan lisent et mettent à jour ce même
registre. Une nouvelle référence pour un rôle conserve la précédente comme `superseded`.

Les effets réussis des outils natifs sont projetés dans le Working Set après leur exécution. Le
rôle `primary_working_document` est unique et revient au premier document créé ; les documents
suivants reçoivent des rôles de référence distincts. Les
fichiers produits, artefacts finaux, destinations et reçus de livraison ont des entrées distinctes.
Les erreurs métier remontent comme erreurs d'outil et ne sont jamais interprétées comme des succès.

Le planner applique les postconditions globales uniquement à la Task racine avant `SUCCESS` :
présence du document demandé, artefact pour tout fichier produit et reçu pour une origine
Messenger. Les groupes internes du plan partagent ce Working Set mais ne possèdent pas ce contrat
global ; leurs permissions locales `artifact_policy` et `delivery_policy` restent seules
applicables afin qu'un artefact intermédiaire ne soit pas pris à tort pour un livrable final. Une
exécution directe qui produit un fichier applique la même exigence d'artefact. Les sous-tâches
peuvent livrer explicitement un
fichier, mais leur résultat textuel n'est pas envoyé automatiquement ; cette responsabilité reste
à la racine. Chaque feuille reçoit une politique d'artefact et de livraison dérivée de sa liste
d'outils ; un artefact intermédiaire ne peut donc pas accéder aux outils d'envoi. Une livraison
Messenger copie le fichier et conserve l’URI source active selon la rétention de son provider.
Le runtime interrompt aussi trois succès identiques sans progression, puis accorde une unique
finalisation sans outils et limitée à une requête afin de restituer honnêtement le travail déjà
accompli. Un scope contenant un outil d'écriture inclut ses outils de lecture et d'inspection
nécessaires à la vérification.

Pour une Task possédée par un `ConversationTaskLink`, la remise dans le salon d'origine est une
postcondition du contrôleur de conversation, pas du modèle. Après le succès terminal, le contrôleur
repère dans le texte les ressources produites du Working Set et les URI explicitement présentées,
vérifie leur existence et leurs droits par `app.file_share`, puis en attache une copie bornée au
salon exact. Un nom relatif tel que `index.html` est résolu uniquement vers
`console://index.html`, et seulement lorsque la console est active et que le fichier existe. Il
n’existe aucun second stockage local implicite. Les URI techniques sont remplacées par le nom de
la pièce jointe après une copie réussie. Un reçu lié à la connexion,
au salon et à la source rend cette projection idempotente. Une livraison explicite vers un autre
destinataire ne satisfait pas ce reçu. Le planner et le garde d'exécution exigent toujours une
preuve de production, mais n'exigent plus que le modèle appelle Messenger pour ce dernier kilomètre.

Le serveur dérive en plus de l'objectif initial un contrat minimal `requires_file` et
`requires_delivery`. Avant toute matérialisation, il refuse un plan qui remplace une demande de
création/livraison de fichier par de simples outils de lecture. À la clôture, ce contrat exige une
preuve de fichier produit et, lorsqu'elle est requise, un reçu de livraison ; un résultat textuel
sans ressource ne peut donc plus produire `SUCCESS`.

Lorsqu'un fichier final existe sans reçu et qu'aucune livraison n'a été tentée, le planner inscrit
un contrat durable de récupération. Le retry explicite rouvre seulement la feuille productrice avec
le chemin et la destination vérifiés, puis exécute l'unique outil de livraison sans modèle IA via
la même projection d'autorisation et d'effets que le MCP. Une tentative de livraison ambiguë n'est
pas rejouée automatiquement.

Les directives textuelles de route restent des préférences : le dispatcher résout d'abord les
routes exposées par `AgentDriverSpec.pipeline_policy`, puis n'applique une directive que si cette
capacité existe. Une contrainte `forced_route` fournie explicitement lors de la création reste
stricte et produit une erreur d'incompatibilité. Cette négociation est entièrement générique et ne
contient aucune branche conditionnelle par driver. Le contrôleur de conversation ne planifie pas :
`@plan` et `@exec` y prouvent seulement qu'une Task durable doit être admise, sans appel LLM de
routage supplémentaire. Cette admission est exécutée avant le modèle conversationnel par le même
service idempotent que `conversation_task_submit`; la Task conserve la directive et la négocie
ensuite avec les capacités déclarées de son driver.

La projection de session Messenger résout enfin une room par UUID local ou identifiant externe,
toujours dans la portée de sa connexion, puis interroge les deux références canoniques.
Elle projette également les UUID canoniques des messages, rooms et pièces jointes dans
`TaskMessage`. Une demande de renvoi d'une version existante réutilise directement ces octets par
UUID et l'admission interdit de créer une Task de régénération pour ce tour.
Pour Nextcloud Talk, le partage OCS est rapproché du message de fichier créé dans l'historique par
son nom DAV unique ; le bridge ne renvoie plus l'identifiant vide qui empêchait la journalisation.

## Conséquences

- Une étape suivante reçoit les UUID et chemins exacts sans recherche sémantique ni convention de
  nommage fragile.
- Les brouillons historiques restent auditables ; le registre indique lequel est actif.
- Un texte terminal optimiste ne suffit plus à clore un travail dont le fichier n'a pas été livré.
- Une version intermédiaire ne peut plus être publiée prématurément ni perdre son URI provider.
- Une livraison manquante peut être reprise sans régénérer le livrable ni répéter les étapes amont.
- La persistance reste sans nouvelle table ni migration : le registre suit la racine dans le JSON
  de Task et peut évoluer par version de contrat.
- Le Working Set n'est pas une nouvelle mémoire de contenu et ne contourne ni les ACL mémoire, ni
  les transports de fichier, ni la façade Messenger.
- La liste de Tasks du contrôleur reste limitée au contexte conversationnel courant et renvoie des
  résumés compacts avec les références actives ; le résultat détaillé se lit explicitement par UUID.

## Preuves dans le code

`back/app/task/working_set.py`, `back/app/tools/resource_effects.py`,
`back/app/memory/mcp.py`, `back/app/agent/planner_service.py`,
`back/app/agent/executor_service.py`, `back/app/agent/facade.py`,
`back/app/harness/runtime.py`, `back/app/conversation/artifact_delivery.py`,
`back/app/conversation/service.py`, `back/app/file_share/resource_delivery.py` et
`back/app/messenger/session.py`.
Le cas Nextcloud est couvert par `back/bridge/nextcloud/messenger.py`.
