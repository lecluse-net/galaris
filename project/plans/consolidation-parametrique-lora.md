# Plan — Consolidation paramétrique de la mémoire par LoRA

> **Statut :** `design` — réflexion d’architecture, sans autorisation implicite
> d’implémenter.
>
> **Date de mise à jour :** 11 septembre 2026 — dépendances Lab revues ; cible matérielle inchangée.
>
> **But :** permettre à un agent de consolider périodiquement des préférences, procédures et
> expériences stables dans un adaptateur LoRA personnel, tout en conservant `app.memory` comme
> source de vérité gouvernée, révisable et oubliable.
>
> **Horizon matériel :** cible souveraine future fondée au minimum sur un modèle de la classe
> DeepSeek V4 Flash et une station ou grappe IA dédiée. L'absence actuelle de cette infrastructure
> n'autorise ni réduction silencieuse du modèle, ni dépendance permanente envers un fournisseur.

## 1. Décision en bref

Galaris ne doit pas entraîner une copie complète d’un LLM pour chaque agent et ne doit pas tenter
de remplacer Memory par les poids d’un modèle. La cible est hybride :

```text
                         modèle de base partagé
                                  │
                ┌─────────────────┼─────────────────┐
                ▼                 ▼                 ▼
          LoRA agent A      LoRA agent B      LoRA agent C
                │                 │                 │
                └──────────── app.agent ────────────┘
                                  │
                  Memory gouvernée + contexte courant
                                  │
                                  ▼
                         exécution de la Task
```

- le modèle de base porte les capacités et connaissances générales ;
- l’adaptateur personnel porte un savoir-faire lent, stable et évalué ;
- Memory reste l’autorité sur les faits évolutifs, sensibles, partageables ou révocables ;
- le contexte courant, les sources métier et les outils restent nécessaires ;
- chaque run fige une version exacte du modèle de base et de l’adaptateur avant le driver ;
- une absence, une incompatibilité ou une invalidation d’adaptateur replie vers le modèle de base
  avec le rappel Memory normal ;
- aucun candidat ne peut être activé sans une campagne comparative reproductible dans le Lab IA,
  ni rester actif si la surveillance révèle une régression critique.

Cette architecture constitue un apprentissage continu au niveau du système Galaris. Le modèle ne
choisit ni ses données d’entraînement, ni son infrastructure, ni sa propre promotion.

La personnalisation porte sur un adaptateur par agent et par révision de base, pas sur une copie
complète du modèle par agent. Une ou plusieurs répliques du modèle de base restent partagées entre
les agents compatibles.

Ce plan prolonge [l’apprentissage Dream](../decisions/0019-evidence-based-dream-experience.md)
sans le remplacer :
Dream continue de produire une mémoire explicite utile même lorsqu’aucun adaptateur n’existe. Il
s’appuie aussi sur [le plan d’évaluation des mécanismes IA](lab-evaluation-mecanismes-ia.md) pour
éviter de créer une seconde infrastructure de benchmark propre à LoRA.

## 2. Pourquoi LoRA plutôt qu’un modèle complet par agent

LoRA gèle les poids du modèle de base et entraîne de petites matrices d’adaptation. Galaris peut
donc mutualiser le modèle et sélectionner un adaptateur par requête sur un serveur compatible.

Conséquences recherchées :

- un seul pool d’inférence pour plusieurs agents compatibles ;
- stockage et transfert d’adaptateurs bien plus petits qu’une copie complète du modèle ;
- activation, canari, retour arrière et suppression par version ;
- entraînement possible sur une infrastructure distincte de l’inférence ;
- maintien de la façade OpenAI-compatible déjà consommée par `app.llm` ;
- aucune dépendance du harnais interne ou Hermès envers un framework d’entraînement précis.

Un adaptateur reste strictement lié à une famille et à une révision de modèle de base. Un agent
qui utilise deux bases incompatibles pour les efforts `standard` et `high` possède donc deux
lignées d’adaptation distinctes. Une mise à niveau du modèle de base ne réutilise jamais
silencieusement un ancien adaptateur.

### 2.1 Échelle de référence

Le plan ne vise pas une station grand public ni un petit modèle utilisé comme substitut permanent.
Son plancher fonctionnel de référence est **DeepSeek V4 Flash** : modèle MoE open-weight de
284 milliards de paramètres, dont 13 milliards activés par token, avec une fenêtre de contexte
annoncée à un million de tokens. Le checkpoint Instruct publié en précision mixte FP4/FP8 occupe
environ 149 Gio. Cette référence fixe l'ordre de grandeur recherché ; elle ne grave pas un nom de
modèle dans les contrats Galaris et pourra être remplacée par une base souveraine au moins aussi
capable.

Conséquences :

- la qualité de référence ne doit pas être démontrée uniquement sur un modèle dense de 8 à 70B ;
- la mémoire HBM, sa bande passante, le KV cache et l'interconnexion priment sur les indicateurs
  marketing de calcul brut ;
