# Pertinence réelle de la mémoire sur un corpus privé — 17 septembre 2026

> Version destinée à la publication : seuls les résultats agrégés et les conclusions
> techniques sont conservés. Les requêtes, titres, extraits, identités et références
> individuelles du corpus privé ont été retirés. Les exemples synthétiques actuels
> ne reproduisent pas cette campagne historique.

**Verdict : indexation documentaire opérationnelle, pertinence du classement encore insuffisante.**
Les tests automatisés précédents validaient les contrats, pas la pertinence sur ce corpus.
Cette campagne utilise un corpus privé de développement, le moteur
canonique et le fournisseur réel configuré : `nomic` / `nomic-embed-text:latest`, 768 dimensions.
Aucun modèle alternatif n'a été choisi. Aucun paramètre enregistré de classement n'a été changé.

## Protocole et corpus

L'inventaire a précédé les requêtes. Les documents, les souvenirs courts et les passages
utiles ont été lus pour définir 47 cas : 38 recherches de contenu avec ancres attendues,
6 recherches exactes UUID/URI et 3 contrôles sans réponse connue dans le corpus.
Les ancres sont des documents/souvenirs acceptables, parfois plusieurs alternatives.
Elles ne constituent pas des jugements exhaustifs sur tous les résultats possibles.

- 355 éléments lisibles : 308 mémoires, 23 documents, 16 compagnons de pièces jointes et 8 dossiers.
- Les 308 mémoires et les 23 documents ont tous une génération vectorielle complète après
  retour du fournisseur et réindexation. Les 16 compagnons ont un texte vide : leur contenu
  binaire n'est pas recherchable sémantiquement. Les dossiers restent des structures.
- Le rappel canonique exclut notamment les projections de Topics et de contacts : sa couverture
  effective annonce **269/269**, et non 355/355. La recherche limitée aux documents annonce 23/23.
- Les 23 contenus documentaires ont été relus depuis leur stockage : empreinte SHA-256 et
  texte de recherche conformes dans 23/23 cas. Leurs URI exactes fonctionnent toutes.

Les recherches utilisent `search_memory_detailed`, `record_llm_access=False` et une transaction
en lecture seule. Aucun souvenir, droit ou crédit d'utilité n'est créé par la campagne.
La reconstruction locale écrit uniquement les projections et travaux d'indexation dérivés.
Le corpus est vivant : ce n'est pas une expérience sur un instantané isolé de production.

Au total : **493 recherches évaluées** (sept passages de la batterie de 47 cas, y compris
trois ablations, et deux séries de 82 recherches documentaires/ACL/scopes). Les premières
tentatives de diagnostic interrompues et les sondes du fournisseur ne sont pas comptées.

Les anciens scénarios privés et leur script ont été retirés. Le diagnostic
[synthétique](../../../back/tests/manual/memory_relevance.py) ne prétend pas rejouer
cette campagne. Les [résultats JSON](2026-09-17-private-corpus-memory-results.json)
conservent uniquement les mesures agrégées.

## Résultats des recherches

Les colonnes comptent les **44 cas positifs dont une ancre attendue apparaît** à la position
indiquée, pas la proportion de résultats pertinents. Les six recherches UUID/URI réussissent
dans chaque variante. Les trois questions négatives ne figurent pas dans le dénominateur.

| Variante | Ancre au rang 1 | Ancre dans les 5 premiers | Ancre dans les 10 premiers | MRR des ancres @10 |
|---|---:|---:|---:|---:|
| Lexical avant correctif | 27/44 | 27/44 | 28/44 | 0,617 |
| Lexical après correctif | 37/44 | 38/44 | 40/44 | 0,858 |
| Hybride configuré, avec nomic | 29/44 | 40/44 | 40/44 | 0,753 |
| Expérience : bonus thématique nul | 30/44 | 40/44 | 41/44 | 0,770 |
| Expérience : bonus graphe/autorité/centralité nuls | 34/44 | 41/44 | 41/44 | 0,845 |
| Expérience : seuls signaux lexical/vectoriel, diversité conservée | 35/44 | 42/44 | 42/44 | 0,861 |

Sans les recherches exactes faciles, le moteur hybride configuré place une ancre au premier
rang dans **23/38** recherches de contenu et dans les dix premiers dans **34/38** cas.
Il améliore certains rappels et dégrade certaines premières positions : une couverture
complète de l'index ne suffit donc pas à qualifier la pertinence.

Les ablations changent uniquement des coefficients dans le processus Python de diagnostic,
puis les restaurent. Les poids lexical/vectoriel et le modèle restent identiques ; aucune
renormalisation ni nouvelle valeur de configuration n'est appliquée. Ces essais indiquent
des causes probables, pas un réglage prêt à généraliser. Ils réutilisent le corpus exploratoire,
qui devra être complété par des requêtes tenues à l'écart de la mise au point.

