<p align="right"><strong>Français</strong> · <a href="../../en/dev/agent-team-qualification.md">English</a></p>

# Qualifier un travail d'équipe avec de vrais agents

Ce pilote prépare puis observe une mission fictive dans l'application assemblée. Le Chat,
les droits, le journal entrant, les Tasks, l'ordonnanceur et le harnais interne sont réels.
Les décisions et réponses des agents ne sont pas scriptées. Ce n'est ni un benchmark du Lab
ni une suite E2E déterministe. Aucun gain de collaboration n'est présumé.

## Préparer sans appel au fournisseur

Prérequis : l'image backend de développement `galaris-backend` doit déjà être construite.
`GALARIS_TEAM_BACKEND_IMAGE` permet de sélectionner une autre image compatible. Les commandes
s'exécutent depuis le dépôt de développement, avec Docker ; aucune toolchain hôte n'est requise.

```bash
make agent-team-pilot ARGS='prepare'
make agent-team-pilot ARGS='prepare --case conflict --mode directed'
```

Chaque commande crée son propre projet Compose, une base et un stockage vides, trois agents
fictifs (responsable, logistique, finances), trois sources HTML et une synthèse existante.
Les trois agents appartiennent à une équipe dédiée, sans droit global sur les autres agents.
La préparation vérifie leurs appartenances avant toute soumission ; les droits des documents
restent accordés séparément, en lecture aux deux collègues.
Les fixtures ne provisionnent pas de Console SSH et Dream est désactivé pour isoler cette mission.
Le fournisseur est désactivé. Le pilote vérifie l'authentification et la lecture des ressources,
puis ouvre réellement le Chat dans Chromium et enregistre une capture. Il ne soumet aucune
mission. `prepare --api-only` vérifie uniquement la préparation backend ; ce résultat ne prouve
pas le parcours navigateur. `APP_ENV=qualification` conserve les protections de production.

La stack n'utilise ni `.env` applicatif comme configuration de service, ni base existante,
ni connexion de messagerie externe. Les outils des agents sont limités aux fonctions nécessaires
au dossier. Les profils et la clé de fournisseur des agents habituels ne sont pas copiés.

## Lancer une mission réelle

Copier `back/tests/agent_team_pilot/provider.example.json` vers un fichier local sous `artifacts/`
ou hors du dépôt. Renseigner `base_url` et `model` pour un endpoint OpenAI Chat compatible,
capable d'appels d'outils et de sorties structurées. Le modèle unique sert aux trois agents et
aux choix structurés par la voie texte. Le profil passe par la validation publique des capacités ;
aucun service natif Decisions n'est sélectionné. La préparation vérifie ces bindings avant
soumission. Le pilote ne découvre ni ne remplace automatiquement un modèle.
Les modèles sous OAuth/abonnement et les harnais externes ne sont pas couverts par cette version.

Conserver la clé dans un fichier séparé de droits `0600`. Ne pas la placer dans le JSON,
la commande ou un fichier versionné. Pour un endpoint local sans clé, configurer explicitement
`allow_no_api_key: true`. Les prix optionnels `input_usd_per_million` et
`output_usd_per_million` permettent le suivi estimé des coûts. Une absence de prix ne vaut pas
gratuité. `max_tokens` et `timeout_seconds` bornent l'admission ; un appel déjà engagé peut
dépasser une estimation. Ils ne constituent pas un plafond de facturation fournisseur.

```bash
make agent-team-pilot ARGS='run --case baseline --mode spontaneous --config /absolute/provider.json --key-file /absolute/provider-key'
make agent-team-pilot ARGS='run --case conflict --mode directed --config /absolute/provider.json --key-file /absolute/provider-key'
make agent-team-pilot ARGS='run --case amendment --mode directed --config /absolute/provider.json --key-file /absolute/provider-key'
```

`run` autorise des appels réels et leur coût. La mission est envoyée une seule fois depuis le
véritable compositeur Chat avec la directive `@task`. L'application choisit les appels, les
délégations, leurs objectifs et la synthèse. L'observateur ne crée aucune sous-tâche et ne
fabrique aucune réponse de collègue. Il collecte ensuite les API authentifiées du Chat et
des Tasks, sans route de fixture exposée dans le backend normal.

Une erreur navigateur après réception du reçu d'envoi ne provoque pas de nouvel envoi :
le pilote collecte le travail déjà admis avant nettoyage. Le code d'échec initial et les
diagnostics navigateur restent conservés, même si l'observation ou la capture échoue aussi.
Sans reçu, la mission n'est pas resoumise automatiquement.

## Scénarios et organisation

