# Processus internes — contrats d'activités et exécution de code isolée

- Statut : `partial` — contrats locaux typés et parcours applicatifs réalisés ; runner de production et qualification avancée ouverts.
- Mise à jour : 2026-10-16, selon les précisions utilisateur et le worktree courant.
- Objectif restant : qualifier et installer le runner fortement isolé, son intermédiaire
  MCP/REST et son déploiement séparé, puis compléter les campagnes de charge et de reprise.

Le contrat cible ci-dessous reste la grille de réception des lots encore partiels.
Les contrats réalisés appartiennent à la
[décision 0174](../decisions/0174-native-document-backed-business-processes.md), au
[profil natif actuel](../../docs/fr/dev/native-processes.md), au
[parcours utilisateur](../../docs/fr/user/internal-processes.md) et aux
[tests fonctionnels](../../docs/fr/dev/functional-tests.md).
La capacité REST des Tools/Connections et sa façade asynchrone sont réalisées : les
réutiliser selon la [décision 0182](../decisions/0182-tool-rest-capability.md), sans refaire
leur configuration, chiffrement, héritage des paramètres ou transport HTTP.
Ces acquis ne prouvent ni la qualification sécuritaire de l'exécuteur isolé,
ni une validation globale ou un déploiement.

### Avancement du 16 octobre 2026

Les IF ont deux sorties True/False et réutilisent les tentatives durables pour IA, code
et humain. Les modes dépendent de l'acteur : IA/code pour agent, humain imposé pour humain.
L'éditeur conserve les instructions, les sources et les déclarations. Les choix humains
passent par les boutons Messenger. Les computations pures sur snapshot du Dataset utilisent
un worker Monty neuf avec limites et sans capacités hôte ; les clés Python utilisables sont
accessibles directement, et le moteur valide puis intègre les sorties retournées.
Cette livraison remplace le constat historique « aucun adapter réel » ci-dessous pour
ce seul sous-ensemble Python pur. Le runner arbitraire sur VM/hôte dédié, le broker de
capacités et les qualifications de charge restent ouverts ; voir la décision 0174 amendée.

### Avancement du 15 octobre 2026

- Réalisé dans `galaris.bpmn/v2` : listes input/output propres à chaque activité et au
  processus, codec typé récursif, nullabilité, omissions et défauts contrôlés à la sauvegarde.
- Réalisé : entrées locales figées, sorties validées, Dataset global protégé, intégrations
  ciblées avec reçus Memory, conservation des URI sans copie automatique, compatibilité v1.
- Réalisé : formulaires de déclaration, lancement et travail humain ; MCP, REST et enfants
  adaptés aux contrats ; jobs externes hors progression du graphe ; convergence ordinaire
  après tous les prédécesseurs. Les autorisations MCP existantes restent applicables.
- Raccordé mais non activé en production : phases Python prétraitement/activité/post-traitement
  via `IsolatedCodeRunner`, avec intentions et confirmations d'arrêt. Les tests utilisent un
  runner synthétique. Aucun adapter réel, runtime Python qualifié, microVM, protocole réseau
  authentifié ni intermédiaire de capacités n'est encore livré ; sans adapter, refus explicite.
- Restent : exécution dans une VM/hôte dédié, qualification système et du nettoyage,
  worker Process en processus distinct, plafonds techniques mesurés, permissions temporaires
  et broker MCP/REST pour le code, campagnes multi-harnais/n8n et mesures sous charge.

Les suites de codec, DB et navigateur vérifient leurs garanties propres ; elles ne constituent
ni qualification de l'infrastructure du runner ni autorisation de déploiement.

## 1. Activités et réception restante

