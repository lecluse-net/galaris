<p align="right"><strong>Français</strong> · <a href="../../en/user/lab-ai.md">English</a></p>

# Utiliser le Lab IA

Pour évaluer le découpage du Planner, le corpus public `planner-boundaries` propose 24 cas
synthétiques : traitement complet par fichier, collections ordonnées et reprises, tâches
uniques complexes à conserver entières, petits lots mécaniques et demandes ambiguës.
Après import avec `scripts/import_lab_reference.py --corpus planner-boundaries --install`
dans le conteneur backend, ouvrir **Lab → Planner**, choisir le jeu et lancer plusieurs
répétitions avec le même candidat et le même juge. Examiner les plans effectivement produits,
notamment les plans vides, la fragmentation d'une tâche unique et les boucles cachées dans
une feuille, en plus des scores. Le Lab applique son contrat serveur courant aux prompts
de base comparés : un ancien prompt ne reproduit pas à lui seul un ancien runtime.
Un plan sans brief ou sans étapes, ou qui mélange plan et clarification, constitue un
échec critique du Lab, même si le juge lui attribue un bon score.
Le barème Planner v4 distingue les choix du modèle des politiques d'artefact et de livraison
ajoutées par le serveur. Leur présence dans le plan évalué n'est pas une erreur de génération ;
`file_copy` implique notamment les valeurs techniques `final` et `required`.
Les campagnes conservent le barème figé à leur création ; les anciens scores ne sont pas réécrits.

Chaque lab présente le traitement testé, **une seule variable métier** et le résultat à
évaluer. Les réglages communs appartiennent au jeu de tests. Un item contient
la valeur de la variable, son contexte et le résultat attendu, avec un nom et sa provenance éventuelle.

| Lab | Variable de l’item | Résultat évalué |
|---|---|---|
| Dispatcher | Demande | Route, effort, action, langue et justification |
| Planner | Objectif | Plan ou clarification |
| Détection des sujets | Échange ordonné | Sujet de chaque message |
| Extraction mémoire | Échange ou compte-rendu de tâche | CREATE, LINK ou IGNORE |
| Apprentissage | Issue d’exécution | Leçons étayées |
| Suivi d’objectif | Résultat du cycle | Décision et suivi durable |
| Exécuteur de tâches | Demande | Réponse et appels d’outils |
| Exécuteur conversationnel | Sollicitation courante | Réponse et actions |
| Exécuteur vocal | Sollicitation transcrite | Réponse orale et actions |
| Analyse de tâches | Dossier d’exécution | Diagnostic structuré |

Une séquence de messages Topics constitue un item. Son historique et son catalogue ne
sont pas des tests supplémentaires. Le lab vocal travaille sur du texte transcrit ;
il ne mesure pas la reconnaissance ou la synthèse audio.

## Confier les Labs à un agent

Activez sa connexion **Lab Galaris**, puis attribuez-lui la compétence système **Galaris Lab**
(`galaris-lab`) dans les autorisations des compétences. La compétence est déjà autorisée pour
l’agent **Galaris** créé à l’installation. Pour les autres agents, elle reste désactivée
par défaut ; la connexion Lab reste à activer explicitement dans tous les cas.
L’agent dispose alors des outils pour découvrir les dix labs, préparer et
copier leurs jeux, modifier les prompts expérimentaux, lancer, suivre, arrêter, reprendre,
rejuger et comparer les benchmarks, puis déposer ses propres évaluations.

Pour capturer des tâches, messages, conversations, tours vocaux ou appels LLM réels,
activez également **Galaris Admin** avec ses fonctions d'inspection des exécutions.
L'accès à la seule documentation produit ne suffit pas. Les diagnostics de tâches
nécessitent ce même accès supplémentaire.

Les jeux et résultats sont ceux du Lab habituel. Les générations synthétiques restent
des brouillons à vérifier. Les opérations longues renvoient une référence durable ;
l'agent consulte leur résultat avec `lab_operation_get` sans les relancer. Les évaluations d'agents sont
identifiées par leur auteur et leur campagne, séparément des revues humaines et du juge.

Donnez à l'agent une question expérimentale, un budget et une condition d'arrêt.
Les réglages modifiés restent propres aux expériences. Ce mandat ne modifie pas les
prompts ou modèles de production. Une connexion ou une fonction révoquée bloque le
nouveau travail ; une inférence déjà partie peut encore être facturée.

