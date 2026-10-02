# File d'attente et priorités des appels LLM par fournisseur

- Statut : `design`
- Date : 2026-10-02
- Portée : conception demandée ; aucune modification du runtime dans ce lot.
- Liens : [inférences durables](llm-calls-durables.md),
  [ADR 0097](../decisions/0097-durable-inference-lifecycle.md),
  [tests fonctionnels](../../docs/fr/dev/functional-tests.md).

## Garantie recherchée

Chaque connexion `LLMProvider` possède une limite d'appels simultanés. Lorsque tous ses
créneaux sont occupés, les appels attendent sans démarrer d'inférence chez ce fournisseur.
À chaque libération, le prochain appel est choisi selon sa priorité configurée, puis son ancienneté
à priorité égale. Deux fournisseurs conservent des capacités et des files indépendantes.

Exemple : avec Ollama limité à `1`, un appel Dream est en cours et plusieurs appels attendent.
Une conversation audio arrivée après les autres obtient le prochain créneau, suivie des
conversations texte, des tâches, des appels API et enfin de Dream. OpenRouter configuré à `0`
peut continuer à servir ses appels en parallèle.

## 1. Constats dans le code

- `back/app/llm/provider_models.py` porte les connexions et leurs modèles. La limite appartient
  au fournisseur, pas à chaque modèle, profil LLM, agent ou utilisateur.
- `provider_schemas.py`, `llm_provider_service.py` et `provider_router.py` proposent déjà les
  contrats de création, modification et configuration du catalogue, protégés par RBAC.
- Ollama est un type de connexion personnalisée enregistré par `back/bridge/ollama`, sans
  profil fixe de catalogue. Un défaut exclusivement porté par `ProviderProfile` le manquerait.
- `inference_execution.py` ordonnance déjà les inférences persistées et leurs tentatives,
  mais lance les racines éligibles sans admission par capacité fournisseur.
- Le transport SDK interne dans `pydantic_ai_utils.py` rejoint `proxy_service.py` pour Chat
  et Responses. Un contrôle placé uniquement autour du harnais manquerait les autres clients.
- Les décisions natives, embeddings, transcriptions et générations média disposent aussi de
  chemins directs. `embedding_service.py` est notamment consommé par Memory, la recherche
  d'outils, `embedding_facade.py` et `profile_inference.py`.
- `purposes.py` décrit les usages sémantiques ; un appel d'une Task via HTTP reste un appel
  de tâche. Son transport ne suffit pas à choisir sa priorité.
- Les traces et plusieurs consommateurs traitent aujourd'hui `running` comme le seul état actif.
  Ajouter `queued` exige de revoir ensemble activité, arrêt, historique, rétention et réconciliation.
- `back/entrypoint.sh` impose un worker Uvicorn. Une coordination asynchrone en mémoire est
  compatible avec cette architecture ; elle ne constituerait pas une limite entre plusieurs
  instances indépendantes du backend.

Ces constats viennent d'une inspection des sources et tests, sans mesure sous charge ni
qualification d'un fournisseur réel dans ce lot.

## 2. Préférence par fournisseur

Ajouter `max_parallel_calls`, entier strict positif ou nul, dans `LLMProvider`, les schémas
API et les contrats frontend. Rejeter valeurs négatives, fractions, booléens et `null` explicite.

| Valeur | Comportement |
|---|---|
| `0` | Pas de limite de concurrence imposée par Galaris |
| `1` | Un seul appel actif pour toute la connexion |
| `N > 1` | Au plus N appels actifs, tous modèles et consommateurs confondus |

Défauts : `1` pour une connexion de type `ollama`, `0` pour OpenRouter et les autres types,
y compris un endpoint OpenAI compatible personnalisé. Ne pas déduire une capacité machine
de son URL. Un administrateur peut mettre Ollama à `0` ou OpenRouter à `1`.

Centraliser la résolution des défauts côté backend, et la projeter dans les données utilisées
par les formulaires. À la création, champ omis = défaut du type ; à la modification ou à la
reconfiguration, champ omis = conservation de la valeur existante. Un changement de type
d'une connexion ne réinitialise pas silencieusement la limite.

