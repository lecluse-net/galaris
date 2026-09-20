# Fiabilisation transversale — contrats et preuves

Ce document sert de mémoire de travail commune pour les corrections du
[plan des travaux conversationnels restants](../plans/fiabilisation-conversationnelle.md).
Les plans ne conservent plus les historiques d'implémentation. Ce document ne remplace ni les
contrats du code, ni les décisions acceptées, ni le
[catalogue de tests fonctionnels](../../docs/fr/dev/functional-tests.md).
Les résultats ci-dessous concernent le développement ; ils ne qualifient pas une production.

## Carte des responsabilités et équilibres à conserver

| Parcours / propriétaire | Garantie à préserver lors d'une correction voisine | Preuve existante à réutiliser |
|---|---|---|
| Admission et rounds / `app.conversation` | Conserver toutes les entrées ; une correction invalide le round devenu obsolète, une question n'arrête pas automatiquement la Task | Tests `conversation/test_service.py`, `test_scheduler.py`, `test_task_admission.py` |
| Exécution / façade `app.agent`, runtime `app.harness` | Un résultat terminal unique ; interrompre le travail possédé, conserver les effets déjà engagés et leur incertitude | `agent/test_driver_boundary.py`, `harness/test_conversation_interrupt.py`, `test_execution_evidence.py` |
| L2 : persistance / `app.task` | Un seul propriétaire valide ; pas de renouvellement d'un lease expiré ; conserver les écritures indépendantes et refuser les vrais conflits métier | `task/test_working_set.py`, `test_amendment_service.py`, tests du scheduler |
| L3 : arrêt/remplacement / `app.task` | Arrêt terminal idempotent ; pas de création implicite après amendement refusé ; création indépendante explicite possible ; successeur libéré seulement après preuve d'arrêt | `task/test_replacement.py`, `conversation/test_task_admission.py`, [ADR 0123](../decisions/0123-explicit-task-replacement.md) |
| Coordination / Task, Goal, Process et drivers externes | Un accusé de demande d'arrêt ne prouve pas l'arrêt physique ; enfants et effets distants ne doivent pas être oubliés | Tests de remplacement, `process/test_lifecycle_workflows.py` ; qualification réelle coordonnée encore ouverte |
| Projections / Chat, Messenger, voix | Une réponse tardive ne remplace pas une sélection récente ; une reconnexion récupère le durable ; les refus courants purgent les données protégées | `chat-recovery.spec.mjs`, `e2e/specs/chat.spec.mjs`, tests Messenger et voix |
| Capacités / `app.tools` et chaque runtime | Annoncer les fonctions réellement disponibles ; conserver les contrôles à l'appel et les révocations ; Search, HTTPS et Browser restent distincts | `tools/test_mcp_loader.py`, `test_mcp.py`, tests des frontières driver |
| Recherche / `app.util`, `app.tools`, SearXNG | Préserver requête, langue configurée, ordre et sources partielles ; distinguer vide, dégradation et échec ; annulation effective | `tools/test_search.py` ; qualification externe séparée ci-dessous |
| Ressources / `app.file_share` et providers | URI canonique et ACL ; temporaire borné ; erreur avant effet distincte d'un effet incertain ; conserver les sources explicites dans le contexte | Tests `file_share`, `tools/test_resource_effects.py`, `conversation/test_task_objective.py` |

Les chemins de tests backend abrégés correspondent à `back/app/<domaine>/tests/`.
Aucune correction de recherche ne doit modifier les décisions d'admission, les règles de
révision, les prompts, les autorisations ou les reprises pour compenser une panne fournisseur.
Une correction de concurrence ne doit pas rendre tous les changements conflictuels, ni
supprimer les vérifications de révision. Le remplacement coordonné reste une extension à
qualifier, pas une raison de libérer prématurément les successeurs simples.

## Méthode pour chaque défaut

1. Distinguer observation de l'incident, reproduction actuelle et hypothèse.
2. Identifier le propriétaire du contrat et tous ses consommateurs, y compris synchrones,
   asynchrones, anciens états persistés et configurations administrées.
3. Écrire la garantie observable et son contre-cas légitime avant la correction.
4. Reproduire au niveau de la frontière fautive ; remplacer seulement les services externes.
5. Corriger la règle générale au niveau de son propriétaire. Garder les refontes séparées.
6. Vérifier ciblé puis consommateurs adjacents ; enregistrer les limites des doubles de test.
7. Relire le diff et préserver les autres travaux. Une validation d'un ancien instantané ne
   qualifie pas les éditions suivantes ; `make validate` est requis avant publication.

## Recherche : faits et frontières de configuration

Au début de ce lot, l'image locale annonce `2026.4.22+74f1ca203`.
Le transport répond en JSON mais les recherches générales précédentes n'ont aucune source,
avec cinq moteurs indisponibles. Cela ne permet pas d'évaluer la pertinence.
Un appel par moteur sur une requête publique technique donne : Google et Wikipedia vides
sans erreur déclarée, Qwant et Mojeek refusés, Bing avec sept sources, dont les premières
sont générales sur Python. Une réponse non vide ne suffit donc pas davantage.

