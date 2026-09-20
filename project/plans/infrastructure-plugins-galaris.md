# Plan — Infrastructure de plugins distribuables pour Galaris

> **Statut :** `design` — architecture cible et ordre de réalisation proposés ; ce document
> n'autorise aucune modification du runtime, du schéma ou de l'interface.
>
> **Date de création :** 3 septembre 2026.
>
> **But :** permettre à Galaris d'installer, valider, activer, désactiver, mettre à jour et retirer
> des plugins versionnés comportant une partie backend et une partie frontend, puis faire évoluer
> cette infrastructure vers un store intégré de bundles signés.

## 1. Résultat cible

Galaris conserve ses trois couches structurelles :

- `core` fournit la tuyauterie technique réutilisable et ne dépend jamais d'un plugin ;
- `app` contient les domaines métier appartenant au produit Galaris ;
- `bridge` contient les connecteurs livrés et maintenus avec Galaris ;
- `plugins` identifie une origine de distribution et une frontière de confiance, pas une quatrième
  responsabilité métier.

Un plugin peut apporter un nouveau métier, adapter un système externe ou contribuer à un domaine
existant par un port public. Son emplacement est `back/plugins/<plugin>/` et
`front/plugins/<plugin>/`, mais sa nature fonctionnelle et ses dépendances restent déclarées dans
son manifeste.

La cible sait :

1. installer un ZIP sans l'activer ;
2. vérifier son identité, son intégrité, sa compatibilité et ses permissions ;
3. conserver plusieurs versions immuables d'un même plugin ;
4. sélectionner une version puis l'activer avec un redémarrage coordonné ;
5. charger ses contributions backend comme celles d'un module déclaré ;
6. charger son frontend précompilé depuis un manifeste runtime ;
7. désactiver le plugin sans perdre ses données ;
8. revenir à une version antérieure compatible ;
9. distinguer retrait du code et purge destructive des données ;
10. utiliser la même chaîne pour un ZIP local et, ultérieurement, un store distant signé.

## 2. État actuel vérifié

### 2.1 Backend

`back/modules.py` contient un registre statique. Les modules actifs peuvent contribuer par
convention des modèles SQLAlchemy, routers FastAPI, privilèges, datasets DbAdmin et outils MCP.
Certains registres spécialisés chargent aussi les providers LLM, drivers, Harnesses et
superviseurs.

Cette base permet de traiter un plugin comme un module à la composition, mais pas encore :

- de découvrir une version installée dans un volume persistant ;
- de distinguer version installée, désirée et effectivement activée ;
- de valider toutes les contributions avant de les rendre visibles ;
- d'appliquer atomiquement un ensemble cohérent de plugins ;
- de revenir automatiquement à la dernière génération fonctionnelle.

Les chargeurs optionnels ne distinguent pas tous une capacité absente d'une dépendance cassée à
l'intérieur du module. Le contrat plugin devra être plus strict et échouer avant activation.

### 2.2 Base de données

`core.dbadmin` importe les modèles des modules déclarés, construit la cible SQLAlchemy du schéma
`public`, puis Atlas applique sa convergence. L'entrypoint effectue cette synchronisation avant le
démarrage de FastAPI.

Retirer un plugin de la cible ne peut donc pas être assimilé à une simple désactivation : ses
tables pourraient apparaître comme des objets à supprimer. Le registre devra séparer les plugins
dont le schéma reste installé de ceux dont les capacités runtime sont actives.

### 2.3 Frontend

`front/modules.ts` déclare les modules frontend. Vite lit cette liste pendant le build pour
produire les routes basées sur les fichiers. Les fichiers `navigation.ts` et `i18n.ts` sont eux
aussi agrégés au sein du bundle.

En production, Nginx sert des ressources statiques déjà compilées. Copier du TypeScript ou des
fichiers Vue après le build ne peut donc pas ajouter une interface. Un plugin distribuable doit
fournir un artefact frontend précompilé et un entrypoint runtime stable.

### 2.4 Déploiement

Le backend possède déjà un volume persistant `/data`, tandis que le frontend de production est une
image Nginx sans accès à ce volume. Une zone publique dédiée aux artefacts frontend des plugins
devra être exposée sans rendre accessibles les autres données de `/data`.

### 2.5 Alignement avec la cible prospective

`project/plans/cible.md` prévoit déjà :

