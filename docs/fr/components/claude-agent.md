<p align="right"><strong>Français</strong> · <a href="../../en/components/claude-agent.md">English</a></p>

# Claude Agent Harness

## Claude Agent embarqué

Le backend installe le SDK Python et lance son exécutable local. Dans **Administrer →
Préférences → Harnais → Harnais interne**, activez **Claude Agent**. Sélectionnez
ensuite **Claude Agent** dans **Fiche Agent → Général → Harnais**. Cette
affectation fonctionne sans conteneur Claude dédié. Pydantic AI reste sélectionnable dans
la même fiche.

Les appels passent par la passerelle locale de Galaris. Le journal LLM permet de retrouver
la tentative de tâche, le round Chat ou vocal, ou la soumission précise en mode `@deep`.
Les outils MCP externes utilisent les connexions du Service et ses fonctions autorisées en
conversation ou en tâche. Les demandes d’accord se traitent dans l’interface habituelle. Voir le
[flux d’exécution](../architecture/flows/agent-execution.md).

### Retour au routage conversationnel précédent

Pour rétablir Pydantic AI pour les nouveaux rounds de Chat et de voix par tours, désactivez
**Utiliser Claude Agent en conversation** sur le même écran. Le réglage
`harness.claude-embedded.conversations.enabled` vaut `true` par défaut.
Conservez `harness.claude-embedded.enabled` à `true` pendant la transition. Les rounds déjà
admis terminent ou reprennent avec leur harnais d’origine. Les affectations de tâches et le
mode `@deep` continuent d’utiliser leur propre harnais. Remettez le réglage conversationnel
à `true` pour rétablir le routage vers Claude selon l’affectation de l’agent.

Avant de désactiver le SDK lui-même, laissez les rounds, tâches et soumissions Deep Claude
en cours se terminer ou traitez explicitement leurs reprises. Pour déplacer des exécutions
futures de tâches ou de Deep, modifiez l’affectation de l’agent dans sa fiche.

Si le worker d’une tâche Claude disparaît avant le premier effet d’un outil, le scheduler
peut relancer l’exécution en conservant son identité et son budget d’appels. Si le résultat
final est déjà enregistré dans le checkpoint, le worker suivant le récupère sans appel au modèle.
Le réglage du plafond de requêtes s’applique aux nouvelles tâches, aux nouveaux rounds de Chat
ou de voix et aux nouvelles soumissions Deep. Une reprise conserve le plafond enregistré et
compte les appels des tentatives précédentes. Une nouvelle soumission Deep prend le réglage
courant, même si elle reprend l’historique de la session. Les anciennes exécutions sans plafond
enregistré adoptent le réglage en vigueur à leur prochaine admission.

Une tâche embarquée interrompue après la création d’un document peut reprendre à partir
du reçu enregistré. Galaris vérifie que l’outil reste autorisé et que l’agent peut
toujours lire le document. La reprise utilise le reçu existant sans répéter la création.
Si le reçu manque ou que ces vérifications échouent, la reprise s’arrête avant un nouvel
appel au modèle. Elle conserve le plafond d’outils admis pour l’exécution et tient compte
des opérations déjà enregistrées.

### Qualification de l’image backend

`make tests-embedded-harness-image` exerce l’image locale désignée par
`EMBEDDED_HARNESS_IMAGE` et contrôle la révision `EMBEDDED_HARNESS_REVISION` embarquée.
La livraison lance aussi cette sonde sur l’image exacte du bundle. La sonde utilise
PostgreSQL isolé et simule le fournisseur de modèles. Elle vérifie les appels LLM
de deux rounds simultanés, le retour des nouveaux rounds sur Pydantic AI et une tâche
qui continue à utiliser Claude. Pendant l’activation de Claude, un agent Pydantic garde
son moteur dans Chat et Tâches. Un agent affecté à Codex ou DeepSeek Agent répond
dans Chat via Claude et envoie ses tâches au harnais affecté.
Par défaut, la sonde simule les endpoints des harnais managés. Le journal inclut l’identité de
l’image, les versions SDK et CLI, les appels rapprochés des reçus du fournisseur et les
tâches reçues par chaque harnais managé. Il vérifie aussi une demande `@task` depuis
Chat pour chaque affectation. La tâche conserve le lien avec son round, s’exécute sur le
harnais choisi et livre une seule notification de résultat dans la salle d’origine.
L’appel structuré partagé qui prépare l’objectif est rattaché au round. Pour une tâche
embarquée, l’appel d’exécution est en plus rattaché à la tâche et à sa tentative.
La sonde rejoue aussi une demande en langage naturel pour chaque affectation. Elle vérifie
l’appel à `task_run`, son reçu, le dispatch et l’exécution de la tâche, puis le retour dans
Chat. Elle teste l’accord et le refus dans les deux boucles embarquées en vérifiant les
tentatives de reprise et les effets de la décision.

Pour exercer Codex et DeepSeek Agent, fournissez leurs identifiants d’images Docker
locales dans `EMBEDDED_HARNESS_CODEX_IMAGE` et `EMBEDDED_HARNESS_DSH_IMAGE`. La sonde démarre
leurs véritables conteneurs sur le réseau de test, appelle la passerelle Galaris et conserve
les identifiants des trois images. Les appels des tâches managées sont alors rapprochés
du fournisseur synthétique et vérifiés par tâche, tentative et round source éventuel.
Les tâches utilisent des agents et des affectations créés pour l’essai.

Avec `EMBEDDED_HARNESS_LOAD_ROOMS=8`, la même commande lance aussi huit nouvelles salles
par harnais sur le même profil, avec le fournisseur synthétique. Ce nombre doit dépasser
celui des workers de conversation et rester inférieur ou égal à 24. Le journal donne la
durée de chaque rafale et rapproche les appels de toutes les salles. En cas d’échec, la
sonde conserve aussi le journal PostgreSQL de l’instance de test.

## Transition depuis un ancien conteneur Claude

L’ancien harnais Claude conteneurisé est retiré du catalogue. Pour un agent qui
l’utilise encore, terminez les tâches ouvertes puis sélectionnez **Claude Agent**
dans sa fiche. Le changement déclenche la procédure habituelle de suppression
du conteneur et de révocation de son jeton. Sauvegardez les fichiers de son
espace de travail avant de confirmer ce changement.
