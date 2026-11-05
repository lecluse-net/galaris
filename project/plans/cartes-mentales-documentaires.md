# Cartes mentales documentaires natives Galaris

- Statut : `design` — orientation produit retenue ; implémentation non commencée.
- Date : 2026-11-05.
- Demande : un type de document « Carte mentale », avec organisation automatique,
  contenus documentaires Galaris et plusieurs thèmes au choix.
- Référence d'interaction souhaitée : « Planner ». L'application exacte et les gestes
  à reprendre restent à identifier ; aucune fidélité à cette référence n'est démontrée.
- Ce plan ne constitue pas une autorisation de coder, de déployer ou de créer un commit.

## 1. Résultat attendu et choix retenus

Créer une carte dans la bibliothèque Documents, construire ses branches au clavier ou
à la souris, enrichir ses nœuds avec les mêmes contenus que les documents Texte et
retrouver l'ensemble après fermeture et réouverture. Galaris calcule la disposition :
l'utilisateur choisit la structure, l'ordre et le contenu, sans placer les éléments
manuellement. La carte peut être insérée dans un document Texte ; un clic sélectionne
son bloc et affiche les commandes permettant notamment de l'ouvrir pour la modifier.

L'éditeur et son expérience sont propres à Galaris. Vue Flow et l'intégration d'une
application complète de carte mentale ne sont pas les solutions retenues. Une petite
bibliothèque de calcul de disposition reste possible, derrière un adaptateur interne,
si elle répond au besoin démontré. Le format documentaire reste indépendant de ce moteur.

Garanties à livrer ensemble :

1. Placement automatique, branches repliables et navigation au clavier.
2. Parité avec les contenus actuellement intégrables dans les documents Texte, dont
   agents, références internes, liens web, images, médias et contenus interactifs.
3. Identité, droits, classement, pièces jointes et révisions du domaine Document.
4. Aperçus, insertion dans les documents et barre contextuelle avec ouverture/édition.
5. Plusieurs thèmes sélectionnables, persistants et compatibles clair/sombre.
6. Conservation du contenu et des brouillons lors des erreurs et conflits.

Les étapes intermédiaires peuvent qualifier un sous-ensemble, mais une livraison limitée
au texte, aux images ou aux URL ne réalise pas la demande de parité documentaire.
La collaboration temps réel, un tableau blanc libre et l'import de tous les formats
externes ne sont pas des prérequis. Ils ne doivent pas détourner le premier parcours.

## 2. État actuel vérifié et consommateurs à préserver

La revue porte sur le checkout de développement, qui contient déjà d'autres changements
documentaires. Relire ces surfaces avant l'implémentation ; préserver ces travaux.

| Surface existante | Conséquence pour le chantier |
|---|---|
| `back/app/document/type_registry.py`, `document_types.py`, `schemas.py` | Les formats publics actuels sont Texte/Données. Étendre validation, valeurs initiales, extraction et contrats ; le registre seul ne suffit pas. |
| `back/app/document/models.py` | Contraintes de type/contenu et discriminant ORM distinguent encore Texte/Données. Une nouvelle valeur exige une évolution explicite, avec DbAdmin. |
| `front/app/document/documentTypes.ts`, `components/DocumentEditor.vue` | Contributions asynchrones éditeur/aperçu ; des sélections explicites de types restent à élargir. |
| `front/core/util/components/RichTextEditor.vue`, `RichText.vue`, `tiptapContent.ts` | Réutiliser le modèle éditorial, les ressources et interactions existants ; le lecteur générique reste inerte pour les scripts. |
| `front/resourcePicker.vue`, `resourceEmbeds.vue`, `resourceDetails.vue`, `front/core/util/richText.ts` | Réutiliser sélection, URI canoniques, rendu des références, détails et navigation, sans nouveau catalogue parallèle. |
| `front/app/document/components/DocumentApplicationBlock.vue`, `back/app/document/document_app_service.py` | Runtime et accès applicatif sont aujourd'hui liés au HTML documentaire ; accueillir du HTML dans un nœud ne rend pas ce contrat compatible automatiquement. |
| `document_cloning.py`, `document_export.py`, `document_thumbnail_service.py` dans `back/app/document` | Vérifier copie des assets, conservation par les révisions, rendus dérivés et droits actuels du lecteur. |
| `front/core/util/workingDocumentEditor.ts`, `front/app/document/documentEditor.ts` | Préserver ouverture en panneau/modale, aperçus, historique de navigation et lecteurs existants. |
| `back/app/document/tests/test_typed_documents.py`, `test_document_thumbnails.py`, `test_document_apps.py` | Étendre les garanties communes existantes avant d'ajouter des suites distinctes. |

