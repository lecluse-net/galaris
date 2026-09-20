# ADR 0089 — Mémoire et documents sans résumé indépendant

- Statut : Accepted
- Date : 2026-09-12

## Contexte

Le champ `summary` de 200 caractères décrivait un objet sans lire sa ressource et
contribuait à son classement lexical et vectoriel. Certaines acquisitions le produisaient
avec le contenu ; les autres écritures pouvaient le laisser inchangé. Les documents
utilisaient notamment des libellés fixes. Une description périmée pouvait donc influencer
la recherche, les embeddings et l'affichage alors que le contenu avait changé.

## Décision

Supprimer `summary` de tous les objets mémoire et documents, de leurs révisions et du
journal d'acquisition, ainsi que des contrats publics et des sorties structurées de Dream.
Cette décision remplace la contribution du résumé à la recherche décrite dans l'ADR 0010.

Le titre, les mots-clés et le contenu courant portent la découverte. Les extraits restent
des projections bornées du texte ou du fragment courant ; ils ne constituent pas une
nouvelle métadonnée éditable. Les objets sans texte restent recherchables par leur titre
et leurs mots-clés. Aucune génération supplémentaire par LLM n'est introduite.

Dream, le Lab et les acquisitions transmettent le contenu utile sans résumé parallèle.
Les anciens checkpoints et cas sauvegardés restent lisibles : la validation ignore leur
ancien champ et la sérialisation du contrat courant ne le réémet pas. Les historiques
bruts de messages LLM et de traitements restent des traces historiques, pas des contrats
actifs à réécrire rétroactivement.

## Application et garanties

DbAdmin retire les trois colonnes `summary` de `memory_items`, `memory_revisions` et
`memory_candidates`, après adaptation de la colonne calculée de recherche. La suppression
des valeurs de ces colonnes est intentionnelle. Les ressources, titres, mots-clés,
révisions de contenu, droits et références restent conservés.

La version de l'index sémantique passe à 3. Sa réconciliation invalide les anciennes
empreintes et programme les embeddings sans résumé ; le rappel lexical reste disponible
pendant leur reconstruction. Les plafonds de fragments et les règles de classement ne
changent pas.

Les tests couvrent la recherche dans le contenu des six catégories et des documents,
l'absence du champ dans les réponses et les révisions, les droits, la restauration,
l'acquisition et la reprise des checkpoints Dream. Les tests d'autorisation et de
concurrence qui modifiaient le résumé utilisent désormais le titre. La conservation
historique du résumé n'est plus une garantie ; celle du contenu et des autres métadonnées
est maintenue.
