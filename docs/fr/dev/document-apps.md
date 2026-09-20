<p align="right"><strong>Français</strong> · <a href="../../en/dev/document-apps.md">English</a></p>

# Formulaires et JavaScript dans les documents

Les documents HTML acceptent directement des formulaires, du CSS et du JavaScript.
L'agent écrit des balises HTML ordinaires ; aucun manifeste applicatif n'est nécessaire.
La barre d'outils CKEditor reste présente et le texte environnant reste éditable.
Il n'y a pas de mode lecture/édition supplémentaire, de bouton de démarrage ou d'assistant
« Ajouter un formulaire ». Le bouton **Source** existant donne accès au code.

Les formulaires s'affichent à leur emplacement dans le document. Leurs contrôles sont
utilisables ; les parties pilotées par le JavaScript ne sont pas éditées par le WYSIWYG.
Le code enregistré se lance à l'ouverture. Passer en Source, modifier le document ou changer
de contexte arrête le runtime ; le rendu reprend après une sauvegarde valide.
Les anciens manifestes `language-galaris-app` restent lisibles et exécutables sans montrer
leur JSON. Les nouveaux documents utilisent le HTML direct.

L'impression, le PDF, son partage mobile et l'archive HTML reprennent le rendu courant :
valeurs des champs, résultats calculés, styles, SVG et images des canvas. Ils capturent
la page ouverte sans relancer son code ni effectuer une nouvelle écriture Dataset.
La copie est statique et nettoyée avant export ; une capture indisponible signale une erreur
au lieu de remplacer le contenu par une invitation à démarrer. La mise en page est recalculée
à la largeur imprimable, avec les règles CSS adaptatives du document, indépendamment de la
largeur du panneau de l'éditeur. Cette préparation se fait sur une copie sans scripts et ne
redimensionne pas le document ouvert. Une capture est annulée si son document change.

## Exemple avec Dataset partagé

Créer un Dataset contenant `[]` avec `file_create(path="document://", name="Réponses",
document_type="dataset", content="[]")`, puis utiliser son URI réelle :

```html
<p>Texte modifiable dans l'éditeur habituel.</p>
<form id="entry" data-dataset="document://11111111-1111-4111-8111-111111111111">
  <label>Réponse <input name="answer" required></label>
  <button>Enregistrer</button>
  <output id="status"></output>
</form>
<style>form { display: flex; gap: 1rem; flex-wrap: wrap; }</style>
<script>
document.getElementById('entry').onsubmit = async event => {
  event.preventDefault();
  const button = event.target.querySelector('button');
  button.disabled = true;
  try {
    const current = await galaris.datasets.read('entries');
    await galaris.datasets.append('entries', {
      answer: new FormData(event.target).get('answer')
    }, current.revision);
    document.getElementById('status').textContent = 'Enregistré';
    event.target.reset();
  } catch (error) {
    document.getElementById('status').textContent = error.message;
  } finally { button.disabled = false; }
};
</script>
```

`data-dataset` déclare la ressource. `data-dataset-alias` choisit son alias (`entries` par
défaut). `data-dataset-access` vaut `write` par défaut sur un formulaire et `read` sur les
autres éléments ; une valeur explicite prime. Déclarer plusieurs ressources avec des alias
différents, au maximum dix. Les déclarations contradictoires sont refusées.

Les outils `file_create`, `file_write`, `file_edit` et `file_append` acceptent ce HTML.
Lire avant de modifier et fournir la révision attendue. Partager séparément le document et
chaque Dataset avec `memory_sharing` puis `document_share` ; un lien n'accorde aucun droit.
Les types de document restent immuables. Les autres champs éditoriaux (Memory, Goal, Agent)
conservent leur profil statique et refusent les scripts.

## SDK et garanties

`galaris.datasets.read(alias)` renvoie `{data, revision}`. `append(alias, value, revision)`
ajoute une valeur JSON à un tableau racine ; `replace(alias, value, revision)` remplace le
contenu. Les deux mutations renvoient le nouvel état et alimentent l'historique du Dataset.
Plusieurs documents peuvent utiliser le même Dataset. Les droits sont ceux du lecteur
connecté, jamais ceux de l'auteur du code. Une déclaration n'accorde aucun privilège.

Une révision dépassée produit `error.code === 'conflict'`. Conserver la saisie et relire
avant de soumettre à nouveau. Aucun retry automatique d'écriture n'est effectué. Les autres
refus utilisent `permission_required`, `denied`, `failed` ou `limit`. Le serveur relit les déclarations persistées,
contrôle les droits de la page et du Dataset et verrouille les lignes avant mutation.
Les requêtes et réponses tardives sont abandonnées à la fermeture ; une écriture déjà
committée reste durable. Les déclarations du HTML direct utilisent l'identifiant technique
`document-html` sur la route existante `/memory/documents/{id}/apps/{app}/datasets/{alias}`.

