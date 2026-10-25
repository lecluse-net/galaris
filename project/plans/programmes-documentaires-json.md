# Petites applications intégrées à Galaris, créées par les agents

- Statut : `partial` — le socle HTML/JavaScript et Dataset existe ; le parcours complet d'une nouvelle application avec données reste à qualifier et à compléter.
- Date initiale : 2026-10-11.
- Objectif précisé par l'utilisateur le 2026-10-25 : « J'aimerais que les agents puissent créer de petites applications intégrées à Galaris. »
- Revue des contrats et tests : 2026-10-25 ; aucun parcours applicatif rejoué lors de cette revue.

L'utilisateur demande une application utilisable : interface, interactions et, selon
le besoin, données persistantes. Exemples de réception synthétiques : un calculateur,
un formulaire de collecte ou un tableau de suivi. Le plan conserve son nom de fichier
historique pour les liens existants ; son périmètre est recentré sur cet objectif.

## 1. Parcours attendu

Un utilisateur demande une petite application à un agent. L'agent crée ou adapte
l'interface, l'enregistre dans Galaris, prépare les données utiles et fournit son
lien. L'utilisateur ouvre l'application dans Galaris, utilise ses contrôles et
retrouve ses données après fermeture et réouverture. L'agent peut ensuite améliorer
l'application en conservant son identité et les données existantes.

Le socle actuel réalise l'interface dans un Document HTML ordinaire, avec CSS et
JavaScript isolés. Les données persistantes appartiennent à un ou plusieurs Datasets
indépendants. Un Document peut ainsi héberger une application sans devenir le
propriétaire du JSON qu'elle utilise. Une application de calcul sans persistance
n'a pas besoin de Dataset.

L'ouverture dans le lecteur documentaire constitue le premier parcours à qualifier.
Un éventuel accès depuis un espace Applications, un menu ou un raccourci reste un
besoin d'intégration à préciser ; aucune de ces surfaces supplémentaires n'est
requise pour établir que le socle existant permet de créer une petite application.

## 2. Socle déjà implémenté

| Capacité | Contrat existant |
|---|---|
| Création par un agent | `file_create(path="document://", ...)` enregistre le HTML ; `file_read`, `file_write`, `file_edit` et `file_append` permettent les améliorations avec contrôle de révision. |
| Interface interactive | HTML, formulaires, CSS et JavaScript ordinaires sont acceptés dans le profil Document. Le code démarre à l'ouverture ; aucun manifeste applicatif ni nouveau type de Document n'est requis. |
| Intégration au lecteur | L'interface interactive reste dans le Document, avec la barre d'outils et le texte éditable habituels. Les aperçus et historiques restent inertes. |
| Données persistantes | `app.dataset` possède JSON libre, historique, révisions, droits, partage, bibliothèque et éditeur. Création par `file_create(path="data://", ...)`, sans Document associé ni schéma imposé. |
| Pont de données | Le HTML déclare ses Datasets par `data-dataset`, alias et accès. Le SDK expose `galaris.datasets.read`, `append` et `replace` avec révision attendue. |
| Droits | Le Document et chaque Dataset ont des droits indépendants. Le pont utilise ceux du lecteur et son consentement personnel serveur pour la révision documentaire courante. |
| Évolution | Le source est conservé dans les révisions du Document. Une modification arrête le runtime et le rendu reprend après sauvegarde valide ; les Datasets conservent leur identité et leur historique propres. |
| Conservation du rendu | Impression, PDF et archive HTML capturent l'état affiché sans rejouer les scripts ni effectuer de nouvelle écriture Dataset. |

Références canoniques : [applications HTML](../../docs/fr/dev/document-apps.md),
[Datasets](../../docs/fr/dev/datasets.md),
[ADR 0125](../decisions/0125-document-applications.md),
[ADR 0187](../decisions/0187-dataset-domain-and-typed-contracts.md) et
[ADR 0223](../decisions/0223-memory-document-independence.md).
Le skill runtime `back/app/skill/system_skills/galaris/SKILL.md` décrit déjà la
création HTML et l'utilisation du pont Dataset pour les agents.

## 3. Écart concret : accès aux données d'une nouvelle application

Les ACL et le consentement applicatif sont deux contrôles distincts. La possession
ou le partage d'un Dataset ne suffit pas à autoriser son accès depuis le JavaScript.
Le serveur exige un accord personnel pour la combinaison lecteur, application,
Dataset, alias et révision du Document. Une édition ou restauration exige un nouvel
accord. Le HTML généré, le SDK et MCP ne peuvent pas l'accorder.

L'icône et la modale de permissions ont été retirées. Les routes humaines de
consultation et de modification de l'accord existent encore, mais aucun parcours
courant dans l'interface ne permet de le donner. Sans accord, l'application reste
visible et le pont retourne `permission_required`.

Ce constat est étayé par les contrats et les tests : le scénario E2E
`e2e/specs/document-apps.spec.mjs` prépare l'accord par une requête API explicite.
Il vérifie le fonctionnement avec cet accord, pas la capacité d'un utilisateur à
le donner dans l'interface actuelle. La revue ne reproduit pas un incident en
application et ne permet pas d'affirmer que toutes les installations sont bloquées ;
les accords déjà enregistrés restent utilisables pour leur révision.

Le travail ouvert est de définir puis réaliser un parcours utilisable d'autorisation,
ou une évolution explicite de ce contrat, pour les nouvelles applications et leurs
mises à jour. Il doit préserver les ACL, la portée des accès et la maîtrise du lecteur.
Ne pas réintroduire automatiquement l'ancienne modale, annoncer une interface absente,
ni supprimer les contrôles serveur pour rendre une démonstration passante.

