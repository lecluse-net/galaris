export default {
    fr: {
        messagingProviders: {
            oneBot: {
                guide: 'Un adaptateur OneBot 11 (NapCat, Lagrange, etc.) ouvre un WebSocket inverse vers Galaris.',
                steps: [
                    'Installez et configurez un adaptateur compatible OneBot 11 en mode WebSocket inverse.',
                    'Définissez ici le nom de plateforme et un secret robuste.',
                    'Connectez l’adaptateur à wss://votre-galaris/ws/onebot/:platform/:user_id avec le secret Bearer, puis associez l’agent dans Outils.',
                ],
                fields: { platform: 'Nom de plateforme', platformHint: 'Exemple : qq', secret: 'Secret du WebSocket' },
            },
        },
    },
    en: {
        messagingProviders: {
            oneBot: {
                guide: 'A OneBot 11 adapter (NapCat, Lagrange, and others) opens a reverse WebSocket to Galaris.',
                steps: [
                    'Install and configure a OneBot 11-compatible adapter in reverse WebSocket mode.',
                    'Set the platform name and a strong secret here.',
                    'Connect it to wss://your-galaris/ws/onebot/:platform/:user_id with the Bearer secret, then link the agent in Tools.',
                ],
                fields: { platform: 'Platform name', platformHint: 'Example: qq', secret: 'WebSocket secret' },
            },
        },
    },
    zh: {
        messagingProviders: {
            oneBot: {
                guide: 'OneBot 11 适配器（NapCat、Lagrange 等）会向 Galaris 建立反向 WebSocket 连接。',
                steps: ['以反向 WebSocket 模式安装并配置兼容 OneBot 11 的适配器。', '在此设置平台名称和高强度密钥。', '使用 Bearer 密钥连接到 wss://your-galaris/ws/onebot/:platform/:user_id，然后在“工具”中关联智能体。'],
                fields: { platform: '平台名称', platformHint: '示例：qq', secret: 'WebSocket 密钥' },
            },
        },
    },
}
