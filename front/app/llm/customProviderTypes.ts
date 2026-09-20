export interface CustomProviderTypeContribution {
  providerType: string
  labelKey: string
  guideKey: string
  hintKey: string
  urlHintKey: string
  icon: string
  bannerClass: string
  apiKeyRequired: boolean
  defaultBaseUrl: string
}

interface ContributionModule {
  default: CustomProviderTypeContribution
}

const canonicalOpenAICompatible: CustomProviderTypeContribution = {
  providerType: 'openai_compatible',
  labelKey: 'llm.customOpenAiCompatible',
  guideKey: 'llm.apiKeyGuide',
  hintKey: 'llm.openAiCompatibleMultipleHint',
  urlHintKey: 'llm.apiUrlHint',
  icon: 'lan',
  bannerClass: 'bg-blue-1 text-blue-10',
  apiKeyRequired: true,
  defaultBaseUrl: '',
}

const bridgeModules = import.meta.glob<ContributionModule>(
  '../../bridge/*/llmProvider.ts',
  { eager: true },
)

export const customProviderTypes = [
  canonicalOpenAICompatible,
  ...Object.values(bridgeModules)
    .map(module => module.default)
    .filter(
      (item): item is CustomProviderTypeContribution =>
        Boolean(item?.providerType),
    ),
]

export function customProviderType(
  providerType: string,
): CustomProviderTypeContribution {
  return (
    customProviderTypes.find(item => item.providerType === providerType)
    || canonicalOpenAICompatible
  )
}
