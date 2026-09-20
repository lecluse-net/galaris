export default {
    fr: {
        messagingProviders: {
            nextcloudTalk: {
                guide: 'Galaris se connecte comme un utilisateur Nextcloud dédié et surveille les conversations Talk auxquelles ce compte participe.',
                steps: [
                    'Configurez l’outil Nextcloud avec son URL WebDAV et ses paramètres de connexion.',
                    'Créez un compte Nextcloud dédié pour chaque agent et ajoutez-le aux conversations Talk utiles.',
                    'Renseignez ses identifiants dans la connexion Outils → Nextcloud ; la même connexion sert à Talk et au partage de fichiers.',
                ],
                fields: {
                    inbound: 'Mode de réception',
                    hpbUrl: 'URL du serveur de signalisation (HPB)',
                    discoveryInterval: 'Découverte des conversations (secondes)',
                    longpollTimeout: 'Attente longue (secondes)',
                },
                options: { polling: 'Polling Talk (recommandé)', signaling: 'Signalisation HPB' },
            },
        },
    },
    en: {
        messagingProviders: {
            nextcloudTalk: {
                guide: 'Galaris connects as a dedicated Nextcloud user and watches the Talk conversations joined by that account.',
                steps: [
                    'Configure the Nextcloud tool with its WebDAV URL and connection parameters.',
                    'Create one dedicated Nextcloud account per agent and add it to the relevant Talk conversations.',
                    'Enter its credentials under Tools → Nextcloud; the same connection serves Talk and file sharing.',
                ],
                fields: {
                    inbound: 'Reception mode',
                    hpbUrl: 'Signaling server URL (HPB)',
                    discoveryInterval: 'Conversation discovery (seconds)',
                    longpollTimeout: 'Long-poll timeout (seconds)',
                },
                options: { polling: 'Talk polling (recommended)', signaling: 'HPB signaling' },
            },
        },
    },
    zh: {
        messagingProviders: {
            nextcloudTalk: {
                guide: 'Galaris 以专用 Nextcloud 用户身份连接，并监控该账户加入的 Talk 对话。',
                steps: ['使用 WebDAV URL 和连接参数配置 Nextcloud 工具。', '为每个智能体创建专用 Nextcloud 账户，并加入相关 Talk 对话。', '在“工具 → Nextcloud”中输入凭据；同一连接同时用于 Talk 和文件共享。'],
                fields: { inbound: '接收模式', hpbUrl: '信令服务器 URL（HPB）', discoveryInterval: '对话发现间隔（秒）', longpollTimeout: '长轮询超时（秒）' },
                options: { polling: 'Talk 轮询（推荐）', signaling: 'HPB 信令' },
            },
        },
    },
}
