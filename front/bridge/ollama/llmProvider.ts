import type { CustomProviderTypeContribution } from '@/app/llm/customProviderTypes'

export default {
  providerType: 'ollama',
  labelKey: 'llm.customProviders.ollama.label',
  guideKey: 'llm.customProviders.ollama.guide',
  hintKey: 'llm.customProviders.ollama.multipleHint',
  urlHintKey: 'llm.customProviders.ollama.urlHint',
  icon: 'dns',
  bannerClass: 'bg-blue-grey-1 text-blue-grey-10',
  apiKeyRequired: false,
  defaultBaseUrl: 'http://ollama:11434',
} satisfies CustomProviderTypeContribution
