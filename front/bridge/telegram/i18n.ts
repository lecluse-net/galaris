export default {
    fr: {
        messagingProviders: {
            telegram: {
                guide: 'Telegram utilise un bot par agent. Les jetons restent chiffrés dans les connexions des agents, pas dans ces réglages globaux.',
                steps: [
                    'Ouvrez @BotFather dans Telegram, lancez /newbot et copiez le jeton du bot.',
                    'Dans Outils → Messagerie, créez la connexion de l’agent avec ce jeton et les identifiants autorisés.',
                    'Envoyez d’abord un message au bot, puis lancez le test ici. Les notes vocales sont prises en charge, pas les appels Telegram temps réel.',
                ],
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
                guide: 'Telegram uses one bot per agent. Tokens stay encrypted in agent connections, not in these global settings.',
                steps: [
                    'Open @BotFather in Telegram, run /newbot, and copy the bot token.',
                    'In Tools → Messaging, create the agent connection with that token and the allowed IDs.',
                    'Send the bot a first message, then run the test here. Voice notes are supported; real-time Telegram calls are not.',
                ],
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
                guide: 'Telegram 为每个智能体使用一个机器人。令牌加密保存在智能体连接中，而不是全局设置中。',
                steps: ['在 Telegram 中打开 @BotFather，运行 /newbot 并复制机器人令牌。', '在“工具 → 消息”中，使用该令牌和允许的 ID 创建智能体连接。', '先向机器人发送一条消息，再在此运行测试。支持语音消息，但不支持 Telegram 实时通话。'],
                fields: { pollTimeout: '接收超时（秒）', maxAge: '更新最大有效时间（秒）' },
            },
        },
    },
}
