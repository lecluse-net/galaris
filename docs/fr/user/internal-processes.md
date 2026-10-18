<p align="right"><strong>Français</strong> · <a href="../../en/user/internal-processes.md">English</a></p>

# Processus métier internes

Les processus sont gérés exclusivement dans **Processus**. Leur définition BPMN et leur
historique leur appartiennent ; ils ne figurent jamais dans la bibliothèque **Documents**,
qui contient du HTML. Les variables et les pièces jointes de chaque run sont stockées directement dans Process.

La page **Processus** réunit les processus internes et externes, dont n8n, dans une seule liste.
Cliquez sur la ligne d’un processus pour ouvrir sa page d’édition, qu’il soit interne ou externe.
La zone de la flèche à gauche charge et déplie ses exécutions ; un second clic replie la sous-liste.
L’icône de modification à droite ouvre également sa page d’édition.
L’ajout d’un processus externe utilise également une page dédiée.
Dans chaque éditeur, **Retour à la liste** se trouve sous le titre, en haut à gauche.
La recherche porte sur la liste commune ; le filtre par agent concerne les processus externes.
Les exécutions internes et externes présentent la date et l’heure de début, la durée,
l’identifiant, le statut, puis le résultat avant les actions. Le bouton **Rafraîchir**
en haut de page recharge aussi les sous-listes ouvertes. Les boutons d’ajout sont regroupés
sur la ligne suivante. La durée exclut l’attente avant
le démarrage, évolue pendant l’exécution et se fige à la fin. Une date de début absente
laisse la durée indisponible. Les exécutions externes n’ont pas de filtre supplémentaire.
**Synchroniser n8n** ouvre une modale avec l’état de l’API et les compteurs d’exploitation.
Sur la page, seul un échec de connexion à une instance n8n configurée affiche un bandeau
d’erreur ; une intégration non configurée n’affiche pas ce bandeau.
Chaque processus interne a un propriétaire humain ou agent et des droits de lecture ou d'écriture attribués aux
utilisateurs, agents et groupes ; il peut aussi être partagé publiquement. Les utilisateurs voient aussi les
processus des agents gérés. Sans propriétaire actif, la définition est réservée aux
administrateurs humains PROCESS_ADMIN.

## Construire et enregistrer

Créer un processus et saisir son titre dans la barre compacte. Le champ **Description**
permet d'ajouter un texte facultatif, modifiable puis conservé avec **Enregistrer**.
En lecture seule, la description reste consultable. Le propriétaire est choisi
à la création. Le champ **Partage** est disponible dès
la création pour donner des droits **Lecture** ou **Écriture** aux utilisateurs, agents
et groupes, ou choisir un partage public. Enregistrer applique ces choix au nouveau
processus ; pour un processus existant, les modifications du partage sont enregistrées
directement. Si le partage échoue après la création, réessayer conserve le processus et
les droits choisis sans créer un doublon.
Le sélecteur d'agent de la première ligne utilise par défaut **Agent qui lance le
processus** : aucun agent spécifique n'est imposé. Choisir un agent exécutant y impose cet
agent aux tâches sans affectation spécifique ; sélectionner **Agent qui lance le processus**
rétablit le défaut.
Le code créé est unique et immuable. Le diagramme commence avec un **Début** et une **Fin**
déjà reliés. Cliquer sur
une poignée d'entrée ou de sortie ouvre un menu pour poursuivre le traitement, insérer
une activité dans le flux, ajouter une branche ou relier une activité existante. Les liens
se modifient depuis ce menu ou leur libellé : départ, arrivée et condition. Ajouter une
**Fin** supplémentaire pour fermer une branche. Pour raccorder deux éléments existants,
glisser une poignée de sortie vers la poignée d'entrée de l'autre élément : un lien
apparaît pendant le geste et est créé au relâchement. Le geste inverse fonctionne aussi.
Échap annule le raccordement ; les doublons, les liens vers soi-même et les cycles sont
refusés. Le dernier événement Fin et le Début ne peuvent pas être supprimés.
Les flèches du clavier déplacent une
activité sélectionnée ; Suppr la retire si l'édition est autorisée. **Organiser** aligne le
graphe ; le zoom et le défilement permettent de consulter les grands diagrammes.
Le bouton **Plein écran** du cartouche de navigation agrandit le diagramme et conserve
ses menus d'édition. Le bouton de sortie ou Échap revient à la page.

