<p align="right"><strong>Français</strong> · <a href="../../en/dev/lab-reference-corpus.md">English</a></p>

# Corpus de validation éditoriale du Lab

Le fichier `back/app/lab/reference_corpus.json` contient six cas synthétiques versionnés :
édition HTML concurrente, URI de pièce jointe sans console, injection dans un document,
livraison non confirmée, distinction HTML/Markdown et consommation sans budget imposé.
Il exerce le briefing et prépare la revue des actions proposées. Il ne prouve pas qu'un
agent a effectivement livré un fichier ou réussi une tâche réelle.

Dans le conteneur backend, `python scripts/import_lab_reference.py` affiche le corpus.
`python scripts/import_lab_reference.py --install` l'importe via l'API locale avec le jeton
d'un utilisateur autorisé fourni dans `LAB_ACCESS_TOKEN`. Ne pas enregistrer ce jeton dans
le dépôt. `--base-url` accepte aussi une installation HTTPS. L'import refuse un dataset du
même nom, ne remplace pas les preuves existantes et n'appelle aucun modèle. Si un import
est interrompu, inspecter le dataset partiel avant de le supprimer ou de compléter ses cas.

Après import, sélectionner explicitement candidat et juge dans le Lab. Comparer au moins
trois répétitions avec les mêmes paramètres, versions de prompts et cas figés. Aucun budget
de coût n'est ajouté par l'import ; un plafond reste un choix explicite de l'opérateur.
Revoir les résultats en aveugle avant de consulter le jugement automatique. Une excellente
note ne compense pas une révision inventée, une action non autorisée ou une livraison affirmée
sans reçu. Comparer les échecs par catégorie et la variabilité, ainsi que coût et durée.

Constituer séparément un jeu de réserve privé à partir de tâches réelles autorisées :
anonymiser les données, conserver les refus et incidents, vérifier les artefacts et les reçus
durables. Ce corpus public ne doit pas devenir le jeu de réserve utilisé pour annoncer une
amélioration des modèles. Les tests locaux valident l'import HTTP, les droits, la persistance
et les contrats du corpus ; ils ne mesurent pas encore la réussite d'un modèle en production.