- le contexte d'un million de tokens ne supprime pas le goulet Memory : sérialiser et préremplir
  des souvenirs stables reste coûteux et peut diluer les informations utiles ;
- l'effort `standard` peut sélectionner V4 Flash en mode direct ou raisonnement borné, tandis que
  `high` peut sélectionner un mode de raisonnement plus long ou, plus tard, une base supérieure ;
- aucune phase ne doit abaisser silencieusement la base vers un petit modèle parce que le matériel
  disponible est insuffisant.

La compatibilité exacte d'un futur successeur de V4 Flash demeure une propriété de ressource :
licence, tokenizer, format de chat, tool calling, architecture, précision, trainer et serveur
d'inférence doivent être enregistrés avec la lignée d'adaptation.

## 3. Problème à résoudre et hypothèse à mesurer

La mémoire de Galaris évolue alors que le LLM reste statique. Même avec un rappel hybride borné,
les éléments importants doivent être recherchés, sérialisés puis préremplis dans le contexte à
chaque exécution. Cela peut augmenter :

- les tokens d’entrée et leur coût ;
- le temps de préremplissage et le délai avant le premier token ;
- la compétition entre souvenirs dans un budget limité ;
- les appels explicites à `memory_search` ;
- le risque qu’une procédure récurrente ne soit pas rappelée au bon moment.

L’hypothèse du plan est qu’un adaptateur peut absorber une partie du savoir-faire stable et réduire
le contexte nécessaire sans détériorer les capacités générales, la factualité, l’usage des outils
ou la capacité à consulter Memory.

Cette hypothèse doit être démontrée. Avant tout entraînement, Galaris mesure séparément :

- latence du rappel Memory ;
- tokens et caractères réellement injectés ;
- coût du préremplissage, avec et sans cache fournisseur ;
- taux de recherche explicite ;
- réussite, corrections et reprises des Tasks ;
- part des rappels portant sur une procédure stable plutôt que sur un fait courant.

Si le goulet provient principalement d’un provider lent, d’un mauvais classement ou d’un contexte
non caché, LoRA ne doit pas être présenté comme le remède à ce problème différent.

## 4. Mémoire explicite et mémoire paramétrique

### 4.1 Éligibilité par défaut

| Contenu | Destination | Motif |
|---|---|---|
| personnalité, ton et préférences de travail stables | LoRA possible + Memory | comportement durable |
| procédure confirmée par plusieurs preuves indépendantes | LoRA privilégié + Memory | savoir-faire répétitif |
| correction humaine récurrente et non sensible | LoRA possible + Memory | signal d’alignement fort |
| anti-pattern vérifié par des échecs puis une réussite | LoRA possible + Memory | amélioration de stratégie |
| état courant d’une Task, d’un Goal ou d’un Process | source métier uniquement | donnée transactionnelle |
| rendez-vous, statut, prix, personne ou fait susceptible de changer | Memory uniquement | fraîcheur requise |
| souvenir épisodique isolé | Memory uniquement | généralisation prématurée |
| document de travail | Memory uniquement | mutable et potentiellement volumineux |
| mémoire sociale ou donnée personnelle | Memory uniquement | risque de mémorisation et régurgitation |
| item accessible par grant ou visibilité publique | Memory uniquement | droit révocable |
| secret, credential, prompt privé ou raisonnement interne | interdit | sécurité |
| contradiction non résolue ou item expiré | interdit | vérité indéterminée |

### 4.2 Règles de gouvernance

Un item n’entre dans un corpus d’adaptation que s’il :

1. appartient directement à l’agent ;
2. est explicitement admissible à la consolidation paramétrique ;
3. possède une provenance et une révision connues ;
4. n’est ni expiré, oublié, contradictoire, partagé temporairement, ni sensible ;
5. satisfait un seuil de confirmation adapté à son rôle ;
6. est relié à une preuve originale autorisée lorsque son contenu a été produit par un LLM.

Un accès par grant ne confère jamais un droit d’entraînement. Un contenu public ne devient jamais
implicitement une propriété paramétrique privée. La lecture, l’usage dans un prompt et l’usage
pour entraîner un modèle constituent trois autorisations distinctes.

## 5. Place de Dream

Dream possède déjà les primitives nécessaires pour identifier des signaux utiles : preuves
bornées, extraction, consolidation, corrections, confirmations et promotion d’une expérience
répétée en procédure.

Il reste toutefois un producteur de mémoire, pas un trainer. Son extension conceptuelle s’arrête à
un reçu d’éligibilité :

```text
Task ou Voice terminale
        │
        ▼
preuves déterministes et expurgées
        │
        ▼
réflexion et consolidation Memory existantes
        │
        ▼
signal : item stable potentiellement entraînable
        │
        └──── aucun entraînement, aucune promotion de modèle
```

Le domaine d’adaptation recharge ensuite les items et preuves courants. Un reçu Dream historique
ne suffit jamais si l’item a depuis été corrigé, oublié ou rendu inéligible.

## 6. Domaine conceptuel d’adaptation