Pour les connexions déjà enregistrées, prévoir une action DbAdmin liée à l'ajout de la colonne :
initialiser les valeurs manquantes à `1` pour Ollama et `0` ailleurs, puis imposer `NOT NULL`
et un défaut serveur générique `0`. L'action ne réapplique jamais les défauts aux valeurs
renseignées. Tester prédicat, postcondition, interruption et idempotence ; pas de migration
Alembic ni de backfill dans le lifespan.

## 3. Inventaire des types et preuve du demandeur

L'inventaire ne doit pas être limité aux cinq exemples proposés initialement. Séparer :
**opération technique** (`purpose`), **demandeur immédiat** (module/service/runtime),
**origine métier** (conversation vocale, conversation texte, Task, API, Dream, etc.)
et **identité autorisée** (utilisateur, agent et ressource possédée). La priorité utilise
l'origine et l'opération, et non la seule identité de l'agent.

### Usages présents dans les sources

Le tableau couvre les valeurs déclarées de `LLMCallPurpose`, les usages littéraux trouvés
dans les chemins d'appel, ainsi que les inférences directes sans `purpose` complet.
Une valeur déclarée n'est pas la preuve qu'un consommateur l'exécute actuellement.

| Famille | Types techniques déclarés ou utilisés | Demandeurs à suivre |
|---|---|---|
| Dialogue | `conversation.text`, `conversation.audio`, `conversation.task_objective` | Harnais conversationnel et construction d'objectif ; distinguer voix/texte et passage vers Task |
| Agent | `agent.exec`, `agent.dispatch`, `agent.planning`, `agent.planning_recovery`, `agent.synthesis` | Harnais, dispatcher, planner ; retrouver l'origine du round ou de la Task |
| Objectif/processus | `goal.tracking`, `process.exec` | Runner Goal, gateways et exécutions de processus |
| Dream/Topics | `dream.topic_continuity`, `dream.topic_reuse`, `dream.topic_creation`, `dream.memory_extraction`, `dream.task_outcome_reflection`, `dream.skill_learning` | Mécanismes Dream, classification et détection de Topics |
| Mémoire | `memory.duplicate_decision`, `memory.conversation_summary` | Acquisition Memory et résumé ; origine interactive ou maintenance à distinguer |
| Pièces jointes Dream | `dream_attachment_summary`, `dream_attachment_document` | `app.dream.attachment_processing` ; provenance Dream malgré usage média/document |
| Audio différé | `audio.segment_summary`, `audio.summary_reduction`, `audio.final_synthesis` | `app.audio.summary_service` ; ne pas assimiler un résumé à la voix en direct |
| Transcription | `audio.transcription` | `transcription_service` ; le même type est utilisé hors et pendant une conversation vocale |
| Image/document | `image.analysis`, `image.generation`, `document.analysis` | Services Image et LLM document ; usages possibles depuis conversation, Task, API ou Dream |
| Lab | `lab.task_analysis`, `lab.mechanism_run`, `lab.mechanism_judge`, `lab.benchmark_analysis`, `lab.dispatcher_judge`, `lab_synthetic_dataset` | Analyses, campagnes, mécanismes et données synthétiques du Lab |
| API de profils | `profile.decision`, `profile.embedding` | `profile_inference.py` et gateways de profils |
| Multimédia | `multimedia.audio_read`, `multimedia.video_read`, `multimedia.sound_generate`, `multimedia.music_generate`, `multimedia.video_generate` | `media_facade`, services multimédia, submit/poll/callback |
| Embeddings internes | Opérations d'embedding sans `purpose` transmis au transport partagé | `embedding_facade`, Memory embedding/index/déduplication, recherche/indexation des Tools |
| Voix de synthèse | TTS ponctuel et streams de parole sans création de `LLMCall` dans `tts_service.py` | Agent/ressource vocale ; ajouter une identité d'opération et son origine |
| Audio temps réel | Sessions STT/TTS et traitements natifs de flux | Façades transcription/parole et bridges ; définir l'unité de capacité et la provenance |
| Gateways génériques | Chat, Responses, compactage, Anthropic compatible ; `purpose` potentiellement omis | Client API utilisateur ou runtime géré ; résoudre identité et contexte avant admission |