| Activité | Travail restant |
|---|---|
| IA | Contrat local et validation réalisés ; qualifier les réponses et ressources avec les harnais réels. |
| Humaine | Formulaires, identité et contrôles réalisés ; étendre les parcours aux volumes et contextes métier cibles. |
| Code | Port et reprise raccordés ; livrer et qualifier le runtime sur runner fortement isolé. |
| Outil MCP | Jobs durables, agent exécutant, autorisations et sortie commune réalisés ; qualifier les serveurs externes réels. |
| API REST | Activité et jobs réalisés via Tools ; qualifier les services métier cibles et les annulations/incertitudes réseau. |
| Sous-processus | Entrées locales et résultats réalisés pour enfants typés/historiques ; compléter les recettes hybrides et sous charge. |

Les transformations adaptent les variables ; les activités accomplissent le travail.
Les gros traitements spécialisés sont confiés à des logiciels extérieurs via MCP ou REST.
La première version ne propose aucun choix de politique de synchronisation.

## 2. Données et transformations facultatives

Le Dataset du run reste l'état métier global : un objet `data` et sa collection de fichiers
`files`. Les états du moteur et reçus restent dans Process. Une activité possède ses
propres `input`, `input_files`, `output` et `output_files`.

```text
data + files
  → prétraitement → normalisation et validation des entrées déclarées
  → input + input_files → activité → output + output_files
  → normalisation et validation des sorties déclarées
  → post-traitement → intégration durable dans data + files
```

| Configuration | Entrée | Sortie |
|---|---|---|
| Nouvelle activité, scripts proposés par défaut | Copier toutes les données et références de fichiers dans `input` et `input_files`. | Fusionner `output` dans `data` et ajouter `output_files` aux fichiers globaux. |
| Script enregistré vide | `input = {}` et `input_files = []`. | Aucun changement de l'état global. |
| Script personnalisé | Initialiser les entrées vides, puis exécuter uniquement ce script. | Appliquer uniquement les modifications produites par ce script ; aucune fusion implicite supplémentaire. |

La copie d'entrée ne partage aucune référence mutable avec les données globales.
La fusion par défaut porte sur le premier niveau : les clés retournées remplacent les clés
correspondantes, les autres sont conservées ; pas de fusion récursive implicite. L'ajout
des fichiers conserve un ordre stable et évite les doublons par URI canonique.
Une suppression ou un remplacement explicite demande un traitement personnalisé.

Python est le langage cible proposé pour les transformations et les activités Code,
à qualifier avec le runner ; le runtime et la version ne sont pas encore retenus.
Le choix antérieur de JavaScript n'est pas une contrainte de ce plan. Exemple avec
les enveloppes JSON décrites ci-dessous, manipulées comme des dictionnaires Python :

```python
# Prétraitement
input["variable_1"] = data["ma_variable_globale_1"]
# Le type est conservé lors d'une copie ; une nouvelle valeur porte son type.
input["seuil"] = {"type": "float", "value": 100.0}
```

```python
# Post-traitement
data["variable_globale_2"] = output["mon_resultat"]
```

Conditions, boucles et opérations usuelles sur objets, listes, chaînes et nombres sont
permises. Ces petits traitements accèdent uniquement aux données fournies, sans réseau,
outils, fichiers système, horloge ou aléa implicites. Tout code éditable, transformations
comprises, s'exécute dans la frontière forte décrite plus bas, jamais dans le backend.

### Valeurs fortement typées et transport JSON

Chaque valeur métier porte une enveloppe JSON `{ "type": "…", "value": … }`.
Le type de la valeur est obligatoire indépendamment de sa déclaration d'entrée/sortie. Ce contrat s'applique
aux données globales, aux entrées/sorties locales, aux transformations, aux snapshots et
aux échanges API/MCP du nouveau profil. `data`, `input` et `output` sont des tables de
variables nommées dont chaque valeur suit ce contrat récursif.

