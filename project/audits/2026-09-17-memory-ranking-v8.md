# Classement mémoire v8 — 17 septembre 2026

> Version destinée à la publication : seuls les résultats agrégés et les conclusions
> techniques sont conservés. Les requêtes, titres, extraits, identités et références
> individuelles du corpus privé ont été retirés. Les exemples synthétiques actuels
> ne reproduisent pas cette campagne historique.

Implémenté en développement, sans publication ni intervention en production.
Le [plan unique](../plans/amelioration-globale-memoire.md) reste `partial` : ce rapport
qualifie l'incrément de classement, pas l'ensemble du programme Memory/Dream.

## Périmètre et méthode

Corpus privé de développement. Le modèle **nomic** configuré
(`nomic-embed-text:latest`, 768 dimensions) et les paramètres enregistrés restent inchangés.
Les appels passent par le rappel canonique, sous transaction SQL en lecture seule et sans
enregistrement d'accès LLM. Aucun modèle génératif ou reclasseur supplémentaire n'est appelé.

La campagne précédente et ses ablations sont conservées dans le
[rapport v7](2026-09-17-private-corpus-memory-relevance.md). Les 47 cas initiaux comprennent
44 cas positifs, dont six UUID/URI, et trois négatifs. Une ancre est un UUID jugé acceptable
avant la recherche ; les labels ne recensent pas tous les souvenirs potentiellement utiles.
Les chiffres ci-dessous sont des présences et positions d'ancres, pas une précision exhaustive.

Avant les changements, 18 questions supplémentaires ont été réservées : 13 positives et
cinq négatives. Leur premier passage a révélé un filtre de majuscules trop strict. Les
questions Word et conversations ont servi à corriger cette règle générale ; leur rejeu
est donc une régression connue et **n'est plus une validation indépendante**.

Après cette correction, une nouvelle liste de 13 questions (dix positives, trois
négatives) a été comparée sans nouveau réglage. Le comparateur alternait les moteurs
avant/après dans un environnement partagé. Les questions, extraits et identifiants
ont depuis été retirés ; les [résultats JSON](2026-09-17-memory-ranking-v8-results.json)
conservent les agrégats calculés sur les observations historiques.

## Résultats

| Série | Première position v7 → v8 | Dans les dix premiers v7 → v8 | Négatifs produisant des résultats v7 → v8 |
|---|---:|---:|---:|
| Mise au point, 44 positifs + 3 négatifs | 29 → **41 / 44** | 40 → **42 / 44** | 3 → **0 / 3** |
| Premier holdout, avant correction des majuscules | 6 → 8 / 13 | 13 → 10 / 13 | 5 → 0 / 5 |
| Rejeu du holdout après correction | 6 → **10 / 13** | 13 → **12 / 13** | 5 → **0 / 5** |
| Nouvelle validation finale, sans réglage ultérieur | 4 → **9 / 10** | 9 → **10 / 10** | 3 → **1 / 3** |

Sur le jeu initial, les 42 ancres trouvées sont toutes dans les cinq premiers résultats.
Les 41 recherches de contenu fonctionnent en hybride ; les six accès exacts évitent le
fournisseur. La couverture canonique est de 269/269 items, ou 23/23 pour les requêtes
restreintes aux documents. Latence observée sur les 47 cas finaux : médiane **339 ms**,
95e percentile empirique **729 ms**. Mesure locale à faible concurrence, sans garantie de charge.

Certains résultats utiles ne correspondaient pas aux ancres choisies. Les labels
historiques ont été conservés dans les calculs, sans correction a posteriori.
Ils ne suffisent pas à mesurer le rappel de tous les faits.

## Changements vérifiés

- La couverture des termes de la question prime sur les bonus du Topic, du graphe, de la
  fraîcheur et du nombre de sources. Les recherches précises ne sont plus dominées par un
  document simplement très connecté. Les poids enregistrés ne sont pas réécrits.
- Les compléments nommés explicites et les identifiants sont contrôlés ; les voisins
  structurels doivent apporter une preuve dans leur contenu. Les compagnons vides et
  dossiers sans réponse ne remplissent plus artificiellement les places disponibles.
- Le lexical conserve la question originale, gère les titres courts, les noms de fichiers,
  des flexions usuelles et des fautes limitées. « Word » et un sujet implicite comme
  « l'utilisateur » ne sont plus écartés par le seul filtre des majuscules.
