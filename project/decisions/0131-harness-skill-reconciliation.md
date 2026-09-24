# 0131 — Réconciliation des skills avant exécution

Statut : accepté. Date : 2026-09-24.

## Garantie

Une exécution Task utilise les skills autorisés et leur contenu courant au passage
de sa barrière d'entrée. Une modification ne redémarre pas un harnais pendant une
Task déjà en cours. Une erreur de projection interdit le démarrage du driver.

## Décision

La bibliothèque persistée et ses fichiers sont l'état désiré. L'empreinte de la
dernière projection réussie, dans `AgentHarness.provider_metadata`, est le reçu.
`app.agent` appelle le port de préparation de `app.harnesses` avant le driver,
après l'admission de la Task par le scheduler. Les providers conteneurisés qui
projettent des skills limitent l'exécution à une Task simultanée par agent.

L'empreinte est recalculée avant chaque nouvelle exécution. Cette vérification couvre
les mutations HTTP, imports, catégories, autorisations, ressources annexes, skills
appris et changements de fichiers, sans notification du navigateur. Les modifications
successives sont regroupées jusqu'à la prochaine exécution ; un runtime absent
n'est pas provisionné automatiquement.

Le reçu est invalidé et committé avant la copie pour survivre à une interruption.
Une empreinte différente après copie provoque une seconde tentative ; une
bibliothèque continuellement modifiée fait échouer la préparation. Une erreur
conserve une projection à réessayer et un diagnostic public sans secret. Une demande
explicite arrivée pendant la copie n'est jamais effacée par son reçu.

Les commandes `refresh`, la compatibilité `sync-skills` et l'apprentissage persistent
une invalidation sans redémarrage immédiat. Le statut expose `skills_status`
(`pending`, `current`, `error`, `not_applicable`). La sélection réelle du provider
détermine les agents concernés, indépendamment du driver de transport. Les échanges
passent par les ports publics d'`app.agent`, sans nouveau cycle entre domaines.

L'interne conserve ses capabilities différées reconstruites au chargement. Le
harnais réseau sans projection conserve son injection bornée de `SKILL.md`.

## Limites et validation

Une Task en cours conserve son contexte déjà chargé. La révision s'applique à
l'exécution suivante ; ce n'est pas une révocation rétroactive du contexte du modèle.
Une reprise avec checkpoint réconcilie une opération distante potentiellement
encore active : elle garde ses skills et credentials, et laisse la modification
en attente pour la prochaine exécution sans checkpoint.
Le rafraîchissement ne garantit pas la décision du modèle de lire un skill.

Les tests utilisent les services et la base réels, en remplaçant seulement le
transport du provider. Ils couvrent les quatre providers, le retrait et l'édition,
les erreurs, les demandes tardives, les changements de sélection et les copies
interrompues, ainsi que les continuations distantes. Une qualification complète
reste nécessaire avant publication.