| Type initial | Valeur JSON non nulle | Sémantique |
|---|---|---|
| `int` | Nombre entier | Entier signé exact ; un booléen n'est pas un entier. |
| `float` | Nombre | Flottant fini ; l'étiquette conserve son type même si le nombre vaut `1`. |
| `string` | Chaîne | Texte Unicode. |
| `bool` | Booléen | `true` ou `false`. |
| `Agent` | Identifiant entier | Référence à un agent Galaris, résolue par sa façade publique. |
| `File` | Chaîne URI canonique | Référence de fichier gérée par `app.file_share`. |
| `User` | Identifiant entier | Référence à un utilisateur Galaris, résolue par sa façade publique. |
| `Document` | Chaîne `document://<uuid>` | Référence à un Document Galaris, y compris un Dataset. |
| `array` | Tableau de valeurs typées | Liste ordonnée, éventuellement vide, avec imbrication récursive. |
| `object` | Objet à clés chaînes et valeurs typées | Table de hachage, éventuellement vide, avec imbrication récursive. |

Tous les types acceptent `"value": null`, y compris `array` et `object` : le type déclaré
est conservé. Une clé absente, une valeur nulle, `false`, zéro, `""`, `[]` et `{}` restent
distincts. La clé `value` reste obligatoire même lorsqu'elle vaut `null`. Aucun type
`null` séparé ni déduction à partir du contenu n'est nécessaire.

Les tableaux peuvent contenir plusieurs types : chaque élément conserve sa propre enveloppe.
Les contraintes d'homogénéité ou de structure interne restent une extension ultérieure des
déclarations simples ; elles ne supprimeront pas le typage individuel. Les clés d'une table de hachage
restent des chaînes JSON, sans conversion silencieuse d'autres types de clés. Les clés
dupliquées sont refusées à la lecture du JSON. Aucun ordre métier ne dépend de l'ordre des
clés d'un objet.

Exemple de données transportées ; identifiants et ressources purement synthétiques :

```json
{
  "data": {
    "quantite": { "type": "int", "value": 3 },
    "montant": { "type": "float", "value": 42.5 },
    "libelle": { "type": "string", "value": "Dossier exemple" },
    "valide": { "type": "bool", "value": false },
    "executant": { "type": "Agent", "value": 101 },
    "responsable": { "type": "User", "value": null },
    "piece": { "type": "File", "value": "nextcloud://Shared/exemple.pdf" },
    "rapport": { "type": "Document", "value": "document://00000000-0000-4000-8000-000000000001" },
    "lignes": {
      "type": "array",
      "value": [
        {
          "type": "object",
          "value": {
            "reference": { "type": "string", "value": "EXEMPLE-1" },
            "quantite": { "type": "int", "value": 3 }
          }
        }
      ]
    },
    "options": { "type": "object", "value": {} },
    "autres_pieces": { "type": "array", "value": null }
  }
}
```

`File` conserve l'URI du provider, par exemple `nextcloud://Shared/exemple.pdf` ; son contenu
n'est pas embarqué en base64. La résolution, les métadonnées, les droits et une éventuelle
matérialisation temporaire passent par `app.file_share`, sans créer un résolveur Process.
La transmission d'une entrée ou sortie ne déclenche aucun téléchargement ni copie de fichier :
seules les URI circulent ; une activité demande explicitement les octets si son travail l'exige.
Les collections ne sont pas des valeurs `File`. `Document` référence le document lui-même ;
une pièce jointe documentaire peut être un `File`. Le type métier `Document` reste distinct
de `File` et de `string`, même si ces valeurs utilisent toutes une chaîne dans le JSON.
Aucune conversion entre types métier n'est implicite.

Les collections `files`, `input_files` et `output_files` conservent leur rôle de manifeste
de fichiers et utilisent le même type `File`, avec descriptions facultatives à côté des
valeurs typées. Une référence `File` peut aussi apparaître dans les données imbriquées sans
imposer de slot ni d'ajout automatique au manifeste. Le typage n'accorde aucun droit :
une référence `Agent` ou `User` ne change ni l'exécutant ni l'affectation humaine ; une URI
ne donne pas accès à son contenu. Résoudre et autoriser les références sous l'identité
effective au moment de leur utilisation, y compris après reprise.

