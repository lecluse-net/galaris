# Cible prospective de Galaris

> **Statut :** `design` — direction produit et ordre de dépendance, sans autorisation implicite
> d’implémenter.
>
> **Date de mise à jour :** 11 septembre 2026 — revue documentaire des dépendances et de la livraison.

## 1. Rôle de ce document

Ce plan décrit les écarts visés entre le runtime courant et la cible de Galaris comme plateforme
de déploiement, de gouvernance et de supervision d’agents autonomes. Chaque chantier doit
revérifier ses prérequis dans le code avant de commencer : certaines briques existent déjà.

Il ne récapitule pas les capacités livrées. Pour connaître le comportement actuel, consulter dans
cet ordre le code et les tests, les décisions acceptées, puis les documents d’architecture. Les
lots détaillés du Lab restent suivis dans
[`lab-evaluation-mecanismes-ia.md`](lab-evaluation-mecanismes-ia.md).

Les critères de référence de la section 6 décrivent une maturité à atteindre progressivement.
Ils ne constituent pas tous des prérequis à une première bêta publique. Les plans spécialisés
de l'[index](README.md) portent leurs lots restants ; ce document n'est pas un second backlog
d'implémentation de ces mêmes lots.

La cible est atteinte lorsque Galaris sait :

- sceller et déployer une version attribuable d’un agent ;
- gouverner toute action à effet avec une identité, une décision et une preuve corrélées ;
- qualifier une release avant promotion et détecter sa dérive après déploiement ;
- coordonner plusieurs agents selon leurs capacités sans dépasser les droits ni les budgets ;
- recevoir des événements métier et réveiller les Goals de façon déterministe ;
- exposer des protocoles et kits de conformité publics sans ouvrir les frontières internes ;
- superviser une flotte isolée, récupérable et exploitable à l’échelle ;
- distribuer des extensions vérifiables sans compromettre la supply chain.

## 2. Règles directrices

### 2.1 Étendre les propriétaires existants

Une capacité future étend d’abord le domaine qui possède déjà son invariant :

- `app.goal` possède les cycles d’autonomie, les réveils, les priorités et les budgets associés ;
- `app.lab` possède les datasets, runs, scores, comparaisons et gates d’évaluation ;
- `app.memory` possède le rappel, la consolidation, la provenance et la publication gouvernée des
  connaissances ;
- `app.agent` reste la façade d’exécution et le point de rattachement des contrats de release ;
- `app.task` reste propriétaire des transitions, leases, tentatives et reprises ;
- `app.messenger` reste propriétaire de l’admission et de la redelivery des messages ;
- `app.tools`, `app.mcp`, `app.file_share` et `app.process` gardent leurs frontières d’effet.

Un nouveau module n’est créé que si une responsabilité autonome, son modèle durable et ses
invariants ne peuvent pas appartenir proprement à l’un de ces domaines. Il exige alors une décision
d’architecture et une surface publique explicite.

Il n’est notamment prévu ni `app.routine`, ni second moteur de conversation, ni second moteur de
tâches, ni domaine `app.evaluation` concurrent du Lab.

### 2.2 Séparer intention, autorisation et observation

Une action à effet ne se réduit jamais à un appel d’outil. Le chemin cible distingue :

```text
ActionIntent
  → ActionDecision
  → identité effective et chaîne de délégation
  → exécution ou simulation
  → ActionObservation
  → vérification, compensation ou escalade
```

Une acceptation distante n’est pas une preuve d’effet. Une issue ambiguë reste `UNKNOWN` ou
`UNVERIFIABLE` et n’est jamais rejouée aveuglément.

### 2.3 Versionner avant de déployer

Le profil éditable d’un agent, sa release exécutable et son déploiement sont trois objets distincts.
Une Task, un appel LLM et une action doivent pouvoir être rattachés à l’empreinte exacte qui les a
produits. Une modification crée une nouvelle version ; elle ne réécrit pas l’historique.

### 2.4 Évaluer avant de généraliser