## 4. Garanties à préserver

- L'agent crée et améliore l'application avec les outils autorisés existants ; aucune étape de publication ou sélection manuelle de version n'est imposée.
- Le prochain affichage utilise le contenu sauvegardé ; une mise à jour ne supprime ni ne réinitialise implicitement les Datasets existants.
- Partager l'interface ne partage pas ses données. Une référence ou déclaration HTML n'accorde aucun droit ; les droits de l'auteur ne sont pas transmis au lecteur.
- Une écriture contrôle la révision du Dataset. En cas de conflit, conserver la saisie, relire et demander une nouvelle soumission sans retry aveugle.
- Fermeture, changement de Document ou nouvelle révision arrêtent le runtime et écartent ses réponses tardives. Une écriture déjà committée reste durable.
- Le code reste dans le runtime isolé existant, sans session, secrets, DOM parent ni outils Galaris implicites. Les quotas et limites du pont Dataset restent applicables.
- Dataset conserve le JSON libre, sans schéma métier imposé. Document conserve HTML et code ; Process conserve ses workflows BPMN, données et fichiers de runs.

Les limites actuelles sont celles du [guide des applications](../../docs/fr/dev/document-apps.md) :
le runtime est un navigateur isolé, sans budget CPU garanti ni accès réseau ordinaire.
Un traitement serveur, un accès à un service externe ou un travail en arrière-plan
exige un besoin et un contrat supplémentaires ; le présent objectif ne les suppose pas.

## 5. Travail restant et réception

| Travail ouvert | Réception attendue |
|---|---|
| Qualifier une première application créée par un agent | Depuis une demande synthétique, l'agent crée l'interface et fournit un lien utilisable dans Galaris ; un calculateur fonctionne sans préparation manuelle du code. |
| Compléter le parcours d'accès Dataset | Un utilisateur autorisé peut utiliser une nouvelle application avec persistance par un parcours prévu pour lui, sans qu'un test ou un opérateur injecte son consentement en coulisses. Le refus et la révocation restent effectifs. |
| Qualifier sauvegarde et reprise | Un formulaire enregistre dans un Dataset natif ; fermeture et réouverture retrouvent les données. Conflits, erreurs et quotas conservent la saisie et n'inventent pas de réussite. |
| Qualifier l'amélioration par l'agent | L'agent modifie la même application ; le nouveau rendu utilise la sauvegarde et retrouve le Dataset existant. Le parcours couvre le renouvellement d'accord éventuellement requis. |
| Qualifier le partage | Deux lecteurs utilisent la même application avec des droits indépendants ; l'absence de droits Document ou Dataset et leur révocation sont vérifiées séparément. |
| Préciser l'accès aux applications | Vérifier si le lien documentaire satisfait l'usage attendu ; ajouter un accès dédié seulement si un besoin concret le justifie. |

Réutiliser les preuves existantes avant d'ajouter des tests :

- `back/app/document/tests/test_document_apps.py` couvre HTML direct, conservation du source, données natives sans Document associé, révisions, droits, consentements et budgets.
- `back/app/dataset/tests/test_datasets.py` couvre contenu JSON exact, racines libres, historique, conflits et refus d'accès.
- `front/browser-tests/document-apps.spec.mjs` couvre contrôles utilisables, conflits sans perte de saisie, isolation, contexte, réponses tardives et absence d'accord.
- `e2e/specs/document-apps.spec.mjs` couvre deux applications partageant un Dataset, avec accord préparé par API : compléter la réception au niveau du parcours humain réellement retenu.

Cette revue consulte ces tests sans les relancer. Pour l'implémentation future,
exécuter les suites ciblées via les cibles Make, puis exercer le parcours assemblé
avec un agent et des données entièrement synthétiques, clavier et petit viewport
compris. Distinguer le résultat des tests de celui de la recette applicative.

## 6. Hypothèses historiques retirées du périmètre nécessaire

Le catalogue personnel de programmes, les fonctions proposées `document_register`,
`document_exec`, `document_exec_get`, `document_test`, le paquet
`galaris.program/v1`, un nouveau domaine `app.program` et un moteur QuickJS serveur
ne sont pas nécessaires à l'objectif précisé. Ils ne constituent plus les critères
permettant de déclarer ce plan terminé. Les agents peuvent déjà enregistrer les
interfaces HTML par les opérations File Sharing existantes.

Le port `ProgramExecutor` du moteur BPMN ne prouve ni ne conditionne la réalisation
de ces petites applications navigateur. Une fonction technique ne devient pas un
Process pour obtenir un suivi durable. Tout besoin ultérieur d'exécution serveur
JSON vers JSON doit être justifié et conçu séparément.

## 7. Condition de clôture

Retirer ce plan lorsque les parcours de création, utilisation, persistance, partage
et amélioration d'une petite application par un agent sont qualifiés, avec un accès
Dataset utilisable selon le contrat retenu. Reporter alors les garanties et limites
dans les guides FR/EN et les tests canoniques, sans garder un plan pour une simple
recette de publication.

Le plan reste `partial` tant que cet écart de parcours demeure. La qualification
d'un éventuel moteur serveur n'est plus une condition de clôture. Toute évolution
structurelle retenue nécessite sa décision ; toute modification de parcours appelle
les guides FR/EN, `make docs-prepare` et la revue du diff. `make validate` reste
exclusivement à la main de l'utilisateur.