Définir un codec commun et versionné pour toutes ces frontières, avec une union discriminée
par `type` et des enveloppes fermées. Refuser type inconnu, valeur incompatible, enveloppe
incomplète, nombre non fini, dépassement des bornes et excès de taille/profondeur. Pour `int`,
retenir en v1 la plage exacte commune JSON/Python/JavaScript, de `-(2^53 - 1)` à `2^53 - 1` ;
refuser les dépassements avant toute perte de précision. Les enveloppes distinguent
notamment `int`, `float`, `Agent` et `User` quand leurs valeurs numériques coïncident.
Les adaptateurs MCP/REST traduisent explicitement vers le contrat externe puis reconstruisent
les valeurs typées à partir du mapping déclaré ; aucune inférence d'un type métier sur une
simple chaîne ou un nombre. Cette traduction ne modifie pas les contrats des Tools existants.

### Déclarations input/output communes à toutes les tâches

Dans le nouveau profil, **toutes les tâches du processus** possèdent deux listes explicites
de variables d'entrée et de sortie : IA, humaines, Code, MCP, REST et sous-processus.
Les frontières d'entrée/sortie du processus complet utilisent le même contrat. Le mécanisme
ne dépend ni d'un langage de programmation ni du type d'exécutant.

Chaque tâche configure ses propres listes, indépendamment des autres tâches, avec
**nom + type + nullable/notnull + valeur par défaut facultative**. Le format de définition
JSON utilise `name`, `type`, `nullable` (booléen) et, si un défaut est défini, `default`
(valeur typée). L'interface présente la nullabilité comme un choix Nullable / Not null et
permet de distinguer l'absence de défaut d'un défaut explicitement nul. Tous les types du
tableau précédent, y compris `array` et `object`, peuvent être déclarés nullables ou non nuls.

```json
{
  "inputs": [
    { "name": "source", "type": "File", "nullable": false },
    { "name": "responsable", "type": "User", "nullable": true },
    { "name": "tentatives", "type": "int", "nullable": false,
      "default": { "type": "int", "value": 1 } }
  ],
  "outputs": [
    { "name": "rapport", "type": "Document", "nullable": false },
    { "name": "commentaire", "type": "string", "nullable": true,
      "default": { "type": "string", "value": "" } }
  ]
}
```

Ces listes décrivent le contrat ; les valeurs transmises restent les enveloppes
`{ "type": "…", "value": … }`. Les noms sont non vides et uniques dans chaque liste.
Une liste vide signifie aucune variable dans cette direction. La possibilité de représenter
`null` appartient à tous les types ; `nullable: false` le refuse pour la variable concernée.
Une variable nullable peut être omise sans erreur. Les règles de normalisation sont les
mêmes en entrée et en sortie, pour toutes les tâches et pour le processus complet :

| Valeur transmise | Défaut déclaré | Résultat |
|---|---|---|
| Valeur présente non nulle | Avec ou sans | Conserver la valeur et contrôler son type ; ne pas appliquer le défaut. |
| `null` explicite | Avec ou sans | Conserver `null` si nullable, sinon erreur ; le défaut ne remplace pas un `null` explicite. |
| Variable absente | Oui | Copier la valeur par défaut, puis contrôler type et nullabilité. |
| Variable absente | Non, nullable | Produire `{ "type": "type déclaré", "value": null }`, sans erreur. |
| Variable absente | Non, notnull | Erreur nommant la tâche et la variable manquante. |

Une valeur présente mais mal typée reste une erreur ; le défaut ne la corrige pas.
Tester la présence de la clé, jamais la vérité de la valeur : `false`, zéro, chaîne vide,
tableau vide et objet vide sont conservés. L'absence de `default` se distingue d'un défaut
typé contenant `null`, autorisé seulement si la variable est nullable. Aucune option
« obligatoire » supplémentaire : notnull sans défaut exige une valeur transmise.

Contrôler les déclarations dès leur sauvegarde, puis à l'admission du snapshot : noms
uniques, types connus, nullabilité explicite et défaut conforme au type et à la nullabilité.
Ces contrôles forment un premier niveau d'erreur, complété par la validation des valeurs
réelles à l'exécution. Un défaut est une valeur constante figée avec la définition du run,
sans expression exécutable. Copier profondément les défauts à chaque normalisation pour
ne pas partager d'objets mutables entre tâches, occurrences, tentatives ou runs. Les défauts
`File`/`Document` restent des URI, avec les mêmes droits vérifiés à l'utilisation.

