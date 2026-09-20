# 0078 — Variable métier unique et campagnes de jugement du LAB

- Statut : accepté
- Date : 2026-09-07
- Complète 0021 et 0023 pour les intrants, la notation du Dispatcher et le parcours commun.

## Décision

Chaque mécanisme possède un contrat exécutable dans `app.lab.contracts` :
une variable métier, un contexte d’item typé, des paramètres partagés et un résultat à évaluer.
Les paramètres appartiennent au jeu ; chaque item contient sa variable, son contexte et sa référence attendue.
L’API et la persistance refusent les paramètres d’item.
Précision du 9 septembre 2026 : l’historique antérieur dépend du message et appartient donc
à `input_data.context`, pour tous les traitements qui le consomment. Cette règle inclut
les messages du Dispatcher, les clarifications du Planner, les médias historiques du Briefing,
le Topic initial et les métadonnées des échanges, ainsi que le suivi antérieur d’un Goal.
Ces champs ne peuvent pas surcharger les paramètres communs. Captures, prévisualisations,
attendus proposés et deux passes utilisent le même contexte d’item ; les snapshots le figent
et l’empreinte du corpus l’inclut. Deux historiques différents ne constituent pas un écart
de paramètres lors d’une capture.
Les consignes et réglages propres à l’algorithme appartiennent au jeu ; les réglages
d’inférence fixes sont décrits avec le contrat. Les inconnus ne sont pas des paramètres
implicitement acceptés.

Le contrat est modifié directement. Aucun convertisseur d’ancien jeu,
alias déprécié ou archivage de code n’est ajouté. Les captures de sources actuelles
extraient variable et contexte ; une source textuelle impossible à décomposer reste
un brouillon avec sa preuve originale à examiner. Si les paramètres observés diffèrent de ceux
du jeu, une confirmation explicite est requise avant ajout. Le jeton retourné avec HTTP 409
lie l’accord aux paramètres courants. Après accord, le jeu garde ses réglages et l’item
reste un brouillon à revoir ; la source n’est conservée que comme provenance.

Un seul worker pilote tous les mécanismes, Dispatcher et diagnostic Tasks compris :
il persiste d’abord toutes les sorties candidates, puis une campagne indépendante
juge ces sorties. Une panne du juge laisse la note absente. La similarité structurelle
reste diagnostique et ne remplace jamais un jugement. Les vérifications objectives
interdisent un verdict de réussite lorsqu’une contrainte critique échoue.

`LabJudgmentCampaign` et `LabJudgmentResult` conservent les campagnes précédentes.
Rejuger crée une campagne, sans rappeler le candidat. Reprendre un benchmark annulé
traite seulement ses publications manquantes. Les résultats acquis restent conservés.
Les leases utilisent un token, un renouvellement séparé et une vérification transactionnelle
à la publication. Un appel fournisseur peut être répété après un crash antérieur à
sa publication ; le système ne promet pas un réseau « exactement une fois ».

Les snapshots conservent les entrées résolues, les consignes, le raisonnement configuré,
les rubriques, l’identité des modèles et des empreintes distinctes du corpus/contexte.
Une modification du binding fournisseur pendant le run produit une erreur explicite.
Les secrets ne sont pas copiés dans le snapshot du modèle.

## Interface et frontières

`LabWorkbench` remplace les deux anciens grands écrans de benchmark. Les trois éditeurs
communs couvrent paramètres du jeu, variable, contexte et référence de l’item. Deux progressions, la couverture,
les coûts, les verdicts et les campagnes sont consultables. Les jeux sont créés et édités
dans l’application ; leur import/export par fichier et ses API sont supprimés.

Le diagnostic interactif Tasks reste disponible, avec un benchmark de ses diagnostics.
Les sources de capture appartiennent aux traitements évalués. Le LAB n’importe pas le
journal des échecs ; son budget de dépendances reste à 14. Les deux imports privés frontend
supprimés sont retirés de la baseline.

Les exécuteurs utilisent des outils simulés et enregistrent appels et réponses.
Le lab vocal évalue la variante transcrite ; il ne mesure ni reconnaissance audio,
ni synthèse vocale. La revue humaine et les répétitions avec budget sont désormais décrites
par l’ADR 0082. Comparaisons de runs, étalonnage avancé et gardes CI automatiques restent
le chantier qualité complémentaire.

## Vérification

Les tests couvrent la résolution des paramètres, les deux passes, les pannes du juge,
le rejeu sans candidat, les leases et les privilèges. Les parcours E2E sont validés sur
Chromium, Firefox et WebKit : tous les labs, édition des paramètres du jeu, contexte des items
et seuil mobile utilisent la vraie API avec une base isolée. Le scénario de confirmation
des écarts simule la réponse API ; les tests DB vérifient aussi le contrat serveur de capture.
Les suites des algorithmes partagés protègent leur fonctionnement en production.

## Qualification du 11 septembre 2026

Le lot et ses dépendances ont été vérifiés dans une copie isolée des travaux en cours
sur les autorisations et les Topics. Les validations passent :

- 286 tests backend du LAB, des algorithmes partagés et des frontières d’architecture ;
- 214 tests frontend et 11 scénarios de composants LAB ;
- les trois parcours E2E sur Chromium, Firefox et WebKit, soit neuf exécutions ;
- typage Python/Vue, catalogues FR/EN/ZH, lint et construction du frontend ;
- cartographie générée et contrats d’architecture.

DbAdmin initialise le schéma dans les bases de tests isolées. Les trois erreurs ESLint
qui empêchaient la construction de l’éditeur documentaire sont corrigées ; ses 19 scénarios
de dictée, lecture vocale et impression/export PDF passent également. Les inférences sont
contrôlées en tests : aucune qualification comparative de modèles distants n’est revendiquée.
Le plan de refonte terminé est retiré ; le plan qualité conserve les chantiers complémentaires.