- l'installation et le retrait d'extensions sans modifier un registre statique du cœur ;
- un SDK minimal et un TCK exécutable hors du monorepo ;
- un format de bundle, des compatibilités et permissions déclarées ;
- SBOM, provenance, signature, révocation et rollback ;
- un registre personnel puis fédéré.

Le présent plan précise l'infrastructure de modules back/front nécessaire à cette intention. Il ne
remplace ni les gates du Trust Kernel, ni ceux de la supply chain décrits par la cible générale.

## 3. Vocabulaire et objets distincts

| Notion | Définition |
|---|---|
| Plugin | Identité fonctionnelle stable, indépendante d'une version. |
| Release | Version immuable d'un plugin et empreinte exacte de son bundle. |
| Bundle | Archive ZIP distribuée contenant manifeste, sources, artefacts et attestations. |
| Installation | Release vérifiée et présente dans le stockage local, mais pas nécessairement active. |
| Deployment | Version désirée et version effective du plugin pour une installation Galaris. |
| Génération | Snapshot atomique de l'ensemble des plugins effectifs au prochain démarrage. |
| Catalogue | Index consultable de plugins et releases, sans pouvoir d'activation. |
| Store | Interface Galaris consommant un catalogue et orchestrant l'installation locale. |
| Retrait | Suppression de l'exécution et de l'interface, avec conservation des données par défaut. |
| Purge | Suppression destructive et explicite des données et artefacts retenus. |

Télécharger, installer et activer restent trois opérations différentes. La disponibilité d'une
release dans un catalogue ne lui confère aucun droit local.

## 4. Répartition des responsabilités

### 4.1 Domaine `app.plugin`

Un nouveau domaine applicatif posséderait :

- l'inventaire des plugins et releases connus ;
- les installations locales et deployments désirés/effectifs ;
- le workflow de staging, validation, activation, rollback, retrait et purge ;
- le cache de catalogue et la future communication avec le store ;
- les décisions administratives sur les permissions ;
- l'historique et les erreurs expurgées ;
- les endpoints protégés par RBAC ;
- l'interface d'administration correspondante.

Ce domaine orchestre les opérations, mais ne charge pas arbitrairement un plugin au milieu d'une
requête HTTP.

### 4.2 Infrastructure `core`

Une infrastructure générique, sans dépendance vers `app` ou `plugins`, fournirait :

- validation sûre des archives ;
- calcul et vérification des empreintes ;
- validation structurelle du manifeste ;
- stockage immuable et staging atomique ;
- lecture du registre de boot ;
- résolution contrôlée des entrypoints ;
- contrats techniques de contributions ;
- construction et vérification d'une génération.

La composition racine relie cette infrastructure au domaine `app.plugin` et aux surfaces publiques
des autres domaines. `core` ne connaît aucun plugin concret.

### 4.3 Répertoires de développement et d'installation

Les plugins maintenus dans le monorepo utilisent :

```text
back/plugins/<module_python>/
front/plugins/<module_frontend>/
```

Les releases externes ne sont pas copiées dans le checkout ni dans l'image applicative. Elles sont
stockées par version :

```text
/data/plugins/
├── staging/
├── releases/<plugin-id>/<version>/<digest>/
├── retained/<plugin-id>/
├── registry/
│   ├── desired.json
│   ├── effective.json
│   └── last-known-good.json
└── quarantine/
```

Une zone ou un volume séparé contient uniquement les artefacts frontend publics. Le frontend ne
monte jamais le volume général `/data`, qui contient d'autres données potentiellement sensibles.

## 5. Format du bundle

### 5.1 Arborescence proposée

```text
galaris-plugin.zip
├── plugin.json
├── README.md
├── LICENSE
├── back/
│   └── plugins/
│       └── acme_weather/
│           ├── __init__.py
│           ├── plugin.py
│           ├── models.py
│           ├── router.py
│           ├── privileges.py
│           ├── dbadmin.py
│           ├── mcp.py
│           └── tests/
├── front/
│   └── plugins/
│       └── acme_weather/
│           ├── pages/
│           ├── components/
│           ├── services/
│           ├── stores/
│           ├── navigation.ts
│           ├── i18n.ts
│           └── index.ts
├── dist/
│   └── frontend/
│       ├── entry.js
│       ├── styles.css
│       └── assets/
├── assets/
│   ├── icon.png
│   └── screenshots/
└── attestations/
    ├── files.sha256
    ├── sbom.json
    ├── provenance.json
    └── signature.sig
```