Ne pas renommer les usages littéraux existants uniquement pour uniformiser la présentation.
Les rattacher au registre et maintenir les anciennes traces.

### État de l'identification actuelle

`create_running_call` conserve déjà Task/tentative, run agent, round conversationnel,
ProcessRun, utilisateur demandeur, agent, libellé du jeton API et référence de corrélation.
Il valide notamment la présence des propriétaires exigés par certains usages et la cohérence
du round/processus avec l'agent. `runtime_correlation.py` résout aussi le contexte des runtimes.
Ces éléments doivent être réutilisés et leurs limites testées, pas remplacés par une déduction
sur le nom du modèle.

L'inspection ne permet toutefois **pas de garantir que tous les appels sont identifiés** :

- `InferenceInput` n'a pas de contrat explicite commun de demandeur/origine métier.
- Une même transcription ou analyse média peut servir plusieurs demandeurs/priorités.
- Les endpoints d'embeddings transmettent modèle, URL et clé, sans origine ni identité de
  connexion dans `EmbeddingEndpoint` ; plusieurs consommateurs internes n'y créent pas de trace.
- Le service TTS invoque le fournisseur sans créer de trace `LLMCall` dans ce service.
- Certains usages sont des chaînes hors enum, et les gateways acceptent un usage absent.
- `infer_call_purpose` déduit un usage depuis le texte pour les anciennes traces : cette
  heuristique historique n'est pas une preuve utilisable pour l'admission actuelle.

**Prérequis au scheduler :** auditer chaque racine de demande et chaque frontière, établir
une matrice « demandeur → appel → propriétaire → type effectif → priorité », puis corriger
les pertes de provenance dans les contrats et adaptateurs. Pour chaque chemin, une preuve
automatisée doit montrer les champs reçus à l'admission et persistés, avec seuls les
transports externes remplacés. Une classification apparemment plausible ne suffit pas.

Créer un descripteur typé partagé dans la surface publique de `app.llm` : type enregistré,
demandeur immédiat, origine immuable et références existantes vérifiées. Le porter dans les
requêtes durables, contextes d'outils, appels spécialisés et reprises/fallbacks. Les branches
concurrentes conservent leur propre contexte sans contamination par un autre utilisateur.
L'autorité d'accès reste celle du système existant ; un contexte d'ordonnancement ne donne
aucun droit supplémentaire.

Publier un registre backend exhaustif des types d'ordonnancement effectivement admis,
avec code stable, libellé i18n, description, origine, opération et priorité par défaut.
Un même `purpose` partagé donne plusieurs types lorsque son demandeur change la priorité
(par exemple transcription vocale interactive versus transcription Dream).
Projeter ce registre dans l'administration, sans liste frontend concurrente.
La couverture complète du registre et de la provenance conditionne la clôture du plan.

## 4. Politique de priorité configurable

Ordre initial, du plus prioritaire au moins prioritaire :

| Rang | Catégorie | Exemples et règle |
|---|---|---|
| 1 | Conversation audio | Traitements nécessaires à un échange vocal en direct : transcription, réponse du modèle, synthèse vocale |
| 2 | Conversation texte | Réponse interactive, routage et analyses nécessaires à cette réponse |
| 3 | Tâche | Exécution, planification, récupération et synthèse de Tasks, processus et suivi d'objectifs actifs |
| 4 | API | Clients externes sans contexte conversationnel ou de tâche vérifié ; API de profils |
| 5 | Dream et fond | Dream, extraction et consolidation mémoire, indexation et travaux différés ; Lab hors contexte interactif |

