<p align="right"><strong>Français</strong> · <a href="../../en/user/tasks.md">English</a></p>

# Confier et suivre une tâche

Les onglets d’**Activités** sont indépendants : les tâches utilisent `TASK_ACCESS`/`TASK_EDIT`,
les conversations texte `CONVERSATION_ACCESS`/`CONVERSATION_CONTROL`, la voix
`VOICE_HISTORY_ACCESS`/`VOICE_HISTORY_CONTROL`, les appels LLM `LLM_CALL_ACCESS`/`LLM_CALL_CONTROL`
et les processus `PROCESS_READ`/`PROCESS_ADMIN`. L’écran ouvre un onglet autorisé et adapte
ses commandes au rôle actif. Consulter une activité ne donne pas accès aux autres historiques.

Un lien vers l'onglet Tâches ou une tâche conserve sa cible pendant la vérification de vos
droits. Le contenu s'ouvre lorsque l'accès est confirmé ; les onglets non autorisés restent absents.

Une tâche conserve un travail durable, son état et son résultat. Ce guide explique le choix
de méthode, les jalons, les plans, les questions et la reprise. Pour créer votre première
demande, suivre le [guide utilisateur](README.md) ; pour trouver les commandes, consulter
les [menus et parcours](navigation.md).

## Consulter les coûts enregistrés

Dans le détail d'une tâche, ouvrir **Détails**, puis **Bilan des coûts** dans la zone
de consommation. Le bilan charge à la demande les appels de cette tâche et de ses
descendants autorisés, une seule fois par appel physique, avec une ventilation par usage.
Il conserve les échecs et reprises ; les totaux des tâches parentes ne sont pas additionnés.

Les montants déclarés, estimés et inconnus sont distingués. **—** indique une information
absente, pas un coût nul. Sur abonnement, la facturation par appel est nulle ; la valeur
d'inférence reste séparée. Les nouveaux montants survivent à la suppression des traces
détaillées. Les anciennes données déjà supprimées et les opérations non tracées ne sont
pas reconstituées. **Actualiser** relit les preuves ; changer de tâche efface l'ancien bilan.
Un statut réussi ne suffit pas à prouver un résultat métier, donc aucun coût par réussite
métier n'est déduit de ce statut.

## Mémoire utile au travail

Dream peut retenir des faits durables issus des tâches réussies, de leurs sous-tâches
et des cycles de Goal. Les instructions préparées par un agent restent attribuées
à l'IA ; elles ne constituent pas une déclaration personnelle de l'utilisateur.
Une exclusion de capture sur une tâche s'applique aussi à ses descendants.

Les souvenirs sont privés à chaque agent. Les Documents et leurs résumés partagés,
les Datasets et les définitions de Process conservent leurs propres droits et contenus.
Les procédures apprises relèvent des Skills. Une ressemblance entre deux souvenirs
ne suffit pas à supprimer un complément ; un désaccord explicite conserve les deux faits.

Le contexte automatique réserve jusqu'à la moitié des places aux souvenirs ordinaires
lorsqu'un calendrier chargé remplit les autres places. Des résultats proches ne prouvent pas que
l'agent connaît la réponse : il doit vérifier les sources et signaler les informations
manquantes. Un conflit rappelé porte ses sources et dates ; le fait le plus récent
n'est pas automatiquement considéré comme vrai.

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

Dans le Chat natif, `@task` placé n’importe où dans le message crée immédiatement une tâche durable
avec le texte restant comme objectif, sans appel au LLM de conversation. Pour le harnais interne
Galaris, `@plan` suffit lui aussi à créer la tâche et à forcer sa planification, sans ajouter `@task`.
Ces directives se combinent, sans ordre imposé, avec `@standard` et `@high`. `@approve` ne donne
aucun accord. Les actions sensibles utilisent [les autorisations](../admin/tool-administration.md). Le Chat
conserve le round et publie aussitôt une confirmation déterministe
dans la room ; le résultat de la tâche y sera publié à sa terminaison. Le bouton `@` du composeur
affiche uniquement les directives compatibles avec le driver de l’agent sélectionné.