## Isolation et limites

Le runtime est isolé dans deux iframes opaques, sans accès au DOM parent, aux cookies,
au stockage de Galaris, aux popups ou à la navigation du parent. Ce mécanisme est interne :
aucun cadre visuel, titre applicatif ou bouton supplémentaire n'est ajouté au document.
Le texte éditorial reste dans CKEditor ; la portion interactive est conservée comme source
opaque par son modèle, puis restituée en HTML ordinaire dans Source et à la sauvegarde.
Les régions interactives partageant des scripts sont réunies dans le même contexte isolé.

La CSP bloque les chargements réseau ordinaires, les soumissions HTML natives, les workers
et les sous-cadres. Embarquer les dépendances et utiliser JavaScript pour les formulaires.
Aucun jeton de session n'est transmis ; seul le pont borné vers les Datasets déclarés est
exposé. Les aperçus génériques, historiques et exports restent inertes et masquent le code
exécutable. La source est conservée pour l'édition et la restauration.

Ouvrir un document exécute son code : ne partager que du code de confiance, particulièrement
lorsqu'il accède à des données sensibles. La CSP n'est pas un pare-feu universel des API du
navigateur ; les constructeurs WebRTC sont rendus indisponibles avant le code applicatif,
sans possibilité de les redéfinir dans ce contexte. Le sandbox ne borne pas la consommation CPU. Le document
et le Dataset restent limités chacun à 2 000 000 octets. Voir la
[décision 0125](../../../project/decisions/0125-document-applications.md).

Les URL Blob créées par le code sont limitées aux MIME passifs `image/png`, `image/jpeg`,
`image/gif`, `image/webp`, `audio/mpeg`, `audio/ogg`, `audio/wav`, `audio/webm`, `video/mp4`,
`video/webm` et `video/ogg`. Les blobs HTML, SVG et sans type sont refusés : une navigation
vers du code Blob pourrait sinon créer un nouveau contexte avant l'arrêt par le parent.

## Autorisations personnelles et quotas serveur

L'accès Dataset est refusé par défaut, y compris pour les documents existants. Chaque lecteur
approuve les couples application–Dataset depuis l'icône **Permissions des applications** de
la barre du document. L'accord est enregistré en base, hors du HTML, pour cet utilisateur,
cette application, cet alias, ce Dataset et cette révision du document. Il ne se transfère
ni à un autre lecteur ni à un autre document. Toute modification du contenu ou restauration
nécessite un nouvel accord ; changer seulement le titre ne change pas la révision du contenu.
Les droits actuels de la page et du Dataset restent vérifiés à chaque appel. Retirer un accord
bloque les prochains appels ; les écritures déjà committées restent durables et des données
précédemment lues ne peuvent pas être retirées au code.

Les routes humaines `GET /memory/documents/{id}/app-permissions` et
`PUT /memory/documents/{id}/app-permissions/{app}/{alias}` consultent et modifient l'accord
avec `{document_revision, access: null | "read" | "write"}`. Elles ne sont exposées ni au SDK
ni aux outils MCP. L'écriture exige le privilège humain d'édition. Le document s'affiche
automatiquement même sans accord ; seules ses opérations Dataset sont refusées avec
`error.code === 'permission_required'`. Un accord `write` permet toujours **l'ajout et le
remplacement complet**, y compris à l'ouverture : examiner ensemble les sources et destinations
autorisées, car du code peut transférer des données entre elles.

Les écritures applicatives valident le JSON entrant et le résultat complet : nombres finis,
profondeur maximale 32, au plus 20 000 nœuds JSON et 2 000 000 octets UTF-8 après sérialisation.
Ce sont des bornes structurelles, pas un schéma de validation métier des champs. Un quota
transactionnel persistant limite chaque couple utilisateur–Dataset à 30 écritures et
4 000 000 octets de contenu résultant par fenêtre de 60 secondes. Documents, onglets et workers
partagent ce quota ; recharger ou réautoriser ne le remet pas à zéro. Les écritures sans
changement de contenu consomment aussi le quota. HTTP 429 porte `Retry-After: 60` et devient
`error.code === 'limit'`. Attendre puis relire avant une nouvelle soumission. Les données
invalides et les conflits n'altèrent ni le Dataset ni le quota d'écritures réussies.

Le HTML capturé pour l'export reste non fiable. Le nettoyage et le retrait des URL s'effectuent
sur l'arbre inerte de DOMPurify avant chargement du cadre de mise en page sans scripts. Les tests
adversariaux couvrent les ressources externes, le code injecté, WebRTC, la saturation du pont,
les navigations Blob exécutables, la copie entre Datasets sans accord, la révocation et les quotas entre workers. Ils ne constituent
pas une garantie d'absence de toute faille navigateur ou de toute saturation CPU/mémoire.
