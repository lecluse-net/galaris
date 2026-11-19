# Affichage des références dans les documents

Statut `partial` · Texte et Carte mentale partagent la première implémentation. Le [contrat technique](../../docs/fr/dev/document-references.md) décrit les capacités livrées. Les lecteurs spécialisés supplémentaires et la fidélité des exports de chaque format se qualifient à mesure de leur ajout.

## Comportement attendu

Une occurrence pointe vers l’URI canonique de sa ressource et possède un mode d’affichage.
La même ressource peut apparaître plusieurs fois dans un document, sous des formes différentes.

| Mode | Rendu |
|---|---|
| **Lien** (`link`) | Titre cliquable et, si le type en fournit une, une icône discrète. Le texte choisi par l’auteur reste prioritaire. |
| **Carte** (`card`) | Aperçu compact qui reprend le rendu actuel des pièces jointes et des références documentaires. Il peut contenir une miniature, un avatar et les métadonnées prévues par le domaine. |
| **Intégré** (`embed`) | Contenu complet dans la surface hôte, avec le lecteur du type. Par exemple, un BPMN navigable ou une image complète. La ressource source reste consultable et modifiable à son emplacement habituel selon les droits du lecteur. |

Remplacer le bouton aux deux rectangles par un sélecteur **Lien · Carte · Intégré**, dans la barre contextuelle de la référence. Chaque mode pris en charge a un bouton, aucun bouton n’apparaît pour un mode indisponible et le sélecteur est omis si un seul mode est possible. En mode édition, les commandes existantes de sélection, d’ouverture, de copie, de retrait et de propriétés restent accessibles. En lecture seule, le lecteur peut ouvrir la cible et manipuler son aperçu ou son contenu intégré selon le type. Le sélecteur suit le modèle de choix unique de la [référence graphique](../../front/app/index/graphic-reference/GalleryToggles.vue), avec état actif, libellés traduits, clavier et focus visible.

## Modes proposés par type de ressource

Le défaut s’applique à une **nouvelle insertion d’objet**. Une demande explicite, comme « Insérer un lien », prime sur ce défaut. Les modes enregistrés et les gestes existants du format Texte (collage d’un lien dans une phrase, import d’une image, collage d’une URI Données en carte, etc.) gardent leur interprétation.

| Ressource | Modes proposés | Défaut Texte | Défaut Carte mentale |
|---|---|---|---|
| Page Web HTTP(S) | Lien, Carte si le service d’aperçu sait la traiter | Lien | Lien |
| Vidéo YouTube reconnue par le lecteur existant | Lien, Carte si aperçu disponible, Intégré | Lien | Lien |
| Image reconnue, notamment une pièce jointe image | Lien, Carte, Intégré | Intégré | Intégré |
| Pièce jointe audio, vidéo ou PDF prise en charge | Lien, Carte, Intégré | Intégré | Intégré |
| Autre pièce jointe ou fichier d’un fournisseur | Lien, Carte si aperçu compact ou fiche de fichier disponible | Carte pour une PJ, Lien pour une référence de fournisseur | Carte si disponible |
| Document Texte | Lien, Carte, Intégré | Lien | Carte |
| Document Carte mentale | Lien, Carte, Intégré | Lien | Carte |
| Document Données (`data://`) | Lien, Carte de métadonnées | Carte | Carte |
| Dossier documentaire | Lien, Carte | Carte | Carte |
| Document d’un autre format, dont Dessin et formats de plugins | Lien, Carte si aperçu disponible, Intégré si le format fournit un lecteur embarquable compatible | Lien | Carte si disponible |
| Agent | Lien, Carte avec l’aperçu d’agent | Lien | Carte |
| Contact | Lien, Carte avec l’aperçu de contact | Carte | Carte |
| Définition de processus natif | Lien, Carte avec aperçu compact, Intégré avec le diagramme BPMN navigable | Lien | Carte |
| Exécution de processus natif | Lien, Carte avec aperçu compact, Intégré avec le diagramme de l’exécution autorisée | Lien | Carte |
| Processus ou exécution externe | Lien, Carte si le domaine fournit les métadonnées, Intégré si le domaine fournit un lecteur complet compatible | Lien | Carte si disponible |
| Tâche | Lien, Carte | Lien | Carte |
| Objectif | Lien, Carte | Lien | Carte |
| Sujet | Lien, Carte | Lien | Carte |
| Discussion Messenger | Lien, Carte | Lien | Carte |
| Échange texte | Lien, Carte | Lien | Carte |
| Appel ou tour vocal | Lien, Carte | Lien | Carte |
| Agenda | Lien, Carte | Lien | Carte |
| Souvenir privé | Lien seul, selon les droits personnels en vigueur | Lien | Lien |
| Autre référence reconnue (événement, cycle d’objectif, compétence, connexion, espace de code, etc.) | Lien si une URI et une navigation prises en charge existent. Carte et Intégré sur déclaration du domaine. | Lien | Carte si déclarée, Lien sinon |