## Créer le jeu

1. Ouvrez le lab et cliquez sur **Nouveau jeu**.
2. Dans **Paramètres du jeu**, renseignez les paramètres communs et les consignes.
   Les champs sont regroupés par thème. La recherche retrouve un paramètre par son libellé ;
   **Tout déplier** et **Tout replier** contrôlent les rubriques. Les listes et objets affichent
   un résumé : ouvrez leur ligne pour les éditer. La barre **Enregistrer** reste accessible
   en bas du formulaire et indique les modifications en attente.
   Le contrat de l’algorithme précise les réglages fixes, la sortie et la rubrique.
3. Enregistrez. Les items et les benchmarks utilisent les valeurs enregistrées.

Les champs dépendent réellement du traitement : catalogue et fenêtre pour Topics,
corpus et classement pour mémoire, limites de plan pour
Planner, contexte et réponses simulées des outils pour les exécuteurs.

## Générer un jeu synthétique

Dans chacun des dix labs, **Générer un jeu synthétique** crée un nouveau jeu adapté au
traitement. Choisissez son nom, le modèle générateur, la langue, 1 à 20 cas et les catégories
à couvrir. Décrivez le domaine, les situations et les contraintes souhaitées : le formulaire
précise les points testables propres au lab. Prévoyez au moins un cas par catégorie.

Le modèle propose les paramètres communs, les entrées, leur contexte et les références.
Si un jeu est sélectionné, **Reprendre le contexte du jeu** est activé par défaut : le nouveau
jeu conserve ses paramètres, ses corpus et outils, sa configuration d’algorithme et ses consignes.
Les cas existants ne sont pas copiés. Enregistrez d’abord les modifications du jeu ; une révision
dépassée est refusée. Vous pouvez désactiver cette option pour créer un environnement fictif
distinct. La génération conserve la référence et la révision du contexte utilisé.

Les situations suivent les usages de chaque lab : échanges avec continuité et reprises pour
les sujets, faits durables et corpus pour la mémoire, dépendances et livrables pour le planner,
preuves d’exécution pour l’apprentissage et le diagnostic, cycles d’un même objectif pour son
suivi, historique et délégation pour la conversation, transcriptions et interruptions pour la
voix. Les références doivent respecter les outils disponibles et leurs réponses simulées.

La génération utilise les contrats et la rubrique du lab, sans importer de conversations ou
de tâches réelles. Les appels d’outils des exécuteurs sont simulés. Les contrats et la cohérence
des références sont contrôlés avant l’enregistrement du jeu complet ; un échec ne crée pas de
jeu partiel. Les jeux existants sont conservés.

Tous les cas arrivent en **brouillon**. Relisez les paramètres communs, puis ouvrez chaque cas,
corrigez-le si nécessaire et enregistrez-le pour le rendre utilisable. Une référence générée
reste une proposition à examiner. La provenance conserve le modèle, les consignes de génération
et le coût. Vous pouvez fermer et rouvrir la fenêtre pendant la génération ; un changement de
lab ne déplace pas le résultat dans le nouveau lab. En cas de délai dépassé, réduisez le nombre
de cas ou choisissez un autre modèle.

## Préparer les items

Dans **Items**, créez un item ou capturez une source réelle. L’éditeur sépare :

- la variable nommée selon le lab ;
- le **contexte de l’item**, dont l’historique antérieur propre à ce message ;
- le résultat attendu et, pour une capture, sa provenance.

Chaque item conserve son propre historique, y compris les clarifications, les médias des
échanges antérieurs et les métadonnées des messages lorsque le traitement les utilise.
Le suivi antérieur d’un objectif appartient également à son item. Ces données ne se règlent
pas dans les paramètres du jeu. Elles accompagnent la variable lors de la prévisualisation,
de la proposition d’attendu, de l’exécution et du jugement.

Les valeurs complexes disposent d’un éditeur JSON. **Prévisualiser les entrées**
montre l’entrée résolue et les consignes. Corrigez les champs incomplets avant
d’enregistrer. Un brouillon n’entre pas dans un benchmark.

**Proposer un attendu à revoir** appelle le modèle du Lab et ne valide pas sa réponse
à votre place. Le candidat ne reçoit jamais l’attendu. Le juge l’utilise comme exemple
non normatif : plusieurs sorties différentes peuvent être valides.