Les sources backend et frontend sont obligatoires pour l'audit et la reproductibilité. Pour une
installation de production, `dist/frontend` est également obligatoire. Galaris ne lance ni
`npm install`, ni script de build fourni par un plugin sur l'hôte de production.

### 5.2 Identité

Le manifeste sépare :

- un identifiant global immuable, par exemple `io.acme.weather` ;
- un code local lisible, par exemple `acme-weather` ;
- un nom de module Python sûr, par exemple `acme_weather`.

L'identifiant et le code ne changent jamais entre deux releases. Un changement d'identité crée un
nouveau plugin. Une seule release d'un identifiant peut être effective dans une génération.

### 5.3 Métadonnées minimales

Le manifeste versionné contient au moins :

- version du format de bundle ;
- identifiant, code, libellé et description localisés ;
- version SemVer de la release ;
- auteur, éditeur, licence, dépôt source et documentation ;
- icône, captures d'écran, types MIME et textes alternatifs ;
- intervalle de versions Galaris compatibles ;
- version de l'API backend des plugins ;
- version du SDK frontend ;
- version minimale de Python et contraintes de plateforme éventuelles ;
- entrypoints backend et frontend ;
- contributions annoncées ;
- permissions demandées ;
- objets SQL possédés et préfixe réservé ;
- dépendances et incompatibilités avec d'autres plugins ;
- politique de mise à jour et compatibilité de rollback déclarée ;
- empreinte de tous les fichiers, SBOM, provenance et signature.

Aucun secret, jeton, mot de passe ou binding local n'entre dans le bundle. Le manifeste ne contient
que les besoins de configuration ; les valeurs sont liées localement après installation.

## 6. Contrat backend

### 6.1 Entry point explicite

Chaque release backend expose un entrypoint unique déclaré dans le manifeste. Celui-ci produit une
description typée et sans effet de bord des contributions :

- package de modèles SQLAlchemy ;
- router FastAPI ;
- privilèges ;
- sources, actions ou reconcilers DbAdmin ;
- outils MCP ;
- paramètres et catalogues backend ;
- composants runtime supervisés ;
- implémentations de ports publics explicitement supportés.

Le manifeste et l'entrypoint doivent annoncer le même ensemble. Une contribution manquante,
supplémentaire ou impossible à importer invalide la release avant activation.

### 6.2 Dépendances autorisées

Un plugin backend peut dépendre :

1. du SDK public correspondant à la version déclarée ;
2. des racines publiques de `core` autorisées par ce SDK ;
3. des racines, `contracts`, `facade` ou `interface` publiques des domaines `app` ;
4. d'un autre plugin uniquement si la dépendance est déclarée et passe par sa surface publique.

Sont interdits :

- les imports vers les services internes ou modèles ORM d'un autre domaine ;
- les imports du cœur ou d'un domaine applicatif vers un plugin ;
- les monkeypatchs et remplacements implicites de symboles Galaris ;
- l'ordre d'import utilisé comme mécanisme d'intégration ;
- la modification de `back/modules.py`, `pyproject.toml` ou du virtualenv courant.

Pour le premier palier, un plugin in-process utilise uniquement les dépendances Python déjà
fournies par le SDK et l'image Galaris. Une dépendance système ou Python supplémentaire exige soit
une évolution gouvernée de l'image, soit le futur mode isolé.

### 6.3 Espaces de noms

Les contributions sont préfixées afin d'éviter les collisions :

- routes HTTP : `/api/plugins/<code>/...` ;
- tables et séquences : `plg_<code_sql>_*` ;
- enums et contraintes : préfixe possédé par le plugin ;
- privilèges : `PLUGIN_<CODE>_*` ou espace logique équivalent ;
- outils MCP : `<code>.*` ;
- composants runtime : `plugin:<code>:*` ;
- paramètres et clés i18n : `plugins.<code>.*`.

Un plugin ne remplace pas une route, un outil, une traduction ou un composant du cœur en dehors
d'un point d'extension explicitement conçu pour cela.

## 7. Contrat frontend

### 7.1 Pourquoi un artefact runtime est nécessaire