Les [documents typés](../decisions/0252-typed-documents.md), le
[contrat éditorial](../../docs/fr/dev/editorial-html.md) et les
[applications HTML](../../docs/fr/dev/document-apps.md) sont les références actuelles.
Le [plan plugins](infrastructure-plugins-galaris.md) évoque des types spécialisés :
ce chantier ne dépend pas de la réalisation d'un système de plugins.

## 3. Modèle documentaire proposé

### Identité et contenu

Ajouter une contribution native sous `app.document` et `front/app/document`, avec le
code proposé `mindmap`. Conserver `document://<uuid>` ; aucun schéma d'URI supplémentaire,
aucune bibliothèque ou politique de partage parallèle. Memory reste privé et Process
conserve ses définitions BPMN ; une carte n'est ni un graphe Memory ni un processus.

Stocker un JSON versionné dans `documents.content`, avec les révisions Document communes.
Le média proposé est `application/vnd.galaris.mindmap+json`, à figer avec le contrat.
Cette enveloppe JSON n'est pas du HTML et ne devient pas un Dataset. Elle contient :

- la version du format et du profil éditorial des corps de nœuds ;
- une racine, des clés stables de nœuds, leurs parents et leur ordre ;
- un titre court et un contenu documentaire riche facultatif par nœud ;
- le thème et sa version, ainsi que l'orientation de la carte ;
- les références et options nécessaires aux blocs documentaires.

Les clés de nœuds sont des identifiants locaux au contenu, pas de fausses clés étrangères
SQL. Le backend valide unicité, parents existants, absence de cycle, racine unique,
structure et limites de profondeur/taille/nombre de nœuds. Le HTML de chaque corps suit
le profil Document existant. Refuser atomiquement une source invalide, sans écraser la
dernière révision valide ; annoncer explicitement une version de format non supportée.

Les positions calculées, dimensions mesurées, URL Blob et DOM des aperçus ne sont pas
des données éditoriales. Zoom, sélection et repli temporaire restent des états de vue
et ne créent pas une révision par interaction. Définir une politique distincte si un
repli doit ensuite être enregistré pour une présentation.

### Sauvegarde, recherche et agents

Réutiliser les contrôles de révision et de métadonnées Document. Sérialiser les sauvegardes
et conserver les nouvelles éditions arrivées pendant une requête. Une réponse tardive
ne remplace ni une autre carte ni un brouillon plus récent. Conflit, coupure, navigation
et fermeture doivent préserver les modifications selon les mécanismes existants.

Annuler/rétablir couvre les changements de structure, de contenu, de thème et d'orientation,
avec une frontière explicite entre saisie de texte et commande de branche. Restaurer une
révision rétablit le contenu de la carte, sans restaurer d'anciens droits ou métadonnées.

Définir l'extraction textuelle déterministe des titres et corps, avec leurs chemins de
branches, pour la recherche et les résumés. Exclure DOM de rendu, scripts exécutés et
contenu de ressources liées : une référence n'est pas une copie à indexer.
Qualifier les consommateurs de résumé/rappel selon les contrats Document/Memory actuels.

Prévoir création, lecture et modification par les agents via les surfaces File Share
existantes, avec le même format validé, les mêmes ACL et la révision attendue. Définir
la représentation textuelle utile et les limites de lecture sans transformer une
pagination de JSON en source réinscriptible complète. Mettre à jour le skill runtime
Galaris lorsque ce support existe ; ne pas imposer de nouvel outil MCP sans besoin établi.

