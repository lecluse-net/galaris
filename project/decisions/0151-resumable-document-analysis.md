# 0151 — Analyse documentaire reprenable et couverture explicite

Statut : accepté. Date : 2026-09-30.

## Problème

La préparation temporaire de la décision 0149 ne permet pas de reprendre une analyse
longue. Les extractions propres à Dream et Messenger divergent et la lecture d'un
tableur imprimé ne conserve pas toutes les données source.

## Décision

Conserver `core.document` comme lecteur local commun, indépendant des domaines.
Correction du 2026-10-01 : l'analyse documentaire est une opération technique de
`app.llm`, pas un processus métier. Sa persistance privée `llm_document_analyses` conserve
les checkpoints, la couverture, les résultats et les autorisations. Un job du scheduler
existant avance les analyses avec un bail expirant ; aucun nouveau scheduler n'est créé.
Le moteur Process `galaris` et ses définitions techniques sont supprimés.
Les outils `document_analyze`, `document_analysis_get`
et `document_analysis_cancel` passent par les autorisations normales du Tool Galaris.
L'entrée est une URI file-share ; les chemins internes ne sont jamais rendus au modèle.

Chaque lot a une identité d'inférence déterministe dérivée de l'analyse et de son rang.
Les résultats terminés sont relus après interruption, sans nouvelle admission facturable.
Une inférence interrompue reste explicite et n'est pas automatiquement rejouée.
Une annulation attend la confirmation de l'arrêt local de l'inférence ; elle ne promet
pas l'annulation de la facturation chez le fournisseur. Les états terminaux de l'analyse
restent immuables et les checkpoints ignorent les publications tardives.

La préparation garde des checkpoints atomiques par page. Une reprise ne rerend pas
les pages terminées. Le cache interne sous la racine documentaire de `/data` est séparé
par agent, URI, empreinte source et version de préparation. Chaque consultation vérifie
les droits et télécharge les octets source avant réutilisation : un checksum identique
ne confère aucun droit et les providers sans version fiable restent couverts.
Une version source différente invalide les résultats déjà admis. Le cache a une rétention
opportuniste de sept jours et un quota de 2 Gio par agent ; les entrées utilisées ne sont
pas purgées. Les dérivés restent privés et ne constituent pas un provider public.

La couverture distingue unités attendues, préparées, textuelles, OCR et visuelles, ainsi
que lots terminés et attendus. Fournir chaque unité ne certifie pas sa justesse sémantique.
Les réponses et en-têtes gardent cette distinction. Les pages imprimées et les cellules
XLSX/ODS sont des preuves séparées : valeurs, formules, styles, feuilles cachées,
fusions et commentaires sont préservés sans recalcul implicite. Le XLS ancien conserve
une limite explicite sur l'extraction structurelle.

Un modèle documentaire sans images peut utiliser le modèle vision configuré du même
profil pour préparer des observations, puis le modèle demandé pour consolider. Les
identités des modèles restent explicites. Sans vision, la couverture visuelle manquante
est annoncée. Aucun contenu de fichier ne devient une instruction système.

Le fallback Chat et Responses conserve le transport choisi. Les items Responses
stateful ou les fichiers hébergés par le fournisseur ne sont pas transformés arbitrairement.
Dream, Messenger/Hermès et le harnais consomment la préparation commune ; leurs budgets
inline restent explicites et le traitement exhaustif est disponible par l'analyse dédiée.

DbAdmin transfère les anciennes analyses avec leur UUID, leurs lots et leurs résultats,
y compris les archives, avant de retirer leurs définitions et runs techniques.
Les inférences payées gardent leur identité et leur historique, détachés des FK Process.
Les processus métier restent intacts. Un éventuel waiter Process est terminé explicitement ;
l'analyse transférée reste consultable avec le même identifiant via `document_analysis_get`.
Le champ de réponse `run_id` reste un alias de compatibilité de `analysis_id`.

La dépendance publique `app.llm → app.file_share` exprime la lecture autorisée des sources.
Le contrôle manquant était l'absence de création de processus métier par l'outil d'analyse ;
le test fonctionnel protège désormais cette séparation, en plus de la reprise et de l'annulation.

## Validation et limites

Tests synthétiques de conversion interrompue, reprise durable des lots, lecture de
500 pages avec frontière fournisseur remplacée, isolation du cache, révocation,
Responses, corruption, chiffrement, TIFF multipage et métadonnées XLSX.
Les benchmarks privés restent sous `artifacts/`. La couverture des 500 pages ne démontre
pas une fidélité sémantique universelle. Les conversions Office restent limitées par
le moteur et ses polices ; leur isolation réseau complète n'est pas qualifiée.
