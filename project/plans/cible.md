# Cible prospective de Galaris

- Statut : `design`
- Revue des sources : 2026-10-08.

Ce document conserve la direction produit et les dépendances de maturité.
L'[index des plans](README.md) possède les chantiers détaillés ; code, tests et décisions
décrivent le runtime. Les ambitions ci-dessous ne sont pas toutes des prérequis à une
première bêta et ne valent pas autorisation d'implémentation.

## Principes

Étendre les propriétaires existants : Agent pour exécution/résolution, Task pour
persistance/reprise, Goal pour autonomie, Messenger pour admission, Memory pour
connaissances, Lab pour mesures, Tools/MCP/File Share/Process pour effets.
Nouveau domaine seulement si responsabilité durable distincte démontrée.
Aucun second moteur de Task/conversation, domaine d'évaluation concurrent ou routine générique.

Distinguer intention → décision → identité/délégation → exécution/simulation →
observation → vérification/compensation/escalade.
Acceptation distante sans preuve ne vaut pas effet ; issue inconnue sans rejeu aveugle.
Profil éditable, release immuable et deployment sont distincts, corrélables aux travaux.
Généralisation après comparaison Lab étalonnée, avec provenance et télémétrie expurgée.

## Livraison publique

Le dépôt possède CI, guides d'installation/exploitation et artefacts de release :
[workflows](../../.github/workflows/) et
[exploitation](../../docs/fr/dev/reliability-operations.md).
Organiser leur distribution publique pérenne et qualifier les artefacts exacts.

Restent : threat model des surfaces à effet ; durcissement MCP externe (egress, SSRF,
DNS/redirections/TLS, tailles/délais et stdio) ; jetons expirables/révocables/scopés/audience ;
reprise générique des consommateurs du journal Messenger avec statut et file morte ;
matrice de concurrence/crash/annulation PostgreSQL ; SemVer/changelog/compatibilité/rollback ;
OCI multi-architecture signée, SBOM/provenance ; SECURITY/CONTRIBUTING/code de conduite ;
fresh install, upgrade, backup/restore/rollback automatiques ; trois parcours publiés
avec qualité, coût, latence et limites.

Réception : Critical mitigées, High restantes avec propriétaire/échéance/contrôle ;
aucune entrée acceptée perdue, double effet externe ou second terminal dans les scénarios
de crash ; installation, upgrade et restauration des artefacts publiés démontrés.

## Gouvernance des effets

Le contrôle générique de portée reste dans le
[plan provenance](portee-provenance-execution-agentique.md).
L'autorisation ponctuelle réalisée relève de
[0153](../decisions/0153-common-action-authorizations.md).

Extension prospective : intercepteur commun aux surfaces à effet, taxonomie versionnée,
`ActionIntent/Decision/Observation`, politiques par portée, identité effective/délégation,
budgets/rate limits atomiques, registre causal, vérification différée et compensations saga.
Modes candidats : OBSERVE, SIMULATE, SUGGEST, APPROVE_EACH, SUPERVISED, AUTONOMOUS ;
approbations expirables et éventuellement multiples.

Chaque adaptateur déclare idempotency key, reçu, lecture après écriture, compensation
ou absence assumée de garantie. Aucun exactly-once universel.
Réception : effet risqué corrélé à politique/identité/stratégie et observation vérifiée,
sinon attente, ambiguïté ou escalade.

## Releases d'agents et promotion

Concevoir `AgentProfileVersion` (mandat/capacités/enveloppes), `AgentRelease`
(snapshot prompts/modèles/driver/skills/outils/politiques/contrats) et
`AgentDeployment` (environnement/bindings/trafic/canari/rollback).

Sceller/signer, diff et inspection sans secrets ; rattacher Task/run/LLMCall/action à
l'empreinte exacte ; travaux engagés inchangés lors d'une activation.
Canari, suspension et rollback ciblent une version, sans réécrire l'historique.

Le [Lab](lab-evaluation-mecanismes-ia.md) porte étalonnage, incertitude, comparabilité,
gardes et exports CI. Relier ensuite les gardes aux releases/deployments,
évaluer permissions/pannes/injections/effets et détecter les dérives par environnement.
Release non qualifiée sans trafic de production ; garde franchie → rollback/suspension
ou décision humaine selon politique. Incidents avec reproduction entièrement synthétique.

## Autonomie événementielle

Les fréquences et cycles parents de Goal existent ; l'inbox métier générique reste à concevoir.
Événements durables, abonnements typés/filtrés/scopés, déduplication/curseur,
réveil déterministe, priorités urgence/échéance/coût, portefeuille borné,
budgets concurrence/coût/fréquence, backpressure/file morte/reprise administrative.
Événement → cycle Goal → Task ordinaire → verdict corrélable.
Redelivery sans double cycle, budgets et politiques conservés.