## 4. Édition des branches et disposition automatique

Le premier prototype doit démontrer ces interactions avant de généraliser l'éditeur :

- Tab : ajouter un enfant ; Entrée : ajouter un frère quand le focus porte sur la branche.
- Flèches : naviguer entre branches ; commandes accessibles pour replier/développer.
- Pendant la saisie riche, conserver les gestes natifs du contenu : Entrée dans un
  paragraphe, Tab dans un tableau ou un formulaire. Ne pas détourner ces touches.
- Réordonner une branche ou changer son parent, avec équivalent clavier et annulation.
- Suppression d'une branche avec descendants explicite ; empêcher tout rattachement
  cyclique. Un déplacement modifie l'arbre, jamais des coordonnées libres.
- Zoom, recentrage et navigation tactile ; sélectionner/éditer/utiliser un contenu ne
  doit pas déplacer involontairement la carte.

Rendre les nœuds avec les composants documentaires Galaris, les liaisons par un dessin
adapté, et mesurer leurs dimensions réelles. Une image chargée, un aperçu résolu, un
changement de police, de thème ou de largeur peut exiger un nouveau calcul de disposition.
Regrouper ces calculs, ignorer leurs résultats périmés et stabiliser la branche active
ainsi que le cadrage. Éviter chevauchements, contenu rogné et oscillations de mesure.

Orientations cibles : autour du sujet central, vers la droite, de haut en bas. Séparer
ce choix du thème et préserver l'ordre des enfants. La répartition gauche/droite doit
être déterministe et éviter de changer toutes les branches après une petite modification.

Qualifier un algorithme adapté aux dimensions variables ; une bibliothèque de disposition
peut être retenue après examen de licence, maintenance, compatibilité et comportement
mesuré. Les noms évoqués pendant la recherche ne constituent pas un choix de dépendance.
Le DOM, les contenus Galaris et les commandes restent sous contrôle de l'application.

## 5. Parité des contenus documentaires

Établir au lot 0 l'inventaire réel des insertions du profil Document, y compris celles
issues du collage, du téléversement et des contributions métier. Cette matrice devient
le périmètre de réception ; les exemples ci-dessous ne constituent pas une liste fermée.

| Famille | Garantie dans un nœud |
|---|---|
| Texte riche, listes, tableaux, code, équations | Même source éditoriale, édition, restitution et conservation après réouverture. |
| Agents et autres ressources Galaris actuellement intégrables | Même sélecteur, référence canonique, icône, aperçu, détail et action d'ouverture selon les droits. |
| Documents Texte, Données et cartes mentales | Référence indépendante ; aperçu et ouverture du bon éditeur, sans appropriation du contenu. |
| Liens web | Validation, ouverture et cartes d'aperçu selon les comportements actuels. |
| Images, fichiers et médias pris en charge | Insertion, résolution, lecture et copie avec leurs URI et limites actuelles. |
| HTML, formulaires, CSS/JavaScript et scènes actuellement admises | Même isolation et pont de capacités, sans exécuter le code dans le DOM des nœuds. |

Partager les composants, codecs, contributions et opérations existants. Extraire seulement
les responsabilités dont la réutilisation est démontrée ; ne pas dupliquer Tiptap, les
barres d'insertion ou le registre des ressources. Les contributions métier passent par
les ports existants : `front/core` ne dépend pas directement de `front/app`.

Limiter les éditeurs riches montés simultanément, tout en conservant le contenu et les
actions des autres nœuds. Un lecteur générique inerte ne remplace pas le runtime requis
pour les formulaires. Définir explicitement le montage et l'arrêt des parties interactives
à l'ouverture, au repli, à la navigation et à la modification de la carte.

Les pièces jointes natives appartiennent au document Carte mentale. Réutiliser les
mécanismes existants de stockage immuable et de rétention historique. Déplacer un nœud
dans la même carte préserve ses assets ; copier vers une autre carte doit relire les
droits, copier/remapper les pièces jointes nécessaires et publier un résultat cohérent.
Un échec ne laisse ni contenu partiel enregistré ni nettoyage silencieusement perdu.

