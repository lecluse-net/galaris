<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/flows/dream.md">English</a></p>

# Flux Dream

`app.dream` exécute les enrichissements qui peuvent attendre une période d'inactivité. Il ne crée
pas de Task agentique et ne passe jamais par un driver.

```text
runtime supervisor
       │
       ▼
app.dream scheduler ──► garde Voice + activité Task
       │                         │ activité
       │                         └──────────► attente / préemption
       ▼
mécanismes ordonnés, un par un
       │
       ├─► classement Topic des messages, tours Voice, Tasks et sessions Voice
       ├─► extraction Memory des Tasks, rounds textuels et tours Voice
       ├─► apprentissage fondé sur les résultats observables des Tasks
       ├─► projection déterministe des Process
       ├─► détection et maintenance déterministes pilotées par Memory
       ├─► déclenchement de la réconciliation des liens Memory
       └─► aucun oubli destructif fondé sur l'inactivité
```

## Cycle

Un réveil appelle les mécanismes dans l'ordre de leur enregistrement. Chacun réclame au maximum un
sujet. Un mécanisme sans sujet ne produit aucun appel LLM. Une nouvelle activité prioritaire arrête
la séquence. Le début d'une conversation Voice annule en plus la sous-tâche courante.

Dream ne déduit pas l'inactivité d'un délai approximatif : il lit la présence d'appels actifs dans
`app.voice` et l'existence de travail agentique runnable ou leased par la surface publique
`app.task`. Le worker est non critique pour la readiness.

## Témoin et reprise

`dream_receipts` est la source durable de couverture. L'identité d'un reçu est
`(mechanism_key, subject_kind, subject_id)` :

- aucune ligne : sujet jamais examiné par ce mécanisme ;
- `running` : lease en cours, récupérable après expiration ;
- `retry` : nouvelle tentative différée ;
- `success`, `result_count=0` : sujet examiné sans résultat ;
- `success`, `result_count>0` : effets appliqués ;
- `error` : budget de tentatives épuisé.

Les identifiants de mécanisme sont stables et ne comportent aucune version. Une évolution du code
ne rescane pas implicitement les sujets déjà traités. Lorsqu'un retraitement est nécessaire, il
doit être déclenché par une nouvelle identité de sujet ou une opération métier explicite.

La sortie préparée est conservée en JSON avant son application. Les effets utilisent des clés
d'idempotence dérivées du reçu et de leur position. Une interruption entre deux écritures ne
redemande donc pas une nouvelle décision au modèle.

## Classement et extraction

Les mécanismes `topic.classify_message`, `topic.classify_task` et
`topic.classify_voice_session` affectent les activités à un dossier thématique global. Les
messages couvrent les conversations textuelles comme vocales. Leur
politique de création est checkpointée avant application et respecte le mode
`DREAM_TOPIC_CREATION_MODE`.

Les mécanismes `memory.extract_task` et `memory.extract_conversation_round` attendent un Topic et,
pour les sources conversationnelles textuelles comme vocales, le contact
exact. Ils utilisent une unique décision structurée `CREATE`, `LINK` ou `IGNORE`, sans outil ni
MCP. Chaque acquisition conserve le reçu et la clé stable du mécanisme, sans métadonnée de
version.

`skill.learn_task_outcome` transforme uniquement des preuves observables et bornées en procédures
réutilisables propres à l'agent. CREATE, REINFORCE, REVISE et WEAKEN alimentent les tables dédiées
`learned_skills` et `learned_skill_evidences`, jamais Memory. L'empreinte des preuves fait partie de
l'identité du sujet : une preuve matérielle tardive crée un nouveau sujet, tandis qu'un rescan
identique reste sans effet. Toutes les Tasks terminales sont éligibles, y compris celles terminées
avant l'activation de l'apprentissage ; Dream les parcourt de la plus ancienne à la plus récente,
une par passage. Le mode `observe` conserve la proposition checkpointée ; `learn` peut ensuite
l'appliquer sans second appel LLM.

Le score lissé `(positif + 1) / (positif + négatif + 2)` rend visibles renforcement et
affaiblissement. Une première occurrence crée seulement une candidate. Une procédure non suspendue
est ajoutée aux skills ordinaires de l'agent seulement si `DREAM_SKILL_MIN_EVIDENCE` Tasks
distinctes ont confirmé la même action répétée et si elle atteint `DREAM_SKILL_ACTIVATION_SCORE`,
dans la limite de `DREAM_SKILL_MAX_ACTIVE`. Le seuil de répétition vaut 3 par défaut. Sa projection
de fichiers sous `.learned/` est reconstruite depuis la base et ne rejoint jamais l'index des
skills administrées.

## Effets déterministes

`memory.project_process` projette les définitions et résultats Process admissibles. Après chaque opération Dream réussie, le
scheduler inscrit dans `app.memory.automation` une réconciliation ciblée pour chaque nœud Memory
touché. La maintenance de `topic_contains`, `contact_contains`, `cycle_of`, `result_of` et des
suggestions thématiques n'est donc plus un mécanisme Dream : elle n'a ni reçu, ni jauge Dream, ni
appel de modèle. `MEMORY_LINK_RECONCILIATION_TRIGGER_MODE` permet de conserver ou désactiver ce
hook ciblé. Un sweep global peut aussi être inscrit selon l'intervalle
`MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS`; il attend toujours que Tasks et Voice soient inactifs.
La page des préférences Dream affiche la prochaine échéance et permet un lancement manuel
immédiat, exécuté dans la requête HTTP sans attendre l'inactivité.

Les politiques de doublon, contradiction et vieillissement appartiennent à `app.memory`.
Le mécanisme Dream `memory.maintain_findings` les exécute séquentiellement pendant l'inactivité :
Memory pilote, Dream exécute. Il ne fait aucun appel de LLM génératif et lit seulement les
embeddings déjà calculés lorsqu'une comparaison sémantique est nécessaire. Ses reçus assurent la
reprise et empêchent le retraitement d'une même révision avec une même politique ; ce travail
mécanique à haut volume est volontairement exclu des jauges Dream. Le vieillissement marque un
souvenir comme ancien sans le supprimer du RAG.

## Suivi opérationnel

Les routes en lecture seule `/api/dream/overview` et `/api/dream/receipts` exposent l'état du
scheduler, la couverture et l'historique paginé des reçus. Le contrat HTTP, les filtres et la page
Dream n'exposent aucune version de mécanisme. Le détail d'un reçu montre sa sortie préparée, son
coût, ses tentatives et sa dernière erreur. Ces routes exigent `TASK_ACCESS`.

La page charge ces projections lorsqu'elle est ouverte, puis écoute les événements `dream.update`
du websocket authentifié. Les transitions du runtime et les changements terminaux des reçus
déclenchent une actualisation regroupée. Une reconnexion resynchronise la projection complète.
Cette lecture n'ajoute aucun worker et ne réveille jamais un mécanisme Dream.

## Extension

Un futur mécanisme implémente `DreamMechanism`, fournit une clé stable, s'enregistre dans le
registre ordonné et utilise le même reçu générique. Les sujets peuvent être des souvenirs, des
groupes de souvenirs, des agents ou d'autres objets durables. Aucun nouveau worker racine ne doit
être ajouté.
