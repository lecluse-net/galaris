# 0218 — Partages additifs dans les arborescences personnelles

Statut : accepté — 23 octobre 2026.

## Contrat

Les arborescences documentaires restent propres à chaque utilisateur. Les documents cumulent
leurs droits propres et les droits de tous leurs répertoires et documents ancêtres, avec
priorité au droit le plus permissif. Seul le classement du propriétaire humain ou du
responsable de l'agent propriétaire transmet des droits à un document partageable. Pouvoir
lire ou modifier un document reçu ne donne jamais le droit de le repartager par classement.
Les partages portent sur le contenu, sans rendre l'arborescence visible aux destinataires.

## Décision

Memory conserve une intention propre par configuration dans `document_sharing_intents`.
Les tables communes de partage restent une projection effective, pour préserver les
consommateurs SQL et les autres domaines. La première initialisation conserve les droits
existants. Toute propagation repart de ces intentions, jamais du résultat précédent : retirer
une source, déplacer un élément ou supprimer un parent retire sa seule contribution.
Les droits d'un autre ancêtre ou les droits propres restent présents.

Les changements de partage et de classement reconstruisent la fermeture additive dans leur
transaction, sérialisée par un verrou consultatif. Une file de travail termine même sur un
graphe historique cyclique. Les changements effectifs invalident les vues ouvertes et les
versions concernées. Le reconciler DbAdmin requis `app.memory.sharing_inheritance` répare
l'ensemble après la structure documentaire à chaque `make update`, sans effet au rejeu
quand la projection est correcte. Aucun traitement séparé n'est ajouté au lifespan.

Le bloc de partage du répertoire est placé au-dessus de la liste F4 et réutilise le formulaire
commun. Les droits hérités restent modifiables localement ; une suppression locale revient
immédiatement si une source l'accorde encore. Réenregistrer un droit effectif inchangé ne
l'acquiert pas comme droit propre. Les Dataset et Process restent hors de cet héritage.

## Vérification

Des scénarios PostgreSQL synthétiques vérifient le cumul des sources, les sous-documents,
les droits lecture/modification, les classements reçus, les retraits et déplacements,
la réparation d'une projection altérée et l'idempotence du reconciler. Les suites de
partage, bibliothèque et structure existantes protègent les consommateurs conservés.