| Scénario | Situation | Vérification humaine attendue |
|---|---|---|
| `baseline` | Sources complémentaires, transport connu mais non engagé | Synthèse complète, sources et informations préservées ; délégation observée ou absente explicite |
| `missing` | Coût du transport absent | Information inconnue identifiée ; complément utile ou limite précise, aucune valeur inventée |
| `conflict` | 60 participants annoncés pour une salle de 48 places | Désaccord sourcé, aucune décision humaine inventée |
| `amendment` | Budget modifié pendant les contributions | Nouvelle enveloppe et nouveau solde, propagation de la consigne, autres faits préservés |
| `amendments` | Deux consignes : 7200 → 6800 → 6500 EUR | Admissions dans l'ordre, dernier budget et réserve de 200 EUR, sans reconfirmation du budget décidé |
| `peer_failure` | Fournisseur Finances inaccessible | Panne réelle, Logistique conservée, récupération ou limite précise sans validation inventée |
| `comparison` | Deux options chiffrées, engagements et capacités | Même grille pour `directed` et `solo` : fidélité, calculs, durée, coût et interventions |

Le cadrage interdit toute **nouvelle** réservation et préserve explicitement la réservation
déjà confirmée. Une consigne de ne pas agir ne constitue donc pas un conflit avec cet état.
La relecture contrôle aussi les inconnues proposées par les collègues : la devise EUR est
fournie par les sources, alors que le statut HT/TTC reste non précisé.

`spontaneous` laisse le responsable choisir ses collaborations ; `directed` lui demande de
piloter les deux collègues sans lui imposer d'ordre d'outils ; `solo` interdit les fonctions de
délégation. Le mode n'est pas une simulation : les agents raisonnent et travaillent réellement.

Dans `amendment`, l'observateur envoie une seule consigne humaine après observation d'au moins
deux collègues distincts en exécution (`EXEC`), non suspendus. Une tâche simplement en file
ne déclenche pas l'envoi. Le déclencheur, les Tasks et le message accepté sont conservés.
Si les contributions ne se chevauchent pas, la consigne n'est pas envoyée : ce cas n'est pas
une qualification du changement en cours. Le couple `amendment/solo` est donc refusé.
Les appels HTTP d'envoi ne sont pas rejoués automatiquement après une issue incertaine.

Une consigne acceptée pendant des délégations est conservée dans `task_amendments`, avec
`applied_at=null` et un reçu `deferred=true`. Les collègues poursuivent leur contribution ;
le fan-in applique les consignes dans leur ordre d'acceptation avant de reprendre la synthèse.
Un plan matérialisé sur la tâche principale reste non amendable. Une pause humaine reste
prioritaire, et un checkpoint incompatible bloque la reprise sans perdre la consigne.
Un message accepté, des tâches `SUCCESS`, ou une source financière mise à jour ne prouvent
pas que le document final est correct : vérifier la cible, les amendements et les contributions.

## Lire les preuves

Dans `amendments`, la seconde consigne n'est envoyée qu'après observation de l'admission durable
de la première, tant que le travail n'est pas terminé. Les deux envois ont des reçus distincts.
Dans `peer_failure`, seul Finances utilise un endpoint local sans serveur : le harnais rencontre
sa vraie erreur de connexion. Aucun statut de Task ni aucune contribution n'est forcé.
Les modes `amendments/solo` et `peer_failure/solo` sont refusés.

Exécuter `comparison` en `directed` et en `solo` avec les mêmes sources, modèle, paramètres et
code figé. Relire les documents avec la même grille, puis comparer appels physiques, coût,
durée et demandes d'intervention. Une seule paire reste exploratoire, sans gain statistique établi.
Contrôler le tableau principal et le message final, pas seulement la présence des bons chiffres
dans une annexe. Un devis connu non engagé reste un coût prévisionnel à inclure dans le périmètre
comparé, avec son statut provisoire ; un total partiel arithmétiquement exact peut tromper la décision.

### Interrompre réellement le backend

```bash
make agent-team-pilot ARGS='run --case amendment --mode directed --restart-after-amendment --config /absolute/provider.json --key-file /absolute/provider-key'
make agent-team-pilot ARGS='run --case amendment --mode directed --restart-after-write --config /absolute/provider.json --key-file /absolute/provider-key'
```

L'observateur attend une consigne durable encore non appliquée et au moins une contribution
terminée. Il conserve un snapshot puis revérifie la consigne avant de demander l'interruption.
Le contrôleur hôte envoie un seul `SIGKILL` au backend de ce projet Compose, conserve la base
et redémarre le même conteneur. Un volume privé conserve `/data` ; le bootstrap vérifie l'identité,
la configuration et le manifeste de l'essai et ne réinitialise jamais les fixtures au redémarrage.
Le volume et les conteneurs sont supprimés par le nettoyage final du seul projet pilote.

