<p align="right"><strong>Français</strong> · <a href="../../en/user/tasks.md">English</a></p>

# Confier et suivre une Task

Une Task conserve un travail durable, son état et son résultat. Ce guide explique le choix
de méthode, les jalons, les plans, les questions et la reprise. Pour créer votre première
demande, suivre le [guide utilisateur](README.md) ; pour trouver les commandes, consulter
les [menus et parcours](navigation.md).

## Standard et high

Le niveau d’effort ne désigne pas deux architectures différentes. Le même driver exécute la
tâche, mais Galaris peut sélectionner un modèle plus puissant. La méthode de travail et
le choix de coordonner plusieurs tâches sont des décisions distinctes du niveau d’effort.

| Niveau | À privilégier pour | Effet attendu |
|---|---|---|
| `standard` | conversation, recherche simple, opération bornée et déterministe, y compris une action destructive explicitement autorisée | réponse rapide et économique ; garde-fous ordinaires inchangés |
| `high` | ambiguïté réelle, contexte substantiel à reconstruire, diagnostic ou récupération complexe, décisions fortement couplées, création technique ou créative exigeante | modèle d’exécution plus robuste |

Le risque opérationnel ne détermine pas à lui seul l'effort : supprimer un fichier précisément
identifié ou réinitialiser un dépôt exact après autorisation explicite peut rester `standard`. Les
contrôles de portée, confirmations et protections contre les effets destructifs restent applicables
quel que soit le niveau.

Vous pouvez laisser Galaris choisir. Les directives `@standard` et `@high` forcent le niveau
lorsqu’elles sont disponibles dans votre canal. `@exec` et `@plan` forcent la route, mais un
driver qui interdit le planner ne peut pas être contraint à l’utiliser.

Pour un document unique, ses recherches, chapitres et relectures restent dans une même exécution
afin de conserver leur cohérence. Un ensemble de livrables pouvant être validés et repris
séparément peut passer par `PLAN`, même s'ils doivent être traités dans l'ordre et partagent un
suivi commun. Un petit lot mécanique ne nécessite pas à lui seul un plan.

Dans le Chat natif, `@task` placé n’importe où dans le message crée immédiatement une Task durable
avec le texte restant comme objectif, sans appel au LLM de conversation. Pour le harnais interne
Galaris, `@plan` suffit lui aussi à créer la Task et à forcer sa planification, sans ajouter `@task`.
Ces directives se combinent, sans ordre imposé, avec `@standard` et `@high`. `@approve` ne donne
aucun accord. Les actions sensibles utilisent [les autorisations](../admin/tool-administration.md). Le Chat
conserve le round et publie aussitôt une confirmation déterministe
dans la room ; le résultat de la Task y sera publié à sa terminaison. Le bouton `@` du composeur
affiche uniquement les directives compatibles avec le driver de l’agent sélectionné.

Le résultat revient automatiquement dans la discussion, même si un outil ou une pièce jointe
a échoué. Si l’agent a déjà envoyé ce même résultat dans cette discussion, Galaris ne le renvoie
pas. Une pièce jointe indisponible n’empêche pas la publication du texte.

## Ce qui se passe après l’envoi

Une demande qui poursuit un travail peut réutiliser son document de suivi sans recopier
son URI dans le dernier message. Galaris résout cette référence depuis le contexte et
conserve la justification de sa mise à jour. Cela n'autorise pas à modifier les autres
documents cités dans la discussion ; leurs droits d'accès restent applicables.

1. La demande créée dans cet écran devient une Task durable.
2. Le Dispatcher choisit la route, l’effort et l’organisation du travail.
3. Une précision manquante peut suspendre la demande ; le planner prépare les travaux décomposables.
4. Le driver exécute l’agent avec ses outils autorisés.
5. Galaris enregistre la trace et le résultat, puis reprend les parents éventuels.

Les conversations texte et voix suivent leur propre contrôleur et leur exécuteur configuré. Elles
ne passent pas par le Dispatcher de Tasks ; lorsqu’elles ont besoin d’un travail durable, elles
créent une Task explicitement liée.

Le contexte de conversation présente les tâches et processus réellement actifs de l’agent,
y compris ceux lancés dans une autre discussion : travail en file, en cours ou en attente,
avec la question ou la dépendance connue. Une attente ancienne reste visible tant qu’elle
n’est pas résolue. Les éléments terminés, en cours d’annulation ou mis en pause manuellement
sont exclus. Vous pouvez ainsi répondre à une question ou envoyer le fichier attendu dans
la conversation : l’agent dispose du contexte pour reconnaître cette contribution. Si plusieurs
attentes correspondent, il doit demander une précision ; la réponse reste soumise aux droits
et à la validation du mécanisme de reprise concerné.