La normalisation intervient après le prétraitement : elle sélectionne les entrées déclarées
par leur nom, dans l'ordre de déclaration, puis contrôle présence, type et nullabilité avant
de lancer l'activité. Ainsi, le prétraitement proposé par défaut peut encore copier le pool,
mais seules les variables déclarées sont remises à la tâche. Un script vide avec des entrées
déclarées utilise leurs défauts ou leur nullabilité ; il échoue seulement si une valeur
notnull sans défaut manque. Renommer ou calculer une valeur reste le rôle d'une
transformation explicite ; aucune conversion silencieuse de chaîne en nombre ou de référence
métier en un autre type.

À la fin, le moteur contrôle les mêmes garanties sur les sorties avant post-traitement.
Une sortie manquante notnull sans défaut, supplémentaire, mal typée ou nulle malgré `notnull`
produit une erreur localisée à la tâche et à la variable et n'intègre aucun résultat global.
Normaliser les sorties d'une activité réussie ; aucun défaut ne transforme une activité en
erreur ou annulée en succès. Les agents reçoivent la
liste de sorties attendues pour leur réponse structurée ; les humains disposent des champs
correspondants ; Code, MCP, REST et sous-processus utilisent la même validation serveur.
La nullabilité d'un conteneur concerne ce conteneur ; ses valeurs imbriquées conservent leur
propre type et la possibilité de valoir `null`.

L'éditeur fournit les deux listes et leurs défauts sur chaque tâche et les conserve à la sauvegarde/réouverture,
dans XML/graphe/API/MCP et dans les snapshots. Il signale les incompatibilités de noms, types
et nullabilité connues entre mappings ; le runtime vérifie toujours les valeurs réelles.
Un éventuel JSON Schema destiné aux adaptateurs est dérivé de ces listes et du codec commun,
sans seconde configuration à maintenir ni schéma complexe à écrire par l'utilisateur en v1.

Valider aussi les enveloppes produites par le post-traitement avant intégration et les entrées
d'un enfant avant admission. Les anciens profils gardent leur contrat sans inventer de listes
vides pour des snapshots qui n'en avaient pas. La conversion d'une définition existante vers
le nouveau profil rend ses listes explicites, sans modifier les runs déjà admis ni deviner
des références métier.

### Intégration durable

Le runtime actuel autorise les tâches à écrire directement dans le Dataset commun.
Faire évoluer ce contrat : chaque activité travaille sur ses données locales et le moteur
intègre ses sorties. Fournir les espaces locaux adaptés aux agents et humains ; aucune
écriture directe dans le pool global ne doit contourner les traitements ou la validation.

1. Figer les entrées préparées, les fichiers et le code de chaque tentative. Une reprise
   ne recommence pas la préparation sur des données différentes.
2. Persister résultat, commande d'intégration et reçu idempotent via les façades des
   propriétaires ; ne pas supposer une transaction commune Process/Memory/fichiers.
3. Regrouper les changements de données en une écriture courte sous révision ; les copies
   intentionnelles de fichiers possèdent leurs reçus de transfert et contrôles d'accès.
4. Une erreur de script ou schéma ne publie aucun état global partiellement intégré.
   Après crash, réconcilier les matérialisations et reçus avant de poursuivre le graphe.
5. Fusionner les changements ciblés sans réécrire une ancienne copie complète du Dataset.
   Préserver les écritures disjointes et signaler les modifications concurrentes incompatibles
   d'une même variable ; l'ordre d'arrivée ne doit pas choisir silencieusement le résultat.
6. Reprendre l'intégration d'un résultat acquis sans réexécuter l'activité. Une sortie tardive
   ou dupliquée ne modifie pas un terminal et ne déclenche pas deux fois le successeur.