Le frontend Galaris est compilé avant son déploiement. La découverte Vite des pages ne peut pas
voir une release installée après ce build. Compiler les sources d'un plugin sur le serveur de
production introduirait en outre des scripts npm arbitraires, des dépendances non verrouillées et
un résultat difficile à attribuer.

Chaque release fournit donc un module JavaScript précompilé par une toolchain officielle et signé
avec le reste du bundle. Les sources Vue/TypeScript restent incluses et doivent permettre de
reproduire l'artefact.

### 7.2 Manifeste runtime

Au démarrage de l'interface, le shell obtient un manifeste contenant uniquement les releases
effectives et leurs URLs content-addressées :

```text
/plugins/<code>/<version>/<digest>/entry.js
```

L'entrypoint reçoit une API frontend bornée et peut enregistrer :

- routes sous l'espace du plugin ;
- navigation ;
- traductions `fr` et `en` ;
- composants destinés à des slots d'extension déclarés ;
- services API et stores propres au plugin ;
- nettoyage associé à sa désactivation logique.

Vue, Quasar, Pinia, Vue Router et vue-i18n sont fournis par l'hôte selon le SDK annoncé. Le bundle
ne doit pas embarquer une seconde instance de ces runtimes. Les imports privés vers les composants
internes de Galaris sont interdits.

### 7.3 Cache et cohérence

- les artefacts versionnés portent un cache immuable ;
- le manifeste runtime n'est pas mis en cache durablement ;
- une nouvelle génération utilise de nouvelles URLs ;
- la PWA ne précache pas automatiquement les releases absentes au build du cœur ;
- une interface ouverte lors d'une activation reçoit une demande de rafraîchissement ;
- un plugin absent du manifeste effectif ne peut pas conserver une route active après recharge.

## 8. Registres et persistance

### 8.1 Modèle durable

Le domaine de gestion devrait distinguer au moins :

- `Plugin` : identité et métadonnées stables ;
- `PluginRelease` : version, manifeste, empreinte, signature et compatibilité ;
- `PluginInstallation` : présence locale et résultat des validations ;
- `PluginDeployment` : version désirée, version effective et état d'activation ;
- `PluginPermissionGrant` : permissions acceptées localement ;
- `PluginEvent` : journal des installations, erreurs, activations, rollbacks, retraits et purges.

Les transitions concurrentes sont sérialisées par plugin et par génération. Une clé d'idempotence
empêche un retry d'installer ou d'activer deux fois la même release.

### 8.2 Projection de boot

Le backend doit connaître les modèles à charger avant que toute l'application soit disponible. Le
registre effectif est donc matérialisé atomiquement sur le volume persistant à partir de l'état
durable.

Le fichier de boot contient uniquement :

- numéro et empreinte de génération ;
- releases sélectionnées avec chemins et digests exacts ;
- ensemble `schema_installed` ;
- ensemble `runtime_enabled` ;
- dernière génération fonctionnelle.

Il ne contient aucun secret. PostgreSQL conserve l'administration et l'audit ; cette projection
est un artefact de déploiement vérifiable, pas une seconde base métier.

## 9. Cycle de vie

### 9.1 États

```text
UPLOADED
  → STAGED
  → VERIFIED
  → INSTALLED
  → PENDING_ENABLE
  → ENABLED

PENDING_ENABLE → FAILED → INSTALLED
ENABLED → PENDING_DISABLE → DISABLED
DISABLED → RETAINED → PURGED
```

Une version peut rester `INSTALLED` sans être active. `FAILED` conserve un diagnostic expurgé et
ne modifie pas la génération effective.

### 9.2 Installation

1. recevoir un ZIP local ou téléchargé par le store ;
2. borner sa taille compressée, sa taille extraite et son nombre de fichiers ;
3. refuser path traversal, liens symboliques, types spéciaux et bombes de compression ;
4. extraire dans un staging non exécutable ;
5. valider manifeste, arborescence, empreintes et signature ;
6. vérifier compatibilités, dépendances, collisions et permissions ;
7. exécuter le TCK et les imports dans une validation isolée ;
8. déplacer atomiquement la release vers son chemin immuable ;
9. persister l'installation comme inactive.

L'échec de n'importe quelle étape laisse la génération courante inchangée.

### 9.3 Activation

Le premier contrat ne promet pas de chargement backend à chaud. L'activation prépare une nouvelle
génération appliquée lors d'un redémarrage contrôlé :

