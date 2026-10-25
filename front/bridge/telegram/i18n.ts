export default {
    fr: {
        messagingProviders: {
            telegram: {
                networkHint: "Aucune URL publique Galaris requise : la réception utilise le long polling. Une connexion Internet sortante vers Telegram et un token BotFather suffisent.",
                guide: 'Telegram utilise un bot par agent. Les jetons restent chiffrés dans les connexions des agents, pas dans ces réglages globaux.',
                steps: [
                    'Créez un outil de code telegrem et de libellé Telegram, activez sa Messagerie avec le bridge telegram, puis ajoutez un paramètre de connexion secret token associé au token du bridge. Le bouton ci-dessous prépare cet outil.',
                    'Ouvrez @BotFather dans Telegram, lancez /newbot et copiez le jeton du bot.',
                    'Dans Outils → Connexions, créez une connexion à cet outil pour chaque agent et collez le token transmis par BotFather. Utilisez un bot distinct par agent et par instance active.',
                    'Envoyez un message au bot. Un nouveau correspondant apparaît dans les conversations textuelles, en pause jusqu’à l’autorisation du manager, également disponible dans Permissions.',
                    'Un correspondant peut ne pas avoir de compte Galaris. Dans Mon profil, l’identifiant distant facultatif sert à associer son compte Telegram à son compte Galaris. Les notes vocales sont prises en charge, pas les appels Telegram temps réel.',
                ],
                createTool: 'Créer l’outil Telegram',
                openTools: 'Ouvrir les outils et connexions',
                toolReady: 'L’outil Telegram est prêt. Créez une connexion par agent et renseignez son token BotFather.',
                toolConflict: 'Le code telegrem est déjà utilisé par un outil dont la configuration diffère. Vérifiez-le dans Outils avant de créer les connexions.',
                toolError: 'Impossible de préparer l’outil Telegram. Réessayez.',
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
                    'Create a Tool with code telegrem and label Telegram, enable Messaging with bridge telegram, then add a secret token connection parameter mapped to the bridge token. The button below prepares this Tool.',
                    'Open @BotFather in Telegram, run /newbot, and copy the bot token.',
                    'In Tools → Connections, create a connection to this Tool for each agent and paste the token from BotFather. Use a separate bot for each agent and active instance.',
                    'Send the bot a message. A new contact appears in text conversations, paused until the manager authorizes replies; the request is also available in Permissions.',
                    'A contact may have no Galaris account. In My profile, the optional remote identifier links their Telegram account to their Galaris account. Voice notes are supported; real-time Telegram calls are not.',
                ],
                createTool: 'Create Telegram Tool',
                openTools: 'Open tools and connections',
                toolReady: 'The Telegram Tool is ready. Create a connection for each agent and enter its BotFather token.',
                toolConflict: 'The code telegrem is already used by a Tool with different settings. Review it in Tools before creating connections.',
                toolError: 'Unable to prepare the Telegram Tool. Try again.',
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
                steps: ['创建代码为 telegrem、名称为 Telegram 的工具，启用消息功能并选择 telegram 桥接器，然后添加映射到桥接器 token 的保密连接参数 token。下方按钮可创建此工具。', '在 Telegram 中打开 @BotFather，运行 /newbot 并复制机器人令牌。', '在“工具 → 连接”中为每个智能体创建此工具的连接，并粘贴 BotFather 提供的令牌。每个智能体及活动实例应使用独立的机器人。', '向机器人发送消息。新联系人会出现在文字对话中，暂停等待管理者授权回复；请求也会列在“权限”中。', '联系人不必拥有 Galaris 账户。“我的个人资料”中的可选远程标识符仅用于关联其 Telegram 与 Galaris 账户。支持语音消息，但不支持 Telegram 实时通话。'],
                createTool: '创建 Telegram 工具',
                openTools: '打开工具和连接',
                toolReady: 'Telegram 工具已准备好。请为每个智能体创建连接并填写其 BotFather 令牌。',
                toolConflict: '代码 telegrem 已被配置不同的工具使用。创建连接前请在“工具”中检查。',
                toolError: '无法准备 Telegram 工具。请重试。',
                tokenLabel: '令牌',
                tokenDescription: 'BotFather 提供的机器人令牌，需在每个智能体的连接中填写。',
                fields: { pollTimeout: '接收超时（秒）', maxAge: '更新最大有效时间（秒）' },
            },
        },
    },
}
