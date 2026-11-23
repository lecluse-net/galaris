# 0316 — Fusion des services Chat et Conversation

Statut : accepté — 23 novembre 2026.

Le service système `chat` porte le canal interne, les choix, la présentation des dépôts,
les appels vocaux et l’inspection des tours. Les noms MCP et leurs restrictions de contexte
restent stables. `app.conversation` traite les échanges communs aux canaux et `app.messenger`
reste propriétaire du journal et des salons.

La connexion Chat est obligatoire. Le paramètre `chat.channel_enabled` règle le canal natif
pour chaque agent. Le réglage d’instance reste celui de **Préférences → Messagerie**.
La réponse automatique Matrix et Nextcloud Talk suit son réglage propre sur la connexion Chat.

DbAdmin conserve les identités du service Chat et de ses connexions existantes, dont dépendent
les salons et les URI `chat://`. Il transfère les politiques globales et locales, le réglage
de réponse automatique et l’historique des autorisations. Il reporte les anciennes
désactivations de connexion sur le paramètre du canal avant de retirer le service Conversation.
Un conflit de configuration ou une autorisation encore en cours interrompt la migration.
