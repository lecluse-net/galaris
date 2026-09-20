# ADR 0047 — Skills auto-apprises renforcées par des preuves

- Statut : Accepted
- Date : 2026-08-24

## Contexte

L'ADR 0019 stockait les procédures apprises depuis les résultats de Tasks comme des nœuds Memory
de rôle `experience`. Cette représentation mélangeait deux responsabilités : se souvenir de faits
et faire évoluer les instructions opératoires d'un agent. Elle rendait aussi le niveau de
renforcement peu lisible et conditionnait l'injection à un mode global plutôt qu'à la qualité de
chaque procédure.

## Décision

Dream conserve deux mécanismes indépendants. Les extracteurs `memory.*` produisent des faits dans
`app.memory`. `skill.learn_task_outcome` analyse les preuves déterministes et expurgées d'une Task
terminale, puis produit au plus trois opérations `CREATE`, `REINFORCE`, `REVISE` ou `WEAKEN` sur des
skills propres à l'agent. Il ne crée ni ne modifie aucun `MemoryItem`.

PostgreSQL est l'autorité de ces procédures via deux tables dédiées : `learned_skills` contient le
Markdown, sa révision, les poids positifs et négatifs, le score et l'état de suspension ;
`learned_skill_evidences` conserve chaque renforcement avec son empreinte, ses références et sa
justification. Une contrainte rend une même preuve idempotente pour une même skill.

Le score est l'estimation lissée `(positive_weight + 1) / (positive_weight + negative_weight + 2)`.
Une skill devient injectable si elle n'est pas suspendue, atteint `DREAM_SKILL_MIN_EVIDENCE` et
`DREAM_SKILL_ACTIVATION_SCORE`, puis reste dans les `DREAM_SKILL_MAX_ACTIVE` mieux classées de son
agent. La première occurrence crée seulement une candidate non injectable ; le seuil compte les
Tasks distinctes confirmant la même procédure et vaut 3 par défaut. Une preuve négative peut donc
la faire repasser sous le seuil sans supprimer son audit.

L'injection est additive : les skills auto-apprises admissibles complètent les skills ordinaires
affectées à l'agent. Le harnais interne les expose comme capacités différées. Les runtimes externes
reçoivent une projection reconstruisible sous `.learned/<agent>/<code>/SKILL.md`; cette projection
n'est jamais indexée comme une skill administrée et la base reste l'autorité.

`DREAM_SKILL_LEARNING_MODE` possède trois modes :

- `off` : aucun scan ni apprentissage ;
- `observe` : preuves et décision checkpointées, sans écriture de skill ;
- `learn` : application idempotente des opérations checkpointées.

Toutes les Tasks terminales, antérieures ou postérieures à l'activation, sont éligibles. Dream les
parcourt de la plus ancienne à la plus récente, une par passage, et les reçus rendent ce rattrapage
idempotent. Le passage d'`observe` à `learn` réutilise la décision existante. Les codes créés sont
préfixés par l'identité de l'agent, le serveur valide le frontmatter `SKILL.md`, les références de
preuves et les cibles. WEAKEN n'est accepté que pour un signal déterministe pouvant contredire une
procédure.

Les paramètres historiques `DREAM_EXPERIENCE_*` restent temporairement lisibles pour compatibilité
de configuration, mais le mécanisme correspondant n'est plus enregistré et les expériences Memory
ne sont plus injectées. Une suppression de données historiques éventuelle est une opération
explicite distincte, afin de ne pas effacer silencieusement des données existantes.

## Conséquences

- Mémoire factuelle et apprentissage procédural évoluent indépendamment dans Dream.
- Le renforcement est auditable, réversible par preuve négative et visible dans l'interface Skills.
- L'activation peut entraîner un rattrapage progressif des Tasks historiques sans worker massif.
- Une procédure faible ou suspendue ne consomme aucun contexte d'exécution.
- Le schéma PostgreSQL gagne deux tables ; aucun fichier appris n'est une source durable.
- Les anciennes expériences Memory restent historiques mais inertes jusqu'à une politique de
  nettoyage explicitement décidée.

## Preuves dans le code

`back/app/dream/mechanisms/skill_learning.py`, `back/app/skill/learning_service.py`,
`back/app/skill/models.py`, `back/app/skill/projection.py`, `back/app/harness/skills.py`,
`front/app/skill/components/LearnedSkillManager.vue` et leurs tests.
