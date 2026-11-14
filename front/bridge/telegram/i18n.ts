export default {
    fr: {
        messagingProviders: {
            telegram: {
                networkHint: "Aucune URL publique Galaris requise : la réception utilise le long polling. Une connexion Internet sortante vers Telegram et un token BotFather suffisent.",
                guide: 'Telegram utilise un bot par agent. Les jetons restent chiffrés dans les connexions des agents, pas dans ces réglages globaux.',
                steps: [
                    'Si aucun service n’utilise déjà la messagerie Telegram, créez un service de code telegram et de libellé Telegram, activez sa Messagerie avec le bridge telegram, puis ajoutez un paramètre de connexion secret token associé au token du bridge. Le bouton de création est proposé uniquement dans ce cas.',
                    'Ouvrez @BotFather dans Telegram, lancez /newbot et copiez le jeton du bot.',
                    'Dans Services → Connexions, créez une connexion à ce service pour chaque agent et collez le token transmis par BotFather. Utilisez un bot distinct par agent et par instance active.',
                    'Envoyez un message au bot. Un nouveau correspondant apparaît dans les conversations textuelles, en pause jusqu’à l’autorisation du manager, également disponible dans Permissions.',
                    'Un correspondant peut ne pas avoir de compte Galaris. Dans Mon profil, l’identifiant distant facultatif sert à associer son compte Telegram à son compte Galaris. Les notes vocales sont prises en charge, pas les appels Telegram temps réel.',
                ],
                createService: 'Créer le service Telegram',
                openServices: 'Ouvrir les services et connexions',
                checkingServices: 'Recherche des services utilisant la messagerie Telegram…',
                toolConflict: 'Le code telegram est déjà utilisé par un service dont la configuration diffère. Vérifiez-le dans Services avant de créer les connexions.',
                toolError: 'Impossible de préparer le service Telegram. Réessayez.',
                tokenLabel: 'Token',
                tokenDescription: 'Token du bot transmis par BotFather, à renseigner dans la connexion de chaque agent.',
                fields: {
                    pollTimeout: 'Attente de réception (secondes)',
                    maxAge: 'Âge maximal d’une mise à jour (secondes)',
                },
            },
        },
    },
    en: {
        messagingProviders: {
            telegram: {
                networkHint: "No public Galaris URL is required: reception uses long polling. Outbound Internet access to Telegram and a BotFather token are sufficient.",
                guide: 'Telegram uses one bot per agent. Tokens stay encrypted in agent connections, not in these global settings.',
                steps: [
                    'If no Service already uses Telegram messaging, create a Service with code telegram and label Telegram, enable Messaging with bridge telegram, then add a secret token connection parameter mapped to the bridge token. The creation button is offered only in this case.',
                    'Open @BotFather in Telegram, run /newbot, and copy the bot token.',
                    'In Services → Connections, create a connection to this Service for each agent and paste the token from BotFather. Use a separate bot for each agent and active instance.',
                    'Send the bot a message. A new contact appears in text conversations, paused until the manager authorizes replies; the request is also available in Permissions.',
                    'A contact may have no Galaris account. In My profile, the optional remote identifier links their Telegram account to their Galaris account. Voice notes are supported; real-time Telegram calls are not.',
                ],
                createService: 'Create Telegram Service',
                openServices: 'Open tools and connections',
                checkingServices: 'Checking Services for Telegram messaging…',
                toolConflict: 'The code telegram is already used by a Service with different settings. Review it in Services before creating connections.',
                toolError: 'Unable to prepare the Telegram Service. Try again.',
                tokenLabel: 'Token',
                tokenDescription: 'Bot token from BotFather, to enter in each agent’s connection.',
                fields: {
                    pollTimeout: 'Reception timeout (seconds)',
                    maxAge: 'Maximum update age (seconds)',
                },
            },
        },
    },
    zh: {
        messagingProviders: {
            telegram: {
                networkHint: "无需公开的 Galaris URL：通过长轮询接收消息。只需能够访问 Telegram 的出站互联网连接和 BotFather 令牌。",
                guide: 'Telegram 为每个智能体使用一个机器人。令牌加密保存在智能体连接中，而不是全局设置中。',
                steps: ['仅当没有服务使用 Telegram 消息时，创建代码为 telegram、名称为 Telegram 的服务，启用消息功能并选择 telegram 桥接器，然后添加映射到桥接器 token 的保密连接参数 token。创建按钮仅在此情况下显示。', '在 Telegram 中打开 @BotFather，运行 /newbot 并复制机器人令牌。', '在“服务 → 连接”中为每个智能体创建此服务的连接，并粘贴 BotFather 提供的令牌。每个智能体及活动实例应使用独立的机器人。', '向机器人发送消息。新联系人会出现在文字对话中，暂停等待管理者授权回复；请求也会列在“权限”中。', '联系人不必拥有 Galaris 账户。“我的个人资料”中的可选远程标识符仅用于关联其 Telegram 与 Galaris 账户。支持语音消息，但不支持 Telegram 实时通话。'],
                createService: '创建 Telegram 服务',
                openServices: '打开服务和连接',
                checkingServices: '正在检查使用 Telegram 消息的服务…',
                toolConflict: '代码 telegram 已被配置不同的服务使用。创建连接前请在“服务”中检查。',
                toolError: '无法准备 Telegram 服务。请重试。',
                tokenLabel: '令牌',
                tokenDescription: 'BotFather 提供的机器人令牌，需在每个智能体的连接中填写。',
                fields: { pollTimeout: '接收超时（秒）', maxAge: '更新最大有效时间（秒）' },
            },
        },
    },
}
