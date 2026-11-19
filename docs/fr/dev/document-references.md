<p align="right"><strong>Français</strong> · <a href="../../en/dev/document-references.md">English</a></p>

# Références documentaires et modes d’affichage

Une occurrence de référence conserve une URI et son mode d’affichage dans le contenu hôte. Deux occurrences de la même URI peuvent prendre deux formes et conserver deux habillages. Le document Texte stocke le HTML éditorial. Une carte mentale utilise le même HTML dans le champ `body_html` du nœud. Le format Données conserve son JSON libre et peut être cité depuis les deux éditeurs.

## Modes proposés

| Type | Modes | Insertion par défaut |
|---|---|---|
| Page Web | Lien, Carte si l’hôte propose le service d’aperçu | Lien |
| YouTube reconnu | Lien, Carte si aperçu disponible, Intégré | Lien |
| Image prise en charge | Lien, Carte, Intégré | Intégré |
| Pièce jointe audio, vidéo ou PDF prise en charge | Lien, Carte, Intégré | Intégré |
| Autre pièce jointe | Lien, Carte | Carte à l’insertion depuis le sélecteur de ressources ou les pièces jointes |
| Processus natif et son exécution | Lien, Carte, Intégré | Lien en Texte, Carte en carte mentale |
| Documents Texte et Carte mentale | Lien, Carte, Intégré | Lien en Texte, Carte en carte mentale |
| Document Données, dossier ou contact | Lien, Carte | Carte dans le sélecteur de ressources |
| Agent, tâche, objectif, sujet, discussion, échange texte, appel, tour vocal, agenda | Lien, Carte | Lien en Texte, Carte en carte mentale |
| Souvenir privé, référence reconnue avec navigation seulement | Lien | Lien |
| Autre format documentaire | Lien, Carte, Intégré si un lecteur compatible est déclaré | Lien en Texte, Carte en carte mentale |

Le défaut d’insertion concerne le sélecteur d’objets. Le collage d’une URL dans une phrase, l’insertion d’un lien explicite et la lecture d’une occurrence historique conservent leurs règles. Une URI documentaire fournit le format réel et sa version via la lecture autorisée du document. Le MIME des fichiers détermine le lecteur des pièces jointes. Un provider image passe par les API File Sharing avec le contexte sélectionné et un contrôle de MIME et de taille avant la lecture de l’original.

## Composants et commandes

`DocumentLink`, `DocumentCard` et `DocumentEmbed` composent la même barre contextuelle avec `DocumentReferenceToolbar`. Chaque base choisit son mode actif. L’éditeur passe les modes disponibles et traite le changement comme une mutation du contenu, avec l’historique Tiptap, le contrôle de révision et le retour du focus. En carte mentale, la même mutation met à jour `body_html` du nœud sélectionné. L’ancre et le bloc hérités passent par les adaptateurs de rendu du lecteur et de Tiptap pour préserver la sérialisation portable.

Dans une carte mentale, la sélection d’une référence conserve son lecteur monté. Tiptap gère la sélection et les commandes contextuelles pendant que le lecteur affiche l’aperçu et, pour une image, la poignée de redimensionnement. La saisie ou une modification du contenu active le rendu de l’éditeur.

La carte mentale lit les URI et titres portables transmis par la bibliothèque lors d’un dépôt. Elle applique le mode d’insertion du type, et utilise l’envoi de pièces jointes du document hôte pour les fichiers locaux et le service d’import existant pour les images web acceptées. Le déplacement de branches reste interne à la carte et conserve les identifiants et descendants. Hors édition, le collage système utilise une ligne par enfant et une URL isolée devient un lien. Le presse-papiers des branches conserve les sous-arbres pour les opérations dans la même carte. L’éditeur de contenu riche traite le collage lorsqu’il est actif.

Une vue spécialisée ajoute ses boutons via `RegisterDocumentReferenceActions`. Elle fournit des `DocumentReferenceAction` avec `id`, `label` traduit, `icon` et `run`. Elle publie à nouveau ses actions quand leur disponibilité change et les retire au démontage. `ProcessPreview` expose par exemple l’ajustement du BPMN à la vue et le retour au diagramme parent. Les commandes sont associées à l’occurrence montée. L’éditeur reçoit seulement celles du bloc sélectionné. [Contrat des actions](../../../front/core/util/documentReference.ts) · [Exemple Process](../../../front/app/process/components/ProcessPreview.vue).

L’apparence est propre à l’hôte et à l’occurrence. Le bloc explicite Carte porte l’accent jaune Solaire dans Texte. En carte mentale, le nœud reprend l’accent de sa branche et porte l’unique bordure d’une carte, d’un document intégré seul ou d’un processus intégré seul. Cette bordure est visible en lecture, en sélection et dans l’export graphique. Les images s’affichent sans bordure dans la carte mentale, y compris en mode Carte. Le bloc explicite Intégré est transparent par défaut. La commande **Apparence** propose une couleur de bordure là où l’hôte la permet, et une ombre indépendante. Les lecteurs conservent leurs propres contrôles.

Dans les documents Texte et les cartes mentales, `ProcessThumbnail` adapte la hauteur des cartes de processus aux proportions de la miniature. Le lecteur `ProcessPreview`, utilisé en mode Intégré et dans les cartes historiques, suit la hauteur du diagramme zoomé. En mode Intégré, la zone défilante de `BpmnCanvas` reçoit le focus et les gestes dans le contenu de l’hôte. Les barres apparaissent lorsque le diagramme zoomé déborde. Le mode plein écran utilise la hauteur disponible.

