export default {
    fr: {
        messagingProviders: {
            whatsapp: {
                networkHint: "La réception WhatsApp Business Cloud exige un webhook HTTPS public accessible par Meta, avec un certificat valide : /api/whatsapp/webhook/TOOL_ID. Un tunnel HTTPS vers ce seul endpoint suffit pour tester une instance locale. Ce bridge ne connecte pas un compte WhatsApp personnel.",
                networkWarning: "L’adresse utilisée dans ce navigateur ({origin}) est locale, privée ou sans HTTPS. Meta ne peut pas l’utiliser telle quelle comme webhook. Déclarez une URL HTTPS publique ou un tunnel dans Meta. Si une autre URL publique existe déjà, utilisez-la : cet avertissement analyse uniquement l’adresse du navigateur, sans vérifier le DNS ni la joignabilité.",
                guide: 'WhatsApp passe par l’API Cloud Meta et un webhook public signé. Les jetons d’accès et numéros restent propres à chaque agent.',
                steps: [
                    'Créez une application Meta, activez WhatsApp Cloud API et relevez l’App Secret.',
                    'Choisissez un jeton de vérification puis déclarez https://votre-galaris/api/whatsapp/webhook/TOOL_ID comme callback Meta, avec l’identifiant du Tool.',
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
                networkHint: "WhatsApp Business Cloud reception requires a public HTTPS webhook reachable by Meta, with a valid certificate: /api/whatsapp/webhook/TOOL_ID. An HTTPS tunnel to this endpoint is sufficient to test a local instance. This bridge does not connect a personal WhatsApp account.",
                networkWarning: "The address used in this browser ({origin}) is local, private or lacks HTTPS. Meta cannot use it as-is for the webhook. Register a public HTTPS URL or tunnel in Meta. If another public URL already exists, use it: this warning only inspects the browser address, without checking DNS or reachability.",
                guide: 'WhatsApp uses Meta Cloud API and a signed public webhook. Access tokens and phone numbers remain agent-specific.',
                steps: [
                    'Create a Meta app, enable WhatsApp Cloud API, and copy the App Secret.',
                    'Choose a verification token, then register https://your-galaris/api/whatsapp/webhook/TOOL_ID as the Meta callback, using the Tool identifier.',
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
                networkHint: "WhatsApp Business Cloud 接收消息需要 Meta 能够访问、带有效证书的公开 HTTPS webhook：/api/whatsapp/webhook/TOOL_ID。测试本地实例时，只需将此端点通过 HTTPS 隧道公开。此桥接不连接个人 WhatsApp 账户。",
                networkWarning: "此浏览器使用的地址（{origin}）是本地、私有地址或未使用 HTTPS。Meta 无法直接将其作为 webhook。请在 Meta 中注册公开 HTTPS URL 或隧道。如果已有其他公开 URL，请使用它：此提示仅检查浏览器地址，不验证 DNS 或可达性。",
                guide: 'WhatsApp 使用 Meta Cloud API 和签名的公共 webhook。访问令牌和电话号码由各智能体分别管理。',
                steps: ['创建 Meta 应用，启用 WhatsApp Cloud API，并复制 App Secret。', '选择验证令牌，然后将 https://your-galaris/api/whatsapp/webhook/TOOL_ID 注册为 Meta 回调，使用工具标识符。', '在“工具 → 消息”中添加永久令牌、电话号码 ID 和允许的发送者。'],
                fields: { graphVersion: 'Graph API 版本', appSecret: 'Meta App Secret', verifyToken: 'Webhook 验证令牌', graphUrl: 'Graph API URL', webhookMaxBytes: 'Webhook 最大大小（MB）', httpTimeout: 'HTTP 超时（秒）' },
            },
        },
    },
}