Définir des **acteurs nommés**, par exemple « exécutant » et « valideur ». Chaque acteur
a un type fixe, agent ou humain, et une affectation. Une tâche agentique choisit uniquement
un acteur agent ; une tâche humaine choisit uniquement un acteur humain. Les tâches sont
placées sur la ligne de leur acteur. Un agent affecté remplace effectivement l'agent de
lancement pour ses tâches, dans le périmètre de gestion du lanceur. Sans affectation
spécifique, l'acteur agent utilise l'agent exécutant. Un acteur humain doit être affecté
à un utilisateur actif avant le lancement. Un acteur utilisé ne peut pas être supprimé.
Le nom et l'affectation se règlent directement dans l'en-tête de chaque ligne. Le bouton
**Nouvel acteur**, dans la bande hachurée sous le diagramme, crée une ligne agent ou humain.
Le nom est un champ de saisie encadré. La corbeille de l'en-tête retire directement une ligne
inutilisée ; elle est désactivée si des activités utilisent cet acteur. Il n'y a plus de bloc Acteurs séparé.
Glisser la poignée de l'en-tête réordonne les lignes avec leurs tâches, sans changer
leurs affectations. Le déplacement s'applique au relâchement ; Échap l'annule.
Les flèches haut et bas sur cette poignée permettent aussi de déplacer la ligne au clavier.
Enregistrer conserve cet ordre.

Pour changer d'acteur, **glisser-déposer la tâche sur la ligne de l'acteur voulu**.
L'affectation change au relâchement et la tâche s'aligne sur sa nouvelle ligne, en conservant
ses instructions et ses liens. Dans le profil typé, une tâche ou un IF adopte le traitement
humain sur une ligne humaine, et IA/code sur une ligne agent. Les définitions historiques
conservent le refus des changements de type incompatibles.
Échap ou une interruption du geste annule le déplacement. Enregistrer conserve l'affectation.
Déposer une tâche hors du tableau crée une nouvelle ligne et un nouvel acteur du même type,
puis lui affecte la tâche. La bande hachurée de 40 px sous le diagramme accepte aussi ce dépôt
et contient le bouton **Nouvel acteur**. Renommer le
nouvel acteur et choisir son agent ou son humain dans l'en-tête de sa ligne ; un acteur
humain doit être affecté avant le lancement. Un geste annulé ne crée aucune ligne.

Cliquer une activité ouvre son formulaire contextuel sous le bloc ; cliquer le libellé
d'un lien ouvre ses paramètres de la même façon. Le formulaire s'adapte à la place
disponible et reste accessible sur mobile et en plein écran. Un clic extérieur, Échap
ou le bouton de fermeture le referme. Les modifications et les brouillons JSON,
même invalides, sont conservés à la réouverture jusqu'à la sauvegarde ou au rechargement.
Le bouton **Enregistrer** se trouve dans la barre du diagramme, à côté de **Valider**,
et reste disponible en plein écran.

Chaque tâche possède ses **Variables d'entrée** et **Variables de sortie** : nom, type,
nullable/notnull et valeur par défaut facultative. Début et Fin règlent les variables du
processus complet. Les noms doivent être uniques ; les défauts sont vérifiés à la sauvegarde.
Les types proposés sont int, float, string, bool, Agent, File, User, Document, array et object.
Les tableaux et tables de hachage peuvent être imbriqués et tous les types peuvent être nullables.
Une variable omise utilise son défaut, sinon null si nullable ; une variable notnull sans
défaut doit être fournie. Un null explicite n'est pas remplacé par le défaut. False et zéro
restent des valeurs. Une erreur de contrat indique la tâche et la variable concernées.
Les corps FOR et WHILE utilisent le même éditeur et un fil d'Ariane.
Une ancienne définition conserve son pool partagé ; **Configurer les entrées et sorties
typées** prépare une conversion explicite à compléter avant sauvegarde. Les runs déjà
lancés conservent leur profil d'origine.
Une erreur d'exécution arrête le processus et ses branches actives. Le suivi renvoie
le code d'erreur, avec son message ; les données du run et les fichiers sont conservés.
Il n'y a aucun traitement de secours ni réessai automatique à configurer.
Un IF possède deux poignées de sortie, **True** et **False**. Sur la ligne d'un acteur IA,
choisir **IA** et saisir les instructions, ou **Code** et saisir un programme Python.
Sur une ligne humaine, le mode humain est automatique : la personne affectée reçoit la
question dans sa messagerie et choisit True ou False. Le run attend ce choix et poursuit
une seule branche. Les IF historiques sans mode conservent leurs anciennes conditions.
Les tâches proposent les mêmes modes selon leur acteur. Le code reçoit les variables du
run directement : `return variable_2 != "pas mon projet"` pour un IF, ou
`return {"variable_1": variable_1 + 1}` pour mettre à jour une sortie déclarée d'une tâche.
Le champ est prérempli avec un exemple commenté ; seules les sorties valides sont intégrées.
Relier la sortie d'une tâche à plusieurs tâches les lance en parallèle. Depuis sa poignée
de sortie, **Ajouter une branche** conserve la liaison existante et ajoute une autre tâche ;
**Relier à une activité** permet de choisir une tâche déjà présente.
Pour réunir les branches, reliez-les directement à la tâche suivante : elle attend la réussite
des branches activées puis démarre une seule fois. Une branche IF non choisie ne bloque pas
cette attente. Aucun bloc de parallélisme dédié n'est à ajouter. Le harnais détermine combien
de Tasks peuvent réellement s'exécuter ensemble.

