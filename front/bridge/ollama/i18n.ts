export default {
  fr: {
    llm: {
      customProviders: {
        ollama: {
          label: 'Instance Ollama',
          guide: 'Indiquez l’adresse de cette instance Ollama. Vous pouvez en créer plusieurs.',
          multipleHint: 'Chaque instance Ollama est un fournisseur distinct : local, GPU, NAS, etc.',
          urlHint: 'Ex : http://ollama:11434 ou http://192.168.1.20:11434',
        },
      },
    },
  },
  en: {
    llm: {
      customProviders: {
        ollama: {
          label: 'Ollama instance',
          guide: 'Enter this Ollama instance address. You can create multiple instances.',
          multipleHint: 'Each Ollama instance is a separate provider: local, GPU, NAS, and so on.',
          urlHint: 'E.g. http://ollama:11434 or http://192.168.1.20:11434',
        },
      },
    },
  },
  zh: {
    llm: {
      customProviders: {
        ollama: {
          label: 'Ollama 实例',
          guide: '输入此 Ollama 实例的地址。您可以创建多个实例。',
          multipleHint: '每个 Ollama 实例都是独立服务商，例如本机、GPU、NAS 等。',
          urlHint: '例如：http://ollama:11434 或 http://192.168.1.20:11434',
        },
      },
    },
  },
}
