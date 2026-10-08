# ADR 0145 — Réveils du runtime après commit

- Statut : Accepted
- Date : 2026-09-27
- Complète [0097](0097-durable-inference-lifecycle.md).

## Décision

Le runtime mono-worker attend des notifications locales après commit au lieu de sonder
les inférences toutes les 250 ms et les conversations toutes les 500 ms. PostgreSQL reste
l'autorité durable ; les notifications ne portent ni messages, ni résultats, ni autorité.
Aucun broker ni changement de schéma n'est nécessaire dans la topologie actuelle.

`core.database.after_commit` regroupe les signaux par transaction. Une libération de
savepoint les transfère à la transaction parente ; rollback, fermeture et transaction
échouée les abandonnent. Une erreur de notification ne transforme pas un commit réussi en
échec applicatif. `watch_committed_changes` observe les insertions/suppressions ORM et les
colonnes choisies par chaque domaine. Les écritures SQL en masse ne passent pas par cet
observateur : un nouveau chemin de ce type doit enregistrer explicitement son réveil.

## Inventaire des producteurs et consommateurs

| Producteur durable | Réveil après commit | Consommateurs |
|---|---|---|
| Admission LLM, y compris `replay` | travail disponible et changement de l'inférence créée | worker et lecteurs |
| Réclamation d'une tentative | changement | lecteurs |
| Journal : message, résultat physique ou trame HTTP | changement | flux interne, adaptateur synchrone, Chat/Responses |
| Pause, arrêt, reprise | contrôle et changement ; travail supplémentaire pour la reprise | exécuteur, lecteurs, worker |
| Fin normale, erreur, annulation, interruption, récupération d'un bail expiré | changement et contrôle | lecteurs, ancien détenteur du bail |
| Task : insertion/suppression, phase, pause, affectation, retry, token de bail, suppression logique | travail Task | scheduler Task |
| Round : insertion/suppression, état, livraison, token de bail ; liens de messages et de travail ; reprises de livraison | travail Conversation | scheduler Conversation |
| Task : phase/libération du bail/tentative ; ProcessRun : état | travail Conversation | notifications de résultats |

Chaque lecteur LLM possède son propre signal et s'abonne avant de consulter la base. Il
efface le signal avant la lecture, jamais entre celle-ci et l'attente. Il vide les pages
du journal par curseur avant de se rendormir. Fermer un lecteur désabonne immédiatement
sa chaîne de générateurs, sans annuler l'inférence autonome ni les autres lecteurs.
La fin d'un exécuteur réveille la file, notamment si une reprise a été admise avant le
nettoyage de l'ancienne exécution. Les pages d'admission excluent les racines déjà lancées.

## Échéances et récupération

- Le bail LLM de 30 secondes est renouvelé toutes les 5 secondes ; les commandes le
  réveillent immédiatement et ne dépendent pas de ce délai.
- Le worker et les lecteurs LLM ont un rattrapage de secours de 30 secondes. Le worker
  recherche aussi les admissions et baux expirés au démarrage.
- Conversation conserve un rattrapage de 30 secondes pour les notifications manquées,
  les écritures externes et les baux expirés.
- Task conserve sa réconciliation de 15 secondes et attend plus tôt lorsqu'un retry
  persisté arrive à échéance. Les minuteries locales de retry restent prises en charge.
- Les maintenances conservent leur fréquence propre, sans scanner la file Task à chaque
  passage. Les heartbeats seuls ne réveillent pas les files observées.

Les écritures externes au processus restent couvertes par ces rattrapages, pas par un
bus interprocessus. Si la topologie change, un transport tel que `LISTEN/NOTIFY` devra
alimenter les mêmes réveils avec réconciliation après reconnexion.

La prise en charge Conversation verrouille directement le round `FROZEN` avec
`FOR UPDATE SKIP LOCKED`, sans verrouiller sa Room. Une actualisation Chat peut
verrouiller la Room juste après l'admission ; l'ignorer lors du réveil reporterait
le round au rattrapage de secours. L'unicité du round `FROZEN`, son verrou et
l'exclusion des rooms ayant déjà un round en traitement préservent la sérialisation
avec l'admission et les autres claimants. Aucun polling ni nouveau signal n'est ajouté.

## Vérification et limites

`test_inference_lifecycle.py` mesure les requêtes durant un fournisseur silencieux et
exerce les commits entre lecture et attente, plusieurs lecteurs, désabonnement, commandes
indépendantes du heartbeat, reprises, rejeux, pagination d'admission et récupération.
`test_protocol_inference.py` conserve les contrats HTTP et SSE.
`test_commit_notifications.py` couvre transactions, savepoints, rollback et échec d'un
callback. `test_scheduler_wakeups.py` couvre les mutations persistées, les retries et
l'absence de scans au repos malgré une maintenance périodique.
Il exerce aussi le scheduler réel pendant une actualisation Chat non committée,
avec le rattrapage éloigné pour qu'il ne masque pas un réveil manqué.
`test_room_never_claims_two_rounds_concurrently` utilise plusieurs connexions et
des claims simultanés, puis vérifie la conservation des inputs du successeur.

Le scénario synthétique de silence relève 24 requêtes SQL en 700 ms avant correction,
puis aucune sur la même fenêtre après correction. Ce résultat ne mesure pas la réduction
du CPU en production et n'attribue pas sa saturation au seul polling. Les tests antérieurs
vérifiaient les résultats et le volume de colonnes transférées, sans budget de requêtes au
repos ; ce budget renforce maintenant le scénario existant.
