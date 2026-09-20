# Corrections de l'audit du 5 septembre 2026

**Statut : les 20 constats sont traités ; validations réussies.**

Suivi des 20 constats de [l'audit initial](2026-09-05-application.md).
Les changements déjà présents ont été conservés ; les corrections concurrentes de tests,
de sécurité temps réel et de documentation Topics ont été intégrées à la validation.

## État par constat

| Constat | Correction | Régression principale |
|---|---|---|
| AUD-01 | Normalisation Unicode, conservation des marques non latines, aucun réemploi sur deux chaînes normalisées vides | `app/topic/tests/test_unicode_reuse.py` : chinois, cyrillique, hindi, accents et emojis |
| AUD-02 | Une lecture distante incomplète renvoie explicitement une disponibilité inconnue ; le cache ne prouve plus qu'un créneau est libre | `bridge/calendar/tests/test_service.py` : panne avec et sans cache, disponibilité et créneaux |
| AUD-03 | Calcul sur tous les événements ; plafond de 500 réservé à l'affichage ; dépassement du parseur signalé explicitement | Même suite : événement bloquant après 500 événements transparents |
| AUD-04 | Reçus et curseur atomiques ; snapshot chiffré ; lease récupérable ; soumission Task/Process idempotente et reprise des erreurs | Même suite : interruption avant/après persistance, panne distante, perte du reçu de Task et expiration du lease |
| AUD-05 | Assemblage des albums Telegram en relisant depuis le premier update non traité, sans acquittement anticipé | `bridge/telegram/tests/test_messenger.py` : offsets inchangés pendant l'assemblage |
| AUD-06 | Résolution des attentes sur toutes les annulations et erreurs terminales de refresh | `app/process/tests/test_recovery.py` : quatre chemins d'annulation et épuisement du refresh |
| AUD-07 | Marqueur durable de résolution ; réparation par callback dupliqué, refresh et scheduler, y compris après clôture de l'enfant | Même suite : interruptions à chacune des frontières de finalisation |
| AUD-08 | `cancelling` reste éligible au polling après une erreur réseau d'annulation | Même suite : échec de cancellation suivi d'une confirmation par polling |
| AUD-09 | Désinscription OneBot conditionnée à l'identité du socket qui se ferme | `bridge/one_bot/tests/test_hub.py` : deux connexions successives, fermeture de l'ancienne |
| AUD-10 | Envoi OneBot inclus dans le `try/finally` ; Future retirée et annulée après échec ou annulation | Même suite : erreur réseau et `CancelledError` |
| AUD-11 | Lecture WhatsApp en flux, arrêt avant d'accumuler un chunk dépassant la limite | `bridge/whatsapp/tests/test_router.py` : corps sans longueur et longueur mensongère |
| AUD-12 | Rejet HTTP 400 des valeurs JSON non objet et de l'UTF-8 invalide avant dispatch | `app/webhook/tests/test_router.py` : tableau, null, nombre, chaîne et octets invalides |
| AUD-13 | Arbitrage retenu : coût facturé historique issu de `LLMCall.cost` pour toutes les agrégations | `app/dashboard/tests/test_dashboard_service.py` : modifier l'abonnement ne change plus les totaux ni les ventilations |
| AUD-14 | Conflit métier traduit en HTTP 409 lors d'une suppression empêchée par une FK ; ressources préservées et langue conservée après rollback | `core/user/tests/test_admin_invariants.py` : agent actif ou archivé, réponse HTTP en français |
| AUD-15 | Utilisateurs paginés/recherchés/triés côté serveur ; arbres d'agents chargés sur toutes les pages ; Topics recherchés côté serveur avec chargement progressif | Tests utilisateurs au-delà de 500 ; tests frontend `agentService.test.mjs` et `TopicSelect.test.mjs` |
| AUD-16 | Dernier administrateur actif protégé pour comptes et affectations, avec verrou commun ; rôle intégré et droits protégés | Tests utilisateurs HTTP, DB et deux transactions concurrentes |
| AUD-17 | Langue enregistrée lors de la création administrative | Test de création en chinois |
| AUD-18 | Documentation Topics ajoutée par le travail concurrent, signatures vérifiées et test de couverture exécuté | `app/skill/tests/test_storage.py` |
| AUD-19 | Cartographies françaises et anglaises régénérées depuis le code ; parité des liens documentaires rétablie | `make architecture-check` réussi, dont 27 tests |
| AUD-20 | Fixtures concurrentes conservées, nouveaux tests ajoutés, compatibilité des appels de création sans clé maintenue | Suite complète : 3 061 succès ; dernière régression utilisateurs : 8 succès |

> Note de revue sur AUD-08 : « oui il faut corriger ça ».

## Validations finales

| Commande | Résultat |
|---|---|
| `make tests` | 3 061 tests réussis, aucun échec, 12 warnings |
| `make tests ARGS='core/user/tests/test_admin_invariants.py'` | 8 tests réussis après le dernier ajustement du cache utilisateur après rollback, dont le nouveau cas HTTP localisé |
| `make typecheck` | Pyright strict : 0 erreur ; vue-tsc réussi ; 321 tests frontend réussis ; parité i18n réussie |
| `make project-context` | Quatre cartographies régénérées |
| `make architecture-check` | Cartographie à jour, frontières respectées, 27 tests réussis |
| `make sync-db` | Développement : convergence réussie, sans redémarrage |
| `git diff --check` et contrôle des nouveaux fichiers | Aucun défaut d'espacement |

Le dernier changement de production après la suite complète vide le cache utilisateur
après un rollback de suppression. Sa validation ciblée garantit une réponse HTTP 409
dans la langue de l'utilisateur, avec les autres invariants administrateur.
Les avertissements de la suite complète restent visibles ; ils ne sont pas des échecs.

## Contrats retenus

- [ADR 0067](../decisions/0067-durable-calendar-and-process-recovery.md) : reprise des calendriers et attentes Process.
- [ADR 0068](../decisions/0068-historical-dashboard-costs.md) : coût historique stable.
- [ADR 0069](../decisions/0069-preserve-administrator-access.md) : protection de l'accès administrateur.

La base de développement a été synchronisée avec `make sync-db`, sans redémarrage.
Les quatre nouveaux champs techniques sont le snapshot chiffré, le token et l'expiration
de lease du calendrier, ainsi que le marqueur de résolution d'attente du Process.

## Limites de reprise

Les événements Telegram déjà acquittés puis perdus avant ces corrections ne peuvent pas
être récupérés automatiquement. Un ancien reçu Calendar sans snapshot ne permet pas de
reconstituer un événement distant disparu ni de prouver l'absence d'un ancien effet sans reçu.
Les nouveaux reçus disposent du protocole durable de reprise. La fenêtre existante de découverte
Calendar reste de sept jours ; les reçus déjà persistés n'expirent pas avec cette fenêtre.

La collecte Telegram ne fait jamais avancer l'offset pendant l'assemblage. Un album à cheval
sur une réponse pleine du fournisseur peut rester réparti sur plusieurs messages canoniques,
mais ses updates ne sont plus acquittés avant traitement.

Les intégrations réelles, les comptes externes et les parcours E2E manuels n'ont pas été utilisés
pour valider ces correctifs. Les garanties de reprise sont testées par injection d'interruptions
et, pour la concurrence administrateur, avec des connexions PostgreSQL indépendantes.
