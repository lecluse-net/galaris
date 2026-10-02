# Plan — Portée et provenance de l’exécution agentique

> **Statut :** `partial` — contrat générique de portée et projection de ses décisions à réaliser.
> **Revue documentaire :** 1er octobre 2026.
>
> **But :** empêcher qu’un planner ou un exécuteur transforme une information de
> contexte en cible ou en instruction opérationnelle non demandée, sans réduire l’autonomie.

Les contrats d’activité, de pause et de provenance consultable sont maintenus dans
l’[ADR 0087](../decisions/0087-task-activity-snapshots.md) et le
[flux d’exécution](../../docs/fr/architecture/flows/agent-execution.md). Les lots ci-dessous
les étendent avec une portée générique ; ils ne réimplémentent pas leurs projections.

## 1. Périmètre restant

La suppression du briefing relève de la [décision 0143](../decisions/0143-retire-execution-briefing.md).
Le Working Set, les reçus de livraison, les checkpoints d'effets et les sessions indépendantes
ne sont plus des lots à créer. Le contrat générique reliant exigences, cibles, effets et
provenance reste à concevoir et à appliquer au planner, à l'exécuteur et aux domaines concernés.

## 2. Objectifs et principes

### 2.1 Objectifs

1. Conserver une exécution autonome pour toute action directement justifiée par la demande.
2. Empêcher l’invention silencieuse d’une nouvelle cible, destination, personne, ressource,
   contrainte ou classe d’effet.
3. Permettre au périmètre d’évoluer pendant le run à partir de résultats d’outils vérifiés.
4. Appliquer la même mécanique aux Tools natifs, MCP externes, Processes et futurs runtimes.
5. Garder l’autorisation RBAC, la pertinence agentique et la portée de la Task comme trois
   contrôles distincts.
6. Reprendre après panne sans répéter un effet dont le reçu durable existe déjà.

### 2.2 Principes non négociables

- L’objectif utilisateur ne peut être remplacé ni affaibli par le planner, le profil,
  la mémoire ou l’historique.
- Une ressource autorisée par RBAC n’est pas automatiquement pertinente pour la Task courante.
- Une ressource pertinente n’autorise pas automatiquement tous les effets qu’elle supporte.
- Le profil de l’agent gouverne son rôle, son style et ses préférences ; il ne confère pas à lui
  seul une cible ou une instruction opérationnelle.
- Un résultat structuré d’outil ou un reçu durable a davantage d’autorité qu’une supposition du
  modèle.
- La découverte et la lecture bornées restent largement autonomes. Une clarification n’est
  demandée que lorsque des choix plausibles produiraient des effets matériellement différents.
- Les contrats restent ouverts aux capacités futures : aucun comportement central ne dépend du
  nom d’un outil, d’une commande, d’un provider ou d’une application particulière.

## 3. Vocabulaire générique

| Concept | Définition |
|---|---|
| Exigence | Élément vérifiable de l’objectif, avec identifiant stable et provenance. |
| Cible | Ressource, acteur, collection, système ou périmètre affecté par une opération. |
| Effet | Conséquence déclarée d’une fonction, indépendamment de son nom ou de sa technologie. |
| Grant | Association durable entre une cible, des capacités permises et leur provenance. |
| Claim | Proposition du planner ou de l’exécuteur reliant une action à une exigence et à une cible. |
| Reçu | Preuve structurée qu’une opération a réellement produit ou transporté un résultat. |
| Contexte | Information utile mais non suffisante, seule, pour autoriser une nouvelle cible ou un nouvel effet. |

Les capacités spécifiques restent des codes extensibles et namespacés appartenant aux domaines.
Le noyau ne connaît que des dimensions transversales utiles à la décision, par exemple :

- présence ou absence de mutation ;
- réversibilité annoncée ;
- visibilité interne ou externe ;
- cible explicite, dérivée ou absente ;
- effet immédiat ou Process durable ;
- garantie d’idempotence et nature du reçu.

Ces dimensions ne remplacent ni le schéma de l’outil ni ses contrôles métier. Elles permettent au
noyau de raisonner sur un outil inconnu sans coder une taxonomie fermée de produits.

