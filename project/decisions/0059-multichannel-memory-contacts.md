# ADR 0059 — Contacts Memory multicanaux et fusion explicite

- Statut : Accepted
- Date : 2026-08-30
- Remplace : la clause « un nœud contact par identité de transport » de l’ADR 0026

## Contexte

La projection sociale historique créait un `MemoryItem` privé pour chaque couple
`(agent, messaging_id, user_id)`. Cette identité exacte protège le rappel contre les homonymes,
mais elle fragmente une même personne entre Matrix, Telegram, Mail, Chat et les comptes `USER` de
Galaris. Une simple fusion des lignes mémoire serait instable : l’observation suivante du canal
supprimé recréerait son ancien item, tandis que messages, Tasks et scopes mémoire conserveraient
des UUID divergents.

## Décision

Le contact canonique reste un `MemoryItem` social `source_managed`, privé à un agent. La table
`memory_contact_identities` lui rattache des adresses fortes : identité Messenger exacte ou
`galaris_user_id` réel. Deux canaux qui portent le même utilisateur Galaris prouvé convergent vers
le même contact. Aucun rapprochement n’est déduit du nom affiché.

`app.contact` possède la surface d’administration et la page Contacts. Une fusion est limitée à
deux contacts du même agent et conserve explicitement l’un des deux UUID. Dans une transaction,
elle déplace les identités, les associations `memory_contact_items`, les scopes Topic/contact, les
arêtes du graphe et les références `contact_memory_item_id` des messages, rounds et Tasks. Elle
oublie ensuite la projection source. Les anciennes adresses restent des alias du contact conservé,
donc un rejeu Messenger ne recrée pas le doublon.

Les privilèges Memory existants protègent cette entité secondaire : lecture avec `MEMORY_ACCESS`
et fusion ou oubli avec `MEMORY_EDIT`. Le périmètre de management de l’agent est vérifié par le
backend. L’oubli explicite efface toutes les mémoires conversationnelles scellées à ce contact,
leurs révisions et ressources, vide les références historiques puis purge physiquement la
projection et ses identités. Une interaction ultérieure recrée un nouveau contact sans restaurer
les données oubliées.

## Conséquences

- une personne peut conserver plusieurs identités de canal sans perdre l’isolation par agent ;
- un lien `USER` est une preuve forte, tandis qu’un nom similaire ne fusionne rien ;
- l’UUID du contact conservé continue de sceller rappel, continuité et extraction Dream ;
- une fusion est irréversible du point de vue de l’ancien item, mais ses adresses et relations sont
  conservées sur le contact canonique ;
- l’oubli d’un contact est une action destructive par contact et ne conserve ni alias ni mémoire
  conversationnelle associée ;
- les bridges restent étrangers à l’annuaire métier et continuent de converger vers Messenger.

## Preuves dans le code

`back/app/memory/models.py`, `back/app/memory/messenger_contact.py`,
`back/app/memory/contact_directory.py`, `back/app/contact/service.py`,
`front/app/memory/pages/contacts.vue` et les tests des modules Contact et Memory.
