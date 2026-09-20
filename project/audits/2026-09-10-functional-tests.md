# Revue fonctionnelle des tests — 10 septembre 2026

Demande : partir du métier, module par module, et protéger les fonctionnalités sans figer
les détails d’anciennes demandes de présentation. Aucun commit ni accès à un compte externe.
Les changements applicatifs déjà présents dans le worktree sont conservés.

## Périmètre du commit de tests

Le commit demandé après cette revue isole les règles de maintenance, le catalogue, les
renforcements Messenger/Process/Dream/DbAdmin et les tests frontend/E2E applicables aux
surfaces déjà versionnées. Les adaptations des nouveaux fichiers HTML et Lab, les attentes
de migration HTML, le correctif documentaire et le contrôle de type CKEditor restent dans le
worktree avec leurs implémentations encore non committées. Les résultats ci-dessous portent
sur le worktree complet testé ; ils ne désignent pas une exécution du seul commit isolé.

## Portée

Le [catalogue FR](../../docs/fr/dev/functional-tests.md) et son
[équivalent EN](../../docs/en/dev/functional-tests.md) relient les modules déclarés, les
responsabilités et les suites qui les protègent. Les modules dont les tests étaient déjà
fonctionnels sont conservés. L’inventaire des suites et l’exécution complète ne constituent
pas une revue exhaustive de chaque assertion ni une preuve de toutes les combinaisons métier.
Les fournisseurs conditionnels partagent le catalogue et les suites de protocole : aucun
test artificiel n’est ajouté simplement parce qu’un package existe.

## Garanties reprises et contraintes abandonnées

| Domaine | Modification de la preuve | Contrainte abandonnée |
|---|---|---|
| Messenger → Task | Renforcement de `test_task_admission_is_idempotent_after_effect_commit` : retirer la première instance de la session, relire l’admission et vérifier qu’une redelivery au contenu différent ne remplace ni le titre ni l’objectif | Aucune ; la preuve existante devient plus discriminante |
| Process → Task | Trois scénarios DB `test_callback_completion_resumes_wait_once_and_survives_redelivery` : succès/erreur/annulation, mauvais jeton sans écriture, résultat relu, attente libérée, doublons et événements tardifs | Quatre variantes d’un test où verrou, DB et journal étaient simulés ; le test unitaire du snapshot moteur reste distinct |
| Conversation / LLM | Fixtures d’objectif conformes au contrat HTML existant ; assertions de projection et de contexte conservées | Ancienne représentation en texte brut, volontairement remplacée par ADR 0080 |
| Dream | Comparaison du contenu et de la révision avant/après l’ajout de provenance | Hypothèse de format texte brut dans un test dont le métier est la non-réécriture |
| DbAdmin | Le socle de contributions exigées reste présent et les contributions indépendantes restent extensibles | Égalité exhaustive de la liste des reconcilers, qui faisait échouer un ajout légitime |
| Frontières DB | Revue et déclaration du CLI d’audit HTML sous `__main__` comme racine autonome | Aucune ; le contrôle AST d’architecture reste strict |
| Skills | Créer, prévisualiser, enregistrer et retrouver une compétence sur mobile/desktop ; annuler sans création ; révoquer les droits | Nombre de boutons, absence de retour à la ligne, quatre largeurs redondantes et largeur de modale |
| Goals / calendrier | Pause/reprise avec révision conservée ; choisir et vider les créneaux permis sur mobile | Nombre exact d’onglets, largeur de modale, déclaration CSS `touch-action` |
| Topics | Recherche serveur, sélection clavier, rejet des réponses tardives, accès à la page suivante dans le vrai composant | Faux `ref`/`watch` et extraction du script de `TopicSelect.vue` dans le test Node supprimé |
| Lab / incidents | Exécution des règles d’accès et du menu ; cartes selon les droits ; navigation de retour ; sélection des participants et invalidation d’aperçu ; sauvegarde des paramètres avec révision sur mobile | Regex de template, position du bouton Retour, libellé à côté de l’avatar, rangées de champs, couleur du pied de formulaire |
| Harnais / modèles | Diagnostic inaccessible puis rétabli ; disponibilité exprimée à l’utilisateur ; commande d’activation réellement exécutée | Classes CSS de succès/échec et regex du bouton de sauvegarde |
| Shell / statut | Connexion clavier, navigation autorisée, préférences persistées et état textuel courant | Couleurs exactes du shell/badge, nombre de cartes marketing |
| Mémoire / éditeur | Modifier une cellule sans perdre les autres ; appliquer et annuler un titre/une taille de texte ; préserver contenu en changeant de mode ; formatage au clavier | Bordure de focus, ombre, rangées et icônes de toolbar, taille de son bouton, position exacte du titre |
| Création documentaire | Correction du profil appliqué à la création, révélée par le parcours E2E HTML ; contenu interactif relu, texte visible indexé, écriture identique sans nouvelle révision et refus des profils protégés | Aucune ; le scénario rouge a conduit à corriger le service, pas à retirer son attente |
| HTML E2E | Créer via API, modifier dans l’éditeur, recharger et retrouver le code inerte dans la source | Ancien bouton d’aperçu supprimé du produit ; l’exécution isolée du lecteur reste prouvée par `interactive-documents.spec.mjs` |
| Code / source | Conserver le code, ses espaces, l’annulation et la coloration sans persister les marqueurs ; géométrie commune du texte et du calque pour garder le curseur aligné | Corps de 12 px, interligne de 18 px et RGB exacts des mots-clés ; nombre de sections Lab et d’onglets LLM |
| Impression / callouts | Contenu courant, images, contenu des encadrés, tableaux imprimables, nettoyage des temporaires | Couleur exacte des bordures et de l’encadré ; le fond de papier et le contenu non coupé restent fonctionnels |
| Résolution E2E | Résoudre au clavier, recharger, rouvrir et retrouver la preuve sans nouveaux messages ni travail rejoué | Présence de `q-table--grid` à un breakpoint précis |
| Lab E2E | Enregistrer sur desktop puis rouvrir objectif et historique sur mobile ; naviguer par les liens applicatifs ; isoler les noms des jeux par exécution navigateur | Compteur de balises `strong`, classe de tableau à 1023/1024 px, collisions de données entre scénarios |

