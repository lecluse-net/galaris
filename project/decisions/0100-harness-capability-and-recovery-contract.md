# 0100 — Contrat commun des capacités et de la reprise des harnais

Statut : accepté — 14 septembre 2026.

## Problème

L’orchestration interprétait les checkpoints du harnais interne et des configurations
Hermès. Plusieurs vocabulaires de capacités divergeaient ; le harnais interne ne
possédait pas les mêmes réglages que les runtimes externes. Les tests avec factories
permissives pouvaient laisser passer une incompatibilité du véritable SDK.

## Décision

`app.agent` possède le contrat commun, l’admission et l’acceptation du résultat. Chaque
driver possède sa projection de cible et son interprétation de checkpoint. Le payload
reste opaque hors de ce driver. Une reprise est classée `safe`, `reconcile` ou `unsafe` ;
l’absence de contrat, une identité différente ou une enveloppe corrompue interdit le
redémarrage automatique. Un amendement conserve les preuves d’effets ; le driver peut
refuser le rebasage d’un historique distant.

Précision du 19 septembre 2026 : l'amendabilité exposée et l'admission sous verrou
interrogent le même contrat de rebasage avant toute annulation ou modification d'objectif.
La vérification ne modifie pas le checkpoint. Une exécution possédée par un lease, ou
déjà admise, sans checkpoint vérifiable reste non amendable jusqu'à un point de reprise sûr.
Un checkpoint incompatible ou corrompu entraîne un conflit qui préserve le travail initial.
Cette vérification est déterministe et n'appelle aucun LLM. La conversation choisit toujours
le rattachement métier : deux résultats indépendants restent deux Tasks, même dans un
document commun. Le refus d'amendement n'autorise ni remplacement ni duplication implicite.

Le descripteur `galaris.harness-capabilities/v1` distingue les fonctions implémentées,
configurées, vérifiées pour la sélection et effectives. L’ensemble effectif est leur
intersection. `stream` reste accepté à la lecture des anciens enregistrements et est
normalisé en `streaming`. Une configuration ne crée jamais une capacité.

`app.harnesses` conserve les politiques par code de provider, y compris le harnais
interne. Elles ont une révision et une mise à jour optimiste protégée par verrou SQL.
Les droits PARAMS_EDIT et la gestion globale sont requis pour une écriture. Le même
formulaire configure tous les providers. Les limites d’exécution, d’inactivité, de
fermeture et de volume sont communes ; les plafonds propres au runtime restent
prioritaires. Les garanties de protocole et les fonctions natives non gouvernables
par Galaris sont descriptives, pas des interrupteurs fictifs.

Les restrictions des outils Galaris sont revérifiées à chaque appel, y compris après
création du catalogue MCP. Les actions de supervision sont également revérifiées lors
de leur exécution différée. Le défaut conversationnel reste indépendant du harnais
sélectionné pour les Tasks.

Une requête est copiée à la frontière : les mappings et modèles mutables ne sont pas
partagés avec le driver. Les callbacks de progression et de checkpoint sont bornés et
validés. La façade garde la publication des événements terminaux. Les chemins `run`
et `stream` passent par la même validation.

Précision du 16 septembre 2026 : `max_stream_bytes` cumule uniquement les événements
émis par le flux (`message` et `result`). Les sauvegardes de progression et checkpoints
remplacent un état durable et restent chacune bornées par `max_result_bytes`, sans
consommer ce cumul. Recompter leur historique complet à chaque sauvegarde interrompait
les Tasks longues malgré des événements et des états individuellement petits.
Les refus de volume indiquent la surface concernée, la taille et le plafond en octets.

L’annulation produit un reçu `requested`, `confirmed` ou `unknown`, avec portée locale
ou distante. Une requête acceptée n’est pas une preuve d’arrêt. Les appels concurrents
sont mutualisés, l’instance active est réutilisée et le délai est borné. Ce registre
est local au processus ; les leases Task et checkpoints restent l’autorité durable.
Chat Completions ne déclare ni annulation distante, ni reprise inexistante.

Les erreurs distinguent configuration, indisponibilité, protocole, quota, délai,
annulation, effet incertain et runtime. Un retry `never` reste interdit ; un retry
`reconcile` exige un checkpoint reprenable, même sans appel d’outil visible.
Une identité de run admis sans checkpoint bloque également la récupération automatique
après crash ou expiration de lease : l’absence de réponse ne prouve pas l’absence d’effet.

## Qualification

- `make tests-harness-contracts` : façade, harnais scriptable, checkpoints, configuration
  SQL, outils, adaptateurs, scheduler et frontière AST interdisant les branches par nom.
- `make tests-mutations` : les régressions injectées sur le terminal, l’isolation et les
  capacités doivent être détectées, dans des copies jetables.
- `make tests-harness-runtimes` : construit les quatre images, puis exécute leurs vrais
  SDK/binaires contre un modèle local déterministe. Réseau externe désactivé, données
  temporaires, aucun secret de production. Les digests et hashes de source sont conservés
  dans `artifacts/harness-runtimes/summary.txt`.
- `make validate` inclut obligatoirement les contrats et les images réelles.

Codex et Claude Agent sont épinglés à des versions explicites ; Hermès à un digest
amont ; DeepSeek à un commit et une version Pydantic explicites. Une mise à jour de SDK
nécessite de repasser ces gates. Le test réel a détecté puis permis de corriger les
options supprimées de DeepSeek et la projection MCP silencieusement ignorée par son
nouveau format de patchs.

## Limites explicites

Aucun test ne prouve une fiabilité absolue d’un runtime tiers, d’un réseau ou d’un modèle.
L’interruption asyncio suppose un driver coopératif ; un arrêt matériel forcé exige
l’isolation dans un processus. Les tests d’images prouvent la compatibilité locale avec
le protocole simulé, sans qualifier les abonnements ni le comportement des vrais LLM.
Les harnais externes restent plafonnés à une Task simultanée ; augmenter ce plafond
exigerait un protocole distant d’identité, de contrôle et de réconciliation plus riche.