La configuration versionnée `resources/search/settings.yml` initialise les installations ;
`data/search/settings.yml` appartient à l'administrateur et est conservé à la réinstallation.
La configuration locale ne force plus Bing, contrairement au modèle versionné. Cette
différence ne doit pas être « réparée » en écrasant des choix locaux.

La qualification doit distinguer quatre niveaux : service joignable, contrat JSON valide,
sources disponibles, sources pertinentes sur plusieurs sujets/langues. Le healthcheck du
conteneur ne porte que le premier. Les tests HTTP simulés ne portent pas les deux derniers.
Comparer les adaptateurs en instance isolée avant toute évolution de l'image ou des moteurs ;
ne pas ajouter de filtre lexical spécifique au sujet de l'incident ni de retry automatique
face aux protections externes.

### Comparaison et correction du neuvième lot

Trois instances jetables ont permis de séparer la version des adaptateurs du choix des
moteurs : ancienne image et candidate avec le même modèle initial forçant Bing, puis
candidate avec le modèle corrigé qui conserve la sélection amont. Aucun montage de la
configuration privée existante n'a été utilisé ; les secrets des probes sont temporaires.
Le script `make check-search` traverse le vrai `SearchClient` asynchrone.

| Requête / langue | Ancienne image, Bing forcé | Candidate, sélection amont |
|---|---|---|
| Recherche patrimoniale / fr (requête retirée) | Sources utiles, cinq moteurs indisponibles | Musée, ville, ministère de la Culture ; un moteur dégradé |
| Python asyncio documentation / en | Pages générales Python, cinq moteurs indisponibles | Documentation officielle asyncio et guides précis ; aucune dégradation |
| photosynthèse chlorophylle / fr | Sources utiles, cinq moteurs indisponibles | Photosynthèse et chlorophylle ; un moteur dégradé |
| Köln Dom Architektur / de | Aide Windows sans rapport, cinq moteurs indisponibles | Cathédrale, histoire et architecture ; un moteur dégradé |

La requête patrimoniale historique est retirée du rapport public. Le corpus manuel utilise
désormais une autre requête publique ; les mesures ci-dessus restent celles du corpus initial.