Une URL locale est résolue avant le choix du type, pour qu’un lien Galaris collé depuis le navigateur obtienne les mêmes capacités que son URI canonique. Le MIME vient des métadonnées autorisées du fichier. Le type d’un document vient de son format, de sa version et de la contribution effectivement chargée. La liste des modes offerts dépend aussi de l’emplacement. Un lien peut rester en ligne dans une phrase. Les cartes et lecteurs de bloc s’insèrent à une position valide de l’éditeur, en préservant le texte adjacent et la structure de la liste, du tableau ou du paragraphe.

## Contrat partagé et responsabilités

Étendre le contrat [RichContentContribution](../../front/core/util/richText.ts). Chaque domaine conserve la résolution de ses URI, la recherche, le titre, l’icône et l’ouverture, et déclare les modes qu’il fournit, le mode par défaut et les éventuelles surcharges de défaut par hôte. Une même contribution peut distinguer plusieurs types, par exemple Contact et Souvenir. Les formats de document utilisent leurs contributions existantes, via [DocumentFormatContribution](../../front/app/document/documentFormats.ts), y compris les formats de plugins. Déclarer un aperçu ou un éditeur ne rend pas un format embarquable.

### Trois composants documentaires et leurs barres d’outils

| Composant | Rendu commun | Commandes de sa barre d’outils |
|---|---|---|
| `DocumentLink` | Ancre accessible, libellé et icône facultative. Le domaine fournit le titre, l’icône et la cible d’ouverture. | Ouvrir, Copier le lien, Modifier le libellé si permis, choisir le mode et retirer la référence. |
| `DocumentCard` | Aperçu avec titre, visuel et métadonnées fournis par le domaine. Réutiliser [ResourcePreviewBlock](../../front/core/util/components/ResourcePreviewBlock.vue), déjà utilisé pour les pièces jointes et le Chat. | Ouvrir, Copier le lien, choisir le mode et retirer la référence. Le type peut ajouter une action telle qu’Agrandir l’aperçu. |
| `DocumentEmbed` | Lecteur complet fourni par le domaine, avec chargement, repli, annulation et capture. Réutiliser le chargement à la demande de [resourceEmbeds.vue](../../front/resourceEmbeds.vue). | Ouvrir, Copier le lien, Apparence si l’hôte le permet, choisir le mode et retirer la référence. Un BPMN peut ajouter **Ajuster à la vue** ou **Diagramme parent**. Une image peut ajouter **Plein écran**. |