## 4. Hiérarchie des sources

La provenance doit être conservée sous forme structurée. L’ordre de priorité cible est :

1. message ou choix explicite de l’utilisateur courant ;
2. contrat structuré de la Task issu de cette admission ;
3. grants et URI exactes du Working Set ;
4. résultats et reçus validés des outils du run courant ;
5. politique explicite du Process ou du canal qui possède l’effet ;
6. contexte conversationnel pertinent et borné ;
7. plan dérivé ;
8. mémoire, profil et fiche de poste.

Une source basse peut suggérer une recherche, un outil ou une formulation. Elle ne peut pas
contredire une source haute ni transformer seule une information en grant.

## 5. Contrat de portée de la Task

### 5.1 Forme cible

Un contrat versionné, sérialisable et indépendant des modèles ORM accompagne `AgentTask` et
`AgentRunRequest`. Une première version peut être persistée dans `Task.data` afin d’éviter un
changement de schéma tant qu’aucune requête SQL dédiée n’est nécessaire.

```text
ExecutionScopeV1
  requirements[]
    id
    statement
    provenance
  grants[]
    target_reference
    capability_codes[]
    provenance
    constraints
  delivery
    owner
    target_reference?
  assumptions[]
  version
```

Les références de fichiers restent exclusivement des URI `app.file_share`. Les autres domaines
exposent une référence publique stable ou un identifiant corrélable déjà défini par leur contrat ;
le noyau ne reconstruit pas une identité à partir d’un libellé humain.

### 5.2 Admission conversationnelle

Lorsqu’un round crée ou amende une Task, il doit transmettre :

- l’objectif autonome ;
- les exigences importantes conservées sans affaiblissement ;
- les cibles explicitement nommées ou jointes ;
- la politique de livraison du round ;
- les références de continuité réellement nécessaires.

L’historique complet ne doit pas être recopié dans la Task. En revanche, retirer cet historique ne
doit pas retirer les faits qui déterminent le périmètre. Le contrôleur promeut donc uniquement les
références et grants pertinents dans le contrat ou le Working Set.

### 5.3 Valeurs par défaut non bloquantes

- Une Task peut explorer en lecture les ressources auxquelles elle a déjà accès, dans les limites
  et budgets existants.
- Une production sans destination imposée peut être créée dans l’espace propre au run annoncé par
  le runtime, puis inscrite au Working Set.
- Le contrôleur du canal peut livrer le résultat dans le contexte courant lorsque son contrat le
  prévoit ; cela n’autorise pas un second transport explicite.
- Une cible découverte par un outil devient une référence candidate vérifiée. Son usage ultérieur
  dépend encore de l’exigence poursuivie, des capacités de l’outil et du niveau d’effet.

Il ne faut donc pas demander à l’utilisateur de choisir un stockage, un nom technique ou un outil
lorsqu’un résultat correct peut être produit et livré dans l’espace normal de la Task.

## 6. Descripteurs d’effet des Tools et Processes

### 6.1 Contrat extensible

`app.tools` reste propriétaire du catalogue et expose, pour chaque fonction effective, un
descripteur optionnel versionné :

```text
EffectDescriptorV1
  capability_code
  mutation
  reversibility
  visibility
  target_arguments[]
  idempotency
  receipt_kind?
```

Le descripteur accompagne la définition filtrée ; il ne confère aucun droit. Les Tools intégrés
le déclarent dans leur domaine. Les serveurs MCP externes peuvent le fournir par métadonnée
standardisée ou par configuration administrée. Les Processes décrivent de la même façon leur
lancement, leurs entrées et leur résultat durable.

### 6.2 Compatibilité avec les outils non enrichis

L’absence de métadonnée ne masque pas l’outil et ne le rend pas inutilisable. Elle produit un effet
`unknown` inspectable :

- un appel sans nouvelle cible explicite continue de suivre le RBAC et le contrat actuel ;
- une opération de découverte ou de lecture peut rester autonome ;
- lorsqu’une cible externe nouvelle ou un effet irréversible est décelable dans les arguments,
  le préflight exige une justification sourcée ou une clarification ;
