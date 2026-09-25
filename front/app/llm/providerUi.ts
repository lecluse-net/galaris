import type { AICapability, LLMProviderType } from './services/llmProviderService'

// Documents are a catalog view of chat models with native file input.
export type ProviderResourceCategory = AICapability | 'documents'

export function providerResourceCategories(capabilities: AICapability[]): ProviderResourceCategory[] {
    return capabilities.flatMap<ProviderResourceCategory>(value => value === 'chat' ? [value, 'documents'] : [value])
}

export function providerResourceCapability(category: ProviderResourceCategory): AICapability {
    return category === 'documents' ? 'chat' : category
}

// Local assets: the provider catalog must not contact third-party logo services.
const PROVIDER_LOGOS: Record<string, string> = {
    'anthropic-api': 'anthropic.svg',
    'azure-speech': 'azure-color.svg',
    byteplus: 'byteplus.png',
    cerebras: 'cerebras-color.svg',
    cohere: 'cohere-color.svg',
    deepseek: 'deepseek-color.svg',
    elevenlabs: 'elevenlabs.svg',
    fireworks: 'fireworks-color.svg',
    gemini: 'gemini-color.svg',
    'google-cloud-tts': 'google-color.svg',
    groq: 'groq.svg',
    huggingface: 'huggingface-color.svg',
    mammouth: 'mammouth.svg',
    mistral: 'mistral-color.svg',
    nvidia: 'nvidia-color.svg',
    ollama: 'ollama.svg',
    'openai-api': 'openai.svg',
    'openai-codex': 'openai.svg',
    openrouter: 'openrouter.svg',
    perplexity: 'perplexity-color.svg',
    sunoapi: 'sunoapi.png',
    together: 'together-color.svg',
    xai: 'xai.svg',
}

export function providerLogo(code: string | null): string | null {
    const file = code ? PROVIDER_LOGOS[code] : undefined
    return file ? `/provider-logos/${file}` : null
}

export interface ProviderConfigurationDraft {
    name: string
    provider_type: LLMProviderType
    base_url: string
    api_key: string | null
    configuration: Record<string, unknown>
    is_active: boolean
    user_id: number | null
    subscription_acknowledged: boolean
}