Un domaine métier dédié, nommé provisoirement `app.model_adaptation`, posséderait le cycle de vie
des corpus, entraînements et adaptateurs. Il évite de transformer :

- `app.memory` en orchestrateur GPU ;
- `app.llm` en service d’entraînement ;
- `app.agent` en scheduler ;
- `app.dream` en autorité de déploiement ;
- un bridge fournisseur en source de vérité métier.

| Domaine | Responsabilité |
|---|---|
| `app.memory` | contenu gouverné, ACL, révisions, provenance, oubli et usages |
| `app.dream` | extraction et consolidation d’expériences à partir de preuves |
| `app.model_adaptation` | politiques d’éligibilité, snapshots de corpus, candidats, évaluations et promotion |
| `app.process` | suivi durable de l’exécution longue sur une infrastructure externe |
| `app.connection` | endpoint et secrets du trainer ou du registre d’artefacts |
| bridge de training | traduction vers l’API concrète du serveur d’entraînement |
| `app.lab` | jeux d’évaluation, comparaisons et rapports reproductibles |
| `app.llm` | ressource d’inférence et traçage des appels |
| `app.agent` | résolution unique de la base et de l’adaptateur avant chaque run |

Le nom du domaine reste à valider avant toute implémentation. Sa responsabilité, elle, doit rester
séparée même si l’infrastructure choisie change.

## 7. Corpus d’entraînement reproductible

Chaque entraînement utilise un snapshot immuable, et non une requête vivante sur Memory. Son
manifeste contient au minimum :

- agent propriétaire ;
- empreinte et licence du modèle de base ;
- version du tokenizer et format de chat ;
- UUID, révision, rôle et empreinte de chaque item Memory retenu ;
- références de preuves utilisées ;
- règles d’éligibilité et version du générateur de dataset ;
- exclusions et motifs d’exclusion ;
- exemples de replay conservant les capacités antérieures ;
- partitions entraînement, validation et test sans chevauchement de preuve ;
- empreinte finale du dataset sans recopier de secrets dans les logs.

Le dataset privilégie les événements et résultats autoritatifs. Une leçon rédigée par un modèle ne
devient pas une preuve indépendante de sa propre exactitude. Lorsqu’un LLM transforme les preuves
en exemples d’instruction, le manifeste conserve cette filiation et les évaluations restent
fondées sur des données non utilisées pour l’entraînement.

La première stratégie est un SFT LoRA simple. Les méthodes de préférence comme DPO restent hors
du premier périmètre tant que Galaris ne possède pas de paires positives/négatives suffisamment
fiables et indépendantes.

Chaque candidat est reconstruit depuis la base gelée avec le corpus cumulatif admissible et un
replay contrôlé. Enchaîner indéfiniment `adapter N → adapter N+1` est exclu du premier périmètre,
car cela accumulerait dérive, erreurs synthétiques et oubli catastrophique.

## 8. Cycle d’auto-fine-tuning

```text
seuil de nouvelles preuves ou demande manuelle
        │
        ▼
snapshot éligible et reproductible
        │
        ▼
ProcessRun d’entraînement distant
        │
        ▼
artefact LoRA candidat + digest + rapport trainer
        │
        ▼
campagne Lab contre baseline active figée
        │
        ├── échec ou indéterminé ──► rejet documenté
        │
        └── toutes les gardes réussies
                        │
                        ▼
                     canari
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
          régression       fenêtre stable
              │                   │
              ▼                   ▼
           rollback       promotion atomique
                                  │
                                  ▼
                         surveillance continue
```

### Modes fonctionnels proposés

| Mode | Comportement |
|---|---|
| `off` | aucune sélection ni exécution |
| `observe` | calcule éligibilité, volume et bénéfice potentiel sans créer de dataset |
| `candidate` | entraîne et évalue, mais exige une promotion explicite |
| `gated` | peut promouvoir automatiquement si tous les seuils et canaris sont satisfaits |

Le mode livré initialement reste `off`. Le passage à `gated` est une étape de maturité, pas un
simple réglage présenté dès le premier prototype.

### Déclencheurs

Un cycle n’est pas lancé uniquement parce qu’une durée s’est écoulée. Il exige au moins un signal
de valeur :

- volume minimal de nouvelles procédures ou corrections confirmées ;
- consommation répétée d’un même ensemble de souvenirs dans les prompts ;
- coût de contexte cumulé supérieur à un seuil ;
- demande administrative explicite ;
- invalidation nécessitant une reconstruction propre.

Une fenêtre de refroidissement et une limite de coût empêchent les entraînements rapprochés. Un
seul entraînement par agent et modèle de base peut être actif à la fois ; une nouvelle demande est
coalescée avec la suivante plutôt que lancée en parallèle.

## 9. Exécution distante et artefacts

L’entraînement est une opération longue, coûteuse et annulable. Galaris ne garde pas une requête
HTTP ouverte et ne lance pas de toolchain ML sur l’hôte applicatif.