- le résultat et les effets observables alimentent la télémétrie afin d’enrichir ultérieurement le
  descripteur, sans apprentissage automatique de droits.

Cette compatibilité évite un basculement fermé où tous les connecteurs historiques devraient être
annotés avant de fonctionner.

## 7. Planner borné par provenance

### 7.1 Entrée

Le planner reçoit :

- l’objectif et ses exigences identifiées ;
- `ExecutionScopeV1` ;
- le Working Set avec URI exactes ;
- la politique unique de livraison ;
- le catalogue effectif et ses descripteurs d’effet ;
- un profil de rôle compact, distinct des informations opérationnelles non pertinentes.

La fiche de poste complète ne doit plus être utilisée comme source implicite de cibles. Si une
préférence opérationnelle doit réellement s’appliquer à toutes les Tasks d’un agent, elle devient
une politique structurée distincte, administrable et inspectable.

### 7.2 Sortie structurée

Chaque étape ou recommandation porte :

- les identifiants d’exigences servis ;
- la cible exacte ou la règle de découverte utilisée ;
- la provenance de cette cible ;
- l’effet attendu ;
- les outils ou Processes utiles ;
- les contrôles et preuves de complétion ;
- les hypothèses et informations manquantes.

Sélectionner un outil signifie seulement qu’il est utile et disponible. Cela ne crée aucun grant.

### 7.3 Validation

Le validateur applique des règles déterministes avant persistance :

- toutes les exigences restent présentes ou explicitement hors de portée ;
- aucune nouvelle cible concrète n’apparaît sans provenance ;
- aucun effet externe n’est ajouté uniquement depuis le profil, la mémoire ou une supposition ;
- la livraison respecte son propriétaire unique ;
- les outils choisis existent toujours dans le catalogue effectif ;
- chaque contrôle de complétion correspond à une exigence ou à une contrainte d’effet.

Une erreur de structure peut déclencher un retry de structured output. Une violation sémantique ne
doit pas être réduite à une correction de format : le modèle reçoit le conflit précis. Après le
budget de correction, le plan est rejeté. La Task attend une clarification si le travail
ne peut pas continuer dans la portée validée.

### 7.4 Injection dans l’exécuteur

Le contexte de plan suit un contrat de priorité explicite :

```text
objectif utilisateur > scope validé > Working Set et reçus > plan validé > profil
```

Le plan validé est contraignant à l’intérieur de ce périmètre. L’exécuteur doit refuser et
signaler toute contradiction résiduelle au lieu de choisir arbitrairement l’un des textes.

## 8. Préflight générique avant un effet

Le wrapper commun d’appel évalue l’outil effectif, ses arguments, le scope courant et
l’exigence poursuivie. Il produit une décision interne qui n’alourdit pas le schéma MCP présenté au
modèle :

| Décision | Usage |
|---|---|
| `allow` | Effet directement couvert par un grant ou production appartenant à la Task. |
| `allow_and_record` | Découverte ou effet réversible justifié, dont la cible ou le reçu enrichit le Working Set. |
| `clarify` | Plusieurs cibles ou effets matériellement différents restent plausibles. |
| `deny` | Violation RBAC, cible interdite ou contradiction explicite avec le scope. |

Le préflight ne duplique pas les autorisations du domaine. Il vérifie la relation entre intention,
cible et effet ; le Tool conserve la validation finale de ses paramètres, ACL, secrets et règles
métier.

Les grants peuvent évoluer sans nouvelle question lorsqu’un résultat vérifié établit une cible
nécessaire à une exigence déjà autorisée. Une expansion vers un autre acteur, une autre collection
ou un effet non impliqué par l’objectif reste explicitement justifiée.

## 9. Livraison et reçus

La politique de livraison possède un unique propriétaire : contrôleur conversationnel, domaine
appelant, Process ou cible explicite. Elle est figée dans le run avant l’exécution.

- Le planner n’ajoute pas un second transport.
- Un transport réussi inscrit source, destination, fonction, idempotency key et reçu.
- Le résultat terminal ne prétend pas avoir livré sans reçu.
- Une reprise consulte les reçus avant de rejouer un effet.
- Une cible alternative découverte pendant le run n’est utilisée que si elle respecte la même
  intention de livraison ou si une clarification l’autorise.

