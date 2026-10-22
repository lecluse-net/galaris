# 0214 — Nouvelle inférence à chaque relance explicite d'une Task réseau

Statut : accepté — 21 octobre 2026.

## Problème

Le bouton Réessayer demandait la récupération du même acteur distant. Un runtime terminé
sans état reprenable restait donc définitivement bloqué, même après une relance manuelle.
La sémantique attendue est une nouvelle inférence avec les mêmes paramètres, dans la même Task.

## Décision

`DriverCheckpointRetryPolicy.prepare_retry` peut retourner `None` pour demander une nouvelle
opération. Les harnais réseau gérés utilisent ce contrat pour chaque relance explicite.
La façade conserve le checkpoint précédent dans `_agent_run_retry_checkpoint`, efface le
checkpoint et l'identité actifs ainsi que les approbations périmées. Les paramètres métier,
la Task et les tentatives précédentes sont conservés. L'archive courante est bornée à une
opération ; les checkpoints des tentatives restent dans leur historique durable.

Avant de soumettre l'inférence, le driver révoque l'ancienne autorité et ses actions encore
en attente, puis confirme l'arrêt ou l'absence de l'ancien acteur. Si l'arrêt échoue ou dépasse
le délai borné, aucune nouvelle autorité n'est émise. Le driver crée ensuite une nouvelle
identité runtime avec une nouvelle autorité. Des observations d'outils bornées sont transmises
comme données non fiables pour permettre la vérification des reçus et clés d'idempotence.
Cette information ne constitue pas une garantie de déduplication sémantique par le modèle.

La récupération automatique d'un lease ou d'une interruption continue d'observer l'acteur
existant. Le journal d'effets du harnais interne et les contrats des autres drivers restent
conservés. Une enveloppe corrompue reste refusée. Aucune Task supplémentaire ni modale de
création n'est requise pour relancer une inférence réseau.

## Vérification

Les tests PostgreSQL couvrent les Tasks simples et les feuilles de plans, la conservation
des paramètres et des preuves. Les tests du vrai client HTTP avec frontière distante simulée
couvrent DeepSeek, Claude Agent, Codex et le transport générique : nouvel acteur après arrêt,
acteur déjà arrêté, acteur absent, arrêt refusé et délai dépassé. Les scénarios de récupération
automatique continuent d'exiger l'observation du même acteur sans soumission.