## Connaissances gouvernées

Le [plan mémoire](amelioration-globale-memoire.md) porte rappel/acquisition/organisation.
Extension prospective : confiance/autorité/sensibilité, détection d'empoisonnement et
conflits de sources, consolidation de procédures, évaluation et promotion gouvernée,
cycle brouillon/revue/publication/dépréciation/retrait, rétention par portée.
Projection Markdown canonique éventuelle sans vault transactionnel, adapters documentaires
avec conflits/révisions/reprise ; aucun domaine documentaire sans responsabilité distincte.
Publication sourcée/versionnée/approuvée, zéro fuite ACL ; aucune promotion automatique
avant étalonnage du Lab.

## Collaboration et interopérabilité

Registre de capacités avec preuves/fraîcheur, contrats de contribution,
affectation selon droits/disponibilité/coût/confidentialité et `CollaborationRun`.
Rôles coordinateur/contributeur/reviewer ; consultation, délégation, parallèle et revue.
DAG borné, fan-in, réaffectation/échec/compensation, profondeur/fan-out/durée/coût/trafic.
Task conserve chaque unité ; aucun scheduler/planner concurrent.
Comparer au solo : cibles de maturité proposées +5 points qualité, -15 % coût ou
-20 % temps de cycle, avec non-infériorité et aucune borne dépassée.

Interopérabilité : profil MCP et conformité, OAuth/protected resource metadata/audience,
mapping A2A vers Task/Messenger/File Share/Process, Agent Cards/stream/artifacts/annulation/reprise,
AG-UI sans autorité métier, OpenTelemetry et politique de contenus sensibles.
SDK minimal et TCK publics pour drivers/bridges/process/outils, adaptateur de référence
hors monorepo, profils/compatibilités/déviations versionnés.
Réception : extension conforme sans import privé ni fuite de causalité/données.

## Supervision, entreprise et élasticité

Carte releases/deployments/capacités/dépendances ; vue Goal/Task/collaboration/Process/action ;
approbations/effets non vérifiés/alertes/prise de contrôle ; exploitation Messenger
(listeners, curseurs, reconnexions, erreurs, files mortes).
Suspension, réduction d'autonomie, rollback ; organisations/environnements/quotas/rétention/audit ;
OIDC/SAML, SCIM, comptes de service et KMS/Vault.
Arrêter isolation par deployment ou multi-tenancy ; API/workers/pools/multi-instance,
backpressure/circuit breakers, backup/failover/restore industrialisés et bruit de voisinage.
Cible de maturité : soak ≥24 h et 10 000 Tasks, error budget et RPO/RTO publiés,
aucune fuite entre portées dans la matrice adverse.

## Écosystème signé

Le [plan plugins](infrastructure-plugins-galaris.md) possède bundle, activation,
conservation de données, SDK/TCK et frontend distribué.
Étendre ensuite aux releases d'agents/skills/outils/templates : registre personnel/fédéré,
signature/SBOM/provenance, compatibilité/permissions, bindings locaux sans secrets embarqués,
révocation/dépréciation/rollback. Audit aligné sur les référentiels applicables,
à revalider lors de conception.
Bundle altéré/révoqué/incompatible ou permissions non acceptées refusés.

### Piste optionnelle — visualisation 3D de la mémoire

Paysage navigable au-dessus du graphe gouverné, Three.js comme candidat,
forces/projection sémantique bornée, exploration assistée/vol libre.
Objectif utilisateur et gain à démontrer avant chantier ; conserve ACL et vue 2D,
sans exposer les embeddings. Ne bloque pas la livraison publique.

## Dépendances et preuves de maturité

Activer dans l'ordre : durcissement/distribution → gouvernance d'effets →
releases et gardes → autonomie/collaboration → interopérabilité/flotte/écosystème.
Préparer les corpus et contrats en amont sans dupliquer les plans spécialisés.

Conserver comme ambitions de référence, distinctes de la première publication :
première mission <15 minutes hors téléchargement ; trois parcours et études de cas publics ;
audit indépendant du contrôle d'effets ; ≥10 000 injections crash/retry/redelivery sans perte
ni double effet ; trois contributeurs réalisant un adapter conforme en moins d'une journée
médiane ; dix deployments indépendants et deux extensions tierces maintenues ;
processus public de contribution/divulgation de sécurité.

Chaque chantier sort de ce plan lorsque repris par un plan borné ou une décision acceptée.
Les preuves appartiennent aux guides, tests, campagnes et audits.