Les contrôles de géométrie restants prouvent un usage (table non coupée, zoom d’image,
défilement, commande accessible) ou une modification de taille choisie dans le document.
La présence d’une mesure dans un test n’est donc pas à elle seule un motif de suppression.

Fichiers retirés après reprise des comportements :
`front/app/agent/agentSelectPresentation.test.mjs`,
`front/core/util/components/pageHeaderNavigation.test.mjs`,
`front/app/topic/components/TopicSelect.test.mjs`.
Le helper `expectSingleRow` n’a plus de consommateur et est retiré.
Une recherche AST de doublons exacts de fonctions backend, noms et docstrings exclus, n’a
pas trouvé de copie supplémentaire ; elle ne prouve pas l’absence de doublon sémantique.

## Défaut produit révélé par l’assemblage

Le premier passage E2E échouait sur les trois navigateurs avant l’ouverture de l’éditeur :
`create_item` appliquait systématiquement le profil `rich-text`, même à un document dont le
modèle public exposait `document`. Les scripts documentaires autorisés par ADR 0080 étaient
donc refusés à la création, alors que la modification utilisait le profil métier correct.
La création utilise désormais le même critère (document non protégé). Les mémoires et
documents protégés continuent de refuser ces scripts. Un document nouveau n’a pas encore de
pièces jointes : sa création refuse les références à des images, qui doivent être ajoutées
ensuite par le chemin existant de téléversement et de validation de propriété.

Les autres échecs Lab E2E provenaient d’un nom unique réutilisé entre navigateurs et des
requêtes de la page d’accueil interrompues par les navigations complètes du test. Les noms
sont isolés et les scénarios parcourent les liens de l’application sans masquer les erreurs.
La ressource d’exemple Three.js a aussi été recopiée à l’identique côté EN et son lien localisé,
conformément au contrôle de parité des assets documentaires. L’image isolée des mutations a
été reconstruite pour inclure la dépendance HTML déjà déclarée dans le worktree.
Une compilation ultérieure a révélé dans le nouveau `ckeditorCodeTools.ts` un accès à
`item.model` sur une union qui autorise aussi les séparateurs de menu. Un contrôle de présence
réduit le type avant cet accès ; la compilation frontend qui suit passe sans conversion forcée.