Le résultat revient automatiquement dans la discussion, même si un outil ou une pièce jointe
a échoué. Si l’agent a déjà envoyé ce même résultat dans cette discussion, Galaris ne le renvoie
pas. Une pièce jointe indisponible n’empêche pas la publication du texte.

Après un accord humain sur une action d'un harnais géré, la même tâche reprend le même
appel lorsque son exécuteur a repris la main. L'accord reste enregistré pendant cette
attente ; ne créez pas une autre tâche pour contourner un refus de reprise et ne répétez
pas l'action. Une pause manuelle reste prioritaire.

## Modifier une consigne pendant les contributions

Dans la même discussion, précisez ce qui change et ce qui reste valable, par exemple :
« Le budget passe à 6 800 EUR ; les engagements restent de 6 300 EUR. »
Lorsque l'agent accepte cette modification pour la tâche en cours, elle peut rester en attente
pendant que ses collègues terminent leurs contributions. Le responsable doit ensuite reprendre
la synthèse avec la nouvelle contrainte et conserver les informations toujours valables.
Une confirmation de mise en attente ne signifie pas que le livrable est déjà corrigé.
Une pause manuelle reste prioritaire ; une tâche terminée n'est pas rouverte par cette voie.

## Ce qui se passe après l’envoi

Une demande qui poursuit un travail peut réutiliser son document de suivi sans recopier
son URI dans le dernier message. Galaris résout cette référence depuis le contexte et
conserve la justification de sa mise à jour. Cela n'autorise pas à modifier les autres
documents cités dans la discussion ; leurs droits d'accès restent applicables.

1. La demande créée dans cet écran devient une tâche durable.
2. Le Dispatcher choisit la route, l’effort et l’organisation du travail.
3. Une précision manquante peut suspendre la demande ; le planner prépare les travaux décomposables.
4. Le driver exécute l’agent avec ses outils autorisés.
5. Galaris enregistre la trace et le résultat, puis reprend les parents éventuels.

Les conversations texte et voix suivent leur propre contrôleur et leur exécuteur configuré. Elles
ne passent pas par le Dispatcher de tâches ; lorsqu’elles ont besoin d’un travail durable, elles
créent une tâche explicitement liée.

En mode voix native, vous pouvez reprendre la parole pendant une consultation lente.
L'agent coupe sa réponse et ne reprend pas automatiquement l'ancienne phrase lorsque le
résultat arrive. Les actions déjà effectuées restent enregistrées.

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
Elle réunit les tâches et les exécutions de processus internes et externes, avec leur état
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
Une mission longue ou complexe peut conserver un suivi par jalons dans la même tâche :
préparation, critères d’acceptation, résultats observés, ressources et prochaine action.
Ce suivi aide à reprendre le travail sans perdre son contexte ni répéter des effets déjà acquis.
Il ne crée pas de sous-tâches pour chaque phase d’un même livrable.

Dans une conversation, une relance comme « et sa limite ? » peut reprendre le sujet humain
récent pour rechercher les souvenirs, même si la recherche vectorielle est indisponible.
« Autre sujet » écarte cet ancien sujet de la recherche automatique. Les droits et la portée
du contact continuent de s'appliquer ; un sujet d'historique ne constitue pas une preuve.

