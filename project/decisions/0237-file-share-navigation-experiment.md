# 0237 — Arrêter la piste FUSE après comparaison de navigation

- Statut : accepté ; expérience terminée.
- Date : 2026-10-25.

Une projection personnelle de File Share par un système de fichiers n'entre pas
dans l'architecture livrée sans gain mesuré et sans non-dégradation de réussite.

La campagne synthétique appariée avec le vrai SDK Hermes et le même modèle réel
réussit 55/60 missions par MCP et 48/60 par répertoire. Le répertoire réduit le coût
par réussite de 78,18 %, mais l'intervalle de l'écart de réussite n'exclut pas une
perte supérieure à la marge de 5 points. Les critères figés de poursuite échouent.
L'[audit](../audits/2026-10-25-file-share-navigation.md) conserve les agrégats,
les régressions par famille, les limites et la provenance des preuves.

La piste FUSE est arrêtée pour ce périmètre. Aucun driver, montage, contrat POSIX
ou mécanisme d'installation FUSE n'est ajouté. Les URI, droits, lectures bornées,
continuations et outils MCP actuels restent les contrats de référence. Les gains
d'une copie locale ne qualifient pas un transport distant ou un provider natif.

Le générateur et la commande de comparaison restent des outils de développement,
sans Task persistée ni Process métier. Ils exécutent des sources figées, isolent les
deux accès et conservent les coûts des échecs. Une expérience future doit avoir son
propre périmètre et ses critères fixés avant analyse ; elle ne reprend pas
automatiquement le chantier clos.