Si le profil de l'agent configure un modèle Décision, le dispatcher de conversation aide à
rattacher votre message à une attente ou à un travail en cours et à choisir un nouveau processus
à lancer. L'agent réalise ensuite l'action avec les contrôles habituels. Sans ce modèle ou si
l'analyse ne peut pas conclure, il doit faire lui-même cette recherche et lancer le processus
adapté si nécessaire. Une demande de suivi ne débloque pas une question en attente.

La même projection est disponible pour la supervision via
`GET /api/conversations/agents/{agent_id}/active-work?page=1&page_size=50`.
Elle réunit les Tasks et les exécutions de processus internes et externes, avec leur état
opérationnel, leurs attentes et leurs références. La réponse contient `items`, `total`,
`page`, `page_size` et `observed_at` ; `kind` distingue `task` de `process`, et `engine_code`
identifie le moteur d’un processus. L’accès exige `TASK_ACCESS`, `PROCESS_READ` et la gestion
de l’agent ; les droits de lecture des processus restent appliqués. La pagination accepte
jusqu’à 500 éléments par page.

## Terminer une tâche de force

**Terminer de force** rend la tâche terminale en erreur et révoque son bail d’exécution,
même si sa révision a changé depuis l’ouverture du détail. Une tentative active est annulée
sans attendre la coopération du harnais. Un worker tardif ne peut plus enregistrer son résultat.
Les droits de modification et la portée de gestion de l’agent restent requis.

L’arrêt est enregistré avant la clôture du cycle d’objectif et les notifications. Ces traitements
ont une attente bornée : leur échec est journalisé et ne remet pas l’arrêt en cause. Répéter la
commande conserve l’état terminal et retente la clôture d’un cycle encore ouvert. Les effets
déjà envoyés à un système externe ne sont pas annulés rétroactivement.

## Une méthode adaptée au travail

Une action bornée, comme renommer un fichier précisément identifié, reste directe.
Une mission longue ou complexe peut conserver un suivi par jalons dans la même Task :
préparation, critères d’acceptation, résultats observés, ressources et prochaine action.
Ce suivi aide à reprendre le travail sans perdre son contexte ni répéter des effets déjà acquis.
Il ne crée pas de sous-tâches pour chaque phase d’un même livrable.

Le détail de Task permet d’inspecter l’activité, les outils et les résultats ; `task_get`
expose le suivi par jalons enregistré. L’exécuteur peut le mettre à jour
avec `task_work_update`, sur sa Task active, avec contrôle de révision. Jusqu’à vingt jalons
sont conservés ; un jalon déclaré terminé ne remplace pas la preuve du résultat ou de sa livraison.
Le suivi possède sa propre révision : les sauvegardes d’exécution ne bloquent pas ses mises à jour.

Pendant une réflexion longue, les sauvegardes intermédiaires sont espacées pour laisser
l'exécution avancer. Les résultats d'outils, erreurs et fins de blocs restent enregistrés
immédiatement ; rouvrir la Task retrouve le dernier suivi sauvegardé.

Si le périmètre ou la profondeur attendue change sensiblement le travail, Galaris peut poser
une question avant de commencer. Répondez dans la conversation liée à la demande. Une inconnue
technique que l’agent peut résoudre par inspection autorisée relève de sa préparation.

## Planner : décomposer un travail coordonné

Dans le suivi détaillé de Task et le panneau de tâches de la discussion, une alerte apparaît
après deux minutes sans activité reçue : réflexion, texte, génération d'arguments ou résultat
d'outil. Elle disparaît dès que l'activité reprend et n'annule ni l'appel ni la Task. Une
réflexion longue reste donc autorisée. Les pauses et attentes déclarées ne déclenchent pas
cette alerte ; une connexion indisponible est signalée séparément.

Pour une Task exécutée par le harnais interne, le bouton **Interrompre l’appel et reprendre**
permet aux utilisateurs autorisés à modifier la Task de demander une reprise guidée.
Le moteur ferme l’appel de génération courant puis poursuit la même Task avec ses résultats
d’outils et son budget conservés. Il refuse l’interruption si un outil est en cours ou si son
effet est incertain. La demande, son acceptation ou son refus apparaissent dans le suivi ;
une réponse tardive après un changement de Task ou de tentative ne modifie pas le suivi courant.