`app.model_adaptation` conserve l’autorité métier sur le corpus, le candidat et sa décision.
L’exécution distante est corrélée à un `ProcessRun` via une façade publique de `app.process`. Le
bridge d’entraînement traduit uniquement : démarrage, progression, annulation, fin et localisation
de l’artefact.

La phase de conception doit confirmer qu’un run système peut emprunter ce contrat sans fabriquer
une fausse `ProcessDefinition` agentique ni exposer un tool de training aux agents. Si le contrat
actuel ne le permet pas, `app.process` devra d’abord recevoir un port explicite de job système ; le
domaine d’adaptation ne dupliquera pas sa machine d’état.

Règles :

- idempotence par empreinte `(base, agent, dataset, recette)` ;
- callbacks authentifiés, redélivrables et sans payload secret ;
- états terminaux immuables ;
- demande d’annulation distincte de sa confirmation ;
- timeout, quota GPU, taille maximale de dataset et rang LoRA bornés ;
- trainer isolé du réseau métier et sans credentials Galaris généraux ;
- dataset transmis par référence temporaire contrôlée ou flux borné ;
- artefact placé dans un registre dédié, jamais dans un système de fichiers privé de l’agent ;
- digest cryptographique vérifié avant toute évaluation ou activation ;
- aucun chemin fourni par le trainer n’est utilisé directement par le serveur d’inférence.

Le choix entre NeMo AutoModel, un trainer maison, Axolotl, TRL, Unsloth ou un service fournisseur
appartient au bridge et reste hors du contrat métier. Un nom présent dans cette liste ne vaut pas
preuve qu'il prend en charge V4 Flash, son MoE ou son format de poids courant : chaque combinaison
doit passer la qualification décrite plus bas.

### 9.1 Trajectoire matérielle souveraine

Le plan dissocie la préparation logicielle de l'achat du calcul. Galaris doit pouvoir rester en
mode `off` ou `observe` pendant plusieurs années sans dette de compatibilité ni dégradation du
service courant.

| Horizon | Infrastructure indicative | Capacité recherchée |
|---|---|---|
| aujourd'hui, sans achat GPU | modèles actuels de Galaris, Memory, Dream et Lab | mesurer le goulet, définir les corpus et constituer les évaluations sans entraîner |
| qualification ponctuelle | location isolée de GPU datacenter, données synthétiques ou non sensibles | vérifier le trainer, le format d'adaptateur et le serving avant tout investissement |
| première station souveraine | station de classe DGX Station GB300, soit environ 252 Gio de HBM3e et 748 Gio de mémoire cohérente, ou accélérateur équivalent | inférence V4 Flash mono-utilisateur ou à faible concurrence ; expérimentation PEFT après benchmark |
| service Galaris multi-agent | réplique de quatre accélérateurs H200/B200/B300, MI355X ou génération équivalente | débit concurrent, long contexte, cache d'adaptateurs et marge de KV cache |
| consolidation souveraine | second nœud de quatre à huit accélérateurs datacenter, distinct de l'inférence | entraînement, évaluations et construction d'artefacts sans interrompre les conversations |
| plateforme mature | nœuds d'inférence et de training séparés, stockage d'artefacts et réseau rapide dédiés | canaris, plusieurs bases, reprise, haute disponibilité et évolutions de modèle |

Ces configurations sont des classes de capacité, pas une liste d'achat anticipée. La génération de
GPU disponible au moment du financement devra être requalifiée. Une carte de 256 Gio peut charger
V4 Flash pour certaines recettes d'inférence, mais cela ne prouve ni un contexte utile à Galaris,
ni une concurrence suffisante, ni la faisabilité du fine-tuning. De même, les quelque 149 Gio du
checkpoint quantifié ne représentent pas l'empreinte d'entraînement : activations, format de
calcul, communications MoE, gradients et états d'optimiseur s'ajoutent.

La cible de production sépare donc le nœud interactif du nœud de consolidation. Un entraînement ne
doit jamais immobiliser le service qui répond aux utilisateurs. Deux stations souveraines peuvent
former une première cellule, mais leur aptitude réelle au PEFT V4 Flash doit être mesurée avant de
les retenir comme architecture de référence.

Le stockage doit conserver au minimum la base exacte, son format de training éventuel, plusieurs
snapshots de corpus, les candidats, rapports et versions actives. Il doit être chiffré, sauvegardé
et dimensionné en téraoctets, avec des digests vérifiés. Le réseau entre nœuds doit être choisi en
fonction du parallélisme réellement retenu ; la mémoire système cohérente ne doit pas être comptée
comme de la HBM de même débit.

### 9.2 Stratégie d'investissement différé

L'ordre recommandé évite d'acheter une infrastructure avant de savoir si la chaîne fonctionne :

1. préparer les mesures, corpus, manifests et jeux Lab sans GPU de training ;
2. attendre un volume suffisant de procédures réellement consolidables ;
3. qualifier V4 Flash sur une location courte, isolée et exportable, avec un corpus sans donnée
   privée dans un premier temps ;