Une hausse d’autonomie, une nouvelle politique, un nouveau runtime ou une orchestration
multi-agent n’est généralisé qu’après comparaison reproductible dans le Lab. Un score n’est un gate
qu’après calibration humaine, mesure de l’incertitude et politique explicite de remplacement de la
baseline.

### 2.5 Conserver une causalité portable

Les identifiants de Task, Goal, release, deployment, collaboration, action, message, process et
trace doivent rester corrélables sans dépendre d’un runtime particulier. La télémétrie exportée
reste une projection expurgée ; la persistance métier demeure l’autorité.

## 3. Chantiers encore ouverts

### 3.1 Durcissement et livraison publique

Le dépôt possède déjà des guides d'installation et d'exploitation, des suites E2E, upgrade et
restauration, ainsi qu'un bundle d'images immuables et une voie de promotion sans reconstruction.
Les [workflows CI](../../.github/workflows/) et le
[guide d'exploitation](../../docs/fr/dev/reliability-operations.md) font foi sur ces acquis.
Le workflow de release produit un artefact CI ; une distribution publique pérenne et la
qualification de cette distribution restent à organiser.

Avant d’élargir l’autonomie :

- publier un threat model couvrant entrées, sorties réseau, secrets, approbations et surfaces à
  effet ;
- supprimer les derniers fallbacks de secrets statiques après conversion vers des références de
  connexion ;
- durcir les clients MCP externes en deny-by-default : egress, SSRF, redirections, résolution DNS,
  TLS, tailles, délais et isolation de `stdio` ;
- rendre les jetons MCP expirables, révocables, scopés, liés à une audience et audités ;
- terminer la reprise générique du journal Messenger vers ses consommateurs avec statut durable,
  redelivery sûre et file morte ;
- qualifier ensemble les suites existantes d'upgrade, smoke, E2E et restauration sur les
  artefacts exacts destinés à être publiés, et vérifier les contrôles obligatoires de la forge ;
- établir une matrice PostgreSQL réelle pour claims concurrents, double callback, crash après
  acceptation distante, annulation et retry ;
- définir la version SemVer canonique, le changelog, la compatibilité et les procédures de release
  et rollback ;
- publier des images OCI multi-architecture signées avec SBOM et provenance ;
- ajouter `SECURITY.md`, `CONTRIBUTING.md` et un code de conduite ; rendre les guides
  d'exploitation français et anglais existants accessibles depuis le parcours de diffusion ;
- automatiser fresh install, upgrade depuis la version supportée précédente, backup, restore et
  rollback sur un profil de référence ;
- publier trois parcours reproductibles avec qualité, coût, latence et limites.

Gate : zéro vulnérabilité Critical non mitigée ; toute High restante possède un propriétaire, une
échéance et un contrôle compensatoire. Les tests de crash n’observent ni entrée acceptée perdue, ni
double effet externe, ni second terminal métier. Une release publique s’installe, se met à niveau
et se restaure automatiquement.

### 3.2 Trust Kernel et Action Ledger

Le Trust Kernel doit devenir l’intercepteur serveur commun aux actions MCP, Process, fichiers,
messagerie, console et bridges.

Il reste à définir et réaliser :

- une taxonomie versionnée des actions, ressources, risques, preuves et compensations ;
- les contrats `ActionIntent`, `ActionDecision` et `ActionObservation` ;
- un modèle de politiques lié à l’organisation, l’environnement, le Goal, l’agent et la capacité ;
- les modes `OBSERVE`, `SIMULATE`, `SUGGEST`, `APPROVE_EACH`, `SUPERVISED` et `AUTONOMOUS` ;
- des approbations persistantes, expirables et éventuellement multiples ;
- l’identité effective, les comptes de service et la chaîne de délégation ;
- des budgets et rate limits atomiques ;
- un registre causal des actions et de leurs observations ;
- la vérification différée d’un effet et l’escalade des états ambigus ;
- des compensations explicites sous forme de saga, sans rollback fictif d’un système externe.

Chaque adaptateur d’effet déclare sa stratégie parmi : clé d’idempotence fournisseur, reçu
rejouable, lecture après écriture, compensation, ou absence assumée de garantie. Le registre ne
promet pas un « exactly-once » universel.

Gate : une action risquée n’est réussie que si sa décision de politique, son identité effective,
sa stratégie d’idempotence et une observation `VERIFIED` sont corrélées. Sinon elle reste en attente,
ambiguë ou escaladée.

### 3.3 Contrats, releases et deployments d’agents

Le modèle cible sépare :

- `AgentProfileVersion` : mandat, poste, capacités attendues, propriétaire, horaires et enveloppes ;
- `AgentRelease` : snapshot immuable des prompts, modèles, driver, skills, outils, politiques et
  versions de contrats ;
- `AgentDeployment` : environnement, bindings locaux, trafic, statut opérationnel, canary et
  rollback.

Travail restant :

- sceller et signer une release avec une empreinte stable ;
- enregistrer la release sur chaque Task, run, appel LLM et action ;
- fournir les diffs de profils et releases ;
- inspecter les bindings d’un deployment sans exposer ses secrets ;
- gérer les états canary, actif, suspendu et rollback ;
- garantir que les travaux déjà lancés conservent leur release d’origine ;
- empêcher tout trafic de production vers une release non qualifiée.

Gate : une exécution est entièrement attribuable à une release immuable et à un deployment. Un
rollback cible une empreinte précise sans modifier les traces ni travaux antérieurs.

### 3.4 Évaluation continue et promotion

Ce chantier complète le plan actif du Lab, sans créer un moteur parallèle.

Il reste à :

- livrer la calibration humaine, les répétitions, l’incertitude, la comparabilité et les tendances
  prévues par le plan du Lab ;
- ajouter les gardes de non-régression et les exports machine utilisables en CI ;
- versionner les rôles travail, validation et holdout ainsi que la gouvernance des datasets ;
- fournir des outils simulés et fixtures d’effets pour les scénarios à risque ;
- évaluer les politiques, permissions, pannes, injections et résultats end-to-end ;
- comparer baseline et candidat sur qualité, coût, latence, stabilité et taux d’erreur ;
- rattacher les gates aux `AgentRelease` et `AgentDeployment` ;
- échantillonner la production et détecter les dérives par release et environnement ;
- convertir un incident en cas candidat avec revue de sa provenance et de ses données sensibles ;
- comparer toute orchestration multi-agent au mode solo.

Gate : aucun seuil décisionnel fort n’est activé avant calibration du juge. Une release non
qualifiée ne reçoit pas de trafic de production ; une dérive franchissant une garde provoque le
rollback, la suspension ou une décision humaine selon la politique pré-déclarée.

### 3.5 Autonomie événementielle des Goals

L’autonomie future reste une extension de `app.goal`. Elle ne crée pas de boucle concurrente aux
Tasks ni de mécanisme générique de routine.

Le premier palier borné est livré dans `app.goal` : chaque Goal choisit soit l'échéance d'une
fréquence, soit la terminaison d'un cycle parent, avec déclenchement durable anti-rejeu, arbre
acyclique et affichage des sous-objectifs. Il n'autorise aucun autre événement, filtre ou condition
métier. L'inbox métier générique décrite ci-dessous reste un chantier distinct et prospectif. Le
contrat actuel est documenté dans `docs/fr/architecture/state-machines.md`.

Travail restant :

- une inbox durable d’événements métier ;
- des abonnements typés avec filtre, portée et propriétaire ;
- une déduplication et un curseur par source ;
- des règles déterministes de réveil d’un Goal ;
- une priorité calculée depuis urgence, échéance, coût d’attente et politique ;
- un portefeuille borné de Goals par agent ;
- des budgets transversaux de concurrence, coût et fréquence ;
- du backpressure, des files mortes et une reprise administrative ;
- une preuve reliant événement, cycle, Task et verdict terminal.

Les horaires ne font que produire un événement déterministe. Un événement réveille un Goal ; le
Goal crée une Task ordinaire ; la Task utilise le pipeline agentique commun.

Gate : une redelivery ne crée pas deux cycles pour la même clé d’idempotence. Aucun réveil ne peut
dépasser les budgets ni contourner les politiques, et toute suppression d’un événement accepté est
auditée.

### 3.6 Consolidation mémoire et connaissances gouvernées

Les travaux futurs prolongent `app.memory` et ses documents, sans dupliquer le stockage ni les ACL.

Il reste à :

- expliciter confiance, autorité, utilité et sensibilité dans la sélection ;
- détecter l’empoisonnement, les conflits de sources et les promotions injustifiées ;
- consolider plusieurs épisodes en proposition de procédure ;
- évaluer, versionner et approuver la promotion d’une procédure ;
- gérer les cycles brouillon, revue, publication, dépréciation et retrait d’une connaissance ;
- publier une projection Markdown canonique sans faire du vault la source transactionnelle ;
- synchroniser des adapters documentaires avec révisions, conflits et reprises idempotentes ;
- expliquer pour chaque élément injecté sa provenance, sa portée et les signaux de sélection ;
- définir rétention et revue des données sensibles par portée d’organisation.

Un éventuel domaine documentaire séparé exige une ADR démontrant une responsabilité que
`app.memory` et `document://` ne peuvent pas porter. Il ne doit ni réimplémenter le rappel, ni
accorder un accès par simple voisinage de graphe.

Gate : zéro fuite ACL dans la suite adversariale. Toute connaissance publiée conserve ses sources,
sa version, son approbateur et son historique de dépréciation. Une promotion automatique reste
interdite tant que ses gates du Lab ne sont pas calibrés.

### 3.7 Réseau de capacités et collaboration gérée

La délégation structurée doit devenir indépendante du canal et du runtime.

Travail restant :

- un registre de capacités avec niveau, preuves, fraîcheur et historique de performance ;
- des exigences de contribution et résultats structurés ;
- un moteur d’affectation fondé sur droits, capacités, disponibilité, coût et confidentialité ;
- `CollaborationRun` et un registre de collaboration borné ;
- les rôles `COORDINATOR`, `CONTRIBUTOR` et `REVIEWER` ;
- les patterns `CONSULT`, `DELEGATE`, `PARALLEL` et `REVIEW` ;
- un DAG concurrent limité aux contributions réellement indépendantes ;
- fan-in, réaffectation, stratégie d’échec et compensation ;
- des bornes de profondeur, fan-out, durée, coût et trafic distant ;
- la même politique et la même preuve d’effet pour un pair local ou A2A ;
- une évaluation du gain réel par rapport au mode solo.

`app.task` reste propriétaire de chaque unité de travail. La collaboration coordonne des
contributions et leurs contrats ; elle ne crée ni scheduler de Task, ni planner concurrent.

Gate : aucune borne n’est dépassée. Sur une cohorte pré-déclarée, le mode collaboratif respecte la
non-infériorité face au solo et franchit au moins un seuil utile : +5 points de qualité, -15 % de
coût ou -20 % de temps de cycle.

### 3.8 Passerelle ouverte et kit de conformité

Travail restant :

- définir le profil MCP supporté et sa matrice de conformité ;
- prendre en charge OAuth 2.1, protected resource metadata, audience et autorisation renforcée
  pour MCP ;
- décider le mapping A2A avec Task, Messenger, File Share et Process ;
- fournir client et serveur A2A avec Agent Cards, streaming, artifacts, annulation et reprise ;
- adapter AG-UI aux événements, états et approbations sans lui donner d’autorité métier ;
- propager une convention OpenTelemetry commune et une politique de contenu sensible ;
- publier un SDK minimal et des TCK pour drivers, bridges, Process et outils ;
- permettre l’installation, l’enregistrement, l’exécution et le retrait d’une extension sans
  modifier un registre statique du cœur ;
- maintenir un adaptateur de référence hors de l’arbre principal ;
- versionner les profils, compatibilités et déviations optionnelles.

Gate : une extension tierce passe le TCK hors du monorepo et ne dépend d’aucun import privé. Les
chemins certifiés conservent la causalité et n’exposent ni mémoire, ni secret, ni connexion interne.

### 3.9 Goal Control, entreprise et élasticité

Travail restant :

- une carte vivante des releases, deployments, capacités, disponibilités et dépendances ;
- une vue corrélée des Goals, Tasks, collaborations, Process et actions ;
- un centre d’approbations, d’effets non vérifiés, d’alertes et de prise de contrôle ;
- une console d’exploitation Messenger pour listeners, curseurs, reconnexions, erreurs et files
  mortes ;
- la suspension d’un agent, la réduction de son autonomie et le rollback de son deployment ;
- organisations, environnements, quotas, rétention et audit exportable ;
- OIDC ou SAML, SCIM, comptes de service et coffre KMS/Vault ;
- une décision explicite entre isolation par déploiement et multi-tenancy partagé ;
- la séparation API/workers, les pools spécialisés et le multi-instance ;
- backpressure, circuit breakers, files mortes et reprise administrative ;
- des exercices industrialisés de backup, failover, restauration et rollback ;
- des tests de bruit de voisinage et d’isolation sur toutes les surfaces.

Gate : un soak d’au moins 24 heures et 10 000 Tasks sur le mix de référence respecte l’error budget.
Le failover et la restauration respectent le RPO/RTO publié, et la matrice adversariale n’observe
aucune fuite entre portées.

### 3.10 Écosystème signé

Travail restant :

- un format de bundle pour release d’agent, skill, outil et template ;
- un manifeste de compatibilité et de permissions ;
- SBOM, provenance, signature et vérification à l’installation ;
- bindings locaux pour modèles, secrets et connexions ;
- registre personnel puis fédéré ;
- publication contrôlée, révocation, dépréciation et rollback ;
- un TCK couvrant altération, signature, révocation, secrets, installation et rollback ;
- des profils d’audit alignés sur NIST AI RMF, OWASP Agentic et les obligations applicables.

Gate : un bundle altéré, révoqué, incompatible ou trop permissif est refusé. Une installation ne
contient aucun secret, ne modifie aucune release existante et peut revenir à une empreinte précise.

### Piste optionnelle — visualisation 3D de la mémoire

Intention conservée depuis l'index, sans plan détaillé ni implémentation démontrée : proposer
un paysage mémoire 3D navigable au-dessus du graphe gouverné existant. Three.js est un candidat
de rendu ; le placement pourrait combiner forces et projection sémantique bornée, avec
exploration assistée et vol libre.

Cette piste ne remplace pas la vue 2D, ne rend pas les embeddings accessibles et conserve
les ACL du graphe. Elle devra recevoir un objectif utilisateur, une mesure d'utilité et un
périmètre propre avant de devenir un chantier. Elle ne bloque pas la livraison publique.

## 4. Ordre d’activation

Les chantiers peuvent être préparés en parallèle, mais leur activation suit cet ordre de
dépendance :

1. durcissement, livraison reproductible et taxonomies communes ;
2. Trust Kernel, Action Ledger et releases immuables ;
3. calibration du Lab, gates de release et deployments canary ;
4. passerelle ouverte et TCK ;
5. autonomie événementielle, consolidation des connaissances et collaboration gérée ;
6. supervision de flotte, contrôle entreprise et scale-out ;
7. distribution fédérée de bundles signés.

Aucune hausse d’autonomie ne précède le Trust Kernel. Aucun deployment de production ne précède
ses gates du Lab. Aucun scale-out ne précède l’observabilité corrélée et les campagnes de reprise.

## 5. Scénarios d’acceptation encore à démontrer

### 5.1 Embauche et déploiement

Un administrateur transforme un poste structuré en profil versionné, construit une release
immuable, la qualifie, la signe et active un deployment canary. Chaque travail et action retrouve
la release exacte ; une nouvelle version n’altère pas les exécutions antérieures.

### 5.2 Action risquée

Une action financière résout la politique et l’identité effective, obtient les approbations
requises, s’exécute avec la meilleure garantie disponible, relit la ressource et enregistre un effet
vérifié. Une issue ambiguë est escaladée et non répétée.

### 5.3 Initiative événementielle

Un événement métier dédupliqué réveille un Goal autorisé. Le cycle crée une Task ordinaire et
respecte priorité, concurrence, coût et cooldown. Le lien causal entre événement, cycle, Task,
actions et verdict est inspectable.

### 5.4 Travail multi-agent

Une mission sollicite des contributeurs et reviewers locaux ou A2A selon leurs capacités et
disponibilités. Le coordinateur agrège des résultats structurés, respecte les bornes et démontre un
bénéfice mesuré face au mode solo.

### 5.5 Apprentissage contrôlé

Plusieurs épisodes sourcés produisent une proposition de procédure. Elle est évaluée, revue,
versionnée, publiée pour une portée explicite puis dépréciable sans supprimer ses preuves.

### 5.6 Incident et compensation

Après un crash sur une frontière externe, le système relit le registre d’action. Il reprend par
vérification, compensation ou décision humaine, sans double effet et sans prétendre connaître un
état que le fournisseur ne permet pas d’observer.

### 5.7 Supervision et reprise

Un opérateur suit la causalité d’une mission, suspend un agent, reprend un travail récupérable,
réduit son autonomie ou revient à un deployment antérieur. Backup, restore et failover respectent
le profil RPO/RTO publié.

### 5.8 Interopérabilité

Un agent externe découvre une Agent Card, soumet une demande autorisée, reçoit événements et
artifacts, puis annule ou reprend l’échange. Les politiques, preuves et bornes sont identiques à
celles d’un pair local.

### 5.9 Isolation

Selon l’ADR retenue, deux organisations ou deux déploiements utilisant les mêmes identifiants
métier restent isolés dans API, jobs, mémoire, workspaces, fichiers, traces, outils, sauvegardes et
administration.

### 5.10 Supply chain

Un bundle est installé seulement après vérification de sa provenance, de sa signature, de sa
compatibilité, de ses permissions, de son SBOM et de ses résultats d’évaluation. Ses secrets sont
liés localement et sa mise à jour crée une nouvelle release.

## 6. Preuves nécessaires au statut de référence

La cible technique ne suffit pas à revendiquer un statut de référence. Il faut simultanément :

- une première mission reproductible en moins de 15 minutes depuis les artefacts publiés, hors
  téléchargement initial ;
- des releases versionnées avec images signées, SBOM, provenance et compatibilité ;
- des procédures publiques d’installation, upgrade, backup, restore et rollback ;
- trois parcours publiés avec configuration, résultat, qualité, coût, latence et limites ;
- un audit de sécurité indépendant du chemin critique après stabilisation du Trust Kernel ;
- des résultats automatisés de conformance, charge, panne et évaluation pour chaque release
  candidate ;
- une campagne publiée d’au moins 10 000 injections crash, retry et redelivery sans double effet ni
  perte d’entrée acceptée ;
- au moins trois essais où un contributeur extérieur réalise un adaptateur conforme en moins d’une
  journée médiane à partir du SDK et du TCK ;
- dix déploiements de production indépendants du mainteneur principal ;
- trois études de cas publiques et deux extensions tierces maintenues hors du dépôt principal ;
- un processus de contribution et un exercice documenté de divulgation de sécurité.

Ces seuils distinguent l’ambition, la démonstration interne et la reconnaissance externe. Ils ne
remplacent aucune preuve de sûreté du runtime.

## 7. Décision directrice

Le prochain palier de Galaris est un control plane de confiance : releases immuables, politiques,
preuves d’effet, évaluation continue, interopérabilité conforme et supervision de flotte.

Les nouveaux travaux doivent renforcer cette chaîne sans réimplémenter les contrats déjà possédés
par Agent, Task, Goal, Messenger, Memory, Lab, Tools ou Process.