Chaque composant fournit sa propre petite barre contextuelle. Les trois barres réutilisent les boutons, groupes, infobulles et conventions clavier de la [barre d’outils documentaire](../../docs/fr/dev/document-formats.md#barre-doutils) et le même sélecteur de mode. Un composant spécialisé compose sa base et ajoute ses propres commandes à la barre de cette base. Il fournit des commandes typées avec un identifiant, un libellé traduit, une icône, un état de disponibilité et une action. Les commandes du type peuvent dépendre de la ressource ou de l’état du lecteur. Par exemple, **Diagramme parent** est disponible dans un sous-processus.

La vue hôte place la barre de l’occurrence active. En édition Texte, elle réutilise l’emplacement contextuel actuel. Elle maintient la sélection et le focus pendant l’usage des boutons, rend les commandes accessibles au clavier et sur mobile et applique les mutations éditoriales dans la transaction de l’hôte. Une bascule remplace la barre par celle du nouveau mode et rétablit le focus sur la référence ou sa commande équivalente. En lecture seule, l’hôte conserve ses gestes de navigation et expose les commandes autorisées dans le menu contextuel ou le lecteur existant. Une action métier utilise les droits et l’API de son domaine. Un retrait vise l’occurrence dans le document hôte.

Les vues spécialisent aussi le contenu par composition Vue, avec des propriétés et des emplacements de rendu typés. Un type qui fournit un titre et éventuellement une icône utilise directement `DocumentLink`. Un lecteur de processus ou de carte mentale se compose à l’intérieur de `DocumentEmbed`. L’hôte transmet ses paramètres de présentation, par exemple la bordure jaune de Texte ou la bordure du nœud.

Dans le HTML éditorial, les ancres et cartes restent portables, avec un adaptateur pour les [objets Tiptap](../../front/core/util/tiptapContent.ts) et pour le [lecteur HTML](../../front/core/util/components/RichText.vue). Ils partagent le même contrat de lien, de carte et d’intégration. Monter du Vue là où le rendu ou les interactions du type le demandent, en gardant les ancres ordinaires légères.

L’hôte déclare les modes autorisés à l’emplacement d’insertion et fournit la largeur, le contexte de lecture, l’habillage et les hooks de capture. L’éditeur, le sélecteur de ressources, les lecteurs et l’export utilisent la même résolution. L’ordre de décision est le mode explicitement demandé s’il est disponible, puis le défaut déclaré pour l’hôte, puis le défaut du type, puis Lien. En lecture, le mode enregistré prime. Si le lecteur disparaît ou échoue, utiliser la carte autorisée disponible ou un repli lisible vers la cible et conserver le mode enregistré. La perte de droits désactive les données chargées dynamiquement et laisse le libellé rédigé dans le document, avec un état neutre.

| Format hôte | Intégration |
|---|---|
| Texte | Lien en ligne ou autonome. Cartes et contenus intégrés dans le flux éditorial, avec le support d’image en ligne déjà disponible. |
| Carte mentale | Même contrat dans le `body_html` de chaque nœud, avec les défauts de la matrice. Le champ `link` historique garde sa navigation. Le nœud recalcule son encombrement quand un lecteur se monte ou change de taille, en conservant sélection, zoom et réorganisation des branches. |
| Données | Le corps reste du JSON libre. Une référence existante dans ses valeurs reste une valeur JSON. L’insertion et le sélecteur de rendu concernent les hôtes qui disposent d’une surface de composition. |
| Autre format | Le format peut exposer une zone d’insertion de références et la relier à son codec, à sa navigation et à son export. Le format définit si cette zone existe et les modes utilisables dans celle-ci. |

Le lecteur Texte peut afficher une Carte mentale et un nœud de carte peut afficher un document Texte, un autre format compatible ou un processus. Les composants intégrés reçoivent un contexte de lecture seule et réutilisent les API du propriétaire. Pour un processus natif, réutiliser [ProcessPreview](../../front/app/process/components/ProcessPreview.vue) pour le BPMN intégré. Le lecteur offre zoom, déplacement et navigation dans les sous-processus, avec ouverture explicite de la source pour les actions métier. Pour une exécution, il lit le graphe figé du lancement. Le lecteur de carte mentale conserve les interactions de lecture de l’arbre. Pour le HTML interactif, réutiliser la politique documentaire existante. Les lecteurs inertes, historiques et exports restent inertes. Tout lecteur interactif autorisé applique la sandbox et, le cas échéant, le consentement Données de la ressource et de la révision réellement exécutées. [Contrat des applications documentaires](../../docs/fr/dev/document-apps.md).

## Habillage d’une occurrence

En Texte, la carte conserve sa bordure jaune Solaire et les styles d’aperçu actuels. Dans une carte mentale, la bordure du nœud porte l’habillage de la carte, sans empiler une deuxième bordure jaune. Un intégré a par défaut un habillage transparent, bordure et ombre désactivées. Dans les hôtes qui le permettent, une commande **Apparence** règle indépendamment une bordure personnalisable (couleur Solaire, épaisseur bornée) et une ombre prédéfinie, avec aperçu et réinitialisation. Les paramètres sont propres à l’occurrence et sont conservés quand on revient au mode Intégré. L’hôte applique des valeurs typées aux styles de son conteneur. Les contrôles internes du lecteur gardent leur style et leur comportement.

## Persistance et compatibilité du format Texte

- Utiliser le HTML éditorial du document hôte comme source. L’URI reste dans un attribut `href` canonique ou dans le `src` autorisé d’une image. Ajouter `data-resource-mode` et des attributs éditoriaux validés pour les réglages propres à l’occurrence (habillage et propriétés éditoriales d’image utiles au retour depuis un lien). Le lien reste une vraie ancre et la carte conserve ses métadonnées éditoriales et son lien de repli. Un intégré garde un lien de repli ou le balisage d’image éditorial existant. Les propriétés d’image peuvent rester en sommeil sur l’occurrence, y compris sa destination de clic indépendante de l’URI de l’image. Les DOM de lecteurs, jetons, URL `blob:` et résultats de chargement restent éphémères. Aucun schéma SQL supplémentaire n’est nécessaire.
- Mettre à jour ensemble le parseur et le sérialiseur Tiptap, le filtrage frontend et [le contrat HTML backend](../../back/core/util/rich_text.py). Restreindre les nouveaux attributs au profil documentaire, aux bons éléments, aux valeurs attendues et aux tailles prévues. Faire passer les URI dans les fonctions existantes d’extraction, de copie et de remappage. Les références à des pièces jointes du document restent identifiables dans les trois modes pour la copie et la gestion des assets. Le corps d’un nœud de carte mentale passe par le même codec HTML.
- Lire les anciennes ancres comme des liens et les anciennes cartes d’agent, de contact, de dossier, de document, du Web et d’objets métier avec leur aperçu existant. Les anciennes figures d’image, images liées, vidéos, lecteurs PDF/YouTube et diagrammes BPMN restent rendus avec leur présentation, leurs interactions et leurs liens actuels. Quand un ancien bloc carte contient déjà un lecteur complet, son mode fonctionnel est Intégré et son habillage historique est conservé jusqu’à un changement explicite. Le premier geste d’ouverture, de lecture, d’export ou d’édition ailleurs dans le corps ne déclenche aucune migration de l’occurrence ni des révisions archivées.
- Basculer le mode dans une transaction d’éditeur annulable et préserver le titre choisi, la légende, le texte alternatif, la taille, l’alignement, le lien de destination d’une image et les éléments adjacents. Conserver les réglages et la présentation éditoriale réutilisables par occurrence, y compris après réouverture. Une référence répétée peut avoir deux légendes et deux tailles. Le cache de conversion actuel indexé par URI ne suffit pas. Si la conversion attend des métadonnées, protéger le résultat par l’ancre de transaction et vérifier que le document, le contexte et l’occurrence visée sont toujours valides avant d’insérer. Un refus ou une réponse tardive laisse l’édition courante intacte.
- La navigation garde ses contrats existants en édition, en lecture et dans les modales. Le clic sur les commandes d’un lecteur reste dans ce lecteur, et le cadre de sélection de l’hôte permet toujours de modifier le mode. Retirer une occurrence ne retire pas le fichier, le document ou l’objet source.

## Droits, imbrication et exports

- Toute lecture dynamique utilise les droits du lecteur et le contexte d’accès légitime de la cible. Les droits d’un hôte ne se transmettent pas à ses références. Une carte éditoriale peut contenir des métadonnées déjà enregistrées selon [l’ADR 0209](../decisions/0209-business-document-references.md). Elles font partie du corps partagé, contrairement aux aperçus et contenus récupérés à la lecture. Une capture privée peut inclure les contenus autorisés au lecteur qui la demande. Une miniature partagée de l’hôte utilise un repli statique pour les références ayant des ACL indépendantes. Pour un souvenir privé ou une connexion, toute carte ou intégration future exige un contrat du domaine sur les informations exposables.
- Étendre la garde de [DocumentResourceEmbed](../../front/app/document/components/DocumentResourceEmbed.vue) à tout le parcours d’intégration, avec une pile d’identités canoniques par branche, une limite commune de profondeur et un budget de chargement par hôte. Autoriser deux occurrences sœurs d’une même ressource. En cas de cycle, de profondeur dépassée ou de lecteur indisponible, garder un repli local cliquable. Charger les aperçus et lecteurs coûteux à l’approche de leur zone visible. Annuler et purger au démontage, au changement de document, d’agent, de session et à l’invalidation d’accès, sans réutiliser les octets d’un autre contexte.
- Réutiliser [documentSnapshot](../../front/core/util/documentSnapshot.ts) pour l’impression, le PDF, le ZIP HTML et les miniatures. Les lecteurs fournissent une capture statique autorisée ou un repli explicite. Une carte conserve son aperçu. Un contenu intégré lisible conserve son contenu dans la limite du support et du budget de capture. Un audio ou une vidéo y conserve un titre et un lien de remplacement. Les exports ne rejouent aucun lecteur externe ni script. Les captures portent l’identité de l’occurrence ou une position validée, pour distinguer deux représentations d’une même URI. L’export natif des cartes mentales conserve la représentation source et les exports d’échange gardent au moins les liens portables.

## Livraison et réception

1. **Établir la référence avant le changement.** Prendre des cas synthétiques de documents et révisions existants. Exercer le collage et la conversion, les pièces jointes avec leurs légendes et dimensions, les cartes Web avec et sans vignette, les diagrammes, les lecteurs multimédias et l’impression. Inventorier les consommateurs de `RichText` et `RichTextEditor`, notamment Texte, Carte mentale, historique, Chat, bibliothèque, Fichiers et les champs hors profil documentaire. Utiliser la [matrice de tests fonctionnels](../../docs/fr/dev/functional-tests.md) et les suites existantes `document-resources`, `rich-text`, `resource-links`, `galaris-links`, `document-apps`, `mindmap` et `native-processes`.
2. **Livrer le contrat de lecture et l’édition Texte ensemble.** Qualifier un Agent en deux modes, une image et un processus en trois modes, ainsi que le Web en lien par défaut. Vérifier insertion, trois états après sauvegarde et réouverture, annuler/rétablir, navigation, sélection au clavier, deux occurrences distinctes, copie de document avec PJ, révision ancienne, réponse tardive et refus de sauvegarde. Exercer une action propre à un type dans la barre du mode, le passage à la barre suivante au clavier et les actions accessibles en lecture seule. Tester le passage HTML frontend/backend avec de nouveaux attributs et les anciennes formes. Comparer captures avant et après dans le shell, en clair, sombre et sous 1024 px. Garder les champs `rich-text` actuels hors Document fonctionnels.
3. **Étendre à Carte mentale et aux lecteurs de format.** Vérifier un Agent ajouté en Carte et une image en Intégré dans des nœuds, puis une intégration Texte ↔ Carte mentale et un BPMN intégré dans chacun des hôtes. Tester la réouverture et l’export, les nouvelles tailles de nœuds, les liens existants, une référence supprimée, un format retiré, le cycle A → B → A, l’accès d’un deuxième lecteur puis sa révocation, et une capture qui dépasse son budget. Qualifier la contribution d’un format de plugin et son repli avec les contrats d’installation et de retrait existants.
4. **Documenter au moment de livrer chaque lot.** Mettre à jour les guides Documents et les parcours FR/EN, le profil HTML et ses exemples MCP, la [façade des formats](../../docs/fr/dev/document-formats.md) et le catalogue des tests. Documenter pour un nouveau type sa résolution, ses modes et défauts, son exemple dans les deux hôtes, les ACL et son rendu d’export. Vérifier les parcours concernés via les cibles Make en conteneurs, puis `make typecheck`, `make docs-prepare`, le contrôle d’architecture et `git diff --check` selon le diff livré.

**Parcours FR.** Dans Texte, insérer un processus, choisir Intégré, naviguer dans son diagramme, régler son habillage puis rouvrir le document. Dans Carte mentale, ajouter un agent et une image, vérifier leurs modes par défaut et intégrer le document Texte dans un nœud. Partager l’hôte avec un lecteur dont les droits diffèrent et vérifier l’affichage ainsi que l’impression.

**EN journey.** In Text, insert a process, select Embed, navigate its diagram, adjust its frame and reopen the document. In a Mind Map, insert an agent and an image, check their default modes and embed the Text document in a node. Share the host with a reader who has different access rights and verify the rendered and printed results.
