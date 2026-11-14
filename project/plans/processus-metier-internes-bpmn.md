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
La capacité REST existante de Tools et ses connexions sont réutilisées selon
[0182](../decisions/0182-tool-rest-capability.md).

## Lots ouverts et réception

Chaque lot termine par un parcours complet avant généralisation.

| Lot | Travail restant | Réception |
|---|---|---|
| Runner distant | Qualifier le Python généraliste, le runtime, le protocole authentifié, le déploiement séparé, les limites et la supervision. | Accès interdits refusés, agents/runs isolés, boucle et saturation arrêtées, environnement détruit et capacités libérées ; runner hostile sans accès au backend. |
| Broker MCP/REST | Donner au code des capacités temporaires médiées par Galaris, sans accès direct aux secrets ou au réseau. | Auteur distinct de l'exécutant, droits révoqués pendant l'attente, référence expirée/rejouée refusée et effet incertain sans nouvel appel. |
| Worker Process distinct | Séparer la progression durable de l'API en réutilisant jobs, occurrences, leases et reçus. | Une attente longue libère les branches et autres runs ; aucun travail utilisateur lors d'une simple lecture ; worker périmé incapable de publier ou doubler le successeur. |
| Reprise de l'extension | Qualifier crash, annulation et nettoyage avec le vrai runner et le broker. | Réconciliation après résultat perdu ; arrêt physique du bon run confirmé ; reprise sans double effet ni écrasement des données concurrentes. |
| Charge et consommateurs | Campagnes multi-harnais/n8n, profondeurs et volumes métier, parcours interne → externe → interne. | Réponses/ressources conformes, droits et interfaces préservés, croissance des données/journaux mesurée et limites publiées. |

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

Réutiliser `app.tools.execute_rest_request`. Le confinement à l'adresse configurée
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