Le format Texte fournit le lecteur `DocumentTextEmbed`. Il rend le contenu avec `EditorialContent` dans une page arrondie à défilement interne. `DocumentEmbed` fournit le cadre redimensionnable commun aux lecteurs de documents et de processus. En édition, le relâchement de la poignée ou une flèche au clavier enregistre la taille sur la référence du document hôte. La lecture seule applique la taille enregistrée. Un changement de dimensions met à jour le cadre du lecteur monté. La capture statique du document Texte utilise le contenu du lecteur au-delà de la zone visible et écarte la poignée.

## HTML persistant et compatibilité

```html
<p><a href="galaris://processes/controle" data-resource-mode="link">Contrôle</a></p>
<blockquote class="galaris-link-card" data-resource-mode="card">
  <p><a href="galaris://processes/controle">Contrôle</a></p>
</blockquote>
<blockquote class="galaris-link-card" data-resource-mode="embed" data-resource-border="#854CF0" data-resource-shadow="true">
  <p><a href="galaris://processes/controle">Contrôle</a></p>
</blockquote>
```

`data-resource-size="640x360"` enregistre la largeur et la hauteur en pixels CSS entiers, de 1 à 4096 par axe. L’attribut suit l’occurrence entre ancre, carte et bloc intégré. Seul le cadre Intégré applique la taille, dans la largeur et la hauteur disponibles. Une occurrence sans taille conserve les dimensions par défaut de son lecteur.

`data-resource-mode` accepte `link` sur une ancre, `card` ou `embed` sur `blockquote.galaris-link-card`, et `embed` sur une image documentaire, sa figure ou son conteneur en ligne. `data-resource-border` contient une couleur hexadécimale à six chiffres et `data-resource-shadow` vaut `true` quand l’ombre est activée. Une occurrence peut garder un fragment éditorial inerte dans `data-resource-image` ou `data-resource-card` pour retrouver, après réouverture, sa légende, sa taille, sa destination de clic ou ses métadonnées rédigées. Le nettoyage frontend et le codec backend contrôlent l’emplacement et la valeur. Les fragments sont bornés à 32 768 caractères. Les URI d’images conservées dans ces fragments participent au contrôle des pièces jointes et au remappage lors d’une copie. Le rendu et les instantanés n’exécutent pas ces fragments.

Les anciens liens, figures et `galaris-link-card` restent compatibles. Les cartes historiques de processus, médias et YouTube conservent leurs lecteurs. Le mode explicite Carte utilise un aperçu compact et le mode Intégré monte le lecteur. La lecture, l’impression ou une modification ailleurs dans le document ne convertissent pas une occurrence ancienne. Le mode, les paramètres et la source éditoriale appartiennent à la révision du document hôte. Le contenu vivant reste chez son propriétaire, y compris le BPMN et le graphe figé d’un run. [Codec éditorial](editorial-html.md).

## Ajouter un type ou un format

1. Déclarer la résolution et la navigation de l’URI dans la contribution `richContent.ts` du domaine. Fournir `card` et, si la contribution couvre plusieurs types, `canCard` pour filtrer ceux qui disposent d’un aperçu. `defaultMode` surcharge le choix de l’hôte quand le domaine a un défaut particulier.
2. Déclarer `embed` pour le type qui fournit un lecteur complet. Relier le lecteur au point de composition `resourceEmbeds.vue`. Employer la source authentifiée du domaine et les composants de lecture existants. Exporter une capture statique autorisée quand le lecteur sait la produire, et déclarer les actions propres à la vue avec le port ci-dessus.
3. Pour un format Document, déclarer `embed` dans la contribution de format et dans les capacités serveur. Le lecteur d’une archive native reçoit la source autorisée en lecture seule sur la révision chargée, via `DocumentContentSource`. `createFormat(host)` peut utiliser `host.DocumentLink`, `host.DocumentCard` et `host.DocumentEmbed` pour composer les références de son propre éditeur. Les formats qui partagent la surface HTML utilisent le contrat de références commun. [Façade des formats](document-formats.md).
4. Vérifier les modes offerts dans les deux hôtes, sauvegarder et rouvrir une occurrence, exercer les refus d’accès et le rendu statique. Ajouter un scénario pour la perte durable que le nouveau type pourrait introduire.

## Accès, imbrication et export

Dans une surface éditoriale documentaire, le clic simple sélectionne une référence
à un document. Le clic modifié par Ctrl ou Cmd emprunte le port de navigation
documentaire. L’espace qui possède l’historique détient aussi le mode plein écran.
`DocumentEditor` déplace son contenu dans un conteneur plein écran commun aux
formats et y expose les commandes d’historique. Les éditeurs Texte et Carte mentale
pilotent cet état depuis leurs barres d’outils.

Une référence utilise les droits actuels du lecteur sur la cible. Le document hôte et le document intégré ont chacun leurs droits. Le lecteur de document consulte sa cible dans le contexte du lecteur, utilise la file d’aperçus et annule une demande remplacée. Il recharge sa cible lors d’une invalidation documentaire. L’intégration porte une pile de documents par branche. Une répétition ou une profondeur dépassée affiche un lien de repli. Les lecteurs documentaires intégrés utilisent un rendu inerte des blocs HTML applicatifs.

L’impression, le PDF et le ZIP HTML utilisent des instantanés statiques. Les aperçus et lecteurs montés que le lecteur peut capturer sont intégrés dans la limite du budget de capture. Une capture indisponible d’une occurrence explicite conserve le repli éditorial. Les exports structurels de cartes mentales conservent les références portables. Une miniature publiée du document hôte s’appuie sur son instantané statique, sans développer les documents liés sous l’identité de l’auteur.