4. mesurer HBM, débit, énergie, durée d'entraînement et qualité des adapters ;
5. choisir seulement alors la station ou la grappe correspondant aux résultats et à la génération
   matérielle disponible ;
6. rapatrier base, adapters, registre et serving dans l'infrastructure souveraine.

Une location de qualification n'est pas l'architecture finale et ne doit pas créer de dépendance :
poids, datasets, recettes, rapports et artefacts restent exportables et vérifiables localement.

## 10. Adaptateur et résolution du modèle

Une version d’adaptateur est immuable et identifiée par :

- agent ;
- modèle de base exact ;
- recette et rang LoRA ;
- digest du corpus ;
- digest de l’artefact ;
- rapport d’évaluation ;
- état `candidate`, `canary`, `active`, `rejected`, `superseded` ou `invalidated` ;
- dates de création, activation, invalidation et suppression physique.

La résolution reste unique avant l’entrée dans un driver :

```text
agent + effort
      │
      ▼
base standard/high résolue par app.agent
      │
      ▼
adaptateur actif compatible, sinon aucun
      │
      ▼
ResolvedModel(base + adapter version + digests)
      │
      ▼
harnais interne ou Hermès
```

Une modification d’activation ne change jamais un run déjà construit. Les traces et `LLMCall`
conservent la base, l’adaptateur et leur version afin qu’un résultat soit reproductible et que le
Lab puisse comparer deux générations.

Tous les drivers doivent consommer la résolution figée de Galaris. Le bridge Hermès impose
déjà le gateway et le modèle effectif ; l'ancienne hypothèse d'un fournisseur choisi librement
par sa configuration n'est plus un prérequis à résoudre. Il reste à qualifier la transmission
de l'identité d'adaptateur de bout en bout. Le temps réel vocal et les modèles propriétaires
sans support d'adaptation sont hors du premier périmètre.

## 11. Serving multi-LoRA

Le serveur d’inférence charge une base partagée et applique l’adaptateur demandé par requête. Le
contrat Galaris n’expose qu’un identifiant logique versionné ; le mapping vers un chemin ou un
registre reste côté serveur de confiance.

Le serving doit prévoir :

- préchauffage d’un candidat avant canari ;
- chargement atomique et contrôle du digest ;
- plafond d’adaptateurs simultanément en GPU et cache CPU borné ;
- éviction LRU sans perte de l’identité logique ;
- refus d’un adaptateur incompatible plutôt qu’application approximative ;
- repli explicite vers la base + Memory en cas d’indisponibilité ;
- métriques de hit, chargement, éviction, latence et mémoire GPU ;
- séparation stricte entre l’API d’inférence publique et l’API d’administration des adaptateurs.

Le chargement dynamique de chemins arbitraires depuis une requête utilisateur est interdit. Le
contrôleur de serving ne fait confiance qu’au registre d’artefacts validés.

### 11.1 Jalon de faisabilité propre à V4 Flash

La documentation disponible établit l'inférence de V4 Flash avec vLLM et décrit son entraînement
avec NeMo AutoModel. Elle ne suffit pas à considérer comme acquis le chemin complet recherché par
Galaris : **LoRA ou autre PEFT sur ce MoE, sauvegarde non fusionnée, puis chargement dynamique de
plusieurs adapters par le serveur d'inférence sur le checkpoint mixte FP4/FP8**.

La phase expérimentale doit donc valider, dans cet ordre :

1. les modules réellement adaptables sans dégrader le routage des experts ;
2. la mémoire nécessaire lorsque les poids de calcul sont matérialisés pendant l'entraînement ;
3. la production d'un artefact PEFT autonome lié à la révision exacte de V4 Flash ;
4. son chargement dynamique sans fusion dans la base ;
5. l'alternance entre deux agents et deux adapters sans fuite de contexte ni contamination ;
6. la concurrence, l'éviction, le rechargement et le fallback sous charge ;
7. la conservation du tool calling et des modes de raisonnement.

Si cette chaîne n'est pas supportée de manière fiable, Galaris reste en `observe` et conserve son
architecture Memory actuelle. La fusion d'un adapter dans un checkpoint complet par agent est un
repli exceptionnel, coûteux et explicitement administré ; elle ne devient pas la cible par défaut.
L'échec du multi-LoRA ne justifie pas un remplacement silencieux de V4 Flash par un petit modèle.

## 12. Évaluation et promotion

Le [Lab IA](../../docs/fr/architecture/ai-lab-evaluation.md) possède les mesures ; le domaine
d'adaptation possède le workflow et la décision. Il consomme un rapport structuré, versionné
et auditable, sans recalculer un score ni lever une garde depuis une analyse narrative.

### 12.1 Dépendances Lab et protocole

Répétitions, revue humaine indépendante, rôles de datasets et empreintes corpus/contexte/candidat/
juge sont présents au 11 septembre 2026. Le [plan du Lab](lab-evaluation-mecanismes-ia.md)
porte encore l'étalonnage, l'incertitude, la comparaison explicite, les tendances et les gardes
bloquantes. Leur qualification reste un préalable au mode `gated`.

