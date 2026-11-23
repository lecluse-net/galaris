# 0312 — Fusion des services Administration et Voice

Statut : accepté — 22 novembre 2026.

Galaris reprend la documentation, les appels LLM et les incidents. Conversation reprend les
fonctions `conversation_round_get`, `voice_turn_get` et `voice_call_*`. Les noms MCP restent
identiques. La portée des inspections repose sur la connexion Galaris. La réponse automatique
Matrix et Nextcloud Talk devient un réglage distinct sur la connexion Conversation.

La [décision 0315](0315-service-management-scope.md) déplace ensuite la portée sur Services.
La [décision 0316](0316-chat-service-merge.md) transfère les outils et le réglage vocal à Chat.

DbAdmin transfère les autorisations effectives et la réponse automatique des connexions Voice
actives avant de supprimer les anciens services. Les outils déplacés sont bloqués par défaut,
et les autorisations conservées continuent de s’appliquer aux agents concernés. Un conflit ou
une référence qui empêcherait le transfert annule la transaction.
