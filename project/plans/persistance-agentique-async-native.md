# Persistance agentique asynchrone native et préparation du portage Rust

**Statut** `design`

Le runtime agentique doit pouvoir exécuter ses accès PostgreSQL avec un pilote asynchrone
natif, sans passage par Greenlet. Le premier lot vise le journal durable de l’inférence et
sa lecture par curseur. Il doit réduire le travail demandé à PostgreSQL sous charge et
laisser des contrats que le futur runtime Rust pourra reprendre sur les mêmes données.
La mise en œuvre de ce plan constitue une étape distincte.

## Point de départ

Galaris utilise déjà `asyncpg` derrière le moteur SQLAlchemy. L’inférence texte regroupe
les fragments avant écriture. Chaque lot journalisé contrôle l’autorité de la tentative,
verrouille l’appel, lit la dernière séquence et publie après le commit. Les vues de suivi
ont aussi leur propre cadence et leurs propres projections. Migrer le pilote et réduire
les accès PostgreSQL sont deux hypothèses à mesurer séparément. Le point d’accès ORM
responsable du `MissingGreenlet` historique reste à identifier avec son traceback.
[Configuration PostgreSQL](../../back/core/settings.py) ·
[Lots de l’inférence texte](../../back/app/llm/text_inference.py) ·
[Journal d’inférence](../../back/app/llm/inference_journal.py) ·
[Suivi des flux](../../back/app/llm/stream_updates.py)

## Frontière cible

- `app.llm` garde la responsabilité de l’admission, des appels physiques, du journal,
  des coûts et des commandes d’inférence. `app.task` et `app.conversation` restent
  propriétaires de leurs transitions, de leurs baux et des checkpoints de leurs exécutions.
  `app.agent` et les harnais passent par les façades et ports existants.
- La qualification sans Greenlet couvre à terme les chemins exécutés depuis l’admission
  jusqu’au résultat durable, y compris préparation du contexte, autorisations, outils
  internes, contrôles, supervision active et reprise. L’inventaire doit suivre les appels
  indirects aux autres domaines pour découvrir leurs accès à la base. Chaque lot annonce
  les parcours effectivement couverts. Le schéma et ses migrations restent gérés par
  DbAdmin pendant cette transition.
- Le pilote Python proposé est `asyncpg` direct. Un adaptateur par responsabilité reçoit
  des valeurs typées et possède la transaction d’une opération atomique. Les pilotes
  coexistent avec un budget total de connexions explicite. La préparation du payload,
  les attentes fournisseur et outil, et la diffusion réseau restent hors transaction.
  Le signal de publication suit le commit.

[Cycle de vie durable](../decisions/0097-durable-inference-lifecycle.md) ·
[Flux agentique](../../docs/fr/architecture/flows/agent-execution.md)

## Lots de travail

| Lot | Travail | Critère de réception |
|---|---|---|
| 1. Référence et inventaire | Figer un parcours reproductible et inventorier producteurs, lecteurs, transitions, accès SQL indirects et transactions partagées. Mesurer le journal, le suivi d’interface et le temps chez le fournisseur séparément. | Le scénario de départ à huit flux est reproductible et localise le coût entre attente du pool, verrous, SQL, sérialisation et diffusion. L’inventaire identifie les frontières déjà portables et les transactions à migrer ensemble. |
| 2. Pilote du journal | Migrer l’ajout par lot et la lecture par curseur sur le schéma actuel. Comparer d’abord le même SQL via le pilote natif, puis la réduction des lectures, écritures et commits. Étendre le pilote à la finalisation et aux écritures de coût liées si leur atomicité l’exige. | Le périmètre pilote passe ses scénarios avec le pont Greenlet interdit. Les lecteurs existants relisent les lots et les résultats terminaux. La variante retenue réduit le travail SQL ou le temps d’attente au-delà de la variabilité établie au lot 1, avec un p95 de mise à disposition des fragments et des commandes dans la tolérance fixée. |
| 3. Baux, checkpoints et contrôle | Migrer par opération complète l’admission, la pause, l’arrêt, la reprise, la récupération des baux expirés et les écritures de checkpoints. Séparer la progression d’affichage de la preuve d’un effet durable. | Un ancien worker est rejeté, un effet acquitté est repris sans rejeu, un résultat terminal reste immuable et chaque coût est compté une seule fois. Les scénarios avec observateur lent conservent le débit d’exécution. |
| 4. Couverture du runtime | Étendre aux chemins indirects recensés au lot 1, en commençant par les plus fréquents. Ajouter chaque parcours au test qui interdit le pont Greenlet et vérifier la charge mixte avec les requêtes ordinaires de l’application. | L’exigence sans Greenlet est satisfaite sur toute la frontière déclarée. Chaque exception encore inventoriée désigne un parcours restant à migrer. |