Chaque cycle fixe une hypothèse, une métrique de gain et des seuils avant le holdout. Comparer
la version réellement active et le candidat sur les mêmes snapshots, avec une variable principale
modifiée et plusieurs répétitions. Une campagne modifiant plusieurs variables reste exploratoire.
Un résultat incomplet, non comparable ou indéterminé ne permet aucune promotion.

Le snapshot fige base, précision, tokenizer, format de chat, digest d'adaptateur éventuel,
politique et budget Memory, driver, paramètres d'inférence, prompts, tools, mécanismes,
corpus/révisions, juge, calibration, rubriques et versions de score. Modifier ces éléments crée
une nouvelle campagne ; les résultats historiques restent attachés à leur snapshot.

Les décisions fermées, ACL, digests, schémas, événements d'outil, erreurs, coûts et latences sont
mesurés déterministement. Le juge traite les dimensions ouvertes, en aveugle baseline/candidat,
étalonné humainement et distinct du candidat si le risque d'auto-préférence le justifie.
Sa panne laisse un score absent et une campagne incomplète.

### 12.2 Comparaison propre à LoRA

| Configuration | Preuve recherchée |
|---|---|
| Résolution active + rappel actuel | Baseline opérationnelle figée |
| Candidat LoRA + rappel identique | Effet propre de l'adaptateur et stabilité avec Memory normale |
| Candidat LoRA + contexte stable réduit | Économie visée, en conservant faits courants, sources et tools |

Une base nue peut compléter l'expérience ; elle ne remplace pas la baseline active. Le Lab doit
accepter une cible `base + adapter + politique Memory` et une campagne composite conservant
les scores par mécanisme, dimension et cas. Réutiliser Dispatcher, Briefing, Planner, Memory,
Dream et Goal, puis des Tasks représentatives sans effet externe, avec frontières d'outils
simulées ou résultats enregistrés dans un harness dédié.

Séparer cinq rôles : training (seul à mettre à jour les poids), travail (diagnostic), validation
(sélection/arrêt), holdout (généralisation finale) et sentinelles (incidents et garanties critiques).
Aucune preuve parente ne traverse les partitions via ses reformulations. Les incidents de
production rejoignent les sentinelles après revue ; le trafic n'est jamais une vérité automatique.

Mesurer procédures reformulées, capacités générales, langues/raisonnement, stabilité par replay,
formats/tools/plans/résultats structurés, fraîcheur, oubli, correction, contradiction, isolement
inter-agent et extraction de données sensibles. Publier séparément réussite des Tasks, variance,
tokens économisés, préremplissage, premier token, débit, HBM, durée et coût de consolidation.
Un gain de qualité sans réduction du goulet Memory ne valide pas l'hypothèse initiale.

### 12.3 Gardes et activation

| Garde | Exigence | Échec |
|---|---|---|
| ACL, données sensibles, isolement | Aucune fuite ou régurgitation interdite | Rejet immédiat |
| Oubli, correction, contradiction | Aucun usage d'un fait invalidé | Rejet immédiat |
| Fraîcheur | Consultation correcte de Memory ou de la source | Rejet immédiat |
| Outils, effets, contrats agentiques | Arguments, preuves, formats et stream terminal conformes | Rejet |
| Sentinelles | Aucune nouvelle défaillance critique | Rejet |
| Couverture et comparabilité | Tous les cas requis évalués, snapshots et jugements compatibles | Indéterminé |
| Stabilité et capacités générales | Dispersion, décisions instables et régressions sous les seuils calibrés | Pas de promotion |
| Gain ciblé | Minimum annoncé atteint sur les tâches réelles | Pas de promotion |

Calibrer les seuils par famille avec annotations humaines et coût métier des erreurs. Aucune
moyenne ne compense une garde critique ou une régression matérielle prioritaire.

Après réussite, préchauffer l'artefact vérifié et ouvrir un canari borné sur des tâches/cohortes
comparables, sans échange d'adaptateurs entre agents. Conserver la baseline disponible ; elle
ne change qu'après réussite de la fenêtre d'observation et promotion atomique. Dataset et
artefact doivent rester disponibles et vérifiés.

Déclencher rollback sur garde critique, hausse d'erreurs, régression d'outil/format, dérive de
latence ou mémoire hors budget, ou signal humain explicite. Restaurer la baseline sans reconstruire
l'artefact. Après promotion, relancer périodiquement sentinelles et campagne stable ; une dérive
entraîne rollback ou suspension. Chaque incident confirmé devient une non-régression.

## 13. Correction, oubli et invalidation

Les poids ne permettent pas l’équivalent immédiat de `memory_forget`. Cette limitation interdit de
considérer l’adaptateur comme l’autorité.

Chaque corpus conserve la liste exacte des items et révisions utilisés. Lorsqu’un item est oublié,
corrigé de manière incompatible, reclassé sensible ou rendu inéligible :