Cet ordre est un **défaut**, pas une liste fixe de cinq types. Chaque fournisseur expose
les types détaillés du registre et permet de régler leur rang dans `call_priorities`,
une configuration persistée distincte des options transmises au fournisseur externe.
Prévoir une colonne JSON typée par les schémas API, non nullable, avec défaut vide `{}` ;
les connexions existantes héritent ainsi de la politique publiée sans surcharge inventée.
Les appels audio en direct restent au rang le plus élevé, réservé : les autres rangs sont
éditables, sans possibilité de dépasser cette priorité absolue. Plusieurs types peuvent
partager un rang ; FIFO départage les appels de ce rang. En mode `0`, ces rangs restent
enregistrés mais n'introduisent aucune attente artificielle.

Ne stocker que les surcharges ; les nouveaux types reçoivent automatiquement leur défaut
publié. Rejeter codes inconnus et valeurs invalides. Une modification omise conserve la
configuration ; la remise aux défauts est explicite. Une sauvegarde réussie reclasse les
appels encore en attente, en conservant leur séquence initiale ; elle ne change pas l'origine
ni les appels actifs. Tester sauvegardes concurrentes et projections obsolètes.

La priorité audio est stricte pour les **appels en attente**. Aucune promotion automatique
par ancienneté ne doit faire passer un travail de fond devant une conversation audio.
À priorité égale, conserver FIFO avec une séquence d'admission monotone. Des arrivées
interactives continues peuvent donc retarder indéfiniment Dream : ce compromis est explicite.

La priorité ne préempte pas un calcul déjà lancé. Arrêter une requête cliente ne prouve pas
l'arrêt du calcul distant. Avec une limite de `1`, l'audio attend la fin du créneau occupé ;
la priorité ne promet pas de latence vocale maximale ni de créneau audio réservé.

Le classement repose sur une origine validée côté serveur et les usages existants, pas sur
un entier arbitraire fourni par le client, le nom du modèle ou un contenu de prompt.
Définir un contrat typé de catégorie et une fonction centrale de résolution :

- Propager l'origine d'un traitement interactif à ses appels nécessaires, notamment STT,
  TTS, vision, embeddings et routage. Un `ContextVar` seul ne traverse pas les racines
  durables ni les transports : conserver aussi cette origine dans les contrats concernés.
- Les appels d'une Task autonome issue d'un dialogue relèvent ensuite de la catégorie tâche,
  sauf appel directement requis pour terminer la réponse interactive courante.
- Une opération Dream conserve son origine de fond lorsqu'elle utilise des outils,
  embeddings ou tâches auxiliaires : un `task_id` ou `agent.exec` ne doit pas la promouvoir.
- Une transcription de document, un résumé audio différé ou un fichier audio joint à un
  message texte n'est pas automatiquement une conversation vocale en direct.
- Les métadonnées externes de corrélation doivent être autorisées et résolues avant toute
  promotion. Un client API ordinaire ne peut pas s'auto-attribuer la priorité audio.
- Une API externe validée sans autre origine va au rang API. Toute nouvelle opération interne
  doit être enregistrée avec son demandeur ; une provenance interne absente est un défaut
  à corriger, pas un succès de classification. Prévoir un diagnostic explicite et une règle
  conservatrice au rang fond pour la transition, sans lui accorder une priorité interactive.

## 5. Coordinateur partagé dans `app.llm`

Créer un service d'admission asynchrone du domaine, indexé par la clé primaire de la connexion.
Chaque fournisseur possède son compteur d'appels actifs et une file ordonnée par rang effectif
du type enregistré, puis séquence FIFO. La décision
de prise de créneau et le transfert au prochain appel sont atomiques, sous verrou bref.
Une admission et une libération ne peuvent survenir qu'une fois par appel.

Le service attend de façon coopérative. Aucun thread bloqué, transaction ou verrou SQL conservé
pendant l'attente ; aucune copie supplémentaire du prompt ou des médias dans la file.
Supprimer les entrées annulées et les états inactifs sans croissance résiduelle.

Le contrôle se place au niveau de l'appel physique fournisseur :

