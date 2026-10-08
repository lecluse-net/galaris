# Analyse documentaire — extensions restantes

- Statut : `partial`
- Revue des sources : 2026-10-08.
- Contrats : [0149](../decisions/0149-transient-document-preparation.md) et
  [0151](../decisions/0151-resumable-document-analysis.md).

Préparation commune, conversions, routage Chat/Responses, reprise, checkpoints et cache
autorisé sont réalisés dans `core.document`, `app.file_share` et `app.llm`.
Le [guide de qualification](../../docs/fr/dev/document-qualification.md) décrit formats,
limites et protocole ; les tests `test_document_pipeline.py` et
`test_document_analysis.py` portent les garanties existantes.

## Extensions justifiées par un manque reproductible

| Périmètre | Travail et réception |
|---|---|
| XLS ancien | Lecture structurelle des feuilles/cellules/formules/métadonnées : le worker ne fournit encore que le rendu PDF et un avertissement. Distinguer caches et recalcul ; conserver l'original. |
| Office, dessins et diagrammes | Qualifier DOC/ODG et combinaisons non couvertes : polices, notes, objets, graphiques et pagination dérivée fidèles à la source. |
| PDF, scans, manuscrit et images | Reproduire les pertes d'ordre, tableaux, figures, rotations ou OCR avant de compléter les lecteurs. |
| EML/MIME et archives | Inventaire et analyse des enfants avec localisateurs et couverture propres ; expansion et récursion bornées. |
| Formats supplémentaires | Matrice qualifiée, adaptateur ou diagnostic explicite ; aucune prise en charge universelle annoncée. |

XLSX/ODS et TIFF multipage ont leurs lecteurs et scénarios ; leur fidélité sur structures
complexes reste à mesurer. Les macros ne sont pas exécutées, aucun recalcul n'est implicite.
Audio/vidéo réutilisent les façades et le [plan multimédia](outils-mcp-multimedia.md).

## Isolation et contrôle sémantique

Compléter et qualifier l'isolation réseau des convertisseurs, notamment LibreOffice :
sources synthétiques avec références distantes, archives excessives et fichiers hostiles
sans accès réseau implicite. Conserver limites CPU/RAM/taille/temps et nettoyage après
interruption, sans invalider les checkpoints terminés.

Qualifier les HTTP 200 incorrects ou insuffisants séparément des refus natifs déjà traités.
Un modèle affirmant avoir lu ne certifie pas sa couverture. Définir des contrôles indépendants
sur faits, nombres, unités, tableaux et citations ; préserver unités réussies et causes de
fallback, avec alternatives bornées. Refus de droits/authentification sans conversion ;
flux ouvert ou effet ambigu sans resoumission aveugle.
Les entrées Responses stateful et fichiers hébergés conservent leur transport/historique ;
leur préparation éventuelle demande une qualification propre.

## Grandes sources

Compléter la recette réelle et répétée du guide : PDF texte de 500 pages, scan de 500 pages,
rapport mixte >100 Mo, tableaux multipages et consolidation sans omission/double compte.
Les scénarios synthétiques de 500 pages prouvent couverture/reprise, pas compréhension.

Comparer lecture directe et préparée sur mêmes sources/questions/profils/budgets FR/EN,
oracle indépendant et corpus tenu à l'écart. Exercer interruption/réouverture, progression,
erreur/retry autorisé, source modifiée et droits révoqués ; garder résultats partiels explicites.
Mesurer conversion/OCR/inférence, p50/p95, RAM, disque, octets et coût par page.
Compléter estimation préalable et projection préparation/traitement/vérification/illisible
si le parcours courant ne suffit pas. Trois essais indépendants sans erreur critique ni
omission cachée sont la porte proposée pour une combinaison promue.

## Dépendances et clôture

L'inventaire et l'entretien des fiches appartiennent au
[catalogue réalisé](../decisions/0155-durable-file-indexing.md).
Acquisition dans Memory, provenance et rappel du texte extrait restent dans le
[plan mémoire](amelioration-globale-memoire.md) ; comparaisons dans le
[Lab](lab-evaluation-mecanismes-ia.md).
Publier formats qualifiés, mesures et limites dans le guide, puis retirer les extensions
réalisées ou transférées. Les artefacts locaux restent hors versionnement.
