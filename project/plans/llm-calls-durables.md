# Inférences durables — extensions restantes

- Statut : `partial`
- Revue des sources : 2026-10-11.
- Contrats réalisés : [0097](../decisions/0097-durable-inference-lifecycle.md),
  [0095](../decisions/0095-pydantic-ai-request-ownership.md) et
  `app.llm.contracts/facade`.

## Évolutions à justifier par un consommateur

Le lot [0170](../decisions/0170-execution-scope-and-durable-controls.md) réalise
`prepare_inference`, l'admission HTTP `prepared=true`, la commande `start`, les révisions
attendues et `deadline_seconds`. La requête est gelée dès la préparation ; une modification
demande une nouvelle identité. L'échéance inclut attente et pauses, sans budget renouvelé
à la reprise. Le rejeu reste une commande explicite qui conserve l'original.
Les suites durables couvrent refus d'accès, concurrence, idempotence, expiration et journal
partiel ; elles remplacent le fournisseur, sans qualifier un compte réel.

| Extension | Garantie et réception |
|---|---|
| Médias et autres entrées | Besoins durables embeddings/STT/realtime/génération/analyse, sérialisation et quotas/rétention ; URI et droits, historique/protocole sans perte, matière nécessaire au rejeu protégée. |
| Consommateurs du rejeu actif/incertain | Le rejeu explicite crée une autre inférence et peut doubler la facturation ; qualifier l'information/consentement de chaque futur consommateur avant son exposition. Aucun effet d'outil rejoué automatiquement. |
| Journal progressif | Mesurer fréquence/taille des blocs avant optimisation ; relecture fidèle sans transaction imposée par token. |

Les noms create/start/submit sont d'anciennes propositions, pas des API à implémenter
littéralement. Les entrées Chat/Task natives de
[0126](../decisions/0126-native-multimodal-inputs.md) existent.
Les harnais gardent les effets d'outils ; aucun rejeu automatique d'effet engagé ni
reprise au token exact promis. Identités, états et sorties arrêtés par 0097 ne sont
plus des arbitrages ouverts.

## Dépendances et clôture

La [convergence SDK](convergence-pydantic-ai.md) possède les protocoles/providers et
l'[ordonnancement fournisseur](ordonnancement-llm-par-fournisseur.md) l'admission physique.
Pour chaque extension : manque démontré, contrat versionné, premier consommateur complet,
persistance isolée, refus d'accès, concurrence, crash, reprise, relecture et coûts.
Réutiliser suites texte/structurée/protocole/cycle durable ; remplacer seulement le provider.
Retirer les extensions réalisées ou transférées ; recette simulée et compte réel
restent des preuves distinctes.