Si l'agent interne répète son raisonnement sans progresser, Galaris interrompt cette
génération et lui demande de changer d'approche, en conservant les résultats d'outils acquis.
La récupération est bornée : une boucle persistante laisse la Task inachevée avec un diagnostic.
La relance d'un plan en échec repart de sa première étape inachevée, y compris dans les groupes
imbriqués, sans rejouer les éléments réussis. Un document qui demande encore des contrôles ou
une mise à jour du suivi reste dans l'inventaire de travail.

Le planner découpe uniquement un objectif qui exige plusieurs blocs de travail coordonnés.
Chaque feuille du plan est une vraie tâche. Une étape n’est pas censée « réfléchir » ou
« rédiger la réponse finale » : elle doit produire une partie vérifiable du résultat.

Le découpage privilégié répète le même traitement complet sur des éléments indépendants :
un fichier à traiter donne une tâche qui le lit, le transforme, le vérifie et enregistre son
résultat. Une tâche unique, même complexe, reste entière : ses phases de recherche,
construction et validation ne deviennent pas des sous-tâches. Cela vaut aussi avec `@plan`,
qui choisit l'orchestration sans remplacer le travail demandé par la rédaction d'un plan.

Pour un traitement répété sur de nombreux documents ou enregistrements, le planner peut créer
une collection : Galaris identifie les éléments depuis l'inventaire, puis crée une tâche par
élément, par vagues. « Un workspace après l'autre » conserve cet ordre tout en séparant les
documents. Le total de progression se précise à la découverte de chaque collection. En cas
d'erreur, **Réessayer** sur le plan reprend le travail en échec et conserve les éléments réussis.
Les plans déjà enregistrés ne sont pas redécoupés automatiquement.

Si vous avez demandé un bilan à enregistrer même en cas d’échec, une clôture indépendante
peut le produire après les travaux échoués. Les autres étapes dépendantes sont écartées.
Un bilan réussi conserve l’erreur du plan ; un réessai manuel reprend le travail inachevé
et actualise ce bilan, en préservant les autres réussites.

Pour les harnais distants, **Réessayer** conserve l'identité de l'exécution et ses reçus ;
il vérifie l'exécution existante avant de poursuivre. Si son autorisation a disparu,
a été révoquée ou a expiré, la reprise reste refusée avec la cause correspondante.
Créer une nouvelle Task constitue une nouvelle exécution, pas une récupération du checkpoint.

Un petit lot mécanique d'au plus cinq éléments connus peut rester une seule tâche, par
exemple renommer trois documents avec les noms fournis. Lire, transformer et vérifier chaque
document reste un traitement par document, même pour un petit lot. Plusieurs cibles ne
suffisent pas, à elles seules, à déclencher le planner.


Ces aides sont activées par driver. Dans la configuration actuelle :

| Driver | Planner |
|---|---:|
| Interne (Pydantic AI) | oui |
| Hermès | non |

Hermès conserve ainsi ses capacités propres sans être enfermé dans un second harnais.

## Quand Galaris pose une question

Dans les **Autorisations des fonctions MCP**, **Global (tous)** propose **Activé**,
**Sur demande** ou **Désactivé** sous forme de boutons accolés : coche verte, point
d’interrogation jaune et croix rouge. Le bouton sélectionné apparaît sur fond plein ;
chaque bouton décrit son effet dans une infobulle. Sans règle globale enregistrée, cette colonne affiche
la valeur définie par le logiciel lorsque la connexion en hérite. Sélectionner un bouton
dans **Cette connexion** définit une exception : les boutons globaux de cette ligne
apparaissent tous non cochés et restent cliquables. Cliquer sur un bouton **Global (tous)**
enregistre cette règle et remet cette connexion en héritage ; ses boutons locaux deviennent
tous non cochés. Les exceptions des autres connexions sont conservées.
La sélection change immédiatement et les boutons restent cliquables pendant la sauvegarde.
Les choix successifs d’une même capacité sont enregistrés dans l’ordre. En cas d’échec,
un message vous prévient et Galaris recharge les règles enregistrées.

Pour la navigation web, **Sites publics autorisés** est le choix initial des nouvelles installations du Navigateur,
globalement ou pour un agent : les nouveaux sites publics ne
déclenchent alors plus de demandes réseau par site. Les instances existantes gardent leur
comportement ; **Autorisation par site** reste disponible.
Localhost et les réseaux privés restent bloqués par défaut ; les filtres et refus explicites
restent actifs. Voir [l’administration du Navigateur](../admin/tool-administration.md).

