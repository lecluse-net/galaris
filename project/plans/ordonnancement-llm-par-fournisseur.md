# Appels LLM — extensions de l'admission par fournisseur

- Statut : `partial`.
- Revue documentaire : 2026-10-20.
- Socle livré : [ADR 0181](../decisions/0181-provider-llm-admission.md).
- Contrat consommé : [inférences durables](../decisions/0097-durable-inference-lifecycle.md),
  complété par les [commandes et échéances](../decisions/0170-execution-scope-and-durable-controls.md).

## Socle actuel

`app.llm.provider_scheduler` partage la limite `max_concurrent_calls` d'une connexion
entre ses modèles et appelants. Le défaut effectif est 10 pour le catalogue et 1 pour
une connexion personnalisée, notamment Ollama ; zéro signifie sans plafond Galaris.
Le champ est administrable et les écritures partielles conservent sa valeur.

Les appels tracés utilisent une admission voix, texte puis fond, avec capacité protégée,
vieillissement et rotation entre contextes. Un stream conserve sa place jusqu'à sa
finalisation ; les outils ne réservent pas un run entier. Les inférences durables
attendent avant claim. Annulation, baisse/hausse à chaud et changement de fournisseur
nettoient leurs réservations. Le délai physique commence au départ ; l'échéance globale
reste celle de l'inférence. Ce coordinateur correspond au backend mono-worker fourni.

Les sources et tests sont dans `back/app/llm/provider_scheduler.py`,
`back/app/llm/tests/test_provider_scheduler.py` et les suites d'inférence durable.
Le [guide administrateur](../../docs/fr/admin/provider-admission.md) décrit le parcours
livré. La présence de tests ne qualifie pas tous les fournisseurs ou la charge réelle.

## Extensions à concevoir ou qualifier

| Écart | Critère de réception |
|---|---|
| Provenance typée exhaustive | Inventaire de chaque racine et preuve demandeur → appel → propriétaire → classe ; distinguer entrée vocale directe, fichier audio et travail issu d'une conversation. |
| Priorités configurables par opération | Registre stable traduit, validation serveur, défauts et remise aux défauts ; ne pas transformer les anciens rangs candidats en configuration déjà disponible. |
| Couverture de tous les transports | Identifier les sessions audio et générations distantes non représentées comme appels physiques tracés ; ne pas les annoncer couvertes par la limite actuelle. |
| Plusieurs backends | Coordination distribuée avant toute garantie de plafond global entre processus indépendants. |
| Diagnostics d'attente | Mesures comparables attente/départ/première sortie, distinction file et appel physique, réconciliation après interruption sans génération automatique. |
| Qualification fournisseur et charge | Exercices Ollama et fournisseurs distants autorisés, appels mixtes, saturation et retour au repos ; comparer débit, latence, mémoire et échecs sous les mêmes conditions. |

## Garanties à préserver

L'admission ne donne aucun droit et ne contourne ni budget, ni annulation, ni refus de
contenu, ni politique de rejeu. Une attente vivante ne doit pas être déclarée bloquée
par le watchdog Task. Un transport actif n'est pas préempté par une priorité plus haute.
Une réponse perdue après effet reste à réconcilier. Une baisse de concurrence n'atteste
pas à elle seule un gain de débit ; une priorité candidate ne remplace pas le contrat livré.

Renforcer les suites existantes avec des événements et barrières déterministes pour les
courses admission/annulation, streams, reprises, changements de configuration et extinction.
Publier les mesures et limites de chaque extension avant d'en annoncer la disponibilité.