1. verrouiller l'opération de deployment ;
2. résoudre la version demandée et ses dépendances ;
3. vérifier de nouveau digest, compatibilité et grants ;
4. précharger les entrypoints dans un processus sans secret ;
5. calculer la cible DbAdmin candidate et son delta ;
6. refuser par défaut une opération destructive ou hors espace possédé ;
7. publier les artefacts frontend content-addressés ;
8. écrire atomiquement la génération désirée ;
9. redémarrer le backend ;
10. faire converger schéma et datasets avant FastAPI ;
11. charger routes, outils et composants runtime ;
12. attendre readiness et probes propres au plugin ;
13. promouvoir la génération en `effective` ou restaurer `last-known-good`.

Une activation intégrée sans intervention shell exigera ultérieurement un superviseur de
déploiement à privilèges bornés. Le backend ne reçoit pas le socket Docker complet.

### 9.4 Désactivation

La désactivation :

- retire le plugin de `runtime_enabled` ;
- arrête ses composants supervisés au redémarrage ;
- retire routes, outils, navigation et entrypoint frontend ;
- conserve sa release sélectionnée dans `schema_installed` ;
- conserve tables, paramètres, connexions, grants et données ;
- n'exécute plus ses datasets ou reconcilers fonctionnels, hors action explicite de conservation.

### 9.5 Mise à jour et rollback

Une mise à jour installe toujours une nouvelle release à côté de l'ancienne. Elle ne remplace aucun
fichier en place.

Le workflow applique une stratégie expand/contract : la nouvelle version doit tolérer le schéma
de transition et l'ancienne doit rester exploitable tant que le rollback est annoncé compatible.
Un changement destructif, un backfill volumineux ou une transformation irréversible utilise les
contrats avancés de DbAdmin et exige sauvegarde, revue et politique de reprise explicites.

Un rollback revient à une empreinte exacte. Il ne promet jamais d'annuler une transformation de
données sans action inverse déclarée et testée.

### 9.6 Retrait et purge

Le retrait exige que le plugin soit désactivé. Il retire ses surfaces exécutables, mais conserve
par défaut l'inventaire de ses objets SQL et les éléments nécessaires à leur protection contre une
suppression implicite.

La purge est séparée et destructive. Elle :

- affiche les tables, fichiers, paramètres et connexions concernés ;
- exige une confirmation forte et les privilèges correspondants ;
- vérifie qu'aucun autre plugin ne dépend de la release ;
- produit ou exige une sauvegarde selon la politique ;
- supprime par une action DbAdmin gouvernée, jamais par disparition silencieuse des modèles ;
- journalise l'opérateur, la génération et le résultat.

## 10. Intégration DbAdmin

Le schéma `public` reste sous l'autorité unique de `core.dbadmin`. Un plugin ne livre ni migration
Alembic, ni script SQL exécuté directement, ni outil Atlas autonome.

Règles proposées :

1. les modèles d'une release installée et sélectionnée participent à la cible même si son runtime
   est désactivé ;
2. les objets possédés utilisent un préfixe réservé et sont comparés au manifeste ;
3. un plugin ne modifie pas une table, un enum ou une contrainte appartenant au cœur ou à un autre
   plugin ;
4. les FK vers une surface stable du cœur restent exceptionnelles et explicites ;
5. les datasets permanents déclarent leur propriétaire et leurs dépendances ;
6. disparition du code, manifeste incomplet ou import défaillant ne vaut jamais autorisation de
   `DROP` ;
7. toute suppression d'objet appartient à une purge ou à une évolution destructive explicitement
   approuvée ;
8. les changements avancés utilisent `DbAdminAction` ou `DbAdminReconciler` avec postcondition et
   idempotence.

Une évolution ultérieure pourra conserver les objets d'un plugin retiré à partir d'un inventaire
de schéma signé, sans réimporter son code exécutable. Ce format doit rester généré depuis les
modèles SQLAlchemy et intégré à la cible DbAdmin, pas devenir une seconde autorité DDL.

## 11. Permissions, secrets et confiance

### 11.1 Permissions déclarées

Le manifeste décrit au minimum les besoins suivants :

- routes et privilèges exposés ;
- accès réseau sortant et destinations attendues ;
- accès aux connexions et secrets locaux ;
- lecture ou écriture de fichiers ;
- outils MCP et catégories d'effets ;
- tâches périodiques ou listeners ;
- subprocess ou runtime externe ;
- modèles et données persistantes ;
- points d'extension frontend utilisés.

