# Lire les preuves de l'audit

Le [rapport principal](../2026-09-07-test-suite-audit.md) expose les constats A01 à A11 et l'ordre de travail recommandé.

- `inventaire-tests.csv` : une ligne pour chacune des 3 284 définitions hors Lab de la copie initiale, avec fichier, ligne, décision, motif, profondeur de revue, exemples d'oracles et rapprochement des résultats.
- `inventaire-fichiers.md` / `.csv` : index des 501 fichiers candidats hors Lab, décisions agrégées et empreintes. Cinq fichiers n'ont pas de définition : quatre scripts/supports Python et la configuration Playwright.
- `resultats.json` : commandes, résultats des suites initiales, cas JUnit backend/frontend, doublons et limites d'exécution.
- `mutations.json` : modifications exactes et résultats des trois expériences frontend ; quatre garde-fous backend détectés.
- `delta-tests.csv`, `delta-resultats.json`, `delta-fin-audit.md` : neuf définitions nouvelles et deux corps modifiés hors Lab, sur une deuxième copie ; résultats ciblés et qualifications complémentaires.
- `dbadmin-volume-benchmark.json` : qualification de 100 000 lignes sur la deuxième copie.
- `sources-initial.sha256`, `sources-delta.sha256`, `etat-initial.txt` : identité des sources auditées et état initial du travail non commité.
- `dispositifs-hors-inventaire.md` : scripts opérationnels, contrôles complémentaires et diagnostics manuels.

## Interprétation des colonnes

`conserver provisoirement` signifie qu'aucune inutilité n'a été démontrée par le triage. Ce n'est pas la promesse qu'une régression quelconque serait détectée. Une décision appuyée sur un corps relu ou une mutation exécutée est identifiée comme telle dans `profondeur`.

`assertions_directes` repère des assertions, attentes d'erreur et appels de vérification dans la définition. Les assertions contenues dans des helpers ne sont pas toutes comptées. `appels_mock_reperes` compte certaines constructions de doubles explicites ; un transport simulé ou une fixture peuvent ne pas apparaître. Ces colonnes servent à orienter la revue, jamais à calculer un score de qualité.

`lecture_sources_dans_fichier` est un indicateur au niveau du fichier : un fichier mixte peut aussi contenir des tests exécutant vraiment le code. `candidat_sources_seules` est un filtre plus précis sur les appels de la définition ; il inclut des conventions légitimes et ne constitue pas un verdict de suppression.

Les compteurs `cas_passes`, `cas_echoues`, `cas_ignores` ne sont renseignés individuellement que lorsqu'un rapprochement JUnit a été effectué. Zéro avec `execution` indiquant une suite réussie ne signifie pas « non exécuté » : les suites auxiliaires et E2E sont documentées à leur niveau. Les lignes du delta doivent être consultées avant de considérer un résultat initial comme actuel.

Les nombres portent sur des définitions avant paramétrage, sauf les résultats d'exécution. L'inventaire ne transforme pas les scénarios manuels ou scripts de support en tests automatisés. Aucun taux de couverture global ou de résistance globale aux mutations n'est déduit de ces données.