Pour les applications, définir une identité stable par nœud/bloc, un espace de noms
sans collisions entre alias et la résolution serveur des déclarations depuis le JSON
persisté. Le serveur doit vérifier les nœuds et révisions courants, sans faire confiance
aux déclarations du navigateur. Les consentements restent personnels, liés à la révision,
distincts des ACL et impossibles à accorder par HTML/SDK/MCP ; les quotas restent communs.
Le parcours d'accord encore ouvert dans le [plan applications](programmes-documentaires-json.md)
doit être résolu ou signalé comme dépendance non satisfaite, jamais contourné dans les tests.

## 6. Thèmes et présentation

Livrer un sélecteur avec des vignettes de la carte courante, une prévisualisation réversible
et une application explicite. Les vignettes n'exécutent pas les applications, ne lancent
pas une nouvelle collecte de ressources et ne modifient pas le document.

Catalogue initial proposé, à qualifier visuellement :

| Thème | Intention |
|---|---|
| Sobre | Nœuds discrets, traits fins, couleurs limitées. |
| Branches colorées | Famille Solaire stable par branche principale, héritée par ses descendants. |
| Cartes | Cadres et surfaces adaptés aux images et aperçus riches. |
| Organique | Liaisons courbes et formes arrondies. |
| Présentation | Typographie plus grande et lisibilité à distance. |

Chaque thème définit formes, traits, typographie et couleurs à partir des tokens exacts
de la [palette Solaire](../../docs/fr/dev/palette-solaire.md). Proposer une variante claire
et sombre suivant l'application, sans modifier le contenu lors d'un changement global.
Conserver les couleurs et sens propres aux ressources intégrées ; ne pas réécrire le
HTML/CSS de l'utilisateur pour appliquer le thème de la carte.

Le thème et sa version sont enregistrés avec la carte et ses révisions ; ses rendus
dérivés sont invalidés après une modification persistée. Préserver les thèmes historiques
ou leur migration explicite. Ne pas faire dépendre les anciennes cartes d'un catalogue
mutable ; un thème inconnu doit conserver la source et proposer un rendu de repli lisible.
Le choix de thème ne modifie ni références, ni arbre, ni assets, ni contenu des nœuds.

## 7. Insertion, navigation et rendus

Étendre l'insertion documentaire existante pour choisir/créer une carte. Le bloc inséré
conserve sa référence et ses paramètres d'affichage ; il ne contient pas un duplicata
éditable de son JSON. Un clic sélectionne le bloc dans l'éditeur Texte ; la barre contextuelle
propose Ouvrir, Modifier si autorisé, Agrandir, Copier le lien, Ajuster l'affichage,
Remplacer et Retirer du document. Retirer le bloc ne supprime pas la carte.

L'ouverture et le retour utilisent la navigation documentaire existante. Conserver
position de lecture et brouillon du document hôte ; au retour d'une modification,
actualiser l'aperçu sans écraser le contenu hôte. En lecture seule, l'accès à la carte
et sa consultation restent possibles ; ne pas masquer ces actions derrière l'édition.

Par défaut, le bloc consulte la dernière révision autorisée. Prévoir une option explicite
de révision figée. Distinguer version du bloc hôte, version de la carte et état courant
des ressources référencées : figer la carte n'archive pas implicitement les documents liés.
La fidélité visuelle d'un export conservé exige son propre snapshot statique autorisé.

Prévenir les expansions récursives de cartes/documents, y compris A → B → A : bornes de
profondeur et de ressources, détection des visites, lien de remplacement exploitable.
Conserver les références même si leur aperçu ne peut pas être développé.

Les miniatures, historiques et exports sont statiques. Leurs captures utilisent le rendu
autorisé sans rejouer les scripts ni écrire dans un Dataset. Une capture indisponible
produit un état ou une erreur explicite, jamais une réussite avec contenu manquant.
Qualifier lisibilité et découpage des grandes cartes pour impression/PDF ; l'export
du format natif préserve le JSON et ses assets, indépendamment d'un export visuel avec perte.