L'administrateur accepte une version précise de ces permissions. Une mise à jour qui les élargit
repasse en attente d'approbation.

Les secrets sont créés ou sélectionnés localement après installation, via les domaines Galaris
propriétaires. Ils ne sont jamais copiés dans le manifeste, le registre de boot, les logs ou les
artefacts frontend.

### 11.2 Limite du mode natif

Un plugin Python importé dans le backend peut techniquement accéder au processus, à son réseau, à
ses variables d'environnement et aux bibliothèques chargées. Un plugin JavaScript exécuté dans la
même origine peut interagir avec le contexte authentifié de l'interface.

Une permission déclarative et une signature n'isolent pas ce code. Le premier palier est donc un
mode **natif de confiance**, réservé aux plugins audités et signés par une autorité acceptée par
l'administrateur.

### 11.3 Mode isolé futur

Un store ouvert à des éditeurs tiers nécessite un second mode :

- backend du plugin dans un conteneur ou processus dédié ;
- identité de service et jetons limités ;
- réseau deny-by-default ;
- volumes et secrets explicitement montés ;
- quotas CPU, mémoire, processus et stockage ;
- communication par API, événements, MCP ou SDK distant ;
- frontend isolé lorsque les capacités demandées l'exigent, par exemple iframe gouvernée ;
- healthcheck, arrêt et suppression indépendants.

Le mode isolé ne reçoit pas les imports Python privés du monolithe. Il consomme uniquement des
protocoles publics versionnés.

## 12. Store intégré

Le store est un producteur de catalogue, jamais l'autorité d'activation d'une installation.

### 12.1 Catalogue distant

Il publie :

- identités, descriptions, catégories, icônes et captures ;
- releases disponibles et compatibilités ;
- URL de bundle et empreinte ;
- identité et clés de signature de l'éditeur ;
- SBOM et provenance ;
- permissions demandées ;
- statut de publication, dépréciation ou révocation ;
- résultats du TCK et éventuelles qualifications Galaris.

### 12.2 Client local

`app.plugin` :

- rafraîchit et met en cache les métadonnées non sensibles ;
- compare les versions sans télécharger automatiquement le code ;
- vérifie le bundle indépendamment du transport TLS ;
- refuse une release révoquée, altérée ou incompatible ;
- demande l'approbation des nouvelles permissions ;
- utilise ensuite exactement le workflow d'installation locale.

Le store ne fournit aucune valeur de secret et ne peut activer seul une release.

### 12.3 Premier niveau de distribution

La première version du store doit être un catalogue administré ou explicitement configuré. Une
place de marché publique, les paiements, évaluations sociales et publications autonomes sont hors
du premier périmètre.

## 13. SDK, TCK et contrôles d'architecture

### 13.1 SDK public

Le SDK versionné doit fournir :

- types de manifeste et contributions ;
- contexte backend sans objets internes arbitraires ;
- enregistrement de router, outils, privilèges et runtime ;
- client des façades publiques autorisées ;
- API frontend de routes, navigation, i18n et slots ;
- utilitaires de compatibilité, logs structurés et corrélation ;
- outils de construction reproductible du bundle.

Une évolution incompatible du SDK augmente sa version majeure. La version de Galaris et celle du
SDK restent deux contraintes distinctes.

### 13.2 TCK hors monorepo

Le TCK vérifie au minimum :

- schéma et parité des métadonnées du manifeste ;
- archive sûre, limites et reproductibilité ;
- empreintes, signature, provenance et SBOM ;
- imports publics seulement ;
- absence de collision de routes, tables, outils et privilèges ;
- Pyright strict sur le backend de référence ;
- typecheck Vue/TypeScript et parité i18n `fr`/`en` ;
- conformité RBAC des routes ;
- correspondance entre manifeste et contributions réelles ;
- démarrage, arrêt et healthcheck ;
- installation, interruption, retry et reprise idempotente ;
- désactivation sans perte de schéma ou de données ;
- mise à jour et rollback annoncés ;
- refus d'un bundle altéré, incompatible ou trop permissif.

### 13.3 Cartographie et baselines

La cartographie générée du dépôt reste déterministe et décrit les modules versionnés dans le
monorepo. Elle ne dépend pas des plugins propres à une installation.