1. résoudre la connexion, le modèle, les droits et la catégorie ;
2. enregistrer l'attente et demander un créneau ;
3. à l'admission, vérifier que la commande, le contexte et le fournisseur restent valides ;
4. marquer le début réel, lancer les délais propres à l'appel fournisseur et envoyer la requête ;
5. conserver le créneau jusqu'à la fin ou fermeture effective du transport, y compris le stream ;
6. finaliser et libérer dans un chemin de nettoyage résistant à l'annulation.

Ne jamais conserver un créneau pendant une exécution d'outil, une pause humaine ou entre deux
tours du modèle. Un sous-appel sur le même fournisseur doit pouvoir démarrer après libération
du parent ; aucun double verrouillage par le SDK, le proxy et le harnais.
Une nouvelle tentative physique revient dans la file avec sa catégorie, après nettoyage de
la précédente ; aucune relance nouvelle n'est introduite par le scheduler.

Qualifier particulièrement la chaîne vocale sur un même fournisseur à `1` : une session STT
ou TTS ouverte mais inactive ne doit pas réserver indéfiniment le créneau requis par le modèle.
Distinguer connexion de transport et calcul d'inférence. Si un protocole impose réellement
des calculs simultanés permanents pour le duplex, ne pas contourner la limite : utiliser un
mode séquentiel/segmenté compatible, des connexions distinctes ou signaler clairement cette
incompatibilité de configuration. Tester ce cas avant de déclarer la voix couverte.

### Modification à chaud

- Augmentation : admettre immédiatement les premiers appels éligibles selon les priorités.
- Diminution : laisser terminer les appels déjà actifs ; suspendre les nouvelles admissions
  jusqu'à ce que le compteur soit inférieur au nouveau plafond.
- Passage à `0` : libérer les attentes admissibles sans oublier de suivre les appels déjà actifs.
- Passage de `0` à une limite : compter ces appels encore actifs pour les admissions suivantes.
- Désactivation ou suppression : refuser les attentes avant tout envoi et suivre les règles
  existantes pour les appels engagés ; aucun créneau perdu.

Publier un changement seulement après succès de l'enregistrement. Ne pas utiliser une copie ORM
ancienne pour rétablir une limite précédente. Tester les courses entre sauvegarde et admission.

### Couverture des chemins

Premier parcours complet : Chat/Responses, avec et sans stream, depuis le dialogue et l'API.
Puis décisions natives et fallback ; puis embeddings, transcription, TTS et génération/analyse
média utilisant une connexion LLMProvider. Les médias asynchrones restent comptés pendant la
période d'exécution distante connue ; un simple accusé de réception n'est pas une fin d'inférence.

Propager l'identité fournisseur et la catégorie aux endpoints d'embeddings ; ne pas limiter
seulement l'API publique en oubliant les recherches et indexations internes. Réutiliser les
façades pour les adaptations de consommateurs. La découverte de modèles, la lecture de quotas,
OAuth et la gestion de modèles ne sont pas des appels d'inférence et restent hors de cette file.

Les SDK ou clients appelant directement une URL externe, sans passer par Galaris, ne peuvent
pas être bornés par ce mécanisme. Documenter la couverture réelle des harnais. Le contrat
de cette version suppose un backend unique ; plusieurs réplicas exigeraient une coordination
partagée avant de conserver la même promesse de concurrence.

## 6. Attente, traces et reprise

Ajouter un état d'appel `queued` distinct de `running`, le demandeur, l'origine, le type et
le rang effectifs, ainsi que les dates
d'entrée en file et de début fournisseur. Préférer des champs additifs ; ne pas réécrire les
dates historiques pour fabriquer des mesures. Définir dans les schémas la compatibilité de
`started_at` existant, puis adapter les calculs de durée à la date de début fournisseur avec
repli explicite pour les anciennes traces.

L'attente ne consomme ni tokens ni coût d'inférence. Les compteurs d'appels physiques et
budgets correspondants se déclenchent au départ effectif. L'état actif présenté aux écrans
comprend les appels en file et en cours, avec des compteurs distincts.
Revoir arrêt/suppression, nettoyage de l'historique, agrégations, rétention, détection d'appels
abandonnés, événements websocket et activité Task/Conversation pour ne pas traiter la file
comme un échec ou comme un historique terminé.

