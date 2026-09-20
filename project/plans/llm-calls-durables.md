# Inférences durables — extensions restantes

- Statut : `partial`
- Revue documentaire : 2026-09-19
- Contrat courant : [ADR 0097](../decisions/0097-durable-inference-lifecycle.md).
- Construction SDK : [ADR 0095](../decisions/0095-pydantic-ai-request-ownership.md).

La façade durable, les requêtes texte/structurées/protocole, le journal, les leases,
pause/stop/resume/replay et les pilotes existent. Leurs exemples d'implémentation ne sont
plus maintenus dans ce plan ; les signatures réelles de `app.llm.contracts` et `facade.py`
font foi. Les écarts providers restent suivis dans la
[convergence SDK](convergence-pydantic-ai.md).

## 1. Préparation sans démarrage

Vérifier un consommateur ayant besoin de persister une requête avant de l'exécuter, puis
définir la séparation création/démarrage sur les primitives actuelles.

- Aucun appel fournisseur avant démarrage explicite.
- Identité, autorité, configuration et idempotence conservées.
- Définir les modifications admises avant démarrage et leur gel ensuite.
- Qualifier crash entre création et démarrage, démarrage concurrent et requête annulée.

Les noms historiques proposés `create/start/submit` ne sont pas un contrat à implémenter
littéralement ni une raison de renommer la façade existante.

## 2. Commandes avec révision attendue

Définir la portée d'une révision attendue pour les commandes, le conflit observable et
la compatibilité des anciens clients. Une commande rejouée conserve son reçu ; une vraie
modification concurrente ne doit pas être écrasée. Couvrir pause/stop/resume concurrents,
changement de génération et réponse tardive.

## 3. Échéance globale

Distinguer échéance de l'inférence et timeout de transport. Définir le budget cumulé des
tentatives, son comportement pendant une pause et sa persistance après redémarrage.
Une échéance expirée ne prouve pas l'arrêt d'un calcul distant : conserver les fragments,
coûts et incertitudes, sans relance implicite.

## 4. Médias et autres formes d'entrée

Inventorier embeddings, transcription, realtime et génération/analyse média, puis étendre
par consommateur avec ses garanties propres.

- Préserver les URI canoniques, droits et matière effectivement nécessaire au rejeu.
- Distinguer résultat typé, blocs progressifs et trames de protocole.
- Définir sérialisation, quotas, rétention et protection des contenus complets.
- Qualifier normalisation et lecture sans perte des historiques/protocoles concernés.
- Réutiliser les intégrations publiques du SDK, sans constructeur privé recopié.

Les harnais conservent la propriété des effets d'outils ; cette couche ne reprend pas
automatiquement un effet engagé et ne promet pas une reprise au token exact.

## 5. Arbitrages complémentaires à justifier par un parcours

- Expliciter le rejeu d'une source encore active ou incertaine, distinct d'un simple
  forçage : tracer consentement, corrélation et conséquences sans effacer l'original.
- Mesurer la fréquence/taille de journalisation des blocs avant diffusion ; conserver la
  relecture sans imposer une transaction par token.
- Qualifier toute nouvelle intégration changeant protocole, éléments opaques ou compaction
  avant sa généralisation.

Les identités de reprise/rejeu, états et sorties typées déjà arrêtés par 0097 ne sont plus
des questions ouvertes. Une nouvelle proposition incompatible exige une décision explicite.

## Réception et clôture

Pour chaque extension : manque démontré, contrat public versionné, premier consommateur
complet, vraie persistance isolée, refus d'accès, concurrence, crash, relecture et coûts.
Réutiliser les suites d'inférence texte, structurée, protocole et cycle de vie ; remplacer
seulement le fournisseur externe. Préserver les requêtes et résultats historiques.

Les tests simulés ne qualifient pas les comptes réels. Avant publication demandée :
`make validate` sur l'instantané final. Retirer le plan lorsque les extensions retenues
sont traitées ou transférées ; ne pas maintenir un second manuel de l'API réalisée.