## 8. Droits, caches et échecs

Chaque lecture de carte, de ressource, de pièce jointe et de rendu dérivé applique les
droits actuels du lecteur, humain ou agent. Partager un document hôte ne partage ni sa
carte intégrée ni les ressources de celle-ci. Une ressource inaccessible présente un
état neutre, sans titre ou aperçu récupéré au nom de l'auteur. Distinguer les libellés
rédigés volontairement dans la carte des informations résolues depuis une autre source :
révoquer l'accès à la source ne peut pas retirer une copie déjà rédigée dans le contenu.

Séparer rendus de la source et enrichissements dépendant des droits du lecteur. Ne pas
réutiliser une miniature contenant des informations privées entre deux lecteurs. Définir
les clés/invalidation des caches pour révision, thème, assets et dépendances autorisées ;
ne pas considérer le seul UUID de la carte comme une clé suffisante. Revérifier l'accès
avant de publier un rendu après une attente ; annuler les requêtes au changement de contexte.

Charger les aperçus à la demande avec concurrence et caches bornés. Un échec isolé ne
bloque pas l'arbre entier ; prévoir attente, refus, erreur et nouvelle tentative sans
boucle infinie. Tester révocation, suppression, réponse tardive et restauration pendant
le chargement. Ne pas promettre l'effacement rétroactif d'un export déjà téléchargé.

## 9. Lots de réalisation et critères de passage

| Lot | Travail | Preuve exigée avant le lot suivant |
|---|---|---|
| 0 — Référence et prototype | Identifier Planner, inventorier les insertions, consulter `/graphic-reference`, maquetter les gestes ; qualifier disposition et un nœud riche représentatif. | Une carte synthétique avec agent, document lié, image et formulaire se réorganise sans placement manuel ; clavier, dimensions tardives et deux thèmes sont démontrés. Lever les limites du runtime et de ses consentements avant de promettre la parité. |
| 1 — Contrat Document | Format versionné, contraintes/discriminant, contribution native, validation, extraction, révisions, bibliothèque, File Share/agents et assets. | Créer/lire/modifier/rouvrir/restaurer via API et agents ; refus d'ACL et conflit réels ; Texte/Données préservés. Évolution du schéma par DbAdmin. |
| 2 — Éditeur automatique | Commandes de branches, clavier, contenu riche réutilisé, mesure et recalcul, undo/redo, autosauvegarde. | Parcours complet sans positionnement manuel ; aucun écrasement de brouillon ou réponse périmée ; gestes natifs du contenu préservés. |
| 3 — Parité documentaire | Couvrir toutes les familles inventoriées, médias et applications, copie/remappage des assets et consentements. | Matrice de parité remplie avec preuves ; refus et erreurs exercés avec vrais composants/services, sans accord injecté en coulisses. |
| 4 — Thèmes | Catalogue, variantes clair/sombre, vignettes, prévisualisation, persistance/versionnement. | Annuler/appliquer/rouvrir/restaurer ; contenu et références identiques après changement ; sélection conservée lors des calculs. |
| 5 — Intégration et exports | Blocs dans Texte, barre contextuelle, navigation aller-retour, aperçus, révision figée, récursion bornée et exports. | Modifier depuis le bloc, revenir et voir le rendu actualisé ; refus indépendants ; PDF/archive sans réexécution ni fuite. |
| 6 — Qualification et documentation | Parcours assemblés, mobile, mesures, contrôles, guides FR/EN et décision d'architecture. | Critères ci-dessous vérifiés ; limites restantes explicites ; aucun sous-ensemble présenté comme parité complète. |

Les lots préparent une livraison cohérente, sans créer de dépendance au chantier plugins
ou à une refonte générale des documents. Revoir le diff et les risques à chaque frontière
partagée avant de généraliser aux autres consommateurs.

## 10. Vérification et réception

