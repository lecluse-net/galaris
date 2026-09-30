<p align="right"><strong>Français</strong> · <a href="../../en/dev/document-qualification.md">English</a></p>

# Qualification documentaire

Le préparateur `core.document` fournit le texte et une image par page de PDF ou de
fichier Office converti. Le worker traite toutes les pages dans ses limites explicites :
512 Mio de source, 2 000 pages, 10 millions de caractères, 2 Gio de mémoire et
20 minutes. Les macros Office sont désactivées. Pandoc traite Markdown, HTML et EPUB ;
le texte simple et les images sont également acceptés. Un format impossible à
convertir échoue explicitement. L'OCR reste une aide à vérifier contre le rendu.

Les passerelles Chat et Responses acceptent `galaris_document_mode` : `auto`, `direct` ou `prepared`.
En automatique, un modèle capable de lire un PDF reçoit le fichier et sa couverture
si les images sont acceptées ; sinon il reçoit la préparation. Le repli concerne
les refus documentaires et les réponses structurées qui signalent une lecture
incomplète. Une réponse libre apparemment valide ne prouve pas une lecture correcte.
Les flux ouverts et les appels d'outils ne sont pas rejoués.

Les lots préparés contiennent au maximum 80 000 caractères et huit images. Une page
comportant peu de texte peut aussi fournir quatre quadrants agrandis,
en plus de la vue entière, pour préserver les petits détails lors du redimensionnement
par le fournisseur. Les images utilisent le niveau de détail élevé. La consolidation
écarte les réserves de simple absence dans un lot quand un autre lot fournit la
réponse complète ; elle conserve les incertitudes portant réellement sur la source.
Une consolidation suit les lots multiples. Les erreurs fournisseur 502, 503 et 504
peuvent être reprises deux fois, uniquement pour une requête terminée sans flux ni
outils. Ces reprises comptent dans le budget global d'appels. La limite par requête est de 64 Mio de fichiers
incorporés et de 64 appels, ajustable à la baisse avec `galaris_document_max_calls`.
Les outils ne sont pas acceptés dans une consolidation multi-lots. Les en-têtes
`X-Galaris-Document-*` indiquent mode, pages source, lots, appels et cause de repli.
Le nombre de pages source ne prouve pas que le modèle a correctement lu chaque page.

## Protocole reproductible

Les sources privées restent dans `refs/` et les rapports dans `artifacts/`.
Une suite de questions doit être vérifiée indépendamment des réponses du modèle :
titres visuels, nombres exacts, tableaux, dessins, manuscrits et faits de fin de document.
Ne pas confondre les résultats historiques et ceux de la version courante.

```bash
make qualify-documents ARGS='prepare-pipeline /qualification/refs /qualification/results/pipeline-run'
make qualify-documents ARGS='trial /qualification/refs /qualification/results/corpus-smoke-suite.json /qualification/results/terra-auto.json --profile abonnement-openai --mode auto --max-calls 6 --max-tokens 2500 --base-url https://galaris.example.test'
make qualify-documents ARGS='trial /qualification/refs /qualification/results/corpus-smoke-suite.json /qualification/results/fireworks-prepared.json --profile exclusif-fireworks --model-slot text --mode prepared --max-calls 6 --max-tokens 2500 --base-url https://galaris.example.test'
```

Remplacer l'origine HTTPS d'exemple par celle de l'instance locale. Le jeton du compte autorisé
vient de `DOCUMENT_QUALIFICATION_TOKEN`, jamais d'un argument en ligne de commande.
`--max-calls` borne le nombre de requêtes documentaires du benchmark ; chacune peut
utiliser les appels internes de préparation/consolidation. Le rapport additionne
les coûts de ces appels. `native` teste le transport direct sans préparation ;
`text` teste l'extraction commune sans images avec le modèle texte du profil. Pour
tester le nouveau préparateur sans capacité fichier, utiliser `prepared` avec un
profil et `--model-slot text` pour son modèle texte ; ne pas modifier un profil
partagé seulement pour une mesure.

Comparer les modes sur la même source, les mêmes questions et les mêmes budgets.
La commande `check` confronte les réponses au référentiel, puis `qualify` rassemble
les preuves. Une erreur fournisseur ou une réponse manquante ne vaut pas réussite.
Les tests synthétiques sont dans `tests/test_document_pipeline.py` et
`tests/test_document_qualification.py`.

## Portée actuelle

Chat/Tasks, Messenger/Hermès et Dream partagent le lecteur local. Les contextes inline
restent bornés ; les notices renvoient à `document_analyze` pour les grandes sources.
Responses replie les fichiers incorporés des messages ; les items stateful et les
identifiants de fichiers hébergés chez le fournisseur conservent leur transport natif.

`document_analyze(uri, question, model_slot="document", max_calls=256)` lance un Process
personnel et renvoie son identifiant. `document_analysis_get` restitue progression,
réponse et couverture après contrôle de la source. `document_analysis_cancel` demande
l'arrêt et attend la confirmation locale de l'inférence. Les lots terminés sont relus,
sans nouvel appel facturable, grâce à leurs identités d'inférence stables. Une inférence
interrompue reste explicite ; elle n'est pas automatiquement refacturée.

Le slot documentaire du profil est utilisé en priorité, avec repli vers son modèle
texte standard s'il est absent. `model_slot="text"` sélectionne ce modèle texte.
Lorsqu'il n'accepte pas les images, le modèle vision configuré du même profil peut
préparer les observations visuelles ; sa provenance est indiquée dans la couverture.
Sans vision, la limite reste visible. La couverture des unités fournies ne certifie
jamais la justesse sémantique (`semantic_accuracy_verified=false`).

Le cache de préparation est privé par agent, URI, empreinte et version du lecteur.
Chaque accès revalide les droits et les octets de la source. Rétention opportuniste :
sept jours ; quota : 2 Gio par agent. Le worker reprend ses pages terminées via des
checkpoints atomiques. XLSX/ODS conservent séparément cellules, formules, caches,
styles, feuilles cachées, fusions et commentaires ; les formules ne sont pas recalculées.
Le XLS ancien conserve une limite explicite sur ses données structurelles.

Les tests couvrent un Process de 500 pages avec fournisseur simulé, la reprise, les
droits, les sources modifiées, l'annulation, les fichiers corrompus/chiffrés et le TIFF
multipage. Les essais réels et leur revue sont consignés dans les artefacts locaux.
Ils ne qualifient pas tous les faits de rapports arbitraires ni tous les formats.
Voir le [plan](../../../project/plans/analyse-documentaire-unifiee.md) et la
[décision](../../../project/decisions/0151-resumable-document-analysis.md).
