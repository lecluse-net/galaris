# Audit et renforcement de l’API interne des harnais — 14 septembre 2026

## Résultat

Les quatre axes de l’audit sont implémentés : checkpoints opaques, politique commune
pour tous les harnais, contrôle/erreurs explicites et qualification renforcée. Cela
réduit les risques de régression ; cela ne constitue pas une promesse de fiabilité
absolue des runtimes ou des modèles externes.

Le worktree contient aussi de nombreuses évolutions indépendantes, conservées. Aucun
commit ni déploiement n’est effectué par cet audit.

## Garanties et consommateurs

| Surface | Consommateurs | Garantie |
|---|---|---|
| Contrats, registre et façade `app.agent` | Tasks, conversations, drivers | Sélection explicite, une seule acceptation terminale, aucun succès avant fermeture propre |
| Politiques de checkpoint | Scheduler, reprise, amendement, livraison déterministe | Aucun payload concret dans la façade ; refus d’une reprise inconnue ou ambiguë |
| Configuration `app.harnesses` | Catalogue, admission, outils MCP, supervision | Même politique pour l’interne et chaque provider ; capacités restreintes, jamais inventées |
| Harnais scriptable et kit commun | Tests de frontière et adaptateurs | Fautes reproductibles sans LLM : ordre, retard, annulation, mutation, volume |
| Images de runtime | Codex, Claude Agent, Hermès, DeepSeek | Vrai SDK/binaire exécutant une tâche contre un service modèle local |
| Task, tentatives et leases | Persistance durable et scheduler | Les anciens propriétaires ne publient pas ; un effet incertain exige une réconciliation |

Les conversations continuent à utiliser leur sélection indépendante des Tasks. Le
registre reste le seul point de composition qui nomme le driver par défaut.

## Changements réalisés

### Frontière d’exécution

Les chemins `run` et `stream` partagent le même validateur. Il accepte zéro ou plusieurs
messages, puis exactement un résultat terminal et une fermeture propre. Un résultat
suivi d’un événement, d’un crash ou d’une attente trop longue reste un échec. Les modèles
retournés sont revalidés, même après mutation ; les enveloppes ambiguës sont refusées.

Les délais de run, d’inactivité et de fermeture ainsi que les budgets en octets bornent
la sortie. Les requêtes sont copiées en profondeur. Les callbacks de progression et de
checkpoint sont également validés et bornés ; la publication terminale reste à la
façade. Les flux des adaptateurs sont explicitement fermés à l’interruption du consommateur.

### Reprise opaque

Un driver contribue une `DriverCheckpointPolicy` avec évaluation `safe / reconcile /
unsafe` et rebasage optionnel. Le harnais interne possède la lecture de ses versions
1/2/3 et du journal des effets. Hermès possède sa stratégie et son identité distante.
Un driver au nom arbitraire peut apporter un autre format sans modifier l’orchestration.

Une enveloppe corrompue ne devient jamais un nouveau run. Un checkpoint ne change pas
de driver. Un amendement conserve les preuves des effets et ne peut effacer aveuglément
un historique distant. L’effet Console incertain nécessite sa preuve de réconciliation.

### Réglages communs

Le catalogue expose une section « Fiabilité et capacités des harnais ». Le harnais
interne a la même surface que les providers externes. Les valeurs sont persistées par
code de provider, versionnées, et protégées contre les écrasements concurrents.

`HarnessCapabilityDescriptor` distingue implémentation, configuration, vérification et
ensemble effectif. Les anciens `stream` sont lus comme `streaming`. Les limites du
runtime restent des plafonds ; une configuration ne crée jamais un support manquant.
Les garanties de protocole et les fonctions natives que Galaris ne gouverne pas sont
présentées comme capacités descriptives, pas comme interrupteurs sans effet.

Les outils Galaris revérifient la politique à l’appel ; les commandes de supervision
la revérifient avant l’action différée. Les éditeurs globaux disposant de PARAMS_EDIT
peuvent modifier les politiques. L’interface conserve les valeurs après un conflit de
révision et les brouillons à la fermeture/réouverture du panneau.

### Contrôle et erreurs

Les reçus d’annulation distinguent `requested`, `confirmed` et `unknown`, avec portée
locale ou distante. L’instance active est réutilisée, les requêtes concurrentes sont
mutualisées et leur durée est bornée. Ce mécanisme local ne remplace pas les leases ni
les checkpoints durables. Une réponse HTTP perdue ne prouve pas un arrêt distant.

La taxonomie commune indique la catégorie d’échec, les effets possibles et la politique
de retry. `never` interdit la relance ; `reconcile` exige un checkpoint reprenable,
y compris lorsque la dernière tentative n’a pas encore enregistré d’outil visible.
Après arrêt brutal ou expiration de lease, une identité de run admis sans checkpoint
interdit aussi le rejeu. Le test de récupération PostgreSQL a reproduit le défaut avant
correction, puis vérifié l’arrêt avec diagnostic.
Le transport Chat Completions ne prétend plus annuler ou reprendre un run distant.

### Qualification des véritables runtimes

Les dépendances critiques sont épinglées : SDK Codex 0.147.0, Claude Agent SDK 0.2.152,
image Hermès v2026.8.31 par digest, DeepSeek au commit déclaré par le provider et
Pydantic 2.13.5. Le test d’image remplace uniquement le service modèle, utilise des
données temporaires et désactive le réseau externe.

Ce contrôle a reproduit deux défauts DeepSeek réels : les options `session_root` et
`cordis` avaient disparu du SDK, et les anciennes entrées de configuration MCP étaient
ignorées par le nouveau système de patchs. L’adaptateur utilise maintenant `dsh_home`,
le profil SDK et une couche de patchs explicite. L’insertion MCP, les skills, le stockage
et les limites sont adaptés ; le test vérifie aussi que MCP est effectivement chargé.

## Preuves reproductibles

- `make tests-harness-contracts` : 965 tests réussis lors de la dernière passe ciblée,
  couvrant façade, checkpoints, configuration SQL, outils, adapters, scheduler et AST.
- Le harnais scriptable explore 121 séquences d’événements, en plus des fautes ciblées.
- Les trois nouvelles mutations (terminal invalide, requête partagée, politique ignorée)
  sont détectées par leurs tests dans des copies jetables.
  Une quatrième mutation protège le refus de rejeu d’un run admis après crash.
- Deux tests navigateur passent sur le vrai formulaire Vue/Quasar : sauvegarde,
  réouverture, provider arbitraire et conflit de révision.
- `make tests-harness-runtimes` construit les quatre images et conserve leur digest,
  le hash de leurs sources et les résultats dans `artifacts/harness-runtimes/`.
- `make validate` intègre les contrats et les images comme étapes obligatoires ; ses
  rapports ne valent que pour l’instantané qu’ils identifient.

## Limites qui restent explicites

Un driver Python qui ignore l’annulation ne peut pas être tué par asyncio ; l’isolation
processus est nécessaire pour un arrêt forcé. La compatibilité d’un SDK avec le service
modèle simulé ne prouve pas la disponibilité d’un abonnement ou la qualité d’un vrai LLM.
Les harnais réseau restent plafonnés à une Task simultanée. Leur parallélisation exige
un protocole distant plus riche, avec identité de tentative, contrôle et réconciliation.
Les fonctions natives propres aux runtimes restent décrites par leurs contributions.

Voir les décisions [0098](../decisions/0098-harness-stream-acceptance.md) et
[0100](../decisions/0100-harness-capability-and-recovery-contract.md).