`LLMCallDeadline` commence au départ effectif, pas à l'entrée en file. Les échéances globales
du consommateur restent applicables : un délai API, décision, recherche sémantique ou métier
expiré retire l'appel sans l'envoyer. Distinguer expiration d'attente et timeout fournisseur.
Ne pas allonger silencieusement les budgets existants ni déclencher un fallback en conservant
une ancienne attente susceptible de partir plus tard.

Examiner le watchdog `TASK_ACTION_TIMEOUT_SECONDS` dans `app.task.scheduler` : une attente
connue et vivante doit être visible comme telle et conserver les leases, sans fabriquer de
tokens ou désactiver la détection des blocages réels. Tester un temps de file dépassant ce
watchdog. Faire évoluer le signal par le port public agent/task si nécessaire, sans import
de `app.task` dans `app.agent`.

La file du coordinateur est en mémoire ; le cycle durable reste celui des inférences et de
leurs tentatives. À l'arrêt, fermer les admissions, retirer les attentes et nettoyer les
transports. Au redémarrage, réconcilier aussi les traces `queued` orphelines et appliquer la
politique existante de reprise, sans transformer automatiquement toute attente en nouvel
appel facturable. Les clients HTTP interrompus resoumettent selon leur contrat d'idempotence.
Une requête jamais envoyée et un calcul distant de résultat incertain doivent rester distincts.

## 7. Administration et activité

Dans `ProviderConfigPanel.vue` et le formulaire de création personnalisée, ajouter le champ
« Appels simultanés maximum » et l'aide « 0 = illimité. 1 = un appel à la fois, conseillé
pour une inférence locale. ». Présenter la valeur correspondant au type avant création,
puis la valeur enregistrée. Sauvegarde, réouverture, refus RBAC et erreurs doivent suivre
le parcours existant de `ProviderWorkspace.vue`.

Ajouter dans cette fiche la liste complète des types d'appels, regroupée pour la lecture
par origine puis opération, avec rang par défaut, rang effectif et modification accessible
au clavier. Afficher explicitement la priorité audio réservée. Permettre une remise aux
défauts ; ne pas réduire l'interface aux cinq catégories d'exemple ni aux seuls types déjà
observés dans l'historique. Préserver les valeurs d'autres types lors d'une sauvegarde ciblée.

Étendre services, types, store et brouillons sans envoyer les secrets omis, écraser une
saisie lors d'une réponse tardive ou réinitialiser les réglages au changement de fournisseur.
Affichage et messages traduits FR/EN, clavier et viewport mobile conservés.

Dans l'activité LLM existante, montrer « En attente », catégorie et durée d'attente, conserver
l'action d'arrêt, et distinguer attente de durée fournisseur. Éviter une position exacte
trompeuse : un nouvel appel prioritaire peut dépasser des appels déjà présents. Expliquer
l'ordre et l'absence de préemption dans l'aide ; aucune nouvelle page nécessaire.

## 8. Lots et critères de réception

| Lot | Livrable | Preuve attendue |
|---|---|---|
| 1 | Inventaire exhaustif, audit/correction du demandeur et de l'origine ; registre et contrats de configuration ; DbAdmin | Provenance démontrée par chemin, liste complète, persistance réelle, omission/0 explicite, idempotence et refus RBAC |
| 2 | Admission Chat/Responses, traces d'attente et modifications à chaud | Parcours complet puis concurrence, FIFO, priorité, streaming et annulation |
| 3 | Décisions, embeddings et médias ; propagation des origines | Appels mixtes sur la même connexion respectant un seul compteur, sans double admission |
| 4 | Administration, activité, watchdog et reprise | Réouverture, erreurs, arrêt en file, redémarrage et parcours assemblé desktop/mobile |
| 5 | Documentation, décision d'architecture et qualification | Sources FR/EN à jour, contrôles et recette locale/cloud avec mesures conservées |

Scénarios indispensables, avec fournisseurs synthétiques et vrais services internes :