`before-restart.json`, `after-restart.json`, `boots.jsonl`, `backend-*.json`, `database-*.json`
et `restart-receipt.json` distinguent interruption, reprise et conservation du stockage.
La reprise normale attend l'expiration des leases ; leurs délais ne sont pas raccourcis.
Les horodatages après reprise doivent confirmer que la consigne n'avait pas déjà été appliquée
avant l'arrêt ; la dernière lecture avant la panne ne suffit pas à le prouver. Un arrêt avant
la première écriture du document ne qualifie pas la récupération d'une écriture déjà validée.
Si la consigne est appliquée avant la fenêtre d'interruption, le scénario est non exercé et
la commande échoue sans provoquer une panne tardive. Les appels d'inférence interrompus
peuvent être repris et facturés : vérifier les effets durables plutôt que compter toute nouvelle
inférence comme un doublon. La garantie observée sur les effets porte sur les documents du pilote.

### Résultats conservés

`--restart-after-write` vise une fenêtre distincte : la cible doit avoir une révision enregistrée
supérieure à sa révision initiale avant la livraison finale. La même révision et son empreinte
doivent survivre à la reprise ; le message final doit être daté après le démarrage du nouveau
processus. Une livraison déjà effectuée avant l'arrêt ne qualifie pas cette fenêtre. Les empreintes
répétées sont signalées ; la relecture reste nécessaire pour détecter des passages répétés dans
un contenu différent. Les deux fenêtres de panne ne sont pas interchangeables.

Chaque invocation affiche son répertoire privé `artifacts/agent-team/run.…/` :

- `manifest.json` : scénario, mission, critères hors contexte candidat, paramètres et ressources ;
- `scenario.md` : demande et sources fictives directement lisibles avant le lancement ;
- `preflight.json` : préparation vérifiée sans mission ;
- `submission.json` : reçu du message réellement envoyé ;
- `timeline.jsonl` : changements observés avec horodatage ;
- `evidence.json` : messages, activités, traces des rounds, Tasks complètes, budgets et documents ;
- `assessment.json` et `report.md` : observations, texte du document final, messages et grille humaine non préremplie ;
- `browser-*.png` et `browser-*-errors.json` : captures et erreurs du navigateur ;
- empreintes des sources, `services.log`, `exit-status.txt` et `cleanup.log` : provenance et diagnostics.

`browser-*-state.json` atteste le contexte sécurisé et l'envoi de l'abonnement à la salle.
`preflight.json` vérifie aussi l'absence d'appels de modèle enregistrés. Si les sources changent
pendant le pilote, `source-changed.txt` le signale et la commande sort en erreur : les observations
ne qualifient alors pas un checkout figé. Le rapport d'exécution conserve les appels physiques et
leur coût d'inférence enregistré ; une estimation ou un tarif absent reste à interpréter comme tel.

Les identifiants de connexion éphémères sont retirés au nettoyage. Les clés et tokens sont
expurgés des diagnostics ; le dossier contient uniquement les ressources fictives du pilote.
Les preuves restent locales. Ne pas les transformer en fixtures copiées d'une autre installation.

Le rapport distingue absence de délégation, un ou deux collègues observés, timeout et erreur
de collecte. Un code de sortie zéro signifie que l'exécution/collecte a abouti, pas que le contenu
est accepté. `SUCCESS` ne satisfait pas automatiquement les critères. La relecture humaine doit
pointer le document et les événements pertinents ; l'empreinte des preuves permet de fixer ce qui
a été relu. Les coûts des Tasks peuvent inclure les descendants et ne sont pas additionnés.

`editorial_observations` indique si le document cible a été observé et signale ses titres
identiques consécutifs ; une cible absente ne vaut pas un contrôle réussi. Ce contrôle ne
réécrit rien et n'accepte pas le contenu. La relecture vérifie aussi que les contradictions
sont étayées par des affirmations incompatibles de même objet/période/périmètre, que les
inconnues restent telles et qu'un désaccord réel n'est pas masqué.

La suppression du projet arrête ses workers locaux ; elle ne certifie pas l'arrêt physique
d'un appel fournisseur. Une interruption ou une collecte défaillante conserve les dernières
preuves et un diagnostic, sans déclarer une réussite. Les services sont supprimés uniquement
dans le projet Compose propre à cette invocation.

## Étendre après la première recette

Relire d'abord une mission complète. Répéter ensuite à modèle, données et budgets comparables,
en distinguant erreurs, corrections humaines, durée et coût par résultat accepté. Les tests
`tests/test_agent_team_pilot.py` protègent la collecte, l'isolation et les conclusions prudentes ;
ils ne démontrent aucune compétence d'agent. Les reprises après crash et les autorisations
humaines interactives restent des qualifications supplémentaires, non exercées automatiquement.