Si les paramètres d’une source diffèrent de ceux du jeu choisi, une confirmation affiche
les écarts avant tout ajout. Annuler n’ajoute aucun item. Confirmer utilise les paramètres
du jeu et crée un brouillon dont l’attendu doit être revu. Les paramètres de la source
restent dans la provenance, sans être utilisés comme réglages d’item.
L’historique de la source est conservé dans le contexte de l’item ; sa différence avec un
autre item du jeu ne demande aucune confirmation.

Une capture conserve la preuve originale. Si un prompt textuel mélange objectif et
contexte sans séparation fiable, le cas reste à compléter ; le texte complet n’est
pas rebaptisé artificiellement « variable ». Les captures sans transcription vocale
restent également des brouillons.

## Exécuter et juger

Choisissez séparément le **candidat** et le **juge**, puis lancez le benchmark.
Les items prêts sont figés avec un unique ensemble de paramètres et réglages du jeu.

1. La première passe exécute tous les items et conserve les résultats avec leurs
   contrôles objectifs.
2. La seconde passe juge les sorties conservées, avec les entrées, les contraintes
   et la rubrique du traitement.

Le détail montre deux progressions, les coûts distincts, les entrées et références,
les sorties, les contrôles et les verdicts. L’analyse Markdown synthétise les
résultats sans changer les scores.

**Terminé** désigne une exécution techniquement achevée, pas la réussite de tous les
items. La couverture indique combien ont réellement été jugés. Une panne du juge
laisse la note absente ; la similarité ne la remplace pas. Une violation critique
interdit le verdict de réussite même si certaines dimensions obtiennent une bonne note.

L’annulation conserve ce qui a déjà été publié. **Reprendre les items restants**
continue un benchmark annulé avec ses réglages figés. **Rejuger les sorties conservées**
crée une campagne indépendante et ne rappelle pas le candidat. Les campagnes
précédentes restent consultables. Relancer depuis le jeu crée une nouvelle exécution.

## Comparer avant et après

Dans **Benchmarks**, ouvrez **Avant / après**, disponible dans les dix labs avec le droit
de lecture. Choisissez le jeu et l'évaluation de chaque côté, puis le changement étudié :
modèle, prompt ou paramètres. Les sélecteurs proposent les 500 évaluations les plus récentes
de chaque jeu. Cliquez sur **Comparer** : les entrées, références et répétitions identiques
sont appariées, même entre deux jeux distincts.

Les réponses sont côte à côte sur ordinateur et empilées sur mobile, avec leurs scores,
verdicts, coûts, durées et défaillances critiques. Dépliez les contrôles et jugements pour
lire les preuves. Un score nul reste zéro ; un jugement absent reste absent. Les écarts
affichent **après moins avant**, sans garantie statistique ni décision automatique de promotion.
Les changements de corpus, de juge ou d'autres réglages incompatibles sont signalés ; aucun
bilan de progression n'est alors calculé. Les évaluations incomplètes portent un avertissement.
La comparabilité porte sur les deux évaluations complètes : un appariement ambigu est
signalé dès la première page, même si le cas concerné se trouve plus loin. À résultats et
jugements identiques, changer de page, de taille de page ou inverser les évaluations ne
change pas ce blocage. Une ambiguïté d'un côté ou de l'autre empêche de choisir une réponse.

Le bilan global décrit les deux évaluations complètes : cas distincts, observations incluant
les répétitions, appariements, résultats manquants avant/après, ambiguïtés, jugements absents
et erreurs. Les hausses, baisses et égalités ne comptent que les paires jugées, notées et sans
erreur ; elles restent absentes si les configurations ne sont pas comparables. Une répétition
ne constitue pas un cas indépendant et ce bilan descriptif ne prouve pas un gain statistique.
Les compteurs de page restent séparés, avec 50 cas par défaut et les choix 10, 20, 50, 100 ou 500.
Un appariement ambigu ne choisit pas arbitrairement une réponse.
La liste part des cas exécutés avant : utilisez **Inverser avant et après**, puis **Comparer**
pour examiner les cas présents uniquement après. Relancez la comparaison après un nouveau
résultat ou jugement ; elle ne se rafraîchit pas automatiquement. La lecture ne lance aucune
inférence et ne modifie ni les évaluations ni les réglages de production.