Le détail de tâche permet d’inspecter l’activité, les outils et les résultats ; `task_get`
expose le suivi par jalons enregistré. L’exécuteur peut le mettre à jour
avec `task_work_update`, sur sa tâche active, avec contrôle de révision. Jusqu’à vingt jalons
sont conservés ; un jalon déclaré terminé ne remplace pas la preuve du résultat ou de sa livraison.
Le suivi possède sa propre révision : les sauvegardes d’exécution ne bloquent pas ses mises à jour.
Si un jalon reste explicitement bloqué à la clôture, la tâche termine en erreur et conserve
son bilan partiel, sans réessai automatique. Les attentes durables existantes restent prioritaires.
Une tâche terminée ne peut plus être amendée : pour autoriser les cibles encore hors périmètre,
formulez une nouvelle demande explicite en référençant le travail déjà réalisé.

Dans les étapes de réflexion, ouvrir un appel d’outil affiche son nom, ses arguments et son
retour, avec son état de réussite ou d’échec. Ces détails restent disponibles pendant le suivi
en direct et après reconnexion. Les aperçus volumineux sont tronqués explicitement et les clés
de secrets sont masquées ; les anciens suivis qui ne contenaient pas ces détails restent incomplets.

Pendant une réflexion longue, les sauvegardes intermédiaires sont espacées pour laisser
l'exécution avancer. Les résultats d'outils, erreurs et fins de blocs restent enregistrés
immédiatement ; rouvrir la tâche retrouve le dernier suivi sauvegardé.

Si le périmètre ou la profondeur attendue change sensiblement le travail, Galaris peut poser
une question avant de commencer. Répondez dans la conversation liée à la demande. Une inconnue
technique que l’agent peut résoudre par inspection autorisée relève de sa préparation.

## Planner : décomposer un travail coordonné

Dans le suivi détaillé de tâche et le panneau de tâches de la discussion, une alerte apparaît
après deux minutes sans activité reçue : réflexion, texte, génération d'arguments ou résultat
d'outil. Elle disparaît dès que l'activité reprend et n'annule ni l'appel ni la tâche. Une
réflexion longue reste donc autorisée. Les pauses et attentes déclarées ne déclenchent pas
cette alerte ; une connexion indisponible est signalée séparément.

Pour une tâche exécutée par le harnais interne, le bouton **Interrompre l’appel et reprendre**
permet aux utilisateurs autorisés à modifier la tâche de demander une reprise guidée.
Le moteur ferme l’appel de génération courant puis poursuit la même tâche avec ses résultats
d’outils et son budget conservés. Il refuse l’interruption si un outil est en cours ou si son
effet est incertain. La demande, son acceptation ou son refus apparaissent dans le suivi ;
une réponse tardive après un changement de tâche ou de tentative ne modifie pas le suivi courant.

Si l'agent interne répète son raisonnement sans progresser, Galaris interrompt cette
génération et lui demande de changer d'approche, en conservant les résultats d'outils acquis.
La récupération est bornée : une boucle persistante laisse la tâche inachevée avec un diagnostic.
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

Pour les harnais réseau gérés, **Réessayer** lance une nouvelle inférence avec les mêmes
paramètres de tâche. La tâche et ses tentatives précédentes restent disponibles ; aucune
modale de nouvelle tâche n'est nécessaire, même si l'ancien runtime n'a plus d'état reprenable.
Galaris retire l'ancienne opération et attribue une nouvelle identité et une nouvelle autorité
runtime. Les reçus d'outils précédents restent disponibles pour vérifier les effets déjà produits.
La récupération automatique après interruption observe toujours l'opération existante.

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

Pour créer puis compléter un document, l’agent peut demander un accord de création et
confier la suite à une tâche de fond sur le même document. Si l’écriture est **Sur demande**,
un second accord porte sur la modification préparée. Vous pouvez fermer puis rouvrir le Chat
pendant l’attente. Refuser la création ne crée aucun document ; refuser la modification
conserve le contenu déjà créé. Un accord ponctuel ne change pas la règle des appels suivants.

