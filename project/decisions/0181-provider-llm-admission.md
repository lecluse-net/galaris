# 0181 — Admission prioritaire des appels LLM par fournisseur

Statut : accepté. Date : 2026-10-13.

## Garantie

Une connexion fournisseur possède une seule limite d'appels LLM tracés simultanés,
commune à ses modèles, profils et utilisateurs. Un fournisseur saturé ne bloque pas
les autres. La valeur 0 signifie illimité. Les appels vocaux puis textuels précèdent
habituellement le fond, avec vieillissement et rotation entre contextes pour éviter
une attente indéfinie.

## Décision

`LLMProvider.max_concurrent_calls` conserve le choix administrateur. Une valeur
historique NULL expose le défaut effectif : 10 pour le catalogue, dont OpenRouter,
1 pour les connexions personnalisées, dont Ollama. Les écritures partielles préservent
la valeur, y compris 0. Aucun compteur ne dépend du profil ou du modèle.

`app.llm.provider_scheduler` possède l'admission du worker unique imposé par
`back/entrypoint.sh`. Les inférences durables sont représentées par des tickets avant
claim ; seuls les tickets admis créent une racine d'exécution et son heartbeat. Chaque
appel physique consomme une place jusqu'à sa finalisation ; les outils ne la retiennent
pas. Un permis réservé avant claim est consommé par le premier appel, sans deuxième
acquisition. Un fallback vers un autre fournisseur libère une réservation inutilisée.

Les appels natifs passent par la même admission lors de la création de leur trace.
La transcription d'un dialogue reçoit la classe voix avant la création du round ; la
transcription d'un fichier reste dans le fond. Les transcriptions et images natives
finalisent également leurs traces lors d'une annulation. La fin d'une inférence nettoie
les réservations de tous ses appels physiques, y compris celles des retries.
Ils libèrent leur transaction avant attente et revérifient l'activation et l'autorité
d'abonnement avant départ. Annulation et erreurs ne doivent pas perdre de place. Les
commandes de file et l'échéance globale restent celles de l'inférence durable ; le délai
physique commence lorsque l'appel part effectivement.

À partir de trois places, une place voix et une place texte restent protégées. À deux
places, le fond est limité à une. À une place, l'admission est ordonnée mais ne préempte
pas un appel engagé. Les sessions de transport audio persistantes non tracées comme
LLMCall restent dans leur domaine ; elles ne sont pas comptabilisées comme des appels
physiques Chat/Responses.

Le journal du protocole regroupe les fragments pendant au plus 50 ms ou jusqu'à 64 Kio,
avec une queue de producteur bornée. Chaque lot est committé avant diffusion. Le journal
sémantique et son terminal unique restent conservés. Les contrôles d'arrêt restent
immédiats et les fragments déjà committés survivent aux interruptions.

## Vérification et limites

Les tests traversent SDK, proxy et PostgreSQL avec un fournisseur HTTP synthétique :
partage entre deux modèles et appel natif, changement à chaud, absence de claim avant
admission, arrêt/pause/expiration en file et restitution du stream. Les tests du scheduler
couvrent priorité, capacité protégée, annulation concurrente, vieillissement et isolement
des fournisseurs. Le navigateur isolé vérifie sauvegarde, valeur 0, réouverture et validation.

Le regroupement du journal se compare sur un même stream synthétique avant et après
correction : cinq commits de fragments de transport deviennent un commit, à réponse
identique. Cette mesure de transactions ne démontre pas un gain de latence en production.
Plusieurs backends indépendants nécessiteraient une réservation distribuée ; cette décision
préserve l'architecture mono-worker actuelle.
