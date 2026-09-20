# ADR 0090 — Mémoire et documents sans motif libre de modification

- Statut : Accepted
- Date : 2026-09-12

## Décision

Supprimer le commentaire libre `reason` des modifications et acquisitions mémoire,
ainsi que des révisions mémoire et documents. Il n'entre ni dans la recherche ni dans
les embeddings et contient souvent un libellé générique. La traçabilité conserve les
versions, contenus, dates, auteurs, tâches et sources.

Le champ disparaît des API, outils MCP, outils vocaux, écritures Hermès, traitements
Dream, adaptateurs de documents des objectifs, formulaires et historiques. Les anciens
messages d'outils archivés restent des traces historiques. Les critères de conservation
de Dream (`retention_reason`), motifs de vieillissement et diagnostics restent distincts.

## Relances des ajouts de document

La détection d'une relance immédiate utilisait le texte `Document content appended`.
Une révision porte désormais un booléen interne `document_append`, alimenté seulement
par l'opération d'ajout. Il n'est ni éditable ni exposé dans les contrats publics.
Les contrôles de tâche, d'auteur, de dernière révision et de contenu restent appliqués.

Une action DbAdmin `AFTER_EXPAND`, déclenchée par le retrait de
`memory_revisions.reason`, convertit les anciens marqueurs avant la contraction.
Elle est idempotente ; sa postcondition vérifie qu'aucun ajout historique n'a été omis.
Les autres motifs libres ne sont pas conservés. DbAdmin supprime ensuite `reason`
de `memory_revisions` et de `memory_candidates`.

La conversion est une mise à jour SQL ensembliste sans lecture des ressources. En cas
d'échec, la transaction est annulée et la contraction attend la réussite de l'action.
Une synchronisation suivante reprend depuis les données. Aucune restauration des
anciens commentaires n'est requise : leur suppression est intentionnelle.

## Garanties

Les tests PostgreSQL vérifient la conservation des contenus et des révisions, la
conversion idempotente d'anciennes données, la relance sans doublon après suppression
de l'ancienne colonne et l'ajout légitime d'un passage déjà présent après une édition.
Les parcours mémoire, documents, Dream et objectifs conservent leurs contrôles de
droits et de concurrence. L'historique reste consultable et restaurable sans commentaire.
