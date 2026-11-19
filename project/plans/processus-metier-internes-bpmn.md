# Processus internes — extensions du runner et qualification

- Statut : `partial`
- Tri documentaire : 2026-11-14.
- Objectif restant : Python généraliste fortement isolé, intermédiaire de capacités,
  worker Process distinct et qualification avancée.

## Contrats réalisés à réutiliser

Le profil natif, les variables typées, les entrées/sorties locales, leur intégration
idempotente, les jobs MCP/REST, les enfants et la convergence sont décrits dans la
[décision 0174](../decisions/0174-native-document-backed-business-processes.md),
le [guide du profil natif](../../docs/fr/dev/native-processes.md),
le [parcours utilisateur](../../docs/fr/user/internal-processes.md) et le
[catalogue des tests](../../docs/fr/dev/functional-tests.md).

`IsolatedCodeRunner` dispose déjà de l'adapter Monty pour les computations Python
pures : worker neuf, snapshot JSON détaché, limites et absence de capacités hôte.
Réutiliser `back/app/process/isolated_code.py` et les scénarios de
`tests/test_decisions.py` et `tests/test_native_bpmn.py`.
Ce sous-ensemble n'est ni du CPython généraliste, ni le runner distant avec broker.
Les limites et garanties du code courant ne sont pas une qualification de cette extension.

Les définitions BPMN, données et fichiers de runs appartiennent à Process. Aucun
Dataset documentaire ne devient leur stockage. Les petites applications HTML du
[plan documentaire](programmes-documentaires-json.md) ont un autre runtime.
La capacité REST existante de Services et ses connexions sont réutilisées selon
[0182](../decisions/0182-tool-rest-capability.md).

## Lots ouverts et réception

Chaque lot termine par un parcours complet avant généralisation.

