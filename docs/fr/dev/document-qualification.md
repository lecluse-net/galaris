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

### Qualification d'une combinaison source/modèle

Définir la combinaison testée : format et structure, version du lecteur, profil,
modèle, mode, langue et budgets. Comparer lecture directe et préparée sur les mêmes
sources et questions FR/EN, avec un référentiel indépendant et un corpus réservé
qui n'a pas servi aux ajustements. Vérifier faits, nombres, unités, tableaux et
citations contre la source, y compris les absences attendues. Un HTTP 200 ou une
affirmation de lecture complète ne remplace pas cette vérification.

Pour les grandes sources, inclure un PDF texte de 500 pages, un scan de 500 pages,
un rapport mixte de plus de 100 Mo et des tableaux multipages. Contrôler les dernières
pages et la consolidation : aucune omission cachée ni double compte. Exercer
interruption/réouverture, progression, erreur et reprise autorisée, source modifiée et
droits révoqués ; les résultats partiels doivent rester identifiables. Relever les temps
de conversion, OCR et inférence, p50/p95, RAM, disque, octets et coût par page.
Évaluer aussi si l'estimation préalable et la progression distinguent suffisamment
préparation, traitement, vérification et parties illisibles.

La commande `qualify` exige au moins trois essais indépendants réussis pour une même
combinaison ; rejouer le même résultat ne compte pas comme un essai supplémentaire.
Publier uniquement les formats, structures et conditions effectivement qualifiés,
avec mesures et limites. Les tests synthétiques de 500 pages prouvent préparation
et reprise, pas compréhension. Les artefacts locaux restent hors versionnement ;
les conclusions publiées ne contiennent que mesures agrégées et constats techniques.

## Portée actuelle

Chat/tâches, Messenger/Hermès et Dream partagent le lecteur local. Les contextes inline
restent bornés ; les notices renvoient à `document_analyze` pour les grandes sources.
Responses replie les fichiers incorporés des messages ; les items stateful et les
identifiants de fichiers hébergés chez le fournisseur conservent leur transport natif.

`document_analyze(uri, question, model_slot="document", max_calls=256)` lance une analyse
privée gérée par `app.llm` et renvoie `analysis_id`. Elle n'apparaît pas dans le catalogue
des processus métier. Passez cet identifiant dans l'argument `run_id` de
`document_analysis_get` pour obtenir progression,
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

Le cache de préparation utilise un répertoire temporaire privé du processus, hors de `/data`,
séparé par agent, URI, empreinte et version du lecteur. Chaque accès revalide les droits et les
octets de la source. Rétention opportuniste : sept jours ; quota : 2 Gio par agent et processus.
La fin normale du processus nettoie le cache. Après un redémarrage, la source est reconvertie
si nécessaire ; les résultats et lots d'inférence restent durables en base et ne sont pas refacturés.
Le worker reprend ses pages terminées encore disponibles via des checkpoints atomiques.
XLSX/ODS conservent séparément cellules, formules, caches,
styles, feuilles cachées, fusions et commentaires ; les formules ne sont pas recalculées.
Les XLS BIFF5/8 disposent d'un lecteur source distinct, avec valeurs mises en cache,
formules décodables, tokens BIFF originaux, formats numériques, époque des dates,
feuilles/lignes/colonnes cachées, fusions et commentaires. Un cache n'est jamais recalculé.
Une formule indécodable reste signalée avec ses tokens, sans expression inventée.
Le rendu PDF peut différer de ces valeurs source. Les limites structurelles sont de
200 000 cellules et 10 millions de caractères ; les formats BIFF plus anciens sont refusés.
La qualification automatisée porte sur BIFF8 synthétique et un XLS produit par le vrai
LibreOffice, pas sur toutes les variantes historiques de BIFF5 ni toutes les formules.
Le cache et les checkpoints utilisent la même version du lecteur pour éviter de réutiliser
une ancienne préparation XLS dépourvue de ces données.

Les tests couvrent une analyse de 500 pages avec fournisseur simulé, la reprise, les
droits, les sources modifiées, l'annulation, les fichiers corrompus/chiffrés et le TIFF
multipage. Les essais réels et leur revue sont consignés dans les artefacts locaux.
Ils ne qualifient pas tous les faits de rapports arbitraires ni tous les formats.
Voir la [décision](../../../project/decisions/0151-resumable-document-analysis.md).

## Limites et extensions conditionnelles

| Périmètre | Limite actuelle et preuve attendue avant extension |
|---|---|
| XLS ancien | BIFF5 est lu mais ses variantes historiques restent à qualifier ; les expressions indécodables gardent leurs tokens et un diagnostic, sans recalcul ni expression inventée. |
| Office, dessins et diagrammes | DOC/ODG sont convertibles ; qualifier polices, notes, objets, graphiques et pagination sur les structures concernées avant d'en annoncer la fidélité. |
| PDF, scans, manuscrit et images | Reproduire une perte d'ordre, de tableau, de figure, de rotation ou d'OCR avant de compléter le lecteur ; vérifier contre le rendu source. |
| XLSX/ODS et TIFF multipage | Lecteurs et scénarios existants ; la fidélité des structures complexes ne découle pas de leur seule prise en charge. |
| EML/MIME et archives | Pas d'inventaire ni d'analyse récursive des pièces enfants dans le préparateur. Une extension doit fournir localisateurs et couverture par enfant, avec expansion et récursion bornées. |
| Autres formats | Adaptateur qualifié ou diagnostic explicite ; aucune prise en charge universelle. Audio et vidéo utilisent leurs façades dédiées. |

### Isolation des conversions

Un sous-processus et des macros désactivées ne constituent pas une isolation réseau.
Le chemin de conversion LibreOffice ne met pas en place de confinement réseau explicite.
Pour qualifier une isolation, utiliser des sources synthétiques avec références distantes,
archives excessives et fichiers hostiles ; observer l'absence d'accès réseau implicite.
Conserver les limites CPU/RAM/taille/temps et vérifier le nettoyage après interruption
sans invalider les checkpoints terminés.

### Exactitude et transports

Le repli existant ne détecte pas toute réponse HTTP 200 incorrecte ou insuffisante.
Tout contrôle sémantique supplémentaire doit s'appuyer sur des preuves indépendantes,
conserver les unités réussies et les causes de repli, et borner les alternatives.
Un refus de droits ou d'authentification ne déclenche pas de conversion ; un flux ouvert
ou un effet ambigu ne permet pas une resoumission automatique. Les entrées Responses
stateful et les fichiers hébergés conservent leur transport et leur historique ;
leur préparation éventuelle nécessite une qualification propre.

Le catalogue et l'entretien des fiches relèvent de
l'[indexation File Share](../../../project/decisions/0155-durable-file-indexing.md).
L'acquisition dans Memory, la provenance et le rappel du texte extrait suivent le
[plan mémoire](../../../project/plans/amelioration-globale-memoire.md) ; les comparaisons
de mécanismes suivent le [Lab](../../../project/plans/lab-evaluation-mecanismes-ia.md).
