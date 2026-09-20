# 0125 — HTML interactif dans les documents

- Statut : Accepted
- Date : 2026-09-19
- Complète : [0124](0124-document-types-and-datasets.md)

## Décision

Les agents écrivent directement du HTML avec formulaires, CSS et JavaScript dans les documents
HTML existants. Aucun nouveau type, manifeste applicatif obligatoire ou stockage parallèle.
Les anciens blocs JSON `language-galaris-app` restent compatibles pour ne pas perdre le contenu
créé avec la première version ; les nouveaux documents utilisent du HTML ordinaire.

La barre d'outils CKEditor reste présente et le texte éditorial reste directement modifiable.
Aucun mode lecture/édition, bouton de démarrage ou assistant de formulaire supplémentaire.
Le code n'apparaît que dans le mode Source existant. Les zones pilotées par JavaScript sont
utilisables et conservées par le modèle de CKEditor comme objets opaques internes, sans cadre
visuel ni titre ajouté. La conversion restitue du HTML ordinaire en Source et à la sauvegarde.
Les régions interactives d'une page partagent le même contexte isolé.

Le HTML déclaré dans le document s'exécute à l'ouverture après sauvegarde. Les attributs
`data-dataset`, `data-dataset-alias` et `data-dataset-access` déclarent ses ressources. Le SDK
expose lecture, ajout et remplacement avec révisions. Le serveur vérifie les déclarations
persistées, les ACL actuelles de la page et des Datasets, et les privilèges d'édition. Il ne
dérive aucune autorité de l'auteur. Partager page et Datasets séparément.

Les déclarations HTML sont des demandes, jamais des autorisations. Chaque lecteur accorde
séparément un accès `read` ou `write` depuis l'icône Permissions du document. La table
`document_app_grants` conserve l'accord personnel pour le document, l'application, l'alias,
le Dataset et la révision exacte. Aucun accord implicite pour l'auteur ou les documents
existants ; toute modification de contenu ou restauration nécessite un nouvel accord.
Le SDK et MCP n'exposent pas la gestion de ces accords. Les ACL et privilèges restent des
conditions supplémentaires à chaque opération. L'affichage automatique reste inchangé.

La table `document_app_write_budgets` partage un budget persistant entre toutes les applications
d'un utilisateur sur un Dataset : 30 écritures et 4 000 000 octets résultants par fenêtre de
60 secondes. Le verrou du Dataset sérialise les workers ; le budget et la mutation sont
committés ensemble. Les écritures identiques consomment le quota, les conflits et JSON invalides
ne le consomment pas. Le JSON entrant et résultant est borné à une profondeur de 32, 20 000
nœuds, nombres finis et 2 000 000 octets UTF-8. Aucun schéma métier ni permission append-only
n'est ajouté : `write` conserve l'ajout et le remplacement complet.

Le sandbox comporte deux iframes opaques, sans `allow-same-origin`. Les scripts et événements
de formulaire sont permis ; CSP bloque les chargements réseau ordinaires, les soumissions
HTML natives, les sous-cadres et les workers. Le parent garde la navigation du cadre applicatif
sous son contrôle. Le MessageChannel ne transmet aucun jeton. Il borne les opérations Dataset
et abandonne les réponses tardives. Source, édition, changement de contexte et révocation
arrêtent le runtime. Les modifications committées restent durables.

L'ouverture d'une page exécute son code avec les droits et accords du lecteur pour les ressources
déclarées. Elle exige toujours la confiance dans l'auteur pour les données autorisées : la CSP
n'est pas un pare-feu universel ; les constructeurs WebRTC sont rendus indisponibles avant les
scripts. Le sandbox ne borne pas la consommation CPU. Les autres profils éditoriaux restent
statiques. Les lecteurs génériques, historiques et exports ne lancent pas les scripts et
n'exposent pas leur source dans la page ; l'édition et la restauration conservent cette source.
La création d'URL Blob est limitée aux MIME image/audio/vidéo passifs du contrat : une URL
HTML exécutable permettrait une navigation vers un nouveau contexte avant l'arrêt du cadre.

L'impression et les exports depuis l'éditeur capturent le rendu en cours dans le sandbox,
avec les valeurs des contrôles, résultats, styles calculés, SVG et canvas. Un MessageChannel
temporaire transporte la copie, nettoyée côté parent, sans exécuter de script dans le rendu
imprimé. Les URL sont retirées sur l'arbre inerte de DOMPurify avant de charger le cadre de
mise en page. La copie est toujours traitée comme non fiable, même si le SDK l'a capturée.
L'export ne rejoue aucun effet Dataset. Les styles sont recalculés sur une copie isolée à la
largeur imprimable avant d'être figés ; la largeur du panneau de l'éditeur ne détermine pas
la mise en page du PDF. Le changement de contexte annule une capture en cours.
Les anciens textes demandant un lancement manuel ne font pas partie de l'interface.

## Garanties

- Texte directement éditable, barre d'outils permanente, applications à leur place sans habillage.
- Le code n'est visible que dans Source, puis son rendu revient dans l'éditeur habituel.
- Formulaires directs et anciens manifestes survivent à l'édition, l'historique et la réouverture.
- Les droits du lecteur, ses accords personnels, les déclarations et les révisions bornent les accès Dataset.
- Les quotas transactionnels résistent aux rechargements, aux documents multiples et aux workers concurrents.
- Tests synthétiques DB, composants réels et parcours complet sur trois moteurs de navigateur.

Contrat : [FR](../../docs/fr/dev/document-apps.md), [EN](../../docs/en/dev/document-apps.md).
