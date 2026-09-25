export const textTiers = ['high', 'standard', 'low', 'ultra-low'] as const
export type TextTier = typeof textTiers[number]
export type ExternalClient = 'claude' | 'codex'

export interface ClientProfile {
  code: string
  models: string[]
}

export function clientProfiles(selectors: string[]): ClientProfile[] {
  const profiles = new Map<string, Set<string>>()
  for (const selector of selectors) {
    const [code, usage, tier, extra] = selector.split('/')
    if (!code || usage !== 'text' || extra !== undefined || !textTiers.some(value => value === tier)) continue
    if (!profiles.has(code)) profiles.set(code, new Set())
    profiles.get(code)?.add(selector)
  }
  return [...profiles].sort(([a], [b]) => a.localeCompare(b)).map(([code, models]) => ({
    code,
    models: textTiers.map(tier => `${code}/text/${tier}`).filter(model => models.has(model)),
  }))
}

export function buildClientConfig(
  client: ExternalClient, origin: string, profile: ClientProfile, model: string,
): string {
  if (!profile.models.includes(model)) throw new Error('Model is not available in this profile')
  const base = origin.replace(/\/$/, '')
  if (client === 'codex') {
    return [
      `model = ${JSON.stringify(model)}`,
      'model_provider = "galaris"',
      '',
      '[model_providers.galaris]',
      'name = "Galaris"',
      `base_url = ${JSON.stringify(`${base}/api/profile/openai`)}`,
      'env_key = "GALARIS_API_TOKEN"',
      'wire_api = "responses"',
      'requires_openai_auth = false',
      'supports_websockets = false',
      '',
    ].join('\n')
  }
  const tierModel = (tier: TextTier): string => {
    const selector = `${profile.code}/text/${tier}`
    return profile.models.includes(selector) ? selector : model
  }
  const env: Record<string, string> = {
    ANTHROPIC_BASE_URL: `${base}/api/profile/anthropic`,
  }
  for (const [alias, tier] of [
    ['HAIKU', 'ultra-low'], ['SONNET', 'low'], ['OPUS', 'standard'], ['FABLE', 'high'],
  ] as const) {
    const selected = tierModel(tier)
    env[`ANTHROPIC_DEFAULT_${alias}_MODEL`] = selected
    env[`ANTHROPIC_DEFAULT_${alias}_MODEL_NAME`] = `Galaris · ${selected}`
    env[`ANTHROPIC_DEFAULT_${alias}_MODEL_DESCRIPTION`] = selected
  }
  env.CLAUDE_CODE_SUBAGENT_MODEL = tierModel('low')
  env.CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = '1'
  return JSON.stringify({ model, env }, null, 2) + '\n'
}

export function clientTokenSetup(client: ExternalClient): string {
  return client === 'codex'
    ? "export GALARIS_API_TOKEN='<GALARIS_API_TOKEN>'\n"
    : JSON.stringify({ env: { ANTHROPIC_AUTH_TOKEN: '<GALARIS_API_TOKEN>' } }, null, 2) + '\n'
}