Une première implémentation relie le type `python` au superviseur TLS sur hôte dédié
et aux capacités MCP/REST déclarées par activité. Le mode par défaut intègre variables
et références de fichiers. Le worker dédié est supervisé par l'API, avec lectures
passives et slots indépendants pour ses appels longs. L'isolation et le redémarrage du
superviseur ont été vérifiés sur le runtime `runsc` réel dans une VM dédiée jetable.
Voir le [contrat d'intégration](../../docs/fr/dev/native-processes.md#python-capabilities).

| Lot | Travail restant | Réception |
|---|---|---|
| Runner distant | Reproduire la qualification et l'endurance sur l'infrastructure de déploiement cible. | Limites et budget de ressources vérifiés sur le profil cible. |
| Consommateurs | Campagnes assemblées avec des harnais externes et des volumes métier représentatifs. | Réponses, ressources, droits et interfaces préservés avec les comptes de qualification et leur charge réelle. |

`make qualify-process-python` inclut un lot reproductible de 112 calculs à quatre en parallèle
et enregistre le rapport agrégé de débit et de latence. L'exécution de ce lot sur le runner
cible reste à qualifier.

### Point de reprise du 18 novembre 2026

- Acquis : endurance de cinq minutes sur VM de qualification, récupération d'un reçu
  File Sharing perdu et parcours BPMN → n8n réel → BPMN. Les environnements
  jetables ont été supprimés.
- Vérifications : 11 scénarios TLS, 184 tests de régression ciblés et 94 tests
  d'adaptateurs de harnais réussis. `make typecheck` et `git diff --check` réussis.
  Le corpus et les contrats d'architecture ont passé les contrôles sur instantané.
  Des modifications concurrentes ont interrompu la publication de la cartographie.
- Le 19 novembre, le premier fournisseur REST qualifié est n8n Data Tables. Après une
  perte simulée de reçu, l'API n8n 2.48.5 a confirmé la ligne d'origine par lecture seule
  et le Process a terminé son arrêt. Le test vérifie une seule insertion. Voir le
  [contrat et la commande de qualification](../../docs/fr/dev/native-processes.md#réconciliation-dune-insertion-n8n).
- À la reprise, identifier l'infrastructure cible et les comptes de qualification
  des harnais externes.

### Qualification locale du parcours Claude Agent

`make qualify-process-harness` relie le moteur BPMN v2, le scheduler Task, le SDK Claude
Agent épinglé et le serveur MCP Galaris. Les scénarios vérifient les sorties valides et
invalides, la lecture du contenu via son URI, la remise d'un reçu MCP sans accord
supplémentaire en mode Actif et sa conservation après un accord en mode Sur demande.
La reprise observe le même run agentique et le contexte révoqué refuse un appel tardif.
L'annulation pendant un accord MCP vérifie l'arrêt du SDK, le refus d'un accord tardif
et le maintien de l'état `cancelling` si la première confirmation d'arrêt se perd.
Le modèle est synthétique. La qualification des comptes et de la charge métier sur
l'infrastructure cible reste ouverte.
Les campagnes **Lab → Processus** disposent d'une vérification agrégée avec
`make qualify-lab` et `--process-campaign`. Elle contrôle toutes les pages, les sorties
attendues et la révision BPMN. Voir le [parcours de qualification](../../docs/fr/dev/testing.md#qualification-des-modèles-et-des-bridges).

### Qualification du runner sur VM dédiée

Le 18 novembre 2026, le superviseur et la sandbox ont tourné dans une VM Debian 12
x86-64 avec un noyau 6.1, Docker 20.10 et gVisor `release-20261116.0`. La VM n'avait
aucun port publié sur l'hôte. Le transport entre le backend de test et le superviseur
validait le certificat et le nom DNS de bout en bout.

- Les sondes ont vérifié la racine en lecture seule, le stockage temporaire privé,
  le réseau sans sortie et l'absence de montages de données. Un certificat non approuvé,
  un nom DNS incorrect et un jeton absent ou erroné empêchent l'accès.
- Le premier démarrage échouait avec le plafond de seize tâches du groupe Docker.
  Le groupe Linux d'une sandbox active a confirmé les plafonds de 128 tâches,
  128 Mio de mémoire et un demi-cœur. gVisor a refusé un dix-septième processus
  ou thread du programme et une écriture dépassant les 8 Mio de `/tmp`.
- Une sortie hors limite produit un reçu d'erreur avec arrêt confirmé. Quatre
  exécutions simultanées ont été admises, la cinquième a reçu HTTP 429 et a réussi
  après libération des places. Aucun conteneur de sandbox ne subsistait après le test.
- Après un `SIGKILL` du superviseur alors que la sandbox tournait sous `runsc`,
  le redémarrage a supprimé la sandbox. La consultation et le rejeu de la requête
  ont rendu le même reçu terminal sans relancer l'exécution.
- Une suspension du daemon Docker pendant 38 secondes a reproduit un blocage
  au-delà des trois tentatives de nettoyage initiales. Après correction, le même
  superviseur a supprimé la sandbox dès le retour de Docker et a enregistré un reçu
  d'annulation stable. Le reçu est resté en attente pendant l'indisponibilité.
- Le parcours BPMN a transmis une variable et un fichier à Python. Après la perte
  simulée d'une réponse du broker et l'interruption de la clôture de la Task, le MCP
  de fichiers a créé une seule sortie, consommée par l'activité suivante.
- Sur la même VM jetable, le broker REST a utilisé la connexion de l'agent affecté,
  distinct de l'agent lanceur, sans restituer ses identifiants au script. La révocation
  REST a empêché tout appel, et celle du droit MCP a prévalu sur un accord donné.
  Une réponse REST perdue après l'effet a laissé un seul appel externe, une sandbox
  arrêtée et un Process en attente de réconciliation.
- Sur VM, un appel présenté au seuil de quinze minutes, simulé avec l'horloge du
  broker, a déclenché zéro requête externe. Une redélivrance exacte du reçu courant
  a conservé le résultat. Le rejeu d'une ancienne identité et la réutilisation d'une
  identité avec d'autres arguments ont été refusés sans nouvel appel au Service.
- Si la sandbox s'arrête après un appel REST admis mais avant la réception du résultat,
  le suivi conserve désormais `effect_outcome_unknown`. L'inspection signale le blocage
  et le debugger refuse Reprendre et Pas à pas. La clôture de l'incertitude reste
  ouverte quand aucune preuve du résultat n'est disponible côté Service.
- Une charge courte sur la VM QEMU émulée a terminé 40 exécutions de calcul en
  119 secondes, à quatre en parallèle, sans conteneur résiduel. Du dépôt de la requête
  au reçu terminal, la médiane était de 11,8 secondes et le p95 de 16,6 secondes.
  Le fichier SQLite des reçus est passé de 12 à 24 Kio pendant ce test.
- Sur ce même profil QEMU, 112 exécutions synthétiques ont terminé en 301 secondes
  à quatre en parallèle, sans sandbox résiduelle. Du dépôt au reçu, la médiane était de 9,8 secondes
  et le p95 de 14,0 secondes. Le fichier des reçus est passé de 12 à 44 Kio. Les mesures
  ponctuelles ont observé jusqu'à 28,1 Mio par sandbox et le quota d'un demi-cœur.

### Reçu tardif et modification concurrente

Dans des sessions PostgreSQL séparées, un reçu REST arrivé tardivement a permis de
terminer l'arrêt sans nouvel appel au Service de test ni écrasement d'une mise à jour
concurrente des données. L'inspection retire le blocage actif et conserve le diagnostic
historique. Quand le run reste actif, le même parcours intègre le résultat du broker
et la mise à jour concurrente. Le test utilise un fournisseur HTTP synthétique et un
transport runner simulé.

### Intégration n8n, profondeur et pagination

Un n8n 2.48.5 isolé a reçu une valeur d'un BPMN parent et a retourné sa transformation
via le bridge. Un second BPMN a consommé cette valeur. Une lecture anticipée laisse
désormais l'admission au worker et ne fait pas basculer le run enfant en `unknown`.
Les tests PostgreSQL couvrent aussi cinq niveaux de boucle avec 24 activités persistées
et l'inspection de 505 occurrences par page bornée à 500. Les suites des adaptateurs
Codex, Claude Agent et Hermes vérifient les contrats de reprise et d'arrêt en test.

## Intermédiaire de confiance pour MCP et REST

Le programme demande une opération par un protocole limité. Un intermédiaire côté Galaris :

- retrouve côté serveur l'agent, le run, l'occurrence et la tentative ; aucun `agent_id`
  fourni par le code ne fait autorité ;
- accepte uniquement les capacités attachées à cette exécution, avec références temporaires,
  non réutilisables par un autre agent/run et révoquées à la fin ;
- résout les connexions actives et secrets côté serveur ; le runner ne reçoit pas les tokens ;
- conserve les modes et autorisations MCP existants, y compris après une attente ;
- vérifie pour REST la propriété de la connexion et son activation : les droits des endpoints
  appartiennent au tiers selon le token, sans catalogue obligatoire, filtre d'URL métier ou
  permissions fines Galaris ;
- enregistre intentions et reçus. Un redémarrage ne rejoue pas les appels précédents d'un
  programme dont les effets sont incertains.

### Preuve requise pour réconcilier un effet sans reçu

Le broker connaît la tentative, l'identifiant de l'appel et l'empreinte des arguments.
Ce lien suffit à remettre le reçu du worker qui avait déjà pris en charge l'appel. Pour
une réponse définitivement perdue, le Service doit aussi disposer d'une référence de
corrélation reconnue par le fournisseur et fixée avant l'envoi. La preuve de résultat doit
porter sur cette référence, le Service et le même compte distant. Le chemin de vérification
appartient au Service et doit pouvoir être utilisé en lecture seule.

| Résultat établi par le fournisseur | Comportement attendu du Process |
|---|---|
| Effet confirmé ou rejet définitif documenté pour la référence exacte | Conserver un reçu lié à l'appel d'origine et terminer l'arrêt une fois les activités arrêtées. Le reçu ne relance ni la sandbox ni une étape suivante. |
| Absence d'effet attestée explicitement pour cette référence | Enregistrer le résultat et clôturer l'incertitude. Une nouvelle exécution passe par l'autorisation ordinaire. |
| Traitement en cours, référence inconnue ou réponse sans preuve définitive | Maintenir `effect_outcome_unknown` et laisser le suivi visible. Un délai dépassé ou un HTTP 404 générique ne prouve pas l'absence d'effet. |

File Sharing fournit une première preuve pour `file_create` approuvé vers `file://`.
Le journal de Services confirme la création pour l'identité exacte de l'appel. Le moteur
enregistre la preuve et clôt la Task de contexte à partir de ce reçu. Le test de perte
du reçu broker vérifie un seul fichier créé et refuse les preuves d'un autre agent,
d'une autre tâche ou d'une autre opération. Une capacité REST générique sans moyen de
recherche fiable côté fournisseur conserve son blocage. Le premier contrat REST couvre
une insertion unitaire dans une Data Table n8n. La recherche filtrée est bornée à deux
lignes et confirme uniquement une correspondance unique sur la référence et les valeurs
d'origine. La suite synthétique exerce le refus des preuves contradictoires et une
redélivrance concurrente aboutissant à un seul reçu.

Réutiliser `app.services.execute_rest_request`. Le confinement à l'adresse configurée
protège les identifiants ; il est distinct des permissions métier du tiers.
Les réponses rendues au programme ne restituent pas les secrets de transport.
Le code utilise les capacités de son exécutant, jamais celles de son auteur.

## Déploiement du worker et du runner

```text
API/MCP → admission durable en base → worker Process de confiance
                                      ↕ protocole borné et authentifié
                               runner sur VM/hôte dédié
                                      └─ sandbox jetable par exécution
```

Le worker peut réutiliser l'image backend ; le runner possède une image minimale
sans les accès de Galaris. Les limites techniques ne deviennent pas des budgets
métier cumulés de Process. Les workflows gardent leur convergence ordinaire,
leurs terminaux et leur arrêt à la première erreur.

## Isolation de l'extension généraliste

Tout code éditable est non fiable, même produit par un agent. Pour cette extension,
un sous-processus partageant les accès du backend ne constitue pas la frontière retenue.

### Déploiement et frontières

- Runner sur une VM ou un hôte distinct du serveur Galaris, avec isolation supplémentaire
  entre exécutions. Qualifier une frontière système de type microVM ou équivalent ;
  un conteneur Docker ordinaire seul ne satisfait pas l'exigence d'isolation forte.
- Aucun montage des sources, volumes, sockets Docker ou répertoires de Galaris ; aucune
  variable d'environnement, session humaine ou clé serveur de Galaris dans le runner.
- Aucun accès de la sandbox à PostgreSQL, au réseau interne, aux métadonnées de l'hébergeur
  ou à Internet. Le superviseur transporte les demandes vers l'intermédiaire ; le code
  ne reçoit pas de réseau direct.
- Protocole authentifié, lié à l'exécution, borné en taille/fréquence ; aucune interpolation
  du code ou des données dans une commande shell. Séparer résultats non fiables, contrôle
  et diagnostics pour empêcher la falsification d'un reçu depuis les sorties du programme.
- Identité technique du runner limitée à ses exécutions ; aucune capacité administrative
  générale ou identité d'agent permanente dans la sandbox.

### Cycle de vie et limites

- Environnement vierge et jetable par exécution, sans état partagé entre agents/runs/tentatives.
  Matérialisations de fichiers minimales, temporaires, bornées et détruites après usage.
- Compte non privilégié, système en lecture seule hors temporaire autorisé, capacités
  retirées, protections système actives ; aucun mode privilégié pour le code.
- Limites serveur de CPU, mémoire, processus, durée, stockage, sorties et concurrence,
  à mesurer avant fixation ; le programme ne peut pas les augmenter.
- Superviseur extérieur capable d'interrompre et détruire l'environnement même si le
  runtime boucle ou sature ; libérer les capacités après arrêt confirmé.
- Nettoyage après succès, erreur, annulation, crash et redémarrage ; aucune donnée d'une
  autre exécution accessible depuis un environnement recyclé.
- Réconcilier l'identité distante avant reprise. Si l'arrêt ou l'effet demeure incertain,
  conserver le diagnostic sans relancer le programme ou l'appel externe.


### Qualification du runtime et du protocole

Qualifier la version de Python, les opérations de données, fonctions externes,
annulation et limites dans cette architecture, puis verrouiller les dépendances.
Le Monty pur existant ne démontre pas la sécurité d'un runtime doté de capacités.
Aucun shell arbitraire, installation libre de dépendances ou accès direct aux secrets.

Inventorier hébergement, mises à jour et canal avec Galaris. L'exécuteur IDE a un
autre contrat : aucun réemploi sans qualification. Une frontière indisponible refuse
l'extension avec diagnostic ; aucun repli automatique vers le backend.

## Vérifications et clôture

Réutiliser les tests de codec, intégration, convergence, annulation et droits.
Avec le vrai runner, injecter les pannes entre résultat, écriture et reçu ;
tester sorties excessives, boucle infinie, usurpation d'identité/reçu, nettoyage,
reprise, deux exécutions isolées et révocation des capacités. Garder les fixtures
entièrement synthétiques.

Mesurer démarrage de sandbox, latences, CPU/mémoire, débit et croissance des données
et journaux sous concurrence. Exercer un parcours assemblé avec un service tiers
synthétique : erreurs, conflit, réouverture, droits, clavier et petit viewport.
Les campagnes hybrides et mocks d'applications restent dans le
[plan Lab](lab-evaluation-mecanismes-ia.md).

Extensions différées conservées : contraintes internes de structure/homogénéité des
conteneurs typés, annotations/métriques extensibles et comparaison de runs lorsqu'elles
manquent, contrôle métier supplémentaire du résultat, FOR parallèle, déclencheurs,
compensation et compatibilité transitive avancée. Le suivi automatique des jobs REST,
les callbacks spécifiques et les programmes serveur réutilisables demandent leur
propre contrat. Aucun CATCH/retry ou juge LLM systématique dans le premier lot.

Actualiser les décisions, flux et machines d'état concernés, les parcours FR/EN,
le skill runtime et le catalogue de tests lors de l'implémentation.
Lancer les vérifications ciblées, `make typecheck`, `make architecture-check` et
`make docs-prepare`, puis revoir le diff et `git diff --check`.
`make validate` reste réservé à l'utilisateur.
Retirer chaque lot réalisé vers les sources canoniques ; un résultat ciblé ne prouve
ni qualification de sécurité globale ni déploiement.