Cette règle généralise le contrat existant des artefacts et des URI sans limiter la livraison aux
fichiers ou à Messenger.

## 10. Projection des décisions de portée

Quand les contrats de portée et le préflight seront réalisés, rendre leurs décisions
consultables dans l'activité existante, sans exposer contenus sensibles ni arguments complets.
Réutiliser `TaskActivitySnapshot`, `activity_snapshot.py` et `live_checkpoint.py` :
aucun second checkpoint visuel ni seconde représentation des messages.

## 11. Extensions transactionnelles du contrôle de portée

Réutiliser les sessions courtes, les leases, les checkpoints et les reçus existants. Les
travaux restants portent sur les nouvelles décisions de scope et de préflight :

- persister leur identité et leur révision avant l'effet, puis revérifier le scope lors de
  la publication ;
- relire grants, décisions et reçus après interruption sans répéter un effet confirmé ;
- conserver l'erreur racine et les erreurs secondaires de ces nouveaux chemins ;
- qualifier leurs conflits et crashs, y compris après effet distant et avant publication.

Sans preuve suffisante, conserver une attente ou une issue incertaine. La généralisation
aux Processes et aux autres runtimes ne peut se déduire du seul checkpoint interne.

## 12. Répartition des responsabilités

### `app.agent`

- posséder les contrats `ExecutionScopeV1`, exigences, claims, descripteurs et plan validé ;
- composer la hiérarchie de prompt ;
- appliquer le préflight générique sans importer les modèles ORM de Task ou Tool ;
- conserver le contrat de stream et le résultat terminal unique.

### `app.task`

- ajouter scope et grants à la persistance existante des reçus, tentatives et leases ;
- promouvoir les ressources exactes dans le Working Set via son port ;
- ordonnancer retry et reprise sans décider de la méthode agentique ;
- enrichir le snapshot opérationnel durable avec les décisions de portée.

### `app.tools` et `app.mcp`

- transporter les descripteurs d’effet avec le catalogue effectif ;
- garder schémas et droits filtrés autoritaires au moment de l’appel ;
- fournir le hook commun de préflight sans couplage à un client concret.

### Domaines propriétaires et bridges

- déclarer les capacités et effets de leurs fonctions ;
- valider cibles, ACL, paramètres, idempotence et reçus dans leur propre domaine ;
- traduire les systèmes externes sans déplacer leur état canonique dans `app.agent`.

### `app.conversation`

- construire l’objectif autonome, les exigences, les références utiles et la politique de
  livraison lors de l’admission ;
- recueillir une clarification sans créer une seconde Task concurrente.

### Frontend Task et Chat

- présenter les nouvelles décisions de portée depuis le snapshot commun existant ;
- préserver la réhydratation, les droits et les états de pause définis par 0087.

## 13. Séquence d’implémentation

### Bloc A — Contrats purs et provenance

- ajouter les contrats versionnés dans `app.agent.contracts` ;
- définir la hiérarchie des sources et les règles de compatibilité ;
- sérialiser une première version dans `Task.data` via `AgentTaskPort` ;
- couvrir parsing, version inconnue, héritage parent/enfant et amendement.

### Bloc B — Admission et livraison

- produire exigences, grants initiaux et politique de livraison depuis le round ;
- promouvoir les URI exactes utiles sans recopier l’historique ;
- garantir un unique propriétaire de livraison ;
- tester création, amendement, pièce jointe, salon courant et cible explicite.

### Bloc C — Planner

- remplacer l’entrée libre par le scope et le profil compact ;
- structurer claims, exigences, hypothèses et preuves ;
- ajouter le validateur sémantique déterministe ;
- distinguer retry de schéma, conflit de scope et information manquante ;
- mettre à jour les datasets et évaluations du Lab concernés.

### Bloc D — Descripteurs et préflight

- étendre le catalogue public de `app.tools` avec les métadonnées optionnelles ;
- annoter un échantillon représentatif de fonctions natives de lecture, création, mutation,
  transport, suppression et Process ;
