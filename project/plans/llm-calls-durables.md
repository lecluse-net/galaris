# Inférences durables — extensions restantes

- Statut : `partial`
- Revue des sources : 2026-10-08.
- Contrats réalisés : [0097](../decisions/0097-durable-inference-lifecycle.md),
  [0095](../decisions/0095-pydantic-ai-request-ownership.md) et
  `app.llm.contracts/facade`.

## Évolutions à justifier par un consommateur

| Extension | Garantie et réception |
|---|---|
| Préparation sans démarrage | Persister une requête sans appel provider, puis démarrer explicitement ; identité/configuration/idempotence conservées, modifications avant gel définies. Crash création/démarrage, départ concurrent et annulation couverts. |
| Révision attendue des commandes | Conflit observable sans écrasement concurrent ; commande rejouée avec même reçu, compatibilité des clients. Pause/stop/resume, génération et réponse tardive couverts. |
| Échéance globale | Budget cumulé des tentatives, pause et redémarrage définis. Deadline physique existante conservée ; expiration sans preuve fictive d'arrêt distant ni relance implicite, fragments/coûts/incertitudes préservés. |
| Médias et autres entrées | Besoins durables embeddings/STT/realtime/génération/analyse, sérialisation et quotas/rétention ; URI et droits, historique/protocole sans perte, matière nécessaire au rejeu protégée. |
| Rejeu actif/incertain | Arbitrage explicite avec consentement/corrélation/conséquences, original conservé ; distinguer forçage, reprise et nouvel effet. |
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
