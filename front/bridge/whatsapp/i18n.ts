export default {
    fr: {
        messagingProviders: {
            whatsapp: {
                guide: 'WhatsApp passe par l’API Cloud Meta et un webhook public signé. Les jetons d’accès et numéros restent propres à chaque agent.',
                steps: [
                    'Créez une application Meta, activez WhatsApp Cloud API et relevez l’App Secret.',
                    'Choisissez un jeton de vérification puis déclarez https://votre-galaris/api/whatsapp/webhook comme callback Meta.',
                    'Ajoutez le jeton permanent, le phone number ID et les expéditeurs autorisés dans Outils → Messagerie.',
                ],
                fields: {
                    graphVersion: 'Version de Graph API', appSecret: 'App Secret Meta', verifyToken: 'Jeton de vérification du webhook',
                    graphUrl: 'URL de Graph API', webhookMaxBytes: 'Taille maximale du webhook (Mo)', httpTimeout: 'Délai HTTP (secondes)',
                },
            },
        },
    },
    en: {
        messagingProviders: {
            whatsapp: {
                guide: 'WhatsApp uses Meta Cloud API and a signed public webhook. Access tokens and phone numbers remain agent-specific.',
                steps: [
                    'Create a Meta app, enable WhatsApp Cloud API, and copy the App Secret.',
                    'Choose a verification token, then register https://your-galaris/api/whatsapp/webhook as the Meta callback.',
                    'Add the permanent token, phone number ID, and allowed senders in Tools → Messaging.',
                ],
                fields: {
                    graphVersion: 'Graph API version', appSecret: 'Meta App Secret', verifyToken: 'Webhook verification token',
                    graphUrl: 'Graph API URL', webhookMaxBytes: 'Maximum webhook size (MB)', httpTimeout: 'HTTP timeout (seconds)',
                },
            },
        },
    },
    zh: {
        messagingProviders: {
            whatsapp: {
                guide: 'WhatsApp 使用 Meta Cloud API 和签名的公共 webhook。访问令牌和电话号码由各智能体分别管理。',
                steps: ['创建 Meta 应用，启用 WhatsApp Cloud API，并复制 App Secret。', '选择验证令牌，然后将 https://your-galaris/api/whatsapp/webhook 注册为 Meta 回调。', '在“工具 → 消息”中添加永久令牌、电话号码 ID 和允许的发送者。'],
                fields: { graphVersion: 'Graph API 版本', appSecret: 'Meta App Secret', verifyToken: 'Webhook 验证令牌', graphUrl: 'Graph API URL', webhookMaxBytes: 'Webhook 最大大小（MB）', httpTimeout: 'HTTP 超时（秒）' },
            },
        },
    },
}