Préserver les types et données métier exactes (`null`, `false`, zéro, Unicode, objets/listes vides).
Les diagnostics bornés et assainis ne remplacent pas les résultats autorisés.

## 3. Agents exécutants, programmes et connexions

Toute activité automatisée possède un agent exécutant, explicite ou hérité du processus
selon la résolution existante. Appliquer cette identité uniformément aux Tasks, programmes,
MCP et REST, au lieu d'utiliser systématiquement le lanceur du run. L'humain affecté reste
une identité distincte pour l'activité humaine.

Les agents peuvent créer, tester et modifier les programmes via l'édition publique des
processus. L'auteur du code et son exécutant peuvent différer : le programme utilise les
capacités de l'exécutant, jamais les connexions, secrets ou droits de son auteur.

Pour commencer, enregistrer le code dans la définition de l'activité et dans le snapshot
du run. Les nouveaux lancements utilisent la dernière sauvegarde ; une édition ne change
pas un run actif. Un sous-processus fige son propre contenu à son admission. Ne pas ajouter
de sélecteur de version métier.
Les programmes documentaires réutilisables restent une extension distincte décrite dans
[leur plan](programmes-documentaires-json.md), pas un prérequis de l'activité Code. Son ancien
choix JavaScript et son modèle d'enregistrement devront être réalignés avant mutualisation.
Une fonction technique autonome ne devient pas un processus métier.

### Intermédiaire de confiance pour MCP et REST

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

Réutiliser `app.tools.execute_rest_request` pour l'activité REST et les programmes.
Le confinement à l'adresse configurée protège la destination des identifiants ; il est
distinct des permissions métier du tiers. Les réponses rendues au programme ne doivent
pas restituer les secrets de transport.

## 4. Arrière-plan et convergence unique

```text
API/MCP → admission durable en base → worker Process de confiance
                                      ↕ protocole borné et authentifié
                               runner sur VM/hôte dédié
                                      └─ sandbox jetable par exécution
```

Réutiliser les jobs, occurrences et mécanismes de reprise existants. Prévoir un worker
Process distinct pour la progression ; l'API enregistre et expose l'état, sans exécution
utilisateur ni traitement long pendant la lecture d'un run. Le worker de confiance peut
réutiliser l'image backend ; le runner possède une image minimale sans les accès de Galaris.

- Une activité attend la réussite de tous ses prédécesseurs de la même invocation/itération,
  avec leurs résultats intégrés, puis démarre une seule fois.
- A, B et C alimentant D peuvent avancer en parallèle ; D attend les trois. Étendre la
  normalisation/validation pour que plusieurs liens entrants ordinaires respectent cette
  règle, sans imposer un réglage de politique ou une gateway manuelle à l'utilisateur.
- Un échec ou une annulation empêche le successeur de démarrer. Préserver l'arrêt à la
  première erreur et la confirmation d'arrêt des effets actifs ; pas de CATCH/retry automatique.
- Les attentes humaines, autorisations MCP et services externes libèrent la progression.
  Une activité longue ne bloque pas les branches indépendantes ou les autres runs.
- Réutiliser leases, identités et reçus ; un worker périmé ou une notification tardive
  ne peut publier un résultat ou déclencher une seconde fois une activité.

Aucun choix « première réponse », quorum, poursuite malgré erreur ou politique avancée
pour cette version. Les IF/FOR/WHILE existants gardent leurs contrats ; les `if` et boucles
d'un script ne changent pas la convergence. Aucun budget cumulé Process à introduire :
les limites techniques de sandbox et capacités des harnais protègent les ressources sans
constituer des plafonds métier de run.

## 5. Isolation forte, prérequis de toute exécution de code

Tout code éditable est non fiable, même produit par un agent Galaris. Ni le backend,
ni son worker, ni un sous-processus partageant leurs accès ne constituent la frontière
retenue. Une restriction de langage est une protection supplémentaire, pas l'unique isolation.

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

### Qualification avant choix du runtime

