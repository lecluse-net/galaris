# Revue documentaire du 20 octobre 2026

La revue rapproche la documentation du code présent et des évolutions du 29 septembre
au 20 octobre. Elle met à jour les guides et les références ; elle ne qualifie pas tous
les parcours applicatifs, les fournisseurs externes ou un déploiement.

## Périmètre et méthode

L'inventaire et la vérification des liens portent sur 392 fichiers Markdown : documents
racine, corpus français/anglais, cartes générées, décisions et plans. Les sources sont
croisées avec les déclarations de modules, routes, modèles, outils MCP, contrats, tests,
catalogues d'interface et commandes Make. Les cinq skills locaux ou système modifiés
reçoivent aussi une validation de leur structure.

Les licences, crédits, références importées et constats des audits historiques conservent
leur provenance. Une décision remplacée garde son contexte historique, avec un renvoi vers
son successeur ; un ancien chemin de code n'est pas présenté comme une procédure actuelle.
Les changements apparus en parallèle dans le catalogue fonctionnel ont été conservés.

## Couverture des évolutions

| Domaine | Résultat documentaire et références |
|---|---|
| Entrées et découverte | READMEs de présentation actualisés ; portails et guides utilisateur, administrateur et développeur orientés par besoin. [Portail](../../docs/fr/README.md). |
| Catalogue fonctionnel | Inventaires comparés au code : 272 fonctions MCP uniques dans chaque langue, 77 modules backend et 39 frontend, sans omission ni fonction supplémentaire. [Catalogue](../../docs/fr/reference/functional-catalogue.md). |
| Documents | Procédures de classement, sous-documents, sélection multiple et raccourcis déplacées dans un [guide dédié](../../docs/fr/user/documents.md) ; navigation allégée sans retrait de ces garanties. |
| Éditeur | Absence de Source documentaire, lecture seule, références métier et aide clavier alignées sur Tiptap ; consignes agentiques corrigées. [Contenus riches](../../docs/fr/user/rich-content.md). |
| Dataset | Parcours bilingue réorganisé autour de la modale, du JSON valide, des révisions, des droits, des utilisations et de la suppression logique ; ancien parcours anglais en panneaux retiré. [Guide](../../docs/fr/user/datasets.md). |
| Stockage et sauvegardes | Textes PostgreSQL distingués des octets `file://`, des miniatures et des sources de migration ; schéma de sauvegarde conservé et variables du dump résolues dans le conteneur. [Administration](../../docs/fr/admin/README.md). |
| Processus | Catalogue natif/externe, BPMN possédé par Process, données de run, acteurs typés, messagerie humaine et restriction temporaire de création UI explicités. [Contrats](../../docs/fr/dev/native-processes.md). |
| Fournisseurs | Guide d'admission ajouté : concurrence par connexion, défauts 10/1, zéro, priorités et limites mono-worker ; distinction entre attente et secours. [Guide](../../docs/fr/admin/provider-admission.md). |
| Autorisations | Ancienne auto-approbation globale et `bypassPermissions` retirés des instructions courantes ; modes de fonctions système et autorisations Claude corrigés. [Claude Agent](../../docs/fr/components/claude-agent.md). |
| Mémoire | Actualisation du graphe corrigée à cinq minutes ; saisie et affichage temporels alignés sur le fuseau global, sans sélecteur de fuseau dans le souvenir. [Parcours](../../docs/fr/user/navigation.md). |
| Frontend et langues | Rubrique Développeurs et trois langues d'interface reflétées dans les guides ; chargement des catalogues et repli expliqués. [Navigation](../../docs/fr/architecture/frontend-navigation.md). |
| Tests | Catalogue des garanties muni de repères stables bilingues ; preuves du navigateur de fichiers replacées hors de la règle de maintenance. [Catalogue](../../docs/fr/dev/functional-tests.md). |
| Plans | Admission fournisseur passée de `design` à `partial` ; travaux restants séparés du socle réalisé. Proposition de programmes documentaires signalée comme à réconcilier avec les frontières actuelles, sans annoncer `document_exec`. [Index](../plans/README.md). |

## Vérifications et portée

- Tests ciblés du corpus et du stockage des skills système : **40 réussis** avec PostgreSQL
  éphémère. Les suites de fonctionnalité citées dans les guides ne sont pas toutes rejouées.
- Validateur officiel des skills : **5 valides** ; cette vérification porte sur la structure,
  pas sur une évaluation comportementale complète des agents.
- Audit Markdown : aucun chemin local ni ancre cassés ; comparaison exhaustive des noms MCP
  et modules dans les deux catalogues. Les chemins d'exemple d'un moteur à créer et les
  sources historiques d'une décision remplacée restent explicitement contextuels.
- Contrôle officiel du corpus : parité des fichiers, niveaux de titres, blocs de code,
  destinations des liens et construction du corpus vérifiées hors réseau.
- `make docs-prepare` rencontre deux écarts d'architecture frontend déjà présents à l'ouverture
  du chantier : dépendance `app/dataset → app/agent` et cycle élargi de domaines frontend.
  La baseline n'est pas augmentée et aucun correctif de code n'est mêlé à cette revue.
- Les cartes sont produites par l'outillage officiel ; aucune sortie générée n'est éditée
  manuellement. La protection contre une modification concurrente des sources a également
  refusé une génération intermédiaire sans publier de sortie partielle.

La revue ne lance ni `make validate`, réservé à l'utilisateur, ni déploiement ni intervention
de production. Le contrôle complet de préparation demeure en échec tant que les écarts
d'architecture ne sont pas résolus. L'index de recherche de l'application active n'est pas
actualisé en contournant ce contrôle. Aucun parcours navigateur ou appel fournisseur réel
n'est revendiqué pour cette modification documentaire.