- un plugin embarqué dans le dépôt apparaît dans la cartographie et les contrôles ordinaires ;
- une release externe produit sa propre cartographie et son rapport TCK ;
- le runtime expose un inventaire des plugins installés/effectifs avec leurs digests ;
- les règles d'architecture reconnaissent `plugins` comme couche dépendante, jamais comme cible
  d'un import provenant de `core`, `app` ou `bridge` ;
- les dépendances inter-plugins sont déclarées et acycliques.

## 14. Expérience d'administration

L'interface initiale comprend :

- liste des plugins installés avec version désirée et effective ;
- import d'un ZIP ;
- détail du manifeste, des captures, permissions et compatibilités ;
- erreurs de validation sans secret ni trace interne complète ;
- activation/désactivation indiquant clairement qu'un redémarrage est requis ;
- progression du changement de génération et readiness ;
- choix d'une version précédente compatible ;
- retrait conservant les données ;
- purge séparée avec inventaire des effets ;
- journal des opérations administratives.

Le futur onglet Store réutilise les mêmes fiches et workflows. Il ajoute recherche, catégories,
versions disponibles, statut de signature et dépréciation, sans créer un second installateur.

Privilèges minimaux à distinguer : consulter le catalogue, installer une release, approuver des
permissions, activer/désactiver, effectuer un rollback, retirer et purger.

## 15. Observabilité et exploitation

Tout événement, log, span et probe d'un plugin inclut lorsque pertinent :

- identifiant et code du plugin ;
- version et digest de release ;
- génération du deployment ;
- opération d'installation ou d'activation ;
- composant ou contribution concerné ;
- corrélations métier normales de Galaris.

La readiness distingue :

- un plugin requis dont l'échec rend la génération candidate invalide ;
- un composant facultatif dégradé après démarrage ;
- une erreur de configuration locale ;
- une release révoquée ou devenue incompatible.

Les métriques doivent permettre de comparer erreurs, latence, consommation et redémarrages par
release. Les diagnostics publics n'exposent ni chemins internes, ni secrets, ni contenu des
variables d'environnement.

## 16. Lots de réalisation

### Lot 0 — Décisions et contrats

- ADR sur la frontière `plugins` et le niveau de confiance natif ;
- manifeste v1 et espaces de noms ;
- contrats d'entrypoints back/front ;
- politique DbAdmin de conservation et purge ;
- modèle de permissions ;
- stratégie de compatibilité et rollback ;
- threat model de l'installation de code.

Gate : un plugin d'exemple peut être décrit sans import privé, ambiguïté de propriétaire ou étape
de cycle de vie implicite.

### Lot 1 — Bundle et registre local

- stockage, staging, quarantaine et empreintes ;
- import ZIP sécurisé ;
- inventaire durable ;
- registre désiré/effectif par génération ;
- validations structurelles et rapport d'erreur ;
- installation inactive seulement.

Gate : crash ou retry à chaque étape ne corrompt ni release existante ni génération effective.

### Lot 2 — Plugin backend natif

- entrypoint typé ;
- composition des routers, modèles, privilèges, DbAdmin et MCP ;
- runtime supervisé ;
- validation isolée ;
- activation/désactivation au redémarrage ;
- conservation du schéma et rollback last-known-good.

Gate : une release défaillante ne prive pas l'administrateur du cœur de Galaris et n'entraîne aucun
`DROP` implicite.

### Lot 3 — Plugin frontend runtime

- builder officiel ;
- SDK frontend ;
- artefacts content-addressés ;
- endpoint de manifeste runtime ;
- chargement de routes, navigation et i18n ;
- cohérence de cache et rafraîchissement ;
- volume public séparé.

Gate : un plugin activé apparaît après application de la génération ; un plugin désactivé disparaît
après recharge sans rebuild de l'image frontend.

### Lot 4 — Administration complète

- écrans d'import, détail, permissions et versions ;
- orchestration de génération ;
- healthcheck et retour automatique last-known-good ;
- retrait, purge et journal ;
- RBAC et tests de refus ;
- SDK et TCK publiables.

Gate : installation, activation, mise à jour, rollback, désactivation et retrait sont démontrés de
bout en bout sur un plugin de référence maintenu hors de son domaine consommateur.

### Lot 5 — Catalogue signé

