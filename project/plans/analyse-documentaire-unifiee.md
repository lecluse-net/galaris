# Analyse documentaire — extensions et qualification restantes

- Statut : `partial`
- Revue documentaire : 2026-10-01
- Contrats courants : [0149](../decisions/0149-transient-document-preparation.md) et
  [0151](../decisions/0151-resumable-document-analysis.md).

La préparation commune, les conversions, le routage Chat/Responses, l’analyse reprenable,
les checkpoints, le cache autorisé et les lecteurs Messenger/Hermès, harnais et Dream ne
sont plus des lots de ce plan. Leurs contrats appartiennent à `core.document`,
`app.file_share` et `app.llm` ; aucun nouveau domaine documentaire n'est requis.
Les preuves et limites sont décrites dans le
[guide de qualification](../../docs/fr/dev/document-qualification.md),
[`test_document_pipeline.py`](../../back/tests/test_document_pipeline.py) et
[`test_document_analysis.py`](../../back/tests/test_document_analysis.py).

## 1. Formats et fidélité encore à compléter

Inventorier les limites du lecteur courant par format et usage, puis retenir uniquement
les extensions justifiées par un fichier synthétique qui démontre le manque.

| Famille | Travail restant et réception |
|---|---|
| XLS ancien | Ajouter la lecture structurelle des feuilles, cellules, formules et métadonnées indépendamment du rendu PDF ; préserver l'original et distinguer valeurs mises en cache et recalcul. |
| Office, dessins et diagrammes | Qualifier les filtres DOC/ODG et les autres combinaisons non couvertes ; vérifier polices, notes, objets, graphiques et pagination dérivée contre la source. |
| PDF texte, scans, manuscrit et images | Mesurer ordre de lecture, tableaux, figures, rotations et OCR ; compléter les lecteurs seulement pour les pertes reproduites. Une page fournie au modèle ne prouve pas sa compréhension. |
| EML/MIME et archives documentaires | Concevoir l'inventaire et l'analyse des enfants avec leurs localisateurs et leur couverture propre ; borner expansion et récursion. |
| Autres formats | Publier la matrice qualifiée ; ajouter un adapter ou un diagnostic explicite sans annoncer une prise en charge universelle. |

Les données XLSX/ODS et le TIFF multipage ont déjà leurs lecteurs et scénarios synthétiques.
Il reste à mesurer leur fidélité sur les cas non couverts, notamment les valeurs affichées,
les relations figure/texte, les notes et les structures complexes. Audio et vidéo consomment
leurs façades existantes ; leurs extensions sont dans le
[plan multimédia](outils-mcp-multimedia.md).

Pour chaque adapter ajouté : détecter le format réel, conserver l'original, vérifier le
résultat indépendamment du lecteur et identifier toute pagination créée par conversion.
Les macros ne sont pas exécutées et aucun recalcul n'est implicite.

## 2. Isolation des convertisseurs

Compléter et qualifier l'isolation réseau des workers, notamment LibreOffice et les formats
susceptibles de charger des ressources externes. Préserver les limites CPU, RAM, taille,
texte et temps déjà appliquées, les profils temporaires et l'arrêt des processus locaux.

Réception : un corpus synthétique avec références distantes, archives excessives et fichiers
hostiles ne déclenche aucun accès réseau implicite ; une interruption nettoie les processus
et temporaires sans invalider les checkpoints terminés. Le contenu reste une donnée,
jamais une instruction système. Les diagnostics persistés sont bornés et expurgés.

## 3. Contrôle sémantique et fallback

Qualifier séparément les refus natifs déjà traités et les réponses HTTP 200 incorrectes ou
insuffisantes. Définir les contrôles indépendants nécessaires pour détecter une omission,
une contradiction avec la source ou une couverture native indémontrable dans une demande
exhaustive. La déclaration du modèle ne constitue pas ce contrôle.

Le contrôle doit préserver les unités déjà réussies et les motifs du fallback. Le nombre
d'alternatives reste borné ; un refus de droits ou d'authentification n'appelle pas une
conversion. Aucun flux ouvert ni effet d'outil ambigu n'est resoumis aveuglément.
Qualifier les entrées Responses stateful et les fichiers hébergés par le fournisseur avant
une éventuelle extension de leur préparation ; le transport et l'historique restent intacts.

Pour les résultats critiques, comparer faits, nombres, unités, tableaux et citations à un
oracle rédigé depuis la source. Distinguer fidélité d'extraction, couverture de préparation,
qualité sémantique et orchestration du fallback.

## 4. Grandes sources et parcours assemblé

La qualification exhaustive et répétée reste à apporter avec des fournisseurs réels :

- un PDF texte de 500 pages, un PDF scanné de 500 pages et un rapport mixte de plus de 100 Mo,
  avec annotations réparties jusqu'à la dernière page ;
- tableaux multipages, sections dépendantes et consolidation globale sans perte ni double compte ;
- mêmes sources et questions en lecture directe forcée et préparée forcée, profils et protocoles
  figés, avec revue indépendante ;
- interruption et réouverture dans l'application, progression, erreur, retry autorisé et
  résultat sourcé, y compris droits révoqués et source modifiée ;
- mesures comparables de conversion, OCR, inférence, p50/p95, pic RAM, disque, octets et coût
  par page ; objectifs chiffrés fixés après la baseline ;
- estimation préalable des unités et du budget, et distinction entre préparation, traitement,
  vérification et unités illisibles lorsque la projection actuelle ne suffit pas.

Le test de 500 pages à frontière fournisseur remplacée protège la couverture et la reprise ;
il ne prouve pas la fidélité sémantique d'une grande source. Les benchmarks locaux restent
sous `artifacts/` ; les fixtures du dépôt sont entièrement synthétiques. FR/EN sont les langues
initiales ; les autres langues demandent une qualification distincte.

Pour une combinaison promue, exiger trois essais indépendants sans erreur critique ni omission
cachée et un corpus tenu à l'écart. Une limite, un budget épuisé ou une absence de vision garde
une issue explicite ; aucune analyse partielle n'est présentée comme complète.

## 5. Dépendances et clôture

Le [catalogue file-share/Memory](indexation-file-share-memory.md) possède l'inventaire des
ressources et l'entretien de leurs fiches. Les expériences de rappel et de provenance fine
restent dans le [plan Memory](amelioration-globale-memoire.md) ; les campagnes comparatives
réutilisent le [Lab](lab-evaluation-mecanismes-ia.md).

Avant toute extension, reproduire son manque et renforcer les scénarios du lecteur ou de
l'analyse concernée. Publier formats qualifiés, mesures et limites dans le guide de qualification.
Retirer ce plan lorsque ses extensions sont réalisées ou transférées et ses critères spécifiques
démontrés. Une publication demandée requiert `make validate` sur l'instantané final.
