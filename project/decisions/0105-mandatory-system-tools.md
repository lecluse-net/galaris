# 0105 — Services système obligatoires et séparation des Tools

Statut : accepté — 17 septembre 2026.

## Décision

`galaris`, `conversation`, `memory` et `file_sharing` sont des services système obligatoires.
La propriété persistée `Tool.can_disable` appartient au logiciel, vaut `false` pour ces quatre
Tools et n'est pas exposée dans les contrats d'écriture. Les autres Tools restent optionnels.

DbAdmin crée leurs connexions pour tous les agents et les réactive lors de la convergence,
ainsi que leur accès conversationnel. Les anciens refus de fonctions sont ignorés pour ces
services, aux niveaux global et connexion. Les API et services refusent toute modification ou
suppression des Tools système, de leurs connexions, paramètres et autorisations. L'interface
les affiche dans les trois onglets avec une icône obligatoire et des contrôles en lecture seule.

Cette décision remplace la conservation des désactivations de Memory et File Sharing décrite
dans [0104](0104-documents-information-hub.md). Les désactivations des Tools optionnels restent
préservées. L'activation système ne modifie ni ACL métier, ni visibilité des ressources, ni
compatibilité des harnais, ni restrictions de contexte des fonctions.

Les neuf fonctions de contrôle `conversation_*` quittent `galaris` pour `conversation` ;
`document_show` y reste. L'inspection `conversation_round_get` reste administrative.
`llm_call` et `llm_calls` rejoignent `galaris_admin`, inactif par défaut, aux côtés de
`conversation_round_get` et `voice_turn_get`. Chaque appel vérifie la connexion administrative
active, même si le catalogue a été construit avant sa révocation.

`memory_summarize` produit une synthèse attribuée via le modèle de l'agent, bornée à 200 messages
et aux 32 000 derniers caractères. Les faits, décisions, engagements et questions ouvertes sont
encodés en HTML éditorial et soumis à l'acquisition Memory habituelle. L'argument inopérant
`replace_existing` disparaît. Une erreur du modèle ne stocke rien ; les mémoires d'une salle ne
sont jamais remplacées en bloc.

Chaque Tool livré dispose d'une description métier précise, consultable dans une modale depuis
la liste. Sans description, aucun lien n'est proposé. Les bridges de messagerie et de fichiers
connus reçoivent une description par défaut à la création et lors de la convergence si leur
description est vide ; les descriptions personnalisées sont conservées. Les fiches détaillées
emploient des titres et listes Markdown pour expliquer leur rôle, leurs possibilités, des cas
d'usage et leurs limites. Les anciens textes courts standard restés identiques sont reconnus et
remplacés par ces fiches lors de la convergence.

## Vérification

Les tests d'intégration couvrent la réparation des connexions existantes, l'activation des
nouveaux agents, les refus de mutation et les autorisations effectives malgré les anciens refus.
Les tests MCP vérifient les familles, les restrictions conversationnelles et la révocation de
l'inspection administrative. Les tests de synthèse couvrent le HTML, les limites, l'historique
vide et l'absence de stockage après erreur du modèle. Les parcours navigateur vérifient les
trois onglets sur desktop et mobile, la modale et la conservation des contrôles optionnels.