- API de catalogue ;
- client et cache local ;
- signatures éditeur et révocation ;
- provenance et SBOM ;
- mises à jour disponibles ;
- interface Store réutilisant l'installateur local.

Gate : catalogue compromis, transport altéré ou release révoquée ne permettent pas l'installation.

### Lot 6 — Exécution isolée

- runner générique ;
- identité et permissions imposées ;
- réseau, ressources, fichiers et secrets bornés ;
- contrats distants versionnés ;
- frontend isolé lorsque nécessaire ;
- TCK adversarial.

Gate : un plugin non fiable ne peut pas lire un secret ou une donnée non accordée, joindre une
destination interdite, modifier le cœur ou survivre à sa désactivation.

## 17. Scénarios d'acceptation

### 17.1 Installation locale

Un administrateur importe un ZIP valide. Galaris affiche identité, version, description, captures,
compatibilité et permissions. La release devient installée mais aucune route, table, tâche ou page
n'est active avant décision explicite.

### 17.2 Activation atomique

Une activation crée une génération candidate. DbAdmin converge le schéma, le backend charge ses
contributions et le frontend reçoit le même digest. La génération ne devient effective qu'après
readiness réussie.

### 17.3 Échec de démarrage

Le plugin lève une erreur à l'import ou dans son healthcheck. Galaris restaure la dernière
génération fonctionnelle, conserve le diagnostic expurgé et reste administrable.

### 17.4 Désactivation sans perte

Après désactivation et redémarrage, routes, outils, listeners et UI ont disparu. Les tables et
données sont intactes. Une réactivation de la même release retrouve son état antérieur.

### 17.5 Mise à jour et rollback

Une seconde version est installée à côté de la première. L'activation conserve les digests exacts.
En cas de régression, le rollback revient à la release précédente si son contrat de compatibilité
le permet, sans réécrire l'historique d'installation.

### 17.6 Retrait et purge

Le retrait ne provoque aucune suppression SQL implicite. La purge présente un inventaire, refuse
les dépendances encore actives, exige confirmation et journalise chaque effet.

### 17.7 Store

Une release découverte dans le store suit exactement le même pipeline qu'un ZIP local. Une
signature invalide, une permission élargie non approuvée ou une incompatibilité bloque
l'installation ou l'activation.

## 18. Questions à trancher avant implémentation

1. Quelle autorité signe les premiers plugins : projet Galaris uniquement, liste de clés
   administrables ou les deux ?
2. Quelle technologie charge les modules frontend distants tout en partageant une seule instance
   de Vue, Quasar, Pinia, Router et i18n ?
3. Quelle représentation signée permet à DbAdmin de retenir les objets SQL après retrait complet
   du code sans créer une seconde autorité de schéma ?
4. Le premier palier autorise-t-il les dépendances entre plugins ou les interdit-il jusqu'au TCK
   multi-plugin ?
5. Quel composant applique un redémarrage depuis l'interface sans exposer le socket Docker au
   backend ?
6. Quels points d'extension frontend sont suffisamment stables pour le SDK v1 ?
7. Quelle politique de sauvegarde est obligatoire avant une évolution destructive ou une purge ?
8. Le store initial est-il exclusivement officiel ou peut-il agréger des catalogues administrés
   par l'opérateur ?

## 19. Hors périmètre initial

- activation/désactivation backend à chaud ;
- compilation npm ou installation pip arbitraire en production ;
- mutation automatique de `modules.py`, `modules.ts`, `pyproject.toml` ou `package.json` ;
- patch d'un composant interne sans point d'extension public ;
- suppression automatique des données à la désinstallation ;
- place de marché publique, paiement et notation sociale ;
- promesse de sandbox pour un plugin natif in-process ;
- coexistence simultanée de plusieurs versions effectives du même plugin ;
- migrations Alembic ou gestion Atlas autonome par un plugin.

## 20. Décision directrice proposée

Le premier palier doit privilégier un contrat simple et vérifiable : plugins natifs de confiance,
bundles immuables et signés, frontend précompilé, installation inactive, activation au redémarrage,
schéma conservé à la désactivation et génération last-known-good.

Le store réutilise ensuite cette infrastructure au lieu d'introduire une seconde chaîne
d'installation. L'ouverture à des éditeurs non fiables reste conditionnée à un mode d'exécution
isolé capable d'imposer réellement les permissions déclarées.