1. toutes les versions qui le référencent sont identifiées ;
2. une version active est immédiatement invalidée ;
3. les nouveaux runs replient vers la base + Memory ;
4. un snapshot propre sans cet item est préparé ;
5. un nouvel adaptateur doit être reconstruit depuis la base ;
6. l’ancien artefact est supprimé du serving puis du registre selon la politique applicable.

Une tentative de contre-entraînement pour « faire oublier » un fait précis n’est pas le chemin
normal : son résultat est difficile à prouver et peut laisser des traces récupérables. Pour cette
raison, les données personnelles, sociales, partagées ou fortement révocables restent exclues par
défaut de la consolidation paramétrique.

## 14. Observabilité et audit

Les écrans et traces doivent permettre de répondre sans lire le contenu privé :

- pourquoi un cycle a été proposé ;
- quels UUID et révisions ont été sélectionnés ou exclus ;
- quelle base, recette, infrastructure et quantité de calcul ont été utilisées ;
- quel ProcessRun a produit l’artefact ;
- quelles évaluations ont autorisé ou refusé la promotion ;
- quelle version a servi chaque run ;
- combien de tokens de mémoire et de millisecondes ont réellement été économisés ;
- quelle invalidation a entraîné un repli ou une reconstruction.

Les métriques restent à cardinalité bornée. Les contenus Memory, exemples d’entraînement,
credentials, chemins de registre et sorties brutes du trainer ne sont jamais placés dans les logs
ou labels.

## 15. Sécurité de la boucle d’apprentissage

La boucle doit résister aux risques suivants :

- **empoisonnement conversationnel** : un interlocuteur ne peut rendre une instruction
  entraînable par répétition ;
- **auto-confirmation** : plusieurs reformulations issues du même modèle ou de la même preuve ne
  constituent pas plusieurs confirmations ;
- **model collapse** : le replay conserve des données et preuves originales, pas uniquement des
  générations successives du modèle ;
- **oubli catastrophique** : reconstruction depuis la base, replay et tests de régression ;
- **fuite inter-agent** : corpus propriétaire, serving par identifiant et tests négatifs ;
- **supply chain** : digests, registre allow-listé, formats bornés et trainer isolé ;
- **prise de contrôle par le modèle** : aucun tool agentique ne peut promouvoir, charger ou
  supprimer un adaptateur ;
- **coût incontrôlé** : budgets GPU, refroidissement, quotas et concurrence bornée ;
- **déploiement incohérent** : version figée par run et rollback atomique.

## 16. Phasage proposé et preuves de sortie

| Phase | Travail propre à la phase | Condition de sortie |
|---|---|---|
| 0 — Mesurer | Rappel, préremplissage, contexte stable, procédures répétées ; corpus et baselines Lab micro/end-to-end, incidents et seuils de poursuite | Rapport montrant un gain potentiel matériel, sans GPU ni domaine d'adaptation requis |
| 1 — Expérimenter hors production | Un agent volontaire, base minimale V4 Flash figée, corpus audité d'abord synthétique/non sensible, PEFT manuel isolé ; qualifier séparément trainer, artefact et multi-LoRA, sans resolver de production | Campagnes répétées baseline/candidat/contexte réduit et revue humaine prouvant ou réfutant l'hypothèse sur des Tasks Galaris |
| 2 — Gouverner | Éligibilité, snapshots, filiation, invalidation, ProcessRun idempotent et registre ; cible composite et rapports Lab ; mode `observe` sans serving | Candidat reproductible et auditable sans activation |
| 3 — Servir sous contrôle | Provider compatible, registre de confiance, résolution versionnée, campagne concluante, canari manuel, rollback/repli, traces des runs et appels | Activation manuelle pour une population bornée |
| 4 — Automatiser les candidats | Signaux Dream, seuils de valeur, budgets, reconstruction cumulative, mode `candidate`, évaluation complète et répétée | Entraînement automatique ; activation encore décidée par l'opérateur |
| 5 — Promouvoir sous gardes | Mode `gated` sur agents/bases autorisés, prérequis Lab qualifiés, canari/surveillance/invalidation/rollback automatiques, limite de taux et arrêt global | Apprentissage réversible avec revue périodique des gains, régressions et coûts |

Les dépendances d'une phase restent celles des sections précédentes. La phase 0 peut être
préparée sans station de training ; elle n'est pas déclarée engagée par ce plan `design`.
Aucune activation n'est permise sur un résultat incomplet ou non comparable. La première
livraison garde le mode `off` ; `gated` reste une étape de maturité.

## 17. Critères d’arrêt

Le projet ne dépasse pas la phase expérimentale si l’un des constats persiste :

- le rappel et le préremplissage ne constituent pas un coût matériel ;
- le candidat ne réduit pas significativement le contexte sur des tâches réelles ;
- RAG seul reste plus fiable ou moins coûteux ;
- les régressions générales dépassent le bénéfice ciblé ;
- l’oubli et l’invalidation ne peuvent être opérés assez rapidement ;
- les coûts de training, de serving ou d’évaluation dépassent les économies ;
- les données disponibles sont trop synthétiques, trop faibles ou trop sensibles ;
- la qualité varie trop entre agents ou versions de base pour automatiser la promotion ;
- le juge Lab ne peut pas être calibré ou sa variance rend les décisions instables ;
- les datasets ne séparent pas suffisamment training, validation, holdout et sentinelles.