Si une connexion Mail exige une validation humaine, son responsable désigné reçoit une demande
privée dans le Chat pour chaque mail préparé. Vérifiez les destinataires, l’objet, l’aperçu du
contenu et la liste des pièces jointes, puis choisissez **Autoriser l’envoi** ou **Refuser**.
Le **Journal des mails** présente le contenu complet et le résultat de l’envoi ; il permet aussi
de décider. L’accord concerne uniquement ce mail. Sans réponse, il reste non envoyé ; après
sept jours, utilisez le journal car la demande du Chat a expiré.

Une information essentielle peut manquer : destinataire, fichier, période, autorisation ou
choix irréversible. L’agent doit alors poser une question courte et attendre au lieu de
deviner. Une question est un résultat valide du tour en cours ; répondez dans la même
conversation pour continuer.

Deux attentes doivent être distinguées. Pour choisir l’organisation d’une mission ambiguë,
une question impossible à transmettre ou expirée sans réponse termine la Task en erreur,
sans démarrer le travail. Un réessai explicite repasse par le routage. Pour le cadrage d’un
plan déjà choisi, le Planner peut demander une unique série de précisions et reprendre à
l’expiration avec des hypothèses explicites. Aucune expiration ne donne une autorisation
d’action sensible.

Si une étape signale qu'un document est hors du périmètre autorisé, changer d'outil ou
réessayer ne donne pas le droit de le modifier. Pour autoriser cette modification, précisez
l'URI exacte du document dans un amendement de la tâche racine. L'agent reçoit un diagnostic
distinct d'une erreur d'arguments ; ce refus ne crée pas automatiquement une demande
d'autorisation ni une mise en attente.

## Lire l’état d’une tâche

Le texte du Chat continue d'apparaître pendant la génération. La supervision des appels
LLM se rafraîchit au plus quatre fois par seconde ; une mise à jour manquée est récupérée
automatiquement. La réponse finale et les coûts conservés restent complets.

| État affiché | Signification pratique |
|---|---|
| Création / dispatch | la demande est en cours de routage |
| Exécution | l’agent travaille ou appelle des outils |
| Plan | Galaris crée ou avance dans les étapes |
| En pause | la tâche attend une réponse, une étape fille ou une reprise |
| Succès | le workflow s’est terminé sans erreur déclarée |
| Erreur | la tentative a échoué ou a été interrompue après les reprises autorisées |

Les onglets **Conversations textuelles** et **Appels téléphoniques** utilisent leurs propres états.
« À jour » signifie que tous les messages connus ont été traités ; « En attente » qu’un nouveau
round peut être réclamé ; « En cours » qu’un contrôleur répond actuellement.

Un succès technique ne garantit pas que le contenu est parfait. Pour une action importante,
vérifiez le livrable, la destination et les outils appelés.

La pause conserve le travail ; la reprise poursuit selon les preuves disponibles.
Un remplacement explicite attend l’arrêt confirmé de l’ancienne Task, de ses descendants
et des processus associés. Une demande d’arrêt reçue, une erreur réseau ou une fin logique
ne prouvent pas toujours l’arrêt distant. Les Goals et attentes non pris en charge restent
refusés par ce parcours ; les autres travaux indépendants sont conservés.

## Écrire une demande fiable

Une bonne demande contient quatre éléments :

1. le résultat final : « produire un CSV », « répondre à Paul », « corriger le document » ;
2. les entrées exactes : période, fichiers, URL, identifiants et destinataires ;
3. les contraintes : langue, format, limites, éléments à ne pas modifier ;
4. le contrôle attendu : totaux vérifiés, fichier partagé, réponse confirmée.

Préférez :

> Analyse les factures de juin dans `nextcloud://compta/2026-06/`, crée `synthese.csv` avec les colonnes
> fournisseur, HT, TVA et TTC, vérifie que HT + TVA = TTC, puis partage le fichier dans le
> salon Comptabilité. Ne modifie pas les fichiers sources.

À :

> Occupe-toi des factures.

## En cas de résultat surprenant

- Vérifiez que le bon agent et le bon salon ont été utilisés.
- Ouvrez le détail de la tâche et regardez les outils réellement appelés.
- Reformulez la cible exacte plutôt que d’ajouter « fais attention ».
- Si l’action peut avoir un effet de bord, demandez une vérification avant répétition.
- Transmettez à l’administrateur l’identifiant de tâche visible dans l’interface ; il permet
  de retrouver les traces sans partager vos secrets.

Ne recopiez jamais une clé API ou un mot de passe dans une conversation. Les secrets se
configurent dans l’administration ou dans l’environnement prévu à cet effet.
