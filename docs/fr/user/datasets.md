<p align="right"><strong>Français</strong> · <a href="../../en/user/datasets.md">English</a></p>

# Documents Données

## Créer et retrouver des données

Ouvrez **Connaissances → Documents**. Cliquez sur une icône **Nouveau document** pour ouvrir sous celle-ci le choix entre
**Texte** et **Données**. Choisissez Données, renseignez le titre et le propriétaire,
puis saisissez votre JSON. Le menu contextuel d'un document ou d'un dossier propose
la même création dans le classement choisi. Fermer ce choix ne crée aucun document.

Le filtre **Type de document → Données** retrouve les documents JSON dans la bibliothèque
commune. Les dossiers, le classement personnel et la pagination sont ceux des Documents.
L'icône Données distingue le type ; un aperçu adapté peut remplacer son image de secours.
Les anciens liens `data://` et `/dataset/:id` ouvrent le même contenu sous ses droits courants.

## Modifier et partager

L'éditeur JSON accepte objets, tableaux et valeurs simples, sans schéma imposé.
Un JSON valide est enregistré automatiquement. Un brouillon invalide reste visible
et ne remplace jamais le contenu enregistré ; la navigation vérifie sa sauvegarde.
Les modifications concurrentes demandent une relecture et préservent le brouillon.

Titre, propriétaire, sujet, partage, mots-clés, résumé et historique utilisent les
commandes communes. Le partage peut viser des personnes, agents ou équipes ; pouvoir
modifier le JSON ne donne pas le droit de repartager le document. Un lien depuis un
Texte ne donne aucun accès aux Données qu'il référence. Le partage d'un dossier peut
accorder des droits supplémentaires aux documents que vous y classez.

## Historique et résumé

Chaque modification du contenu produit une version. L'historique permet de consulter
le JSON d'une version et de le restaurer comme nouvelle version. Le titre, les droits,
le propriétaire, le résumé et les mots-clés courants sont conservés lors de cette restauration.
Le JSON enregistré conserve son contenu exact, y compris les nombres et les fins de lignes.

L'icône **Voir le résumé** recharge la description courante et les mots-clés sans toucher
au brouillon. Les descriptions existantes sont conservées. Dream peut compléter une
description absente au-delà de 1 000 caractères de JSON normalisé et actualiser une
description automatique après plus de 25 % de changement cumulé. Ces seuils sont réglables ;
les descriptions manuelles sont préservées.

## Utiliser les données avec un agent ou une page

Un agent peut rechercher un document Données, filtrer ses lignes, les trier et calculer
un total côté serveur sans recopier tout le JSON dans la conversation. Les résultats
indiquent la version consultée et distinguent valeurs absentes, nulles et types incompatibles.
Les unités doivent être précisées ; une modification entre deux pages demande une nouvelle lecture.
La recherche sémantique dépend du modèle vectoriel et de l'indexation Dream.

Une application HTML dans un document Texte conserve un accord personnel pour accéder
aux Données. Cet accord dépend de la version de la page, ne remplace pas le partage et
peut être révoqué. Les écritures utilisent le quota commun côté serveur.
Les définitions de processus métier restent dans Process ; elles ne sont pas des documents Données.