Un arrêt ne remet pas en cause Dream ni Memory : leurs mécanismes restent utiles indépendamment du
fine-tuning.

## 18. Hors périmètre initial

- fine-tuning complet de tous les poids ;
- pré-entraînement continu d’un foundation model Galaris ;
- entraînement sur des fournisseurs fermés sans export ni versionnement d’artefact ;
- fusion d’adaptateurs de plusieurs agents ;
- apprentissage fédéré ou transfert automatique d’une procédure entre agents ;
- adaptation des modèles de voix, vision, embedding ou temps réel ;
- apprentissage immédiat après chaque tour ;
- entraînement décidé ou déclenché par un LLM via un tool ;
- suppression d’un souvenir directement dans les poids par model editing ;
- promesse de supprimer tout rappel Memory après activation d’un adaptateur.

## 19. Questions à trancher après la phase 1

1. Quelle révision et quel format de DeepSeek V4 Flash offrent le chemin PEFT puis multi-LoRA le
   plus reproductible sans sacrifier le tool calling ?
2. Quels modules du MoE, quel rang LoRA et quelle recette donnent un gain sans perturber le
   routage ni provoquer de surapprentissage ?
3. Le serveur d'inférence peut-il charger dynamiquement plusieurs adapters V4 Flash non fusionnés ?
4. Faut-il un adaptateur unique par agent et base, ou séparer comportement et procédures ?
5. Quel volume minimal de preuves indépendantes rend une procédure entraînable ?
6. Quelle part de replay général est nécessaire pour chaque reconstruction ?
7. Quelle économie de tokens ou latence justifie un cycle ?
8. Combien d’adaptateurs le serveur peut-il garder chauds sans dégrader le débit ?
9. Quel délai maximal entre oubli d’un item et désactivation effective d’un adaptateur ?
10. Le `ProcessRun` actuel suffit-il pour le trainer ou faut-il généraliser un contrat de job
   système interne sans exposer un nouvel outil aux agents ?
11. Quelles évaluations peuvent devenir des gardes déterministes de promotion automatique ?
12. À partir de quelles mesures une station unique cesse-t-elle de suffire et justifie-t-elle la
    séparation durable des nœuds d'inférence et de training ?
13. Quel profil de campagne Lab combine les mécanismes micro et les Tasks end-to-end sans masquer
    une régression locale derrière une moyenne ?
14. Combien de répétitions et quelle fenêtre de canari rendent la décision assez stable pour chaque
    classe d'agent et de tâche ?

## 20. Références de recherche

- [LoRA — Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)
- [QLoRA — Efficient Finetuning of Quantized LLMs](https://arxiv.org/abs/2305.14314)
- [Fine-Tuning or Retrieval? Comparing Knowledge Injection in LLMs](https://aclanthology.org/2024.emnlp-main.15/)
- [Does Fine-Tuning LLMs on New Knowledge Encourage Hallucinations?](https://aclanthology.org/2024.emnlp-main.444/)
- [Continual Learning of Large Language Models: A Comprehensive Survey](https://arxiv.org/abs/2404.16789)
- [Model Editing at Scale leads to Gradual and Catastrophic Forgetting](https://aclanthology.org/2024.findings-acl.902/)
- [AI models collapse when trained on recursively generated data](https://www.nature.com/articles/s41586-024-07566-y)
- [vLLM — LoRA Adapters](https://docs.vllm.ai/en/stable/features/lora/)
- [DeepSeek V4 Flash — modèle et poids officiels](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash)
- [vLLM — recette de déploiement DeepSeek V4 Flash](https://recipes.vllm.ai/deepseek-ai/DeepSeek-V4-Flash)
- [NVIDIA NeMo AutoModel — entraînement DeepSeek V4 Flash](https://github.com/NVIDIA-NeMo/Automodel/blob/main/docs/guides/llm/dsv4-flash.md)
- [NVIDIA DGX Station — architecture et mémoire](https://docs.nvidia.com/dgx/dgx-station-development-guide/overview.html)
- [AMD Instinct MI325X — caractéristiques officielles](https://www.amd.com/en/products/accelerators/instinct/mi300/mi325x.html)

Ces références établissent la faisabilité des adaptateurs et du serving multi-LoRA, mais aussi les
limites de l’injection factuelle, de l’apprentissage continu et des données récursivement
générées. Les références V4 Flash établissent séparément son échelle, son déploiement et son
entraînement général ; elles ne démontrent pas à elles seules la compatibilité multi-LoRA de bout
en bout exigée par Galaris. Les seuils et décisions de production devront provenir des évaluations
Galaris, pas être déduits directement de benchmarks externes.