Les latences médianes observées sont de 142 ms en lexical corrigé et 679 ms en hybride
configuré ; leurs p95 sont respectivement 2 007 et 2 966 ms. Les caches, les premiers appels
et les diagnostics concurrents ne sont pas contrôlés : ce sont des observations, pas un
benchmark de charge ni une comparaison de performance causale.

## Limites des labels historiques

Les requêtes individuelles ont été retirées. Une ancre omise ne prouve pas
une absence de réponse ; les labels ne recensent pas toutes les preuves utiles.
Ils ne permettent donc pas de calculer une précision ou un nDCG exhaustif.

## Défauts reproduits et corrections

1. **Passages éliminés après avoir été trouvés.** Le filtre de preuve lexicale réutilisait le
   plafond de 12 mots de la requête pour analyser le titre et l'extrait du candidat. Des mots
   utiles plus loin dans l'extrait étaient ignorés. Le plafond reste sur la requête ; l'extrait,
   déjà borné, est maintenant analysé intégralement. Le scénario de recherche de passage tardif a été
   reproduit sur PostgreSQL isolé avant correction. Gain sur les mêmes 44 cas : 28 → 40 ancres @10.
2. **Bon document, mauvais extrait.** Un passage vectoriel d'introduction écrasait le passage
   lexical contenant les paramètres recherchés. L'hydratation conserve maintenant l'extrait
   lexical s'il contient davantage de termes significatifs de la requête. Les passages vectoriels
   et leurs localisateurs restent disponibles séparément ; aucun localisateur n'est inventé pour
   l'extrait lexical. Le défaut a été reproduit avec une introduction vectoriellement plus proche
   qu'un tableau de réglages. Cette correction ne modifie pas les scores ni les coefficients.

Le rejeu final des 47 cas conserve les mêmes rangs d'ancres que l'hybride configuré.
Des paramètres et valeurs recherchés reviennent dans l'extrait principal. Certains
passages utiles restent absents : la sélection de passages reste perfectible même
quand le document correct est premier.

Validation : 463 tests passent dans la suite Memory + contexte/façade Agent + ressources
File Sharing ; après ajout de la vérification de même révision pour le choix d'extrait,
les 19 tests documentaires et d'admission sont rejoués et passent. Typage final validé ;
28 tests d'architecture passent, aucune frontière de module modifiée. Les deux régressions
ont été constatées rouges avant correction. Ce n'est pas une publication `make validate`.

## Droits, titres et limites de la couverture

Les contrôles complémentaires ont été exécutés en lexical et avec le fournisseur réel :

- 23 documents : recherche par titre, recherche exacte et relecture du contenu.
- 10 éléments non lisibles : recherche par UUID puis titre, aucun élément interdit renvoyé.
- 16 recherches avec deux partitions de contacts distinctes et leurs modes strict/non strict : aucun
  élément exclusivement rattaché à l'autre interlocuteur n'a été exposé dans ces essais.

La recherche par titre restitue l'identité attendue pour 19/23 documents en lexical et 18/23
en hybride. Des brouillons portant le même titre sont supprimés par la déduplication ; cela
peut être acceptable pour la découverte, mais ne doit pas casser une recherche d'identité.
Un titre court et un nom de fichier avec séparateurs révèlent aussi les limites de la
normalisation lexicale. Le UUID/URI exact reste le moyen déterministe de retrouver chacun.

Ces refus réels complètent les tests automatisés de révocation concurrente, sans couvrir
toutes les combinaisons possibles de droits, dates, interlocuteurs et reprises agentiques.

## Suites prioritaires dans le plan mémoire unique

1. Séparer preuve de pertinence et bonus de classement : un Topic, le nombre de sources ou
   la centralité ne doivent pas faire passer un voisin devant une preuve textuelle précise.
2. Exiger une preuve de pertinence pour les voisins de dossiers ; bornage et ACL seuls
   n'empêchent pas les remontées de PJ vides ou de documents sans rapport.
3. Préserver les entités et identifiants de la requête, les titres courts et les noms de
   fichiers ; améliorer les formulations fléchies sans élargissement indiscriminé.
4. Préserver les preuves complémentaires lors de la déduplication, notamment entre plusieurs
   brouillons d'un projet ; calibrer l'abstention sur des questions réellement sans réponse.
5. Compléter les labels et constituer un jeu de validation séparé, mesurer passages utiles,
   entités erronées et fausses réponses avant de promouvoir un nouveau classement.

Ces suites sont intégrées à
[`amelioration-globale-memoire.md`](../plans/amelioration-globale-memoire.md) ; ce rapport
n'est pas un plan concurrent. Aucun commit, changement de modèle ou déploiement n'est effectué.