Valider vérifie le profil exécutable. Enregistrer crée une sauvegarde du processus.
Un brouillon JSON invalide reste visible et bloque la sauvegarde. Le diagramme s'affiche
directement, sans onglets ni éditeur XML. L'historique présente à gauche les dates des
états antérieurs. Cliquer une date ouvre son diagramme
à droite. Sur mobile, le diagramme apparaît sous la liste. L'état actuel reste visible
dans l'éditeur au-dessus.
L'icône **Revenir à cet état**, sur chaque ligne, demande confirmation avant de remplacer
le diagramme et la configuration du processus courant. Le dialogue explique que les
modifications non enregistrées seront perdues et que l'historique et les exécutions
existantes seront conservés. Aucun lancement ne sélectionne une ancienne version.
La corbeille **Supprimer cet état** demande confirmation puis supprime définitivement
la sauvegarde choisie. L'état courant ne figure pas dans cette liste et ne peut pas être
supprimé. Supprimer une sauvegarde ne modifie ni le brouillon ni les exécutions existantes.
Annuler une confirmation ou rencontrer une erreur conserve le brouillon.
Le sélecteur numérique dans le pied de la liste règle le nombre de sauvegardes
affichées. Le pied indique aussi la plage affichée, le total et les flèches de navigation.

## Lancer et suivre

Demandez à l'agent de lancer le processus depuis le Chat. L'agent recueille les informations
et les fichiers nécessaires, prépare les variables d'entrée déclarées et lance la dernière
version enregistrée. La page des processus sert à l'édition et au suivi, sans formulaire
de lancement manuel. Un appel transmet ses entrées locales à
l'enfant et intègre ses sorties validées. Chaque enfant conserve ses propres données.
Les sous-processus n'ont pas de
profondeur métier maximale.

Chaque run conserve son graphe de départ et ses variables dans son champ `data`.
Une table de pièces jointes relie les fichiers à ce run. Aucun Dataset n'est créé.
Les données et fichiers suivent les droits de lecture et d'écriture du processus,
sans partage supplémentaire. Une révocation s'applique aussi aux runs existants.
Le suivi affiche **Données du run** et **Pièces jointes** ; les fichiers gérés peuvent
être téléchargés. Le moteur intègre les sorties validées et conserve les reçus techniques
séparément des variables métier.
Une sortie invalide n'est pas intégrée. Les changements disjoints sont conservés et un
conflit de variable est signalé. Les références de fichiers circulent sans téléchargement
ni copie automatique ; les droits sont contrôlés lors des opérations sur leur contenu.
La sortie du run correspond aux variables déclarées sur Fin. Le partage du processus
s’applique aussi à ses runs. Deux runs possèdent des données distinctes.
Dans l'ancien profil uniquement, les participants continuent à éditer le JSON partagé et
les fichiers initiaux sont copiés dans ses pièces jointes, selon le contrat historique.

