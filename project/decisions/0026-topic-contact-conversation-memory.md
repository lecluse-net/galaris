# 0026 — Mémoire conversationnelle scellée par interlocuteur puis classée par Topic

- Statut : Accepted
- Date : 2026-08-06

## Contexte

Un Topic est global à l'instance, tandis qu'un contact Messenger est privé à un agent. Relier
directement un souvenir conversationnel au seul Topic permettrait à l'agent de réutiliser chez un
interlocuteur une préférence, un fait personnel ou un engagement appris auprès d'un autre.

## Décision

Chaque souvenir extrait d'un message, d'un tour vocal ou d'une Task issue d'une conversation est
immédiatement attaché au contact canonique par `memory_contact_items`. Cette portée est suffisante
pour l'extraction, la déduplication et le rappel, même si aucun Topic n'est encore positionné.

Lorsque le classement existe, le souvenir reçoit en plus l'association canonique ternaire :

```text
Topic public + contact Memory privé de l'agent + MemoryItem privé
```

`memory_topic_contact_scopes` identifie alors le couple exact pour un agent et
`memory_topic_contact_items` en porte les membres et leur provenance. Les liens binaires
`topic_contains` et `contact_contains` restent des projections de navigation reconstructibles ;
ils ne suffisent jamais à autoriser un rappel conversationnel.

Le journal Messenger, les rounds, les tours Voice et les Tasks portent le contact Memory exact.
Une conversation vocale à plusieurs contacts, ou dont l'identité distante n'est pas prouvée,
reste sans contact et ne peut donc produire de mémoire privée. Les Tasks de filiation fiable
héritent Topic et contact sans inférence. Les extracteurs, la consolidation sémantique, le rappel
de nouveauté et l’apprentissage exigent le contact, mais n'attendent jamais le Topic.
Le réconciliateur de liens d'`app.memory` complète le scope ternaire après un classement tardif.
Il s'exécute pour les nœuds touchés après chaque succès Dream et globalement une fois par jour à
charge nulle.

Indépendamment de ce scellement social, chaque souvenir garde une association n↔n avec ses sources
canoniques. `memory_sources` référence directement la Task, le round texte ou le tour Voice en plus
de son identité de provenance extensible. Réutiliser ou fusionner un souvenir existant ajoute donc
la nouvelle activité à ce même UUID au lieu de perdre la filiation qui a confirmé le souvenir.

Un même souvenir conversationnel ne peut pas être associé à deux contacts distincts. Les fusions,
scissions et suppressions de Topics déplacent ou retirent aussi les scopes ternaires sans retirer
le scellement au contact. Le rejeu
déterministe reconstruit ces associations depuis les provenances canoniques.

La projection publique d'un Topic est le seul `MemoryItem` qui possède ce Topic par une clé
`topic_id ON DELETE CASCADE`. Ses liens sortants ou entrants ont eux-mêmes `ON DELETE CASCADE`,
sans cascade du lien vers l'autre nœud mémoire. Toutes les activités canoniques qui portent un
Topic — Tasks, sessions et tours Voice, messages du journal et rounds — utilisent au contraire
`ON DELETE SET NULL`. La suppression logique applicative reproduit explicitement ces effets, car
une contrainte PostgreSQL ne s'exécute que lors d'une suppression physique.

La déduplication exacte et la consolidation sémantique respectent cette frontière : un contenu
identique appris auprès de deux contacts produit deux `MemoryItem` privés distincts. Une mise à
jour, fusion ou contradiction préparée dans un scope ne peut cibler un souvenir appartenant à un
autre contact ; lorsqu'un Topic existe, la cible doit aussi appartenir au couple exact.

## Conséquences

- Un Topic conserve une unique projection Memory publique et globale.
- Chaque identité de transport conserve un nœud contact privé par agent.
- La génération de souvenirs et le classement thématique avancent indépendamment.
- Deux interlocuteurs parlant du même sujet ne partagent aucun souvenir conversationnel implicite.
- La voie globale d'un rappel conversationnel admet le même contact dans d'autres Topics et les
  souvenirs autonomes, mais exclut les souvenirs scellés par tout autre contact.
- Une identité absente ou ambiguë bloque la mémorisation au lieu de choisir un contact probable.
- Les souvenirs autonomes sans interlocuteur peuvent conserver une appartenance au Topic seul.
- Supprimer un Topic purge sa seule projection et ses arêtes, jamais les souvenirs qui y étaient
  reliés.