La candidate conservant Bing forçait encore des sources sans rapport (Amazon dans la
requête allemande). L'évolution retenue est donc double : image épinglée
`2026.9.19-367fb6537` et suppression de l'activation forcée de Bing dans les seules
valeurs initiales. Pas de remplacement de moteur selon le texte de la requête.
Le [contrat SearXNG des moteurs](https://docs.searxng.org/admin/settings/settings_engines.html)
distingue la désactivation par défaut du retrait d'un moteur ; les surcharges administrées
existantes restent conservées. La documentation d'administration décrit leur vérification.

Les premières sources ont été relues ; ce petit corpus ne prouve ni une pertinence
universelle ni la disparition future des refus fournisseurs. Les classements varient entre
appels. Il reproduit une défaillance de pertinence actuelle sur un autre sujet que l'incident,
mais n'établit pas rétrospectivement l'origine exacte des résultats de la démo.
Les rapports publics complets sont conservés localement dans
`artifacts/search/2026-09-19/` (non versionnés).

`make check-search` est volontaire, ne lance pas de retry et n'entre ni dans le healthcheck
ni dans les tests automatiques. Son script distingue sources absentes/échec (code 1),
sources présentes mais dégradation (2), sources présentes sans dégradation déclarée (0).
Le verdict final du corpus est **2**, pas un succès intégral des moteurs externes.
Il ne déduit jamais la pertinence du nombre de résultats.

Le service de développement existant reste sur l'ancienne image tant qu'il n'est pas
recréé ; les preuves de cette section portent sur les instances isolées. Aucun déploiement
ni changement de configuration administrée n'est effectué par ce lot.

Validation automatisée du lot : 416 tests backend (dont 31 de recherche), 277 tests
frontend, types et traductions, 28 tests d'architecture, installation/mises à jour simulées
avec conservation des personnalisations. Le contrôle externe demeure dégradé (code 2),
malgré les sources utiles. Instances et configurations temporaires supprimées.

## Dixième lot : contrôles courants et coordination persistée

Trois défauts ont été reproduits avant correction : un code d'erreur Browser arbitraire
pouvait traverser la frontière publique (trois échecs), un descendant actif ou un enfant
terminal encore loué échappait au garde de remplacement (deux échecs), et un outil natif
déjà monté restait exécutable après révocation de sa connexion ou de sa fonction (deux échecs).

| Contrat corrigé | Consommateurs et contre-cas vérifiés | Preuve |
|---|---|---|
| Codes Browser limités au protocole public, enveloppes non objet traitées sans exception secondaire | FR/EN, statut HTTP conservé, session expirée sans rejeu de l'action, ouverture explicite d'une nouvelle session | `browser/test_service.py`, `test_mcp.py`, 21 tests du véritable exécuteur Chromium |
| Coordination recherchée sur tous les descendants et auprès du propriétaire Process | Process lié à la tâche, au descendant ou à l'attente ; état actif ou annulation distante incertaine, y compris historisée ; fin confirmée et tâche indépendante autorisées ; apparition avant libération du successeur bloquée | `task/test_replacement.py`, `process/test_lifecycle_workflows.py` : 142 tests avec Browser |
| Projection d'autorisation native relue avant chaque effet | Connexion et fonction révoquées puis réactivées dans le même serveur MCP ; second agent intact ; refus classé avant effet ; outils image, fichiers, mémoire, Goal et multimédia conservés | `tools/test_live_authorization.py` avec vraie DB et MCP ; suite consommateurs : 387 tests |

Le port de coordination est assemblé au bootstrap : Task ne dépend pas de Process.
Une annulation logique avec `remote_may_continue` ne constitue pas une preuve d'arrêt.
Cette correction renforce le contrat de remplacement simple de l'ADR 0123 ; elle
n'implémente pas une orchestration d'arrêt de tout un arbre Goal/Task/Process.
Le catalogue d'un run reste construit à son ouverture : une capacité nouvellement activée
peut exiger une reconstruction, mais une révocation interdit immédiatement l'appel suivant.

La première qualification globale a aussi révélé trois attentes de tests obsolètes :
l'interruption typée d'un document n'est plus une erreur MCP récupérable ; la disponibilité
initiale du multimédia doit être posée explicitement par le scénario ; les préférences d'aide
personnelles relèvent de l'utilisateur authentifié, avec isolation HTTP déjà testée.
Leurs garanties sont conservées. Les unités de diagnostic simulent une autorisation accordée
pour atteindre leur frontière de panne ; le nouveau scénario de révocation utilise les
services et droits réels. Aucun contrôle de production n'est désactivé pour ces unités.

Les quatre probes des SDK/binaires réels de harnais passent contre un modèle local
déterministe. Ils qualifient le démarrage, les échanges et la terminaison normale, **pas**
l'arrêt physique d'un effet distant. La qualification complète est enregistrée séparément
par `make validate` dans `artifacts/validation/*/summary.txt` ; un instantané antérieur aux
corrections ne qualifie pas le worktree final.

## Qualification transversale et dispatcher — 19 septembre

Les contrats réalisés du dispatcher appartiennent aux décisions
[0101](../decisions/0101-dispatch-without-action-judgment.md) et
[0102](../decisions/0102-harness-dispatch-choices.md). Leur ancien plan d'implémentation est
retiré ; la mesure de latence et le corpus comparatif T4 rejoignent L0 du plan conversationnel.
L'absence d'inférence pour un humain ou un choix unique, les contraintes incompatibles,
les anciennes requêtes et la persistance des décisions restent couvertes par les tests.

L'instantané `artifacts-validation.NS7bZN` a passé les onze contrôles de `make validate` :
fournisseurs, statique, backend, composants, mutations, régressions, exécuteur, gestionnaire
de harnais, contrats, runtimes et E2E. Résultats : **5 775 tests backend**, un test volumétrique
DbAdmin volontaire ignoré, **476 composants**, **378 E2E** et **19 mutations détectées**.
Les tests de reprise ciblés avaient également passé **529 scénarios**.

Le rapport officiel est **STALE** : HEAD a avancé pendant l'exécution et seul
`docs/catalogue-fonctionnel-fr.md` différait alors entre les archives. Hors ce document, leur
comparaison était identique octet pour octet. Cette preuve concerne le code testé ; elle ne
transforme pas le verdict en qualification du worktree courant pour publication. Résumé et
comparaison sont conservés localement sous `artifacts/validation/artifacts-validation.NS7bZN/`.
Le présent nettoyage documentaire intervient après cette qualification et ne la relance pas.

Les garanties des premiers lots restent dans la matrice ci-dessus, les contrats et tests
référencés, la décision [0029](../decisions/0029-unified-conversation-rounds.md), les flux
d'exécution/ressources et le catalogue fonctionnel. Leurs anciennes listes d'implémentation
ne sont plus des travaux futurs.

## Suivi opérationnel distinct — autorisations de dialogue

Le plan d'implémentation des équipes et droits de dialogue est retiré : son contrat réalisé
est la [décision 0083](../decisions/0083-shared-teams-and-dialogue-permissions.md).
La note du 11 septembre signalait une synchronisation de développement non appliquée : le
contrôle automatique avait refusé la suppression des anciennes tables et des privilèges,
même après sauvegarde et vérification. Aucune levée de ce blocage n'est établie par ce
nettoyage ; vérifier l'état actuel et résoudre ce point avant l'opération concernée.
Les anciens états ne sont pas assimilés à un défaut d'implémentation à refaire. Aucune
synchronisation ni autorisation d'intervention sur une base ne découle du retrait du plan.

## État et travaux ouverts

Le plan ne conserve que mesures de latence, qualification d'arrêt physique, remplacement
coordonné, autres surfaces de capacités/diagnostics, recherche dans l'environnement cible,
livraison de médias, contexte utile, langue/effort et frictions. Les mesures et extensions
non réalisées ne sont pas déclarées terminées par le nettoyage. Une publication requiert
toujours une nouvelle qualification du code et de la documentation à publier.
