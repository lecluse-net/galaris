export default {
    fr: {
        messagingProviders: {
            matrix: {
                networkHint: "Aucune URL publique Galaris requise pour les messages : Galaris se connecte au homeserver via /sync. Le homeserver doit être joignable depuis Galaris. Utilisez un salon non chiffré.",
                guide: 'Chaque agent utilise un compte Matrix. Galaris reçoit les messages avec la synchronisation standard du homeserver.',
                steps: [
                    'Créez un compte Matrix dédié pour chaque agent et invitez-le dans les salons voulus.',
                    'Copiez un jeton d’accès longue durée, ou conservez un mot de passe dédié.',
                    'Renseignez le homeserver ici, puis le compte de chaque agent dans Outils → Messagerie.',
                ],
                fields: {
                    homeserver: 'URL du homeserver Matrix',
                    homeserverHint: 'Exemple : https://matrix.example.com',
                    syncTimeout: 'Délai de synchronisation (ms)',
                },
            },
        },
    },
    en: {
        messagingProviders: {
            matrix: {
                networkHint: "No public Galaris URL is required for messages: Galaris connects to the homeserver through /sync. The homeserver must be reachable from Galaris. Use an unencrypted room.",
                guide: 'Each agent uses a Matrix account. Galaris receives messages through standard homeserver sync.',
                steps: [
                    'Create one dedicated Matrix account per agent and invite it to the relevant rooms.',
                    'Copy a long-lived access token, or keep a dedicated password.',
                    'Enter the homeserver here, then each agent account in Tools → Messaging.',
                ],
                fields: {
                    homeserver: 'Matrix homeserver URL',
                    homeserverHint: 'Example: https://matrix.example.com',
                    syncTimeout: 'Sync timeout (ms)',
                },
            },
        },
    },
    zh: {
        messagingProviders: {
            matrix: {
                networkHint: "消息功能无需公开的 Galaris URL：Galaris 通过 /sync 连接主服务器。主服务器必须能够从 Galaris 访问。请使用未加密的聊天室。",
                guide: '每个智能体使用一个 Matrix 账户。Galaris 通过主服务器的标准同步接收消息。',
                steps: ['为每个智能体创建专用 Matrix 账户，并将其邀请到相关聊天室。', '复制长期访问令牌，或保留专用密码。', '在此输入主服务器地址，然后在“工具 → 消息”中配置每个智能体账户。'],
                fields: { homeserver: 'Matrix 主服务器 URL', homeserverHint: '示例：https://matrix.example.com', syncTimeout: '同步超时（毫秒）' },
            },
        },
    },
}