Si une connexion Mail exige une validation humaine, son responsable désigné reçoit une demande
privée dans le Chat pour chaque mail préparé. Vérifiez les destinataires, l’objet, l’aperçu du
contenu et la liste des pièces jointes, puis autorisez ou refusez l'action.
Le **Journal des mails** présente le contenu complet et le résultat de l’envoi ; il permet aussi
de répondre à la même autorisation. La décision prise à un endroit s'applique aux deux.
L’accord concerne uniquement ce mail et permet à la tâche de reprendre l'appel préparé :
« accord enregistré » ne signifie pas encore « envoyé ». Sans réponse, le mail reste non envoyé ;
une autorisation expirée exige une nouvelle demande. Les anciennes validations Mail encore
en attente restent accessibles dans le journal.

Après acceptation du mail par SMTP, Galaris en conserve une copie dans le dossier « Envoyés »
configuré ou annoncé par votre serveur. Si cette copie échoue, le reçu le précise sans
annuler l'envoi réel. Une reprise avec la même clé et le même contenu répare la copie
sans envoyer un second mail.

Le **Journal des mails** possède les onglets **Envoi** et **Réception**. Réception conserve
les en-têtes, l’expéditeur, l’agent destinataire, les dates d’accord, de lecture et d’admission
en tâche, ainsi que les refus, blocages et erreurs. Avant l’accord, le corps et les pièces
jointes ne sont pas téléchargés. Après lecture, le journal conserve une page de contenu
de 50 000 caractères maximum et les métadonnées des pièces jointes ; un éventuel abrègement
est indiqué. Le mail complet reste disponible par pages dans la boîte source.

Par défaut, une adresse mail présente dans les **Contacts** de cet agent autorise directement
le traitement. Un nom affiché, une autre adresse ou le carnet d’un autre agent ne suffit pas.
Un expéditeur inconnu déclenche une autorisation commune auprès du responsable de l’agent,
dans le Chat privé et dans **Permissions** ; elle peut aussi être examinée depuis Réception.
Un refus ou une expiration ne déclenche aucune lecture ni tâche. L’accord reprend automatiquement
la réception, sans créer de tâche en double. Les contacts sont projetés par Messenger après admission.

La fonction **mail_process** utilise les mêmes règles globales et locales que les autres fonctions :
**Actif** permet de traiter tous les expéditeurs ; **Sur demande** impose un accord pour chaque mail,
y compris ceux des contacts ; **Bloqué** interdit le traitement. Sans règle explicite, les contacts
sont admis et les inconnus demandent un accord. **Toujours traiter les mails** active cette fonction
uniquement pour la connexion de cet agent. **Toujours interdire le traitement des mails** la
bloque pour tous les expéditeurs de cette connexion, sans lire les mails suivants ni créer
de tâche. Modifiez ou retirez l’une ou l’autre décision dans le tableau de bord **Permissions** de l’agent.
Les autorisations d’envoi restent indépendantes du droit de lire et traiter le mail.
Seuls les mails de la boîte de réception (`INBOX`) peuvent être traités, lus ou admis en tâche,
y compris leurs pièces jointes. Une recherche dans Envoyés, Corbeille, Archives ou un sous-dossier
peut retourner des en-têtes, mais ne crée aucune réception ni demande de traitement.
Les anciennes entrées hors INBOX ne peuvent plus reprendre leur traitement. Le journal couvre
les nouveaux mails observés par l’écoute et les mails INBOX retrouvés par les outils ; le démarrage
conserve le curseur existant et ne relance pas les anciens mails de la boîte.

Une information essentielle peut manquer : destinataire, fichier, période, autorisation ou
choix irréversible. L’agent doit alors poser une question courte et attendre au lieu de
deviner. Une question est un résultat valide du tour en cours ; répondez dans la même
conversation pour continuer.

Deux attentes doivent être distinguées. Pour choisir l’organisation d’une mission ambiguë,
une question impossible à transmettre ou expirée sans réponse termine la tâche en erreur,
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
Un remplacement explicite attend l’arrêt confirmé de l’ancienne tâche, de ses descendants
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