Python est la cible proposée ; Monty est un candidat à expérimenter à l'intérieur de cette
architecture, sans le considérer comme installé, qualifié ou suffisant seul. Vérifier la
version, les opérations de données, fonctions externes, annulation et limites ; verrouiller
et documenter les dépendances après qualification.

Inventorier les prérequis d'hébergement, l'isolation système, les mises à jour et le canal
avec Galaris. L'exécuteur IDE existant a un autre contrat : aucun réemploi tel quel sans
qualification. Si la frontière exigée est indisponible, refuser l'exécution avec diagnostic ;
aucun repli automatique vers le backend ou un runtime moins isolé.

## 6. Lots restants et réception

Chaque lot termine par un parcours complet avant généralisation. Définir les nouveaux
modules, modèles, états et réglages selon les besoins réels, sans deuxième moteur métier
ni wrapper Process autour d'une fonction technique.

| Lot | Travail restant | Réception |
|---|---|---|
| A — Contrats et compatibilité | Version du profil, codec JSON des valeurs typées et nullables, tableaux/tables de hachage récursifs, références métier, listes input/output nom/type/nullable/défaut facultatif sur chaque tâche et le processus, scripts ; identité des exécutants ; conservation des runs existants. | Aller-retour exact des déclarations, défauts, types et valeurs par Dataset/API/MCP/XML/graphe ; omission nullable acceptée et défauts appliqués seulement aux absences ; anciens snapshots interprétés selon leur contrat ; scripts conservés ; pas de réactivation implicite des anciens champs supprimés à la lecture. |
| B — Runner isolé | Protocole, déploiement séparé, frontières réseau/système, expérimentation Python/runtime, limites et supervision. | Accès interdits refusés, deux agents isolés, boucle/saturation arrêtées, capacité libérée ; runner hostile sans accès au backend. |
| C — Parcours des données | Worker de progression, prétraitement isolé, entrées locales, sorties structurées IA/humain, post-traitement et intégration idempotente. | Start → activité → End avec défauts/vides/personnalisés ; validation sans état partiel ; crash après résultat sans réexécution. |
| D — Activités et connexions | Raccorder Code, MCP, REST et sous-processus aux mêmes contrats et à l'agent exécutant ; fonctions externes médiées par Tools. | Auteur différent de l'exécutant, connexions propres, révocation, attente MCP, refus REST du tiers conservé, enfant avec noms de variables différents. |
| E — Convergence et reprise | Attente de tous les prédécesseurs, intégrations concurrentes, générations de worker, annulation et reprise du runner. | Trois branches dans tous les ordres puis un seul successeur ; écritures disjointes préservées, conflit explicite, aucune suite après erreur ou double effet après crash. |
| F — Éditeur et consommateurs | Mini éditeurs, listes input/output nom/type/nullable/défaut facultatif pour chaque tâche, saisie typée pour scalaires/tableaux/objets, sélection de références Agent/File/User/Document, essais sur exemples, agent/MCP/REST, inspection et diagnostics, documentation et campagnes Lab. | Sauvegarde/réouverture conservant déclarations, absence de défaut/défaut nul et autres valeurs, droits, correction d'erreur, clavier/mobile, navigation et réponse tardive ; aucune exécution de code par le navigateur d'édition. |

Le lot B conditionne la livraison de C/D dès qu'ils exécutent du code éditable. Aucun
shell arbitraire, installation libre de dépendances ou accès direct aux secrets en v1.

## 7. Vérifications et extensions différées

Réutiliser les scénarios existants. Toutes les données et pièces jointes conservées dans
les tests du dépôt restent synthétiques.