Depuis le panneau **Processus** du Chat, la liste des exécutions d'un processus ou le suivi des processus dans Tâches,
ouvrir un run affiche une modale centrée sur son diagramme enregistré au lancement.
Dans le Chat, les runs se lisent du plus ancien au plus récent, en bas. Remonter la liste
charge les runs plus anciens en conservant la position de lecture. L'arrivée d'un nouveau
run fait défiler la liste vers le bas ; une simple mise à jour d'état conserve la position.
Le code du diagramme est préparé en arrière-plan dès qu'un run interne est présent,
et la modale ne charge les autres écrans de ressources que lorsqu'ils sont ouverts.
Les activités en cours sont mises en évidence, y compris les branches parallèles.
Cliquer un nœud ouvre sa fiche d'exécution en lecture seule : données de sortie,
retour de tâche ou d'opération, données d'entrée, tentatives, instructions réellement
exécutées et erreurs disponibles. Le sélecteur de la fiche permet de consulter les
différentes exécutions d'une activité, avec pagination si nécessaire.
Une activité non exécutée l'indique explicitement. Fermer la modale arrête son rafraîchissement.
Le diagramme et la fiche d'activité ouverte suivent les événements du run en temps réel,
sans perdre la sélection. Après une reconnexion, l'affichage rattrape les changements
manqués ; un contrôle toutes les deux secondes reste actif tant que le run est en cours.
Le graphe et les détails restent consultables pendant le chargement des coûts et
statistiques, qui se mettent à jour séparément.
Le Chat, le catalogue, le suivi dans Tâches et les liens de runs ouvrent la même modale.
Son titre regroupe l'état,
la dernière activité, puis le temps écoulé et le coût total du processus avec ses
sous-processus. L'UUID cliquable sur fond transparent se trouve à gauche du conseil de
consultation dans la barre du graphique. Cliquer l'UUID copie la référence interne
`galaris://processes/runs/<uuid>`. Le graphique remplace les compteurs et listes d'occurrences ou de
sous-processus ; la fiche de l'activité appelante permet d'ouvrir le sous-processus lancé.
Les agents peuvent la lire avec `file_info`, `file_read` ou `processus_get`, selon les droits
du processus ou avec le droit dédié d'administration Process.

Le suivi montre le graphe, les occurrences, les prompts réels, erreurs, données,
sous-processus et métriques disponibles. Les corps de boucle et les enfants s'ouvrent
à la demande. Pause suspend les nouvelles admissions tout en observant les effets
acceptés. Pas à pas admet une occurrence et laisse ses descendants composites avancer
jusqu'à sa fin. Pause et points d'arrêt persistent après redémarrage. Annuler reste
en cours jusqu'à confirmation des arrêts nécessaires.

Le cartouche **Avancement de l’exécution** indique les occurrences terminées, actives,
prêtes et en échec, la dernière activité et les attentes précises : réponse dans la
messagerie, autorisation, tâche ou sous-processus. **Reprendre** poursuit la même
exécution. **Arrêter l’exécution** demande confirmation, ferme les demandes humaines
et interrompt les tâches et enfants. Une exécution arrêtée ne peut plus être reprise.
Un résultat d'opération incertain exige une réconciliation avant reprise ; une longue
attente ne suffit pas à déclarer un blocage.

Les agents utilisent `processus_get` pour cette vue. Les droits du processus autorisent
la lecture de ses runs et de leurs données ; son droit d'écriture autorise les contrôles.
L'administration dédiée `process_admin` reste disponible. Le partage d'un processus
s'applique à ses exécutions existantes.

Une réponse à la question d'une activité concerne l'exécution existante : elle ne demande
pas un nouveau lancement. L'agent répond brièvement par défaut ; demandez les détails utiles.
Dans le Chat, les nouveaux lancements sont bornés à la demande reçue : un réessai technique
retrouve le même run. Un changement de processus ou de paramètres exige une demande qui le prévoit.

Toutes les interactions humaines passent par la messagerie : Chat interne ou messagerie
externe. Une activité IA peut aussi poser une question en cours de travail : elle attend
votre réponse dans la conversation, puis reprend avec les informations reçues, sans créer
de tâche supplémentaire pour attendre. La réponse enregistrée est conservée lors de la reprise,
même si l'agent reformule la même demande.
Une activité
sans variable de sortie peut simplement produire un message de résultat.

