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

## Campagne délai, coût et qualité

Les corpus `latency_corpus_fr.json` et `latency_corpus_en.json` contiennent chacun quatre
cas de `conversation_executor` : calcul simple sans outil, recherche en Memory, lecture
d'état d'une Task et admission simulée de Task. Toutes les données sont fictives.
Les outils ont des réponses fixes, réinitialisées pour chaque observation ; aucune Task
réelle n'est créée. La recherche porte sur Memory, sans accès web.

Dans le conteneur backend, prévisualiser puis importer chaque langue avec le même contrat
authentifié que ci-dessus :

```bash
python scripts/import_lab_reference.py --corpus latency-fr
python scripts/import_lab_reference.py --corpus latency-fr --install
python scripts/import_lab_reference.py --corpus latency-en --install
```

1. Dans **Lab → Conversation → Benchmarks**, choisir le corpus importé. Examiner ses quatre
   cas, les références et les réponses d'outils avant de lancer les modèles.
2. Fixer le juge, sa grille, le prompt, les paramètres, le niveau de raisonnement et le nombre
   de répétitions (cinq par cas, par exemple). Exécuter A puis B en ne changeant que le modèle
   candidat, ou dupliquer le jeu pour tester uniquement un prompt ou des paramètres.
   Conserver les empreintes et identifiants des runs ; ne pas comparer FR à EN.
3. Répéter dans l'ordre B puis A pour repérer les effets de cache, de charge et d'ordre.
   Ne pas regrouper ces blocs dans une prétendue mesure indépendante. Un plafond de coût
   reste un choix explicite ; aucune inférence n'est lancée par l'import.
4. Dans **Avant / après**, examiner d'abord les nouvelles défaillances critiques, les passages
   réussi → échoué et les baisses par critère. Ouvrir leurs cas, même hors de la première page,
   puis revoir en aveugle les réponses et les appels d'outils.
5. Lire les médianes de première sortie, de durée candidate, de coût candidat et de qualité.
   Chaque mesure affiche son propre nombre de paires ; la médiane des écarts appariés n'est
   pas nécessairement la différence des médianes. Examiner aussi chaque cas et ses répétitions.

La première sortie est horodatée par le SDK à la première portion de texte non vide ou au
premier nom d'appel d'outil. Les pensées et le texte vide sont exclus. Le chronomètre commence
juste avant l'exécution candidate, après construction du modèle et de l'agent ; il inclut
l'éventuel comptage préalable des tokens, mais exclut la file Lab, le juge et le transport
vers l'utilisateur. Cette mesure ne prouve ni que l'appel d'outil réussira, ni que la réponse
est correcte : les jugements et contrôles restent nécessaires. Sa provenance est
`lab-executor-stream/v1`, stockée dans les observations du candidat, hors de sa sortie jugée.
Un rejugement conserve cette mesure, le coût et la durée candidats. Les anciens runs ou
les mesures absentes restent inconnus ; aucune durée totale ne leur sert de remplacement.

La durée et le coût sont ceux de la passe candidate ; les coûts de juge se lisent séparément
dans le benchmark. Le coût enregistré dépend des informations du fournisseur et ne constitue
pas une facture. Les métriques appariées exigent une passe candidate terminée des deux côtés ;
les métriques de qualité exigent également des jugements comparables. Aucun résultat réel
de cette campagne n'est livré avec le corpus. Publier un gain demande encore des exécutions
avec fournisseurs réels et une qualification du parcours utilisateur complet.