| Garantie | Vérification à ajouter ou adapter |
|---|---|
| Transformations/types | Défauts/vides/personnalisés, conditions/boucles, aller-retour de chaque type avec valeur et null, absent/null/faux/zéro/vides, tableaux hétérogènes et objets imbriqués, bool refusé comme int, bornes numériques, types inconnus/enveloppes invalides/clés dupliquées refusés, erreur de script, contraintes facultatives et validation stricte, taille/profondeur et sérialisation. |
| Contrats de toutes les tâches | Même scénario paramétré IA/humain/Code/MCP/REST/enfant : listes propres à chaque tâche, nom unique, sélection des entrées déclarées, liste vide, omission nullable normalisée à null, omission notnull sans défaut refusée, défaut appliqué seulement à une absence, null explicite préservé ou refusé selon nullable, défaut nul/invalide contrôlé à la sauvegarde, false/zéro/vides préservés, copies mutables indépendantes et défauts figés après reprise, type divergent/sortie supplémentaire refusés, aucune activité lancée sur entrée invalide ni intégration sur sortie invalide ; défauts sans effet sur une activité en erreur ou annulée. |
| Références métier | Agent/User distincts d'int, Document/File distincts de string, URI canonique conservée, références nulles sans résolution, ressource absente ou accès révoqué refusés à l'utilisation, aucune usurpation d'exécutant ni attribution de droits par une valeur. |
| Données et fichiers | Aucun accès implicite au pool global, entrées sélectionnées seulement, ACL source/destination, transfert repris sans doublon, agents/runs distincts. |
| Intégration/convergence | Crash aux frontières résultat/écriture/reçu, doublons/hors ordre, écritures disjointes, conflit de variable, une seule admission après trois prédécesseurs. |
| Isolation réelle | Fichiers/environnement/réseau/DB refusés, identité/reçu falsifiés, allocations/sorties excessives, boucle infinie, destruction et environnement suivant vierge. |
| Capacités externes | Usurpation d'agent impossible, référence expirée/révoquée ou rejouée refusée, droits MCP, token REST contrôlé par le tiers, secrets absents des réponses et traces. |
| Reprise/compatibilité | Redémarrage moteur/runner pendant calcul ou attente, état/code figés, contrats historiques, n8n, humains, debugger, métriques et harnais à un slot préservés. |
| Interface/Lab | Parcours assemblé avec vraie sandbox et service tiers synthétique, erreurs/réouverture/conflit, droits, clavier/mobile ; campagnes adaptées aux nouvelles signatures. |

Mesurer démarrage de sandbox, latences, CPU/mémoire, débit, croissance des Datasets/journaux
et reprise sous concurrence. Les recettes multi-harnais et interne → externe → interne,
les grandes profondeurs/volumes et mesures comparatives restent à qualifier. Conserver
les preuves dans le Lab ou les artefacts ; la présence d'un contrat n'atteste pas sa
qualification dans tous les environnements.

Les mocks d'applications et campagnes hybrides restent une seconde phase du
[plan Lab](lab-evaluation-mecanismes-ia.md). Garder aussi comme extensions distinctes :
annotations/métriques extensibles et comparaison de runs lorsqu'elles manquent encore,
contrôle métier supplémentaire du résultat, FOR parallèle, déclencheurs, compensation et
compatibilité transitive avancée. Aucun juge LLM systématique, CATCH/retry, convergence
avancée ou budget Process supplémentaire dans ce premier lot. Suivi automatique de jobs
REST, callbacks spécifiques et programmes documentaires réutilisables seront contractualisés
séparément, sans rejeu d'un appel à l'issue inconnue.

À l'implémentation, actualiser la décision d'architecture, les machines d'état et flux
concernés, le skill runtime, les parcours FR/EN et le catalogue des tests. Modèles/actions
passent par DbAdmin, interfaces par les contrats publics, réglages permanents par
`.env.example` et settings. Préserver droits documentaires, métriques et consommateurs
existants ; aucun accroissement de baseline sans revue.

Qualifier d'abord le runner réellement confiné et un parcours vertical, puis lancer tests
ciblés, `make typecheck`, `make architecture-check`, parcours assemblés et `make docs-prepare`.
Avant publication sans CI, lancer `make validate` sur les sources finales et lire le résumé.
Terminer par revue du diff et `git diff --check`. Ce plan ou une vérification partielle ne
constitue ni une qualification de sécurité globale ni une autorisation de déploiement.
