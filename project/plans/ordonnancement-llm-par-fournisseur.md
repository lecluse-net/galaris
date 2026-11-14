# Appels LLM — extensions de l'admission par fournisseur

- Statut : `partial`
- Tri documentaire : 2026-11-14.

## Contrats à réutiliser

L'admission partagée, le contexte typé et la rotation par propriétaire sont réalisés :
[0181](../decisions/0181-provider-llm-admission.md),
[guide administrateur](../../docs/fr/admin/provider-admission.md),
`back/app/llm/admission.py`, `provider_scheduler.py` et leurs tests.
Les inférences durables conservent les contrats de
[0097](../decisions/0097-durable-inference-lifecycle.md)
et [0170](../decisions/0170-execution-scope-and-durable-controls.md).
Le coordinateur fourni est mono-worker.

Les racines tracées couvrent proxy Chat/Responses, décisions natives, transcription
à la demande, image native, médias spécialistes et embeddings publics.
Les embeddings internes, la synthèse vocale, les transcripteurs persistants et les
sessions audio natives ne sont pas tous couverts ; inventorier leurs contrats avant
de les intégrer. La couverture des racines ne prouve pas celle de chaque demandeur.

## Extensions à concevoir ou qualifier

| Écart | Critère de réception |
|---|---|
| Provenance typée exhaustive | Prouver chaque demandeur en amont et inventorier les opérations réellement anonymes. |
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
