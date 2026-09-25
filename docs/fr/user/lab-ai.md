<p align="right"><strong>Français</strong> · <a href="../../en/user/lab-ai.md">English</a></p>

# Utiliser le Lab IA

Chaque lab présente le traitement testé, **une seule variable métier** et le résultat à
évaluer. Les réglages communs appartiennent au jeu de tests. Un item contient
la valeur de la variable, son contexte et le résultat attendu, avec un nom et sa provenance éventuelle.

| Lab | Variable de l’item | Résultat évalué |
|---|---|---|
| Dispatcher | Demande | Route, effort, action, langue et justification |
| Briefing | Objectif | Briefing et ressources choisies |
| Planner | Objectif | Plan ou clarification |
| Détection des sujets | Échange ordonné | Sujet de chaque message |
| Extraction mémoire | Échange ou compte-rendu de Task | CREATE, LINK ou IGNORE |
| Apprentissage | Issue d’exécution | Leçons étayées |
| Suivi d’objectif | Résultat du cycle | Décision et suivi durable |
| Exécuteur de tâches | Demande | Réponse et appels d’outils |
| Exécuteur conversationnel | Sollicitation courante | Réponse et actions |
| Exécuteur vocal | Sollicitation transcrite | Réponse orale et actions |
| Analyse de tâches | Dossier d’exécution | Diagnostic structuré |

Une séquence de messages Topics constitue un item. Son historique et son catalogue ne
sont pas des tests supplémentaires. Le lab vocal travaille sur du texte transcrit ;
il ne mesure pas la reconnaissance ou la synthèse audio.

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
corpus et classement pour mémoire, ressources pour Briefing, limites de plan pour
Planner, contexte et réponses simulées des outils pour les exécuteurs.

## Générer un jeu synthétique

Dans chacun des onze labs, **Générer un jeu synthétique** crée un nouveau jeu adapté au
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
de Tasks réelles. Les appels d’outils des exécuteurs sont simulés. Les contrats et la cohérence
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

## Tasks

L’analyse interactive d’une Task reste disponible : sélectionnez la Task, ajoutez
éventuellement un contexte humain, puis lancez son diagnostic. Ce parcours relit les
preuves canoniques et ne rejoue pas la Task.

Dans la même page, **Tester et juger les diagnostics** ouvre le parcours par jeu.
Le menu **Ajouter un cas au Lab** d’une Task propose aussi le diagnostic.

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

## Organiser la couverture

Dans les paramètres, choisissez le rôle du jeu : **Travail** pour les ajustements,
**Validation** pour les vérifications avant livraison, **Réserve** pour une évaluation
indépendante. Ces rôles ne restreignent pas les droits de lecture ou d'édition.

Attribuez une ou plusieurs catégories aux items : nominal, ambiguïté, contexte incomplet,
multilingue, robustesse, sécurité, incident réel ou alternative valide. Les compteurs
portent sur les items prêts et actifs ; le filtre retrouve tous les items d'une catégorie,
y compris les brouillons. Les catégories sont figées dans chaque benchmark.