### Protocole du pilote

- Conserver le numéro de séquence de l’appel physique et le curseur de l’inférence
  lorsqu’un même run traverse plusieurs appels ou un repli fournisseur. Garder les
  formats versionnés existants, les droits de lecture, la rétention et un unique résultat
  terminal. [Schéma du journal](../../back/app/llm/models.py) ·
  [Lecture par curseur](../../back/app/llm/inference_execution.py)
- Tester un écrivain par tentative, appliqué à toutes ses écritures ordonnées de journal.
  Le contrôle du bail et l’ajout restent atomiques. Une séquence peut être réservée ou
  avancée durablement si les mesures le justifient. La reprise d’un lot dont le commit
  est incertain doit réconcilier son identité avant de réécrire. Les contraintes d’unicité
  protègent l’ordre, et la garde de propriété protège la succession des workers.
- Respecter l’ordre de verrouillage entre cycle de vie et appel. Revalider la lecture
  après attente sur un verrou avant de supprimer un aller-retour existant. Tester la
  concurrence entre ajout, reprise et finalisation avec deux connexions réelles.
- Conserver les signaux locaux existants pour le pilote. Évaluer `LISTEN/NOTIFY` si
  l’attente entre processus ressort des mesures. Le signal peut se perdre et les lecteurs
  rattrapent le journal par curseur. Un éventuel Redis relève d’une décision distincte sur
  la diffusion, avec un besoin établi sous charge.

## Compatibilité avec Rust

Le livrable durable comprend le protocole de persistance, les invariants SQL et un corpus
de conformité réutilisable. Le client `asyncpg` est l’implémentation Python de transition.
Les frontières échangent des identifiants, valeurs scalaires, dates, événements versionnés
et erreurs de domaine. Un adaptateur ne reçoit ni objet ORM, ni session, ni `ContextVar`,
ni instance SDK. Les payloads historiques propres aux fournisseurs gardent leur format
et leur interprétation actuels.

Conserver les opérations à la granularité du lot, de la commande ou de la transition.
Un futur adaptateur Rust doit pouvoir reprendre un lot complet, y compris son contrôle
d’autorité, son commit et le signal qui suit. Une connexion, une transaction et un écrivain
appartiennent à un seul runtime pour cette opération. La parité se vérifie sur les mêmes
fixtures versionnées et sur le même schéma PostgreSQL. Le choix d’une bibliothèque Rust,
d’un pont PyO3 ou d’un worker séparé reste dans la trajectoire Rust.

Le pilote prépare la référence du lot R00, les invariants des lots R05 et R07 et le portage
de la persistance du lot R11. Sa qualification n’attend pas une implémentation Rust.
La future bascule Rust doit toutefois relire les écritures Python et exercer les scénarios
d’interruption et de reprise sur des données historiques.
[Migration progressive vers Rust](migration-progressive-rust.md)

## Mesures, recette et retour arrière

- Rejouer le même corpus synthétique en Docker avec un flux puis huit flux simultanés,
  sans observateur puis avec des observateurs dont un lecteur lent. Inclure une charge
  prolongée, des requêtes ordinaires en parallèle, et des coupures pendant l’append, après
  le commit et avant le terminal. Fixer version, charge, matériel, taille des fragments et
  budget de connexions. Conserver les preuves brutes sous `artifacts/`.
- Relever les requêtes et commits par lot, les octets SQL, WAL et WebSocket, les attentes de
  connexion et de verrou, le délai fragment reçu → événement publié, le temps des requêtes
  ordinaires, le retard de la boucle, le débit, le CPU et la mémoire. Comparer les percentiles
  sur plusieurs passages. Le lot 1 fixe la tolérance de non-régression avant l’implémentation.
- Réutiliser les tests du cycle de vie et du protocole pour la perte de lease, la relecture,
  les commandes, les refus d’accès et les coûts. Ajouter les cas manquants au corpus partagé.
  La garde de test doit détecter un passage indirect par Greenlet, avec un contrôle qui la
  fait échouer sur le chemin historique. Une campagne synthétique et une qualification avec
  fournisseurs réels donnent des preuves distinctes.
  [Cycle de vie](../../back/tests/test_inference_lifecycle.py) ·
  [Flux de protocole](../../back/tests/test_protocol_inference.py)
- Qualifier le retour à l’adaptateur précédent sur la même base. Suspendre l’admission
  concernée, laisser finir les tentatives ou les arrêter selon leurs règles de reprise,
  puis réorienter les nouvelles. Démontrer la lecture des anciens et nouveaux lots, sans
  double écriture, perte de résultat ou appel fournisseur déclenché par la bascule elle-même.
  Toute évolution de schéma ultérieure passe par DbAdmin et exige sa propre preuve de compatibilité.
