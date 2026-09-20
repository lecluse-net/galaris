# 0082 — Répétitions, budget et revue humaine du Lab

Statut : accepté. Date : 10 septembre 2026.

## Décision

Un benchmark peut exécuter de 1 à 20 répétitions de chaque item prêt. Les répétitions
partagent les paramètres figés, mais chaque résultat est identifié par le run, le cas
et le numéro de répétition. La reprise conserve les publications acquises ; le
rejugement ne rappelle pas le candidat. Les anciennes publications valent répétition 1.

Le budget facultatif en USD couvre les coûts enregistrés du candidat et de toutes les
campagnes de jugement. Le worker vérifie le budget sous le verrou du run avant de
réclamer une nouvelle évaluation. Le coût d'une évaluation en cours, éventuellement
composée de plusieurs appels, peut dépasser ce seuil. Ce mécanisme n'est pas une
réservation financière stricte ; les coûts non remontés par un fournisseur ne peuvent
pas être pris en compte. L'analyse Markdown facultative reste facturée séparément.
L'épuisement termine le run en `partial` avec `stop_reason=budget_exhausted`.

`LabHumanReview` conserve une appréciation indépendante par résultat, campagne et
utilisateur. Le serveur valide chaque dimension contre la rubrique figée de la campagne,
calcule la note et conserve le verdict humain sans modifier le jugement automatique.
Les contrôles objectifs critiques restent contraignants. Les réponses de revue ne
transmettent ni identité du modèle, ni jugement automatique tant que cet utilisateur
n'a pas soumis son appréciation. Après révélation, elle est immuable. Un autre
utilisateur ou une autre campagne possède sa propre revue. Ce parcours masque les
notes ; il ne garantit pas que l'utilisateur n'a jamais consulté l'écran des résultats.

Les jeux portent un rôle `work`, `validation` ou `holdout`. Les items portent des
catégories de couverture, copiées dans les snapshots. Ces métadonnées n'entrent pas
dans le prompt candidat et ne constituent pas de nouvelles règles d'accès. Les
compteurs de couverture comptent les items prêts et actifs, sans sommer artificiellement
les catégories qui se chevauchent.

## Conséquences

Le détail privilégie sorties lisibles, critères et contrôles ; les données brutes
restent accessibles. Les statistiques décrivent les répétitions observées et affichent
les jugements manquants, sans prétendre mesurer la généralisation à d'autres items.
Les comparaisons de runs, tendances et gardes CI restent des travaux distincts.

La convergence du schéma passe exclusivement par DbAdmin. Les tests de persistance
vérifient reprise, budget, isolation des revues et immutabilité après révélation.
