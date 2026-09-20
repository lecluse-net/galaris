# 0040 — Markdown des Goals porté par des documents Memory protégés

- Statut : Accepted
- Date : 2026-08-20

## Contexte

`Goal.description` et `Goal.tracking_markdown` conservaient directement deux textes Markdown dans
la table `goals`. Ces contenus intermédiaires n'étaient donc ni des documents de travail
révisionnés, ni visibles dans l'espace Documents, alors que leur cycle de vie et leur édition
relèvent du même besoin.

Une simple projection Memory aurait laissé deux copies modifiables et une autorité ambiguë. La
contraction déclarative du schéma ne peut par ailleurs supprimer les anciennes colonnes qu'après
avoir préservé et rattaché leur contenu.

## Décision

Chaque Goal possède exactement deux documents `MemoryItem` privés de nature `document` et de type
`working` : un pour sa description et un pour son suivi. La table `goals` ne conserve plus le
Markdown ; elle porte les clés étrangères UUID non nulles `description_document_id` et
`tracking_document_id`. Les deux références sont distinctes et utilisent `RESTRICT`.

Ces documents sont mutables et restent donc éditables dans l'IHM Documents ainsi que par les
commandes Goal existantes. Ils portent toutefois `deletion_protected = true` : aucune façade
publique, y compris administrative, ne peut les oublier. Cette protection est indépendante de
`source_managed`, qui continue de désigner les projections générées et non modifiables. Une mise à
jour effectuée depuis Documents incrémente la révision du Goal et déclenche sa synchronisation ;
une mise à jour effectuée par Goal écrit le document sans produire une seconde notification.

`app.goal` dépend uniquement d'un port de documents. `app.memory` fournit l'adapter concret au
bootstrap, ce qui préserve la direction des dépendances entre domaines. Les réponses API Goal
continuent d'exposer `description` et `tracking_markdown`, résolus depuis les documents, et ajoutent
leurs deux UUID afin que l'IHM puisse ouvrir les documents canoniques.

Avant qu'Atlas ne contracte le schéma, la transition initiale a exécuté une expansion idempotente :

- sauvegarde de tous les textes historiques dans
  `galaris_migration.goal_markdown_backup` ;
- création et rattachement des deux documents protégés pour chaque Goal existant ;
- reprise du dernier `continuation_context` non vide lorsqu'un ancien suivi est vide, conformément
  au backfill Goal antérieur ;
- vérification que chaque Goal possède deux références distinctes.

Atlas supprime ensuite les colonnes texte et rend les références obligatoires. La sauvegarde est
conservée hors du schéma applicatif `public` pour permettre un audit ou une reprise manuelle. Le
hook et son script temporaires ont été retirés après validation de la contraction en production.

## Conséquences

- Memory devient l'unique stockage du contenu Markdown des Goals, sans devenir propriétaire du
  modèle métier Goal.
- `app.memory` est désormais une dépendance de runtime obligatoire pour créer, lire ou modifier un
  Goal. Cette décision remplace donc, pour Goal uniquement, l'indépendance à une panne ou à une
  désactivation de Memory énoncée dans 0010.
- La recherche Goal inclut le contenu indexé des deux documents tout en conservant les filtres et
  ACL du domaine Goal.
- La suppression logique d'un Goal ne supprime pas ses documents ni leur historique ; ses clés
  étrangères restent attachées à la source historisée.
- Toute nouvelle nature de document appartenant à un domaine doit expliciter séparément son droit
  d'édition et sa politique de suppression au lieu de détourner `source_managed`.
- Cette décision remplace également les passages de 0010 qui décrivaient la description et le
  suivi Goal comme des textes seulement projetés ou ne changeant pas leur persistance.