La section **Régressions à examiner** compte les paires où apparaît un échec critique
(jugement ou contrôle objectif) et les passages réussi → échoué. Elle affiche aussi les
baisses, hausses et écarts moyens par critère commun. Les boutons retrouvent les cas concernés
sur tout le run avant pagination ; **Tous les cas** retire le filtre sans changer le bilan
global. Une apparition critique signifie aucune défaillance avant, au moins une après ;
les explications libres ne servent pas d'identifiants de défaillances. Des jugements sans
version de grille comparable restent inconnus, même lorsqu'ils portent un score.

**Délai, coût et qualité** présente les médianes et les effectifs appariés. La première sortie
est le premier texte non vide ou appel d'outil observé par le Lab, sans file d'attente ni juge ;
ce n'est pas une confirmation de réussite. Les mesures absentes restent « — ». Le coût est
celui du candidat enregistré. Le [protocole FR/EN](../dev/lab-reference-corpus.md)
fournit quatre parcours synthétiques pour préparer une comparaison reproductible.

**Bilan des coûts** affiche les montants enregistrés pour toutes les observations du
run, y compris erreurs et reprises, et les coûts du juge séparément, rejugements inclus.
Les nouvelles preuves distinguent coûts déclarés, estimés et inconnus ; elles survivent
à la suppression des traces détaillées. Les appels payés d'un worker qui a perdu son
bail sont rapprochés sans compter deux fois les appels déjà publiés.
Le coût candidat par réussite reste « — » si les exécutions, vérifications ou coûts
sont incomplets, ou sans réussite vérifiée. La réussite est celle du benchmark selon
ses contrôles et son juge ; elle ne prouve pas un effet métier réel. Les médianes et
écarts de coût excluent également les montants sans provenance exploitable. Aucun coût
historique n'est recalculé avec les tarifs courants ; l'analyse Markdown reste séparée.

## Tâches

L’analyse interactive d’une tâche reste disponible : sélectionnez la tâche, ajoutez
éventuellement un contexte humain, puis lancez son diagnostic. Ce parcours relit les
preuves canoniques et ne rejoue pas la tâche.

Dans la même page, **Tester et juger les diagnostics** ouvre le parcours par jeu.
Le menu **Ajouter un cas au Lab** d’une tâche propose aussi le diagnostic.

## Interpréter les résultats

Comparez les mêmes items, paramètres et rubriques, avec une couverture suffisante.
Les empreintes du corpus, du contexte et des modèles sont conservées dans les
snapshots. Le juge reste un évaluateur automatique à étalonner sur des exemples
revus. Une simulation d’outil ne prouve pas un effet réel en production.

Voir le [contrat d’architecture](../architecture/ai-lab-evaluation.md).

## Lire, répéter et revoir

Les listes d'items affichent le texte sans balises HTML, y compris dans les messages
imbriqués. Les entrées originales restent intactes dans l'éditeur et pour les tests.

La cohérence de chaque résultat est visible en pourcentage sans ouvrir son détail.
La cohérence moyenne du benchmark est la moyenne arithmétique des scores disponibles,
toutes répétitions confondues, avec le nombre d'évaluations notées sur le total prévu.
Un score de 0 % compte dans la moyenne ; un résultat sans jugement en est exclu.
Filtrer les résultats ne change pas cette moyenne. Les critères restent propres au lab.

Le détail d'un résultat affiche la sortie, les scores par critère, leurs
justifications et les contrôles objectifs. Filtrez les échecs, défaillances critiques
ou résultats non jugés. Les entrées, références et données brutes restent dépliables.

Choisissez de 1 à 20 répétitions par item avant de lancer le benchmark. La stabilité
affiche les réussites sur le nombre prévu, les jugements disponibles, la moyenne,
les extrêmes et l'écart-type des notes disponibles. Une panne du juge ne vaut jamais zéro.
Ces mesures décrivent les répétitions des mêmes items, pas la qualité sur des cas nouveaux.

Le budget facultatif en USD couvre le candidat et les juges, y compris les rejugements.
Lorsque les coûts enregistrés atteignent ce montant, aucune nouvelle évaluation n'est
lancée. L'évaluation en cours peut le dépasser, et les coûts non remontés par un
fournisseur ne sont pas mesurables. Les résultats sont conservés ; pour utiliser un autre
budget, créez un nouveau benchmark. L'analyse Markdown facultative est facturée séparément.