## État initial exécuté

- Parcours backend ciblés : 231 réussis, 2 échecs sur les attentes texte brut.
- Backend complet avec couverture : 3 463 réussis, 7 échecs, 1 ignoré ; 79 % sur la sélection
  critique agrégée. Les sept échecs précèdent les changements de tests de cette revue.
- Cinq échecs relevaient des attentes de contenu texte brut après le changement HTML déjà
  présent. Deux relevaient du reconciler supplémentaire et du CLI autonome d’audit HTML.
  Leur mise à jour suit le contrat existant, sans assouplir les règles métier ou les ACL.

## Validation finale

| Commande | Résultat exécuté |
|---|---|
| `make tests-coverage` | 3 474 réussis, 1 ignoré, 8 avertissements ; couverture agrégée de la sélection critique : 79,35 % (seuil existant : 70 %) |
| `make typecheck` | Pyright et vue-tsc sans erreur ; 212 tests Node réussis ; 4 823 paires EN/FR et messages chinois vérifiés |
| `make project-context architecture-check` | Cartographie régénérée, contrats satisfaits et 27 tests d’architecture réussis |
| `make tests-mutations` | Baselines vertes ; les quatre mutations contrôlées sont détectées : transition invalide, collaboration terminale rouverte, dépassement du budget enfant, double démarrage runtime |
| `make tests-front-components` | 111 scénarios réussis sur l’instantané frontend de ce passage |
| Composants ciblés après les dernières simplifications | 22 scénarios Code / Source / Lab / LLM réussis |
| `make tests-e2e` | 62 réussis, 1 échec MFA WebKit sur le second clic, sans requête réseau ; reprise ciblée décrite ci-dessous |
| `make tests-e2e ARGS='specs/reliability.spec.mjs --grep MFA --repeat-each=3'` | 9 réussis : 3 répétitions par navigateur après soumission clavier, sans retry |
| `git diff --check` | Sans erreur |

Les passages ciblés précédents comprenaient 122 tests backend pour les sept corrections
initiales, 48 tests Process et 54 tests documentaires/Goal. Le test ignoré est la qualification
DbAdmin sur table volumineuse, explicitement optionnelle. Les quatre mutations ne constituent
pas un score de mutation de tout le dépôt.

Journaux locaux conservés sous `artifacts/functional-tests/2026-09-10/` (répertoire ignoré par
Git). Le worktree évoluait aussi sur les chantiers HTML, palette et Lab : les nombres décrivent
les instantanés réellement exécutés, pas une certification de modifications ultérieures. La
suite complète de composants a été suivie de tests ciblés pour les derniers fichiers modifiés.
Les traces navigateur principales se trouvent sous `artifacts/front-components/` dans
`galaris-front-tests-local-228965` (complet) et `galaris-front-tests-local-259895` (ciblé), et
sous `artifacts/e2e/` dans `galaris-e2e-local-214073` (complet) et
`galaris-e2e-local-271502` (répétitions MFA).

Le test MFA utilise désormais Entrée depuis le champ effectivement saisi. Le passage WebKit
précédent avait laissé le formulaire affiché sans seconde requête après le clic ; la trace est
conservée, sans conclure à une correction de ce comportement du clic. Les nouvelles assertions
gardent le refus serveur, le succès du second facteur et la session restaurée. Le remplacement
d’un mot-clé de code utilise une sélection explicite puis une saisie, au lieu d’une position
supposée après Home et les flèches ; la conservation des espaces et l’annulation restent testées.

## Pérennité et limites

`AGENTS.md`, le guide de tests FR/EN et ADR 0079 imposent le choix d’une garantie avant le test,
la recherche de preuves existantes et la justification des changements d’attente. Les scénarios
restent dans les collectes Make/CI existantes ; aucune suite parallèle n’est ajoutée.
Les anciens tests unitaires qui exécutent de vraies règles avec doubles de transport restent
utiles, même s’ils utilisent `readFileSync` pour charger TypeScript. Leur simple présence ne
prouve pas qu’ils inspectent seulement le texte source.

Les droits des comptes externes, la qualité générale des modèles réels et la protection de
branche distante ne sont pas certifiés par cette intervention. Les répétitions CI et les
qualifications de livraison sont distinguées des commandes réellement exécutées ci-dessus.