Une activité affectée à un humain utilise une messagerie reliée au compte de cette personne.
Une tâche humaine envoie ses consignes
dans la conversation et attend durablement la réponse, sans lancer de tâche IA pour attendre.
Répondez naturellement ou joignez le fichier demandé, même sans texte. L'agent retrouve les
demandes en attente et leurs données attendues ; il demande une précision si la réponse est
incomplète ou pourrait concerner plusieurs étapes. Un message sans rapport laisse le processus
en attente. Les fichiers conservent leur référence dans leur messagerie d'origine.
Seule la personne affectée peut répondre ; les sorties sont validées avant la reprise.
Une réponse retransmise à l'identique ne termine pas deux fois l'activité, et une réponse
après annulation ne relance pas le processus. L'affectation ne donne aucun accès aux données
des autres exécutions. Le suivi reste dans Processus ; la boîte « Mes activités humaines »
est remplacée par ces échanges dans la messagerie.

Durées et coûts sont des mesures sans budget Process bloquant en v1. Un coût indisponible
ou partiel n'est pas présenté comme nul. Le total inclusif ajoute les enfants accessibles
et conserve la distinction des coûts estimés. Une reprise réattache les Tasks/Runs admis ;
un effet Tool sans reçu certain n'est pas rejoué automatiquement.
Le montant facturé et la valeur d'inférence sont séparés, notamment sous abonnement.
La table détaille ces mesures pour chaque occurrence, y compris les boucles et retries.
Archiver une définition conserve son BPMN, son historique et les liens de ses runs.

## Auditer et tester

Les agents autorisés inspectent la définition complète par MCP, ses prompts, acteurs et
historique, puis proposent ou appliquent une correction selon leurs droits.
Une capacité Tool ne remplace pas l'accès au processus et à ses données.

**Lab → Processus** prépare des cas inventés, éventuellement générés par le modèle Lab,
puis lance une campagne réelle. Chaque cas conserve son run, ses mesures et un contrôle
exact facultatif de sortie. Les vrais Tools autorisés sont utilisés ; les mocks sont
reportés à une seconde phase.

Les secrets restent dans les Connections. Les nœuds Tool appellent des opérations MCP
déclarées. L'activité API REST utilise la connexion de son agent et une requête relative
à l'API configurée ; un refus HTTP arrête l'activité. Les activités Code et les scripts
facultatifs de préparation/intégration utilisent un interpréteur Python limité et isolé,
sans accès aux fichiers, au réseau ou aux packages tiers, avec des limites de temps et de mémoire.
Les programmes
documentaires nécessitent leur exécuteur qualifié séparé ; son absence est signalée.
Les conventions sont détaillées dans le [profil BPMN natif](../dev/native-processes.md).

Chaque document, jeu de données et définition de processus conserve un partage indépendant. Modifier les droits d’une ressource ne modifie pas ceux d’une autre ressource liée. La mise à jour conserve les partages existants, y compris les accès par groupe. Voir le [mécanisme de partage](../dev/sharing.md).

## Citer un processus dans un document

Dans la barre d'outils du document, **Insérer un lien ou un fichier** puis
**Ajouter une PJ interne** ouvre le sélecteur de ressources file_share. Son arborescence,
ses fichiers compacts et sa recherche dans l'emplacement permettent de sélectionner
plusieurs ressources, y compris des définitions internes et des runs. Les cases et
Maj permettent la sélection multiple ; un double-clic ouvre un dossier.
La commande **Insérer un lien ou un fichier** de la barre d'outils regroupe les liens
web, les ressources internes et le téléversement. Les ressources sélectionnées sont citées
dans le texte sans rejoindre les PJ. Sous le document, **Téléverser** ajoute uniquement
des fichiers ; les références existantes n'y sont pas listées.
La miniature représente le processus ;
un badge de lecture distingue ses exécutions. Ouvrir une définition affiche sa modale
en lecture seule ; ouvrir un run affiche sa modale de suivi.

Dans l'éditeur, l'action de présentation du lien permet de passer du lien au
diagramme et de revenir au lien. Survoler le cadre du diagramme, ou y déplacer le
focus au clavier, affiche les commandes de zoom et de plein écran en haut à droite.
Ces commandes restent accessibles sur écran tactile. Le diagramme d'un run correspond
à la définition figée lors de son lancement.

Citer une ressource ne donne aucun droit sur le processus. Chaque lecteur doit y
avoir accès indépendamment du document. Retirer sa citation du texte ne supprime
ni le processus ni son exécution.