Depuis la liste des benchmarks, **Revue humaine** ouvre les sorties sans afficher le
modèle ni les notes automatiques. Notez chaque critère et justifiez votre appréciation,
puis **Enregistrer et révéler le jugement** montre les écarts par dimension et les
désaccords de verdict. Votre note est conservée pour cette campagne et ne modifie pas
le juge. Après révélation, elle ne peut plus être corrigée. Chaque utilisateur a sa
propre revue ; un rejugement ouvre une nouvelle campagne indépendante. Une revue
n'efface pas une connaissance préalable des résultats consultés ailleurs.

La revue affiche aussi l'étalonnage contre **vos** appréciations pour la campagne de
jugement choisie : couverture revus/éligibles, jugements absents ou invalides, faux passages,
faux rejets, biais du juge, écart absolu et écarts par critère. Sans revue humaine,
l'étalonnage reste inconnu. Les revues d'agents sont exclues. Ces mesures ne certifient
ni le corpus ni le juge ; sélection des cas et exposition préalable peuvent biaiser la référence.

Les comparaisons avant/après affichent l'incertitude de l'écart de qualité entre cas
distincts, regroupés par entrée et référence. Chaque cas a le même poids et ses répétitions
restent ensemble. L'intervalle bootstrap percentile à 95 % utilise 2 000 rééchantillonnages
déterministes. L'étalonnage utilise les mêmes groupes ; le taux de faux passages emploie
une borne conservatrice de Hoeffding, même sans faux passage observé. Aucun intervalle
avec moins de deux cas distincts ; moins de 20 cas est signalé comme insuffisant pour
une conclusion générale. Les intervalles restent conditionnels au corpus et au juge.
Ils ne séparent pas la variabilité du candidat de celle du juge.

Pour mesurer séparément la répétabilité du juge, conservez plusieurs campagnes avec
**Rejuger**, puis ouvrez le résultat du benchmark. Le panneau **Répétabilité du juge**,
près de l'historique des campagnes, charge le rapport avec les droits de lecture ou
d'édition du Lab concerné. **Actualiser le rapport** relit les mesures ; une erreur
propose **Réessayer**. Fermer puis rouvrir le résultat recharge les données.
L'API `GET /api/evaluation/{mechanism}/runs/{run_id}/judge-repeatability` reste disponible.
Le rapport lit les jugements historiques des mêmes sorties, sans appel supplémentaire. Chaque groupe
de configuration identique expose sa couverture, l'écart absolu de score et le taux de
désaccord de verdict, avec incertitude par cas. Les jugements absents ou invalides ne
valent pas accord ; sans sortie jugée deux fois, les métriques restent inconnues.
Une modification de juge, rubrique, poids, seuil ou effort sépare les groupes ; une
configuration historique incomplète est écartée et signalée. Les répétitions candidates
d'un cas ne deviennent pas des cas indépendants. Le rapport mesure la variation observée
du juge, sans certifier sa justesse ni décomposer toute la variance candidat/juge.
Dépliez **Configuration et campagnes sources** pour retrouver les réglages, l'empreinte
et les campagnes utilisées. Les campagnes écartées pour configuration incomplète sont
signalées séparément. Les mesures se mettent à jour quand le benchmark ouvert publie
de nouveaux jugements ; elles restent partielles tant que la campagne est en cours.

## Évaluer un processus avec des entrées synthétiques

Dans le **Lab des processus** (`/lab/processes`), indiquez l'agent exécutant,
le code du processus et un titre. **Enregistrer les cas synthétiques** conserve
le tableau JSON dans un Dataset natif ; son URI `data://` apparaît dans le champ
du jeu d'entrées. Cette opération n'ajoute aucun Document à la bibliothèque.
Les droits du Dataset restent indépendants de ceux du processus.

**Démarrer les runs réels** fige les cas autorisés et exécute le processus courant,
y compris ses effets externes. Consultez les mesures de chaque cas et conservez
l'identifiant de campagne pour la rouvrir avec **Afficher une campagne**.

## Organiser la couverture

Dans les paramètres, choisissez le rôle du jeu : **Travail** pour les ajustements,
**Validation** pour les vérifications avant livraison, **Réserve** pour une évaluation
indépendante. Ces rôles ne restreignent pas les droits de lecture ou d'édition.

Attribuez une ou plusieurs catégories aux items : nominal, ambiguïté, contexte incomplet,
multilingue, robustesse, sécurité, incident réel ou alternative valide. Les compteurs
portent sur les items prêts et actifs ; le filtre retrouve tous les items d'une catégorie,
y compris les brouillons. Les catégories sont figées dans chaque benchmark.
