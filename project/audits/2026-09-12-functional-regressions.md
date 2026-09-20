# Renforcement fonctionnel et régressions — 12 septembre 2026

## Méthode et périmètre

Les nouveaux scénarios partent de garanties observables : résultat durable, droits,
absence de doublon, comptabilisation, reprise et libération des ressources. Les workflows
utilisent les services du produit et PostgreSQL éphémère ; les fournisseurs et transports
externes sont remplacés. Les tests audio et les transitions de schéma utilisent les vrais
décodeurs et PostgreSQL/Atlas. Aucune modification du schéma produit n'est nécessaire.

Le seuil critique reste à 95 %, branches comprises. Le périmètre critique et ses exclusions
restent inchangés. La couverture complète mesure également les modules jamais importés ;
95 % critique ne signifie pas 95 % de toute l'application. Les changements simultanés
du worktree sont préservés ; les campagnes complètes utilisent des copies figées.

## Garanties renforcées

| Domaine | Garanties | Scénarios |
|---|---|---|
| Process | Admission idempotente, autorisation revérifiée, reprise bornée, suppression et conservation de l'historique, filtres/pagination, attente ajoutée tardivement, fichiers bornés et autorisés, export expurgé | `back/app/process/tests/test_lifecycle_workflows.py` |
| Concurrence Process | Deux transactions découvrent une seule exécution ; les collisions entre workflows sont refusées | `back/app/process/tests/test_worker_concurrency.py` |
| Médias | Soumission facturable unique, fournisseur admis immuable, reprise d'un téléchargement partiel, reçus durables, refus d'une réparation ambiguë, événements tardifs sans effet | `back/app/multimedia/tests/test_multimedia.py` |
| Lab | Publication et coût uniques, ancien propriétaire refusé, annulation conservée, modèle absent signalé sans substitution, sortie candidate préservée sans juge | `back/app/lab/tests/test_publication_guarantees.py` |
| DbAdmin | Contribution invalide refusée avant SQL, indépendance des contributions, ordre de dépendances, simulation sans journalisation, verrou exclusif, diagnostic conservé, ajout/rejeu de valeurs enum sans perte | `back/core/dbadmin/tests/test_dataset_guarantees.py`, `test_operator_guarantees.py`, `test_postgresql_transitions.py`, `test_transitions.py` |
| Runtime | Démarrage annulé, nettoyage en échec ou expiré, récupération sans double worker, maintien des autres services et santé publique sans secrets | `back/core/tests/test_runtime.py` |
| Sessions et tâches | Famille révoquée non ressuscitée, compte inactif refusé, expiration et rotation, filiation cyclique refusée et admission sans agent impossible | `back/core/user/tests/test_refresh_session.py`, `back/app/task/tests/test_budget.py` |
| Stockage et transferts | Limites vérifiées avant consommation, budget libéré, contenu précédent préservé après erreur, chemins et liens symboliques confinés | `back/app/memory/tests/test_storage.py`, `back/core/util/tests/test_byte_budget.py`, `test_http_buffer.py`, `test_transfers.py` |
| Audio | Décodage réel, durée/amplitude préservées, fragmentation PCM, entrée vide ou invalide, annulation avec fermeture après la fin du thread | `back/app/voice/tests/test_audio_streaming.py` |

## Défauts reproduits puis corrigés

1. **Réponse de démarrage après callback terminal.** Six combinaisons succès/erreur/annulation
   et réponse perdue/acceptée échouaient : l'erreur ou l'identité distante finale était
   écrasée. Le résultat terminal prime désormais sur la réponse de démarrage ; le job est
   clos sans relance. Deux mutations distinctes réintroduisent les branches fautives.
2. **Diagnostic DbAdmin perdu.** Une synchronisation contenant des erreurs insérait les
   détails avant leur parent et violait la clé étrangère. Un flush du parent précède
   désormais les détails dans la même transaction. Le scénario vérifie le dernier verdict
   et les bornes de 100 détails et 4 000 caractères.
3. **Découverte Process concurrente.** Après le conflit d'insertion, le rollback expirait
   l'objet Tool ; sa relecture implicite déclenchait `MissingGreenlet`. Les valeurs utiles
   sont capturées avant le commit et la propriété du workflow est revérifiée à la reprise.

`project/regressions.json` relie ces défauts aux tests JUnit et aux mutations. La campagne
de mutations réexécute d'abord chaque scénario sans défaut, puis exige un échec comportemental
après réintroduction du défaut dans une copie jetable.

## Validation

Les campagnes intermédiaires complètes ont donné 3 986 tests réussis et 91,03 % critique,
puis 4 056 tests réussis et 94,86 % critique. La campagne finale figée se trouve dans
`artifacts/validation/functional95.3SOGHq/` ; les traces avant/après et les contrôles sont
conservés dans son sous-dossier `evidence/`.

| Contrôle final | Résultat |
|---|---|
| `make tests-coverage` | **4 069 réussis, 1 ignoré**, 213,77 secondes de suite ; 223 scénarios supplémentaires par rapport aux 3 846 du départ |
| Couverture critique combinée | **95,60 %** : 3 500 / 3 610 lignes et 951 / 1 046 branches ; seuil de 95 % franchi |
| Couverture backend complète | **75,35 % des lignes**, **57,51 % des branches**, y compris les sources jamais importées |
| Seuils par domaine | Aucun seuil critique ni global en recul |
| `make coverage-check COVERAGE_DIFF_BASE=HEAD` | Toutes les branches critiques modifiées sont couvertes |
| `make tests-mutations` | **13 / 13 défauts détectés**, baseline verte avant chaque injection |
| `make regression-check` | 4 régressions reliées à des tests réussis et mutations détectées |
| `make typecheck` | Pyright strict, vue-tsc, **227 tests frontend** et parité des catalogues : succès |
| `make lint` | Ruff et ESLint : succès |
| `make architecture-check` | Cartographie à jour ; échec préexistant sur la parité FR/EN de `features.md` (blocs, titres, liens) |
| `git diff --check` | Succès |

Le cas ignoré est la qualification DbAdmin sur table volumineuse, activée explicitement
avec `DBADMIN_LOAD_TEST=1`. Aucun modèle ni schéma produit n'a été modifié dans cette campagne.

Le qualificatif « tous les tests manquants » ne constitue pas une garantie vérifiable :
cette campagne ferme des lacunes identifiées et conserve la mesure complète des autres
domaines, sans prétendre qualifier les services externes réels ni éliminer tout défaut futur.
