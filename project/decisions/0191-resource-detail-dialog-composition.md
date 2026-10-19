# 0191 — Composition des modales de détail des ressources

Statut : accepté

## Contexte

Le détail d’un sujet doit ouvrir les tâches, rounds, espaces et ressources liés sans
quitter la page. Les domaines concernés utilisent déjà les composants Topics pour
l’affectation : les importer en retour depuis Topics créerait des cycles supplémentaires.

## Décision

`core.util` expose `ResourceDetailDialog` et un contrat de cible limité au type,
à l’identifiant, au titre et au contexte d’agent éventuel. Il charge à la demande le
point de composition applicatif `front/resourceDetails.vue`, découvert comme fournisseur
sans importer les domaines dans Core.

Les runs internes ouverts depuis le Chat utilisent cette même composition avec la cible
`process_run` et le composant public de suivi natif de Process. Le diagramme figé, les
activités et commandes restent ceux de Process ; le Chat ne duplique pas leur lecture.
Les processus externes conservent leur détail spécifique.

Le fournisseur peut exposer un préchargement de code par type de cible. `core.util`
le relaie avec `preloadResourceDetail`, sans lecture de données ni nouvelle dépendance
entre domaines. Le Chat prépare ainsi le diagramme lorsqu'un run interne est présent.
Les services et vues des autres types sont importés uniquement lorsqu'ils sont utilisés.

Ce fournisseur assemble les services et vues publics des domaines. Il conserve leur
autorisation serveur, leurs actions et leurs composants de détail. Les lectures tardives
sont ignorées après fermeture ou changement de cible ; les traces LLM ne bloquent pas
la lecture du round. La fermeture par l’arrière-plan reste disponible.

Pour les Documents, la navigation ordinaire appartient au contexte d’affichage le plus
proche : bibliothèque, panneau de travail du Chat ou modale documentaire. Le contrat
`documentNavigationKey` de `core.util` délègue au contexte sans coupler les lecteurs aux
pages métier. L’historique et les boutons précédent/suivant sont partagés dans Core ; chaque
contexte conserve ses visites. Le fournisseur `documentEditor.ts` de Memory résout la
cible et son contexte d’accès avant remplacement, puis fournit le contenu initial à l’éditeur.
Une sauvegarde refusée conserve le document courant ; une fermeture ou une sélection plus
récente invalide la réponse en attente.

L’action contextuelle explicite « Ouvrir dans une modale » utilise `ResourceDetailDialog`
et ouvre un contexte distinct, y compris depuis une modale. Elle conserve le document et
l’historique d’origine et ferme le menu contextuel à l’origine de l’ouverture.

Les Datasets exposent leur propre `DatasetDialog`, composé avec `DatasetEditor`, depuis
la bibliothèque Dataset et le fournisseur de détails. Les cartes du Chat délèguent à ce
fournisseur au lieu du lecteur de fichiers générique. La fermeture consulte la garde des
brouillons avant de retirer l’éditeur. La contribution `richContent.ts` de Dataset résout
les URI `data://` et les URL de cette installation ; ses cartes conservent une référence,
sans copier le JSON dans les Documents.

## Vérification

`front/browser-tests/topic-detail.spec.mjs` couvre les six types de cibles sur desktop
et mobile, le clavier, la fermeture, le réessai après refus et les réponses tardives.
Le contrôle d’architecture ne doit ajouter aucune dépendance entre les domaines.
Les suites `chat-document-workspace.spec.mjs`, `document-navigation.spec.mjs` et
`document-dialog-navigation.spec.mjs` couvrent les trois contextes documentaires, leurs
historiques indépendants, la sauvegarde avant navigation et l’ouverture explicite en modale.
`dataset-dialog.spec.mjs` couvre le Chat, la fermeture avec brouillon, la réouverture et
la conversion des liens Dataset en cartes ouvrables en lecture comme en édition.
