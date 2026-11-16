import type { CustomProviderTypeContribution } from '@/app/llm/contracts'

export default {
  providerType: 'ollama',
  labelKey: 'llm.customProviders.ollama.label',
  guideKey: 'llm.customProviders.ollama.guide',
  hintKey: 'llm.customProviders.ollama.multipleHint',
  urlHintKey: 'llm.customProviders.ollama.urlHint',
  icon: 'dns',
  bannerClass: 'bg-solaire-gray-light text-solaire-gray',
  apiKeyRequired: false,
  defaultBaseUrl: 'http://ollama:11434',
} satisfies CustomProviderTypeContribution
