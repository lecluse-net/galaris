export default {
    fr: {
        messagingProviders: {
            oneBot: {
                networkHint: "L’adaptateur OneBot ouvre un WebSocket vers Galaris. Une URL publique n’est nécessaire que si l’adaptateur ne peut pas joindre Galaris via le réseau local ou un VPN.",
                networkWarning: "L’adresse utilisée dans ce navigateur ({origin}) semble locale ou privée. Vérifiez la connexion depuis l’adaptateur ; localhost désigne sa propre machine ou son conteneur. Utilisez une adresse Galaris joignable via le réseau local, un VPN ou un tunnel. Cet avertissement analyse uniquement l’adresse du navigateur, sans vérifier le DNS ni la joignabilité.",
                guide: 'Un adaptateur OneBot 11 (NapCat, Lagrange, etc.) ouvre un WebSocket inverse vers Galaris.',
                steps: [
                    'Installez un adaptateur OneBot 11 en mode WebSocket inverse Universal, avec les messages au format tableau de segments.',
                    'Dans Outils, activez la Messagerie avec le bridge one_bot, renseignez sa plateforme et associez les paramètres de connexion user_id et token.',
                    'Dans Outils → Connexions, configurez le compte du bot et son secret pour chaque agent. Connectez l’adaptateur à wss://votre-galaris/ws/onebot/:platform/:user_id avec ce secret Bearer. Un réseau local ou VPN suffit ; le dialogue avec un nouveau contact nécessite l’accord du manager.',
                ],
                fields: { platform: 'Nom de plateforme', platformHint: 'Exemple : qq', secret: 'Secret du WebSocket' },
            },
        },
    },
    en: {
        messagingProviders: {
            oneBot: {
                networkHint: "The OneBot adapter opens a WebSocket to Galaris. A public URL is only needed if the adapter cannot reach Galaris through the local network or a VPN.",
                networkWarning: "The address used in this browser ({origin}) appears local or private. Check connectivity from the adapter; localhost refers to its own machine or container. Use a Galaris address reachable through the local network, a VPN or a tunnel. This warning only inspects the browser address, without checking DNS or reachability.",
                guide: 'A OneBot 11 adapter (NapCat, Lagrange, and others) opens a reverse WebSocket to Galaris.',
                steps: [
                    'Install a OneBot 11 adapter in Universal reverse WebSocket mode, using segment arrays for messages.',
                    'In Tools, enable Messaging with the one_bot bridge, enter its platform and map the user_id and token connection parameters.',
                    'In Tools → Connections, configure each agent’s bot account and secret. Connect the adapter to wss://your-galaris/ws/onebot/:platform/:user_id with that Bearer secret. A local network or VPN is sufficient; dialogue with a new contact requires manager approval.',
                ],
                fields: { platform: 'Platform name', platformHint: 'Example: qq', secret: 'WebSocket secret' },
            },
        },
    },
    zh: {
        messagingProviders: {
            oneBot: {
                networkHint: "OneBot 适配器向 Galaris 建立 WebSocket 连接。只有适配器无法通过本地网络或 VPN 访问 Galaris 时，才需要公开 URL。",
                networkWarning: "此浏览器使用的地址（{origin}）似乎是本地或私有地址。请从适配器检查连接；localhost 指适配器自身的机器或容器。请使用可通过本地网络、VPN 或隧道访问的 Galaris 地址。此提示仅检查浏览器地址，不验证 DNS 或可达性。",
                guide: 'OneBot 11 适配器（NapCat、Lagrange 等）会向 Galaris 建立反向 WebSocket 连接。',
                steps: ['安装 OneBot 11 适配器，使用 Universal 反向 WebSocket 模式和消息段数组格式。', '在“工具”中启用消息服务，选择 one_bot 桥接，填写平台并映射 user_id 和 token 连接参数。', '在“工具 → 连接”中为每个智能体配置机器人账户和密钥。使用此 Bearer 密钥连接到 wss://your-galaris/ws/onebot/:platform/:user_id。局域网或 VPN 即可；与新联系人对话需要管理员批准。'],
                fields: { platform: '平台名称', platformHint: '示例：qq', secret: 'WebSocket 密钥' },
            },
        },
    },
}