- Les documents combinent jusqu'à trois passages lexicaux/vectoriels de la même génération.
  Les réglages techniques, les paramètres de tableaux et les listes de contrôles sont présents
  dans les extraits observés. Les tests relisent effectivement le passage via URI et offset.
- Les copies exactes sont dédupliquées ; des documents proches portant des seuils différents
  sont conservés. Une proximité vectorielle ne vaut plus identité de fait.
- Une réponse vide porte `relevance_status=no_sufficient_evidence`, distinct des diagnostics
  de panne et de couverture. Aucun remplissage jusqu'à dix résultats n'est obligatoire.

Les seuils et règles précis sont consignés dans l'[ADR 0108](../decisions/0108-memory-document-retrieval.md).
La comparaison des versions protège aussi le mélange des preuves lexicales et vectorielles :
une ancienne preuve lexicale n'est jamais transférée sur une nouvelle version sémantique.

## Documents, isolation et tests automatisés

Le contrôle réel supplémentaire vérifie :

- **23/23 documents** retrouvés par UUID/URI et par leur titre, y compris titres courts et
  noms de fichiers ; rang maximal 8, certains titres sont partagés par plusieurs documents ;
- **23/23 contenus** avec SHA-256 et projection textuelle conformes au contenu relu ;
- **10 éléments interdits**, chacun interrogé par UUID et titre : aucun résultat interdit ;
- **16 recherches** par contact, strictes et non strictes : aucun item exclusivement rattaché
  à l'autre contact ne fuit dans ces essais.

Validation finale du code :

```text
make tests ARGS='app/memory/tests app/agent/tests/test_conversation_context.py app/agent/tests/test_facade.py app/file_share/tests/test_resource_service.py -q'
467 passed, 2 warnings, 75.16s

make typecheck
réussi : Pyright, vérifications frontend et parité i18n

make architecture-check
réussi, dont 28 tests d'architecture et contrôle de cartographie
```

Les deux avertissements proviennent de la dépréciation d'`asyncio.iscoroutinefunction` dans
SlowAPI. Les tests fonctionnels couvrent le changement de classement, l'isolation entre contacts,
les documents complémentaires, les titres/formats, l'absence de réponse, les passages, les
droits et changements concurrents. Ils utilisent des vecteurs substitués ; la qualité
linguistique est mesurée séparément par la campagne nomic.

La revue finale a supprimé une condition lexicale devenue toujours vraie et ses branches
inaccessibles, sans changer le comportement mesuré. Les empreintes finales sont également
retirées des exports publics ; la suite du périmètre et le typage ont été relancés après ce nettoyage.

Des attentes de tests ont été changées lorsque le contrat changeait volontairement : un
Topic explicite ne garantit plus la première place ; un lien persistant ou un dossier lisible
ne rend plus automatiquement son voisin pertinent ; la fusion par similarité ne supprime
plus un fait distinct lors du rappel. La présence des liens et les droits restent vérifiés.

## Limites conservées et suites

Deux questions initiales ne retrouvent toujours pas leurs ancres attendues.
Les paraphrases éloignées et le multilingue restent à améliorer avec le modèle configuré.

La dernière validation conserve un faux positif : un cas négatif renvoie un souvenir
sans preuve répondant à la question. Les deux autres négatifs sont vides. Ce résultat est conservé sans
retoucher les seuils après examen du jeu réservé ; l'abstention n'est donc pas parfaite.

Le contrôle des compléments nommés est une heuristique, pas une résolution des identités,
alias ou relations. Les seuils vectoriels ne sont pas des probabilités calibrées ; d'autres
modèles configurés et d'autres corpus doivent être évalués avant généralisation. Les candidats
restent bornés, et une réponse vide ne prouve pas que le fait n'existe nulle part dans la mémoire.
La déduplication est conservatrice, pas un regroupement exhaustif des paraphrases.

L'évaluation suivante devra compléter les jugements, diversifier les corpus et séparer
absence de fait, reformulation et identité implicite. L'utilité dans une tâche agentique
complète n'est pas encore démontrée. Aucun `make validate` global ni déploiement n'a été
effectué : ces résultats ne qualifient pas une publication du dépôt entier.
