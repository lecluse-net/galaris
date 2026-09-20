export default {
    fr: {
        messagingProviders: {
            matrix: {
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
                guide: '每个智能体使用一个 Matrix 账户。Galaris 通过主服务器的标准同步接收消息。',
                steps: ['为每个智能体创建专用 Matrix 账户，并将其邀请到相关聊天室。', '复制长期访问令牌，或保留专用密码。', '在此输入主服务器地址，然后在“工具 → 消息”中配置每个智能体账户。'],
                fields: { homeserver: 'Matrix 主服务器 URL', homeserverHint: '示例：https://matrix.example.com', syncTimeout: '同步超时（毫秒）' },
            },
        },
    },
}