Partir du [catalogue fonctionnel](../../docs/fr/dev/functional-tests.md). Réutiliser ou
paramétrer les suites typed-documents, document-resources, document-apps, document-thumbnails,
document-authoring et context-menus. Ajouter une couverture propre aux cartes pour les
invariants qui n'existent pas encore ; conserver des données entièrement synthétiques.

| Garantie | Vérification attendue |
|---|---|
| Arbre valide et conservation | Tests purs de racine/ordre/parents/cycles et sérialisation ; annulation complète et lecture de versions antérieures. |
| Persistance et accès | Intégration PostgreSQL/API/File Share avec vrais services, deux lecteurs, révisions concurrentes, restauration et assets historiques. |
| Édition des contenus | Tests de composants réels sur familles distinctes ; sauvegarde/réouverture, collage, médias, détails de ressources, formulaires et échecs de chargement. |
| Organisation automatique | Interactions navigateur après insertion/suppression/repli et chargement tardif ; absence de chevauchement fonctionnel et de contenu rogné, sans figer des coordonnées ou styles. |
| Thèmes | Conservation de source, référence et sélection ; annuler/appliquer/restaurer. Inspection visuelle de chaque thème en clair/sombre ; pas de snapshots permanents de goûts esthétiques. |
| Intégration | Quelques E2E traversant bibliothèque → carte → document Texte → modification → retour, avec droits indépendants et erreurs réseau. |
| Runtime et export | Consentement/refus/révocation, deux nœuds avec mêmes alias, changement de révision et réponse tardive ; capture sans nouvelle exécution ni effet Dataset. |
| Accessibilité et petits écrans | Clavier complet, focus, menus nommés, fermeture des dialogues par fond, alternative structurée à la carte ; mobile sous 1024 px uniquement. |
| Frontières existantes | Texte/Données, partage, recherche, pièces jointes, résumés et lecteurs conservés ; contrôles d'architecture et parité i18n. |

Mesurer ouverture, ajout d'une branche, recalcul après image/aperçu, mémoire et nombre
de requêtes sur un corpus synthétique commun de 100, 500 et 1 000 nœuds, dont une carte
profonde et une carte riche. Ces tailles sont des paliers de qualification, pas des
capacités déjà garanties. Fixer les budgets au lot 0 et comparer les candidats dans les
mêmes conditions ; ne pas annoncer de gain sans mesure. Vérifier files et mémoire bornées,
annulation à la fermeture et absence de chargement systématique de toutes les ressources.

### Parcours de réception français/anglais à reporter dans les guides lors de la livraison

- **FR** : créer une Carte mentale, ajouter/réorganiser des branches automatiquement,
  insérer agent, lien, image et document, utiliser un contenu interactif autorisé,
  choisir un thème, fermer/rouvrir, intégrer dans un Texte, ouvrir Modifier depuis sa
  barre contextuelle, revenir, vérifier l'aperçu, puis exporter. Un second lecteur
  exerce les refus et une révocation sans fuite ni perte du contenu hôte.
- **EN**: create a Mind Map, add and reorganize branches with automatic layout, insert
  an agent, link, image and document, use authorized interactive content, choose a
  theme, close and reopen, embed the map in a Text document, open Edit from its context
  toolbar, return, check the updated preview and export. A second reader exercises
  access denials and revocation without disclosure or loss of the host document.

À la réalisation, mettre à jour les guides Documents et Navigation FR/EN, le catalogue
fonctionnel, le contrat éditorial et le skill runtime selon les surfaces livrées.
Documenter le choix structurel dans `project/decisions/` lorsque les contrats sont figés,
sans présenter ce plan comme du runtime existant. Les guides actuels restent exacts
pendant la conception : la carte mentale n'y est pas annoncée comme disponible.

Utiliser les cibles Make ciblées en conteneurs pour tests backend, composants/E2E,
`make typecheck`, `make architecture-check`, `make project-context` et `make docs-prepare`
selon les changements. `make validate` reste réservé à l'utilisateur. Terminer par
la revue du diff et `git diff --check`. Tenir l'entrée de ce plan à jour à chaque
changement de statut ; aucune phase n'est aujourd'hui implémentée ou qualifiée.
