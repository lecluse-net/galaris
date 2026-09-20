export default {
    fr: {
      contextHelpPages: {
        "browser": "Le navigateur agentique donne à un agent un véritable environnement de navigation : il peut ouvrir des sites, lire leur contenu, observer la page et interagir avec elle à l’aide de ses outils. Il complète les recherches d’informations lorsque la demande nécessite une action sur un site ou une page qui se construit dans le navigateur. Chaque session est isolée pour garder le contexte du travail en cours. Les réglages de cette page encadrent la durée des sessions, la quantité de texte extraite et les captures d’écran. Ils permettent d’adapter le travail web des agents aux pages consultées et aux ressources disponibles."
      },
        browserSettings: {
            title: 'Navigateur',
            subtitle: 'Réglez les délais, l’extraction et les captures du Tool Navigateur. Les changements s’appliquent aux prochaines opérations ; les dimensions par défaut concernent les nouvelles fenêtres.',
            loadError: 'Impossible de charger les préférences du navigateur.',
            retry: 'Réessayer',
            fields: {
                sessionTtl: 'Durée maximale d’inactivité d’une session (secondes)',
                maxSessions: 'Nombre maximal de sessions simultanées',
                timeout: 'Délai maximal d’une opération (secondes)',
                viewportWidth: 'Largeur par défaut de la fenêtre (pixels)',
                viewportHeight: 'Hauteur par défaut de la fenêtre (pixels)',
                contentMaxChars: 'Taille maximale du texte extrait (caractères)',
                htmlMaxBytes: 'Taille maximale du HTML (Mo)',
                tileHeight: 'Hauteur des segments de capture (pixels)',
                maxTiles: 'Nombre maximal de segments par capture',
                maxTotalBytes: 'Taille totale maximale d’une capture (Mo)',
            },
        },
    },
    en: {
      contextHelpPages: {
        "browser": "The agent browser gives an agent a real browsing environment: it can open websites, read content, inspect the page and interact through its tools. It complements information searches when a request requires action on a website or a page built inside the browser. Each session is isolated to preserve the current work’s context. These settings control session duration, extracted text and screenshots. They let you adapt agents’ web work to the pages they visit and the resources available."
      },
        browserSettings: {
            title: 'Browser',
            subtitle: 'Configure Browser Tool timeouts, extraction and screenshots. Changes apply to subsequent operations; default dimensions apply to new windows.',
            loadError: 'Browser preferences could not be loaded.',
            retry: 'Retry',
            fields: {
                sessionTtl: 'Maximum session idle time (seconds)',
                maxSessions: 'Maximum concurrent sessions',
                timeout: 'Operation timeout (seconds)',
                viewportWidth: 'Default window width (pixels)',
                viewportHeight: 'Default window height (pixels)',
                contentMaxChars: 'Maximum extracted text (characters)',
                htmlMaxBytes: 'Maximum HTML size (MB)',
                tileHeight: 'Screenshot tile height (pixels)',
                maxTiles: 'Maximum tiles per screenshot',
                maxTotalBytes: 'Maximum total screenshot size (MB)',
            },
        },
    },
    zh: {
      contextHelpPages: {
        "browser": "智能体浏览器提供真实的网页浏览环境：智能体可以打开网站、阅读内容、观察页面，并通过工具进行交互。当请求需要在网站上执行操作或读取由浏览器动态生成的页面时，它能补充普通信息搜索。每个会话相互隔离，以保留当前工作的上下文。此页面设置会话时长、文本提取量和屏幕截图限制，帮助您根据访问页面和可用资源调整智能体的网页工作。"
      },
        browserSettings: {
            title: '浏览器',
            subtitle: '配置浏览器工具的超时、内容提取和截图。更改适用于后续操作，默认尺寸适用于新窗口。',
            loadError: '无法加载浏览器偏好设置。',
            retry: '重试',
            fields: {
                sessionTtl: '会话最大空闲时间（秒）',
                maxSessions: '最大并发会话数',
                timeout: '操作超时（秒）',
                viewportWidth: '默认窗口宽度（像素）',
                viewportHeight: '默认窗口高度（像素）',
                contentMaxChars: '提取文本最大长度（字符）',
                htmlMaxBytes: 'HTML 最大大小（MB）',
                tileHeight: '截图分段高度（像素）',
                maxTiles: '每次截图最大分段数',
                maxTotalBytes: '截图最大总大小（MB）',
            },
        },
    },
}