- 36 demandes sur une connexion à `1` : maximum observé au transport = 1 ; à `2` = 2 ;
  à `0`, aucun plafond introduit par Galaris ; deux modèles partagent le compteur.
- Fournisseur A saturé : B continue immédiatement. Deux connexions Ollama restent indépendantes.
- Un appel bloquant actif, puis attentes Dream/API/tâche/texte/audio en ordre inversé :
  après libération, observer audio, texte, tâche, API, Dream ; FIFO dans chaque catégorie.
- Appel audio arrivé pendant Dream actif : aucune préemption, mais audio reçoit le prochain slot.
- Nouvelle demande ne dépasse pas une attente de même priorité lors d'une libération concurrente.
- Origine Dream conservée à travers Task/outil/embedding ; chaîne vocale STT/modèle/TTS prioritaire ;
  client externe incapable de falsifier sa catégorie.
- Tous les usages enum, littéraux et directs de l'inventaire ont un type enregistré et une
  preuve de demandeur ; cas origine absente, ambiguë ou contradictoire traités explicitement.
  Une origine interne manquante ne doit pas être silencieusement acceptée comme identification
  correcte ; seule l'API ordinaire possède un défaut API documenté. Anciennes traces non
  identifiées restent inconnues, sans backfill déduit des prompts.
- Rangs de chaque type modifiables par fournisseur, isolation A/B, égalité/FIFO, reclassement
  des attentes, nouveau type avec défaut, audio toujours prioritaire et erreurs de configuration.
- Stream lent : créneau conservé après les headers et le premier token ; fermeture anticipée,
  erreur avant headers, timeout, annulation et double nettoyage ne perdent ni ne doublent un slot.
- Annulation avant admission : aucune requête fournisseur, aucun token et aucun coût ; tester
  aussi la course entre annulation et transfert du créneau.
- Limites `1 → 2 → 1 → 0 → 1`, y compris appels actifs commencés en mode illimité.
- Décision native en échec puis fallback sur le même fournisseur : aucun interblocage ;
  appels d'outils et tours successifs ne conservent pas un ancien créneau.
- Échéance d'attente, timeout fournisseur et watchdog Task distingués ; pas de départ tardif
  après un fallback ou un arrêt, leases valides, états terminaux immuables.
- Réconciliation après crash, relecture d'anciennes traces, coûts, pagination et isolation des
  utilisateurs conservés ; nombre d'entrées mémoire revient au repos après les rafales.
- UI : modifier puis rouvrir chaque fournisseur, conserver 0, invalider les mauvaises valeurs,
  vérifier autosauvegarde, erreur/retry, changement de sélection et lecture sans privilège d'édition.

Renforcer les suites existantes `test_provider_catalog.py`, `test_llm_call_trace.py`,
`test_inference_lifecycle.py`, `test_protocol_inference.py`, `test_decision_inference.py`,
les tests d'embeddings/transcription et `provider-autosave.spec.mjs` / `llm-calls.spec.mjs`.
Ajouter une suite du coordinateur pour les garanties de concurrence, avec barrières et
événements déterministes plutôt que temporisations fragiles.

Mesurer séparément attente, durée fournisseur et délai jusqu'à première sortie utile.
Comparer les mêmes rafales locales avant/après pour saturation, échecs et consommation de
ressources ; la seule baisse du nombre d'appels simultanés ne prouve pas un gain de débit.
Une recette avec Ollama et OpenRouter qualifie les comptes et transports réels ; les tests
synthétiques ne suffisent pas à cette conclusion.

Après implémentation : tests ciblés via `make tests`, contrôles frontend ciblés, `make typecheck`,
`make architecture-check`, parcours assemblé et `git diff --check`. Mettre à jour les guides
FR/EN des fournisseurs, de l'activité et de l'exécution, le catalogue de tests et une ADR
pour la politique d'admission/priorité ; lancer `make docs-prepare`.
Avant publication demandée, `make validate` sur l'instantané final et lecture de son résumé.
Clore ce plan seulement une fois le périmètre couvert et les limites de qualification explicites.
