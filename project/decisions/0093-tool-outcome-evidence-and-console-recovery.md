# ADR 0093 — Preuves d’exécution et reprise des commandes console

- Statut : Accepted
- Date : 2026-09-12
- Précise et remplace les règles d’acquittement des erreurs de l’ADR 0045.

## Garantie et incident

Une interruption entre un effet externe et son accusé de réception ne doit jamais déclencher
une seconde mutation aveugle. Une tâche observée a révélé un journal
conservateur et des arguments compactés utilisés après interruption. Traiter toute exception
`ModelRetry` comme un rejet serait une fausse correction : une panne réseau après mutation peut
produire exactement cette exception.

## Décision

Le checkpoint interne v3 conserve un journal d’effets indépendant de l’historique destiné au
modèle. Chaque appel possède un UUID écrit avant dispatch, ses arguments et sa politique.
Les snapshots sauvegardés sont détachés de l’état mutable du run. Les arguments d’un appel
sans réponse ne sont pas compactés. Une reprise remplace les réponses provisoires sans ajouter
un second retour pour le même appel.

Une réponse MCP d’erreur est un rejet seulement si le serveur natif fournit une preuve liée
à l’UUID et au nom de l’outil : validation des arguments avant entrée dans le corps, ou
`ToolCallRejectedError` explicitement levée avant effet. Le serveur agrégateur retire cette
preuve des réponses externes. Une erreur non idempotente sans preuve devient `outcome_unknown`.
Les anciennes erreurs textuelles, y compris `ModelRetry`, ne constituent pas une preuve.
Les erreurs de validation historiques structurées peuvent être réconciliées par identifiant.

`galaris-exec` v2 accepte cet UUID avant lancement. Il persiste l’intention et son empreinte,
verrouille la prise en charge puis écrit l’identité du superviseur avant de lancer Bash.
Un doublon retrouve le même reçu ; des arguments différents avec le même UUID sont refusés.
L’écriture atomique et les fsync protègent les reçus et les sorties terminales. Un superviseur
disparu sans reçu terminal laisse une issue inconnue, jamais une autorisation de recommencer.
Un lanceur disparu avant la prise en charge peut être repris à partir de l’intention persistée.
`exit` et `exec` dans Bash n’empêchent pas la persistance du résultat par le superviseur.

Le harnais relit les reçus console à la reprise sur la même connexion, machine, clé hôte et
identité Unix. Le scheduler peut programmer une tentative bornée de réconciliation, même avant
le premier résultat visible ; elle ne permet pas de redéclencher une opération sans reçu.
Un changement de cible conserve le blocage. Les opérations standard SSH restent disponibles,
mais une déconnexion ou un timeout sans reçu conserve une issue inconnue.

Les retries manuels conservent le journal. Les écritures de progression et de checkpoint sont
conditionnées à la tentative active et à son lease non expiré ; le dernier checkpoint est aussi
archivé dans cette tentative. La livraison déterministe conserve son propre reçu écrit avant
dispatch et ne peut pas effacer un envoi incertain. Le daemon console arrête les sessions avec
les droits Unix de leur propriétaire, jamais à partir d’un PID utilisateur exécuté comme root.

## Validation et exploitation

`make tests-recovery` couvre MCP réel, PostgreSQL et SSH réel avec perte d’accusé, doublons
concurrents, arrêt forcé du lanceur et du superviseur, annulation, retry manuel, historique et
écriture tardive d’un ancien lease. Les services externes payants ne sont pas sollicités.
Ces tests font également partie de la suite backend de `make validate`.

Le compteur `harness_effect_recovery_total` distingue `started`, `completed`, `rejected`,
`unknown`, `recovered`, `blocked` et `replayed`. Les journaux structurés corrèlent run et opération,
sans copier les commandes, arguments ou sorties. Surveiller l’apparition de `unknown`/`blocked`
et examiner les reçus correspondants avant toute relance opérationnelle.

La reprise console exige le helper v2 et la conservation du home persistant. L’exécuteur intégré
embarque le helper avec son image ; une cible externe doit recevoir la mise à jour du helper via
son installation existante. `console_status.operation_recovery_available` expose la capacité.
Ne pas purger `.galaris/sessions` tant que des tâches peuvent reprendre leurs opérations.
Les anciens checkpoints ne possèdent pas nécessairement d’UUID distant récupérable : aucune
migration ne peut inventer ce reçu. Ils restent bloqués si les traces ne prouvent pas l’issue.

Cette garantie est « au plus une exécution » par UUID pour la console équipée, pas une transaction
distribuée exactement une fois pour une commande arbitraire. Une commande peut avoir produit des
effets partiels avant sa mort ; les services externes sans clé d’idempotence ni API de statut
exigent toujours une réconciliation explicite. Aucun déploiement ni retry de production ne fait
partie de la qualification locale.

## Précision du 14 septembre 2026 — Redmine #166

La présence d'un helper fonctionnel ne prouve pas sa capacité de reprise : la détection
préfère v2 à v1, et l'installation vérifie `operation_recovery_available`. L'interface
propose aussi la mise à jour d'une connexion enhanced restée en v1. Un reçu `running`
peut acquitter le lancement de `console_start`, mais ne clôt pas un `console_exec` interrompu.
Les instructions agentiques séparent les modifications des tests longs suivis par polling.
Le helper distribué reste compatible avec Python 3.11 et ultérieur, indépendamment du
backend Python 3.14 : la syntaxe des exceptions multiples sans parenthèses empêchait son
lancement sur le Python 3.13.5 d'une console configurée. Le test de l'asset vérifie également
la grammaire minimale avant d'exécuter sa commande de version.

Une commande contenant le texte `git push`, même avec un code shell zéro, n'est plus un reçu
de livraison. Cette heuristique reconnaissait aussi un simple `grep`, masquait les échecs
intermédiaires et déclarait publiés tous les fichiers console sans lien au dépôt concerné.
Les anciens reçus `console_exec:git_push` restent consultables dans l'historique, mais sont
exclus de la validation du plan et de la récupération après livraison. Les fichiers déposés
à l'URI durable explicitement demandée et les vrais reçus des outils de livraison conservent
leurs garanties. Un succès Git doit être vérifié sur le remote, la ref et le SHA concernés ;
aucun outil de publication Git structuré n'est ajouté par cette correction limitée.

Les tests qui acceptaient toute commande contenant `git push` sont remplacés par le refus
de cette fausse preuve. Les tests de livraison effective, destination explicite et reprise SSH
continuent de couvrir les garanties conservées. L'audit et ses pièces sont dans
`project/audits/2026-09-14-redmine-166-tool-recovery.md`.