- conserver le comportement compatible des fonctions non annotées ;
- brancher le préflight commun et persister sa décision dans la timeline.

### Bloc E — Projection de la portée

- intégrer les nouvelles décisions de scope/préflight dans l'activité existante ;
- qualifier leur lecture après reconnexion avec les droits et états de pause courants.

### Bloc F — Reprise des décisions de portée

- raccorder scope, grants et préflight aux transactions et checkpoints existants ;
- conserver erreur racine et erreurs secondaires lors de leur persistance ;
- injecter des pannes entre décision, effet et publication pour vérifier l'absence de doublon.

### Bloc G — Documentation et garde d’architecture

- ajouter l’invariant de provenance et de non-extension de scope ;
- mettre à jour les flux d’exécution, de Process et de ressources ;
- documenter les métadonnées des Tools externes ;
- régénérer la cartographie si les contrats ou outils exposés changent.

## 14. Matrice minimale de tests

### Portée et provenance

- Profil contenant plusieurs cibles possibles, objectif sans cible : aucune cible n’est inventée.
- Objectif avec cible explicite : cette cible est conservée avec sa provenance.
- Cible découverte par un résultat d’outil : elle peut être promue et réutilisée.
- Libellé humain ambigu : il ne devient pas un identifiant ou une URI implicite.
- Mémoire ou historique contradictoire : l’objectif courant reste prioritaire.
- Fonction inconnue sans descripteur : elle reste découvrable et utilisable selon les règles de
  compatibilité, sans obtenir de grant implicite.

### Planner

- Ajout d’une cible sans source : rejet sémantique.
- Omission ou affaiblissement d’une exigence : rejet.
- Retry de structured output : corrige le format sans valider automatiquement le sens.
- Choix d’un outil disponible mais hors scope : l’outil reste visible, le claim est rejeté.
- Information essentielle manquante : clarification unique et reprise de la même Task.

### Effets et livraison

- Production dans l’espace de Task sans destination : autorisée et inscrite au Working Set.
- Deux transports concurrents proposés : un seul propriétaire est exécuté.
- Redelivery d’un reçu identique : aucune duplication.
- Effet externe réussi puis panne DB : le retry reprend depuis le reçu.

### Projection de la portée

- Décisions de scope et de préflight accessibles après reconnexion, sans données sensibles.
- Droits, pause, compteurs et checkpoints existants préservés lors de leur projection.

### Transactions

- Exception ORM avant effet, après effet et pendant finalisation.
- Rollback réussi ou en échec secondaire avec conservation de la cause initiale.
- Perte de lease pendant application du résultat.
- Crash entre reçu, Working Set et résultat terminal sans répétition de l’effet.

## 15. Critères d’acceptation

- Aucun composant agentique ne peut introduire silencieusement une cible concrète sans provenance.
- Un profil riche continue d’aider le raisonnement sans agir comme une autorisation implicite.
- Les Tools et Processes futurs participent au mécanisme sans modification du noyau par produit.
- Les fonctions non enrichies restent compatibles et observables.
- Une Task autonome peut explorer, produire, vérifier et livrer sans questions artificielles.
- Les effets externes ou difficilement réversibles sont justifiés, reçus et rejoués de façon sûre.
- Planner, exécuteur et livraison partagent le même scope versionné.
- Chat, TaskDetails et `task_get` montrent les mêmes décisions de portée après reconnexion,
  en conservant les garanties d’activité et de pause existantes.
- Une panne SQLAlchemy conserve sa cause initiale et ne provoque pas la répétition aveugle d’un
  effet déjà réussi.

## 16. Hors périmètre

- construire une liste centrale de produits, commandes ou providers interdits ;
- remplacer le RBAC ou les ACL propres aux domaines ;
- analyser le texte arbitraire d’une commande comme unique barrière de sécurité ;
- imposer une confirmation humaine à chaque appel d’outil ;
- donner au planner le droit d’exécuter ou de créer des grants ;
- créer un second système de fichiers virtuel à côté d’`app.file_share` ;
- fusionner les états canoniques de Task, Process et LLMCall ;
- implémenter ce plan dans le présent changement.
