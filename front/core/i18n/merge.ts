export type LocaleMessages = Record<string, unknown>

function cloneMessageValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(cloneMessageValue)
  if (value && typeof value === 'object') {
    return deepMergeMessages({}, value as LocaleMessages)
  }
  return value
}

/** Merge locale messages without retaining references to the source catalog. */
export function deepMergeMessages(
  target: LocaleMessages,
  source: LocaleMessages,
): LocaleMessages {
  for (const key of Object.keys(source)) {
    const sourceValue = source[key]
    const targetValue = target[key]
    if (
      sourceValue
      && typeof sourceValue === 'object'
      && !Array.isArray(sourceValue)
      && targetValue
      && typeof targetValue === 'object'
      && !Array.isArray(targetValue)
    ) {
      deepMergeMessages(
        targetValue as LocaleMessages,
        sourceValue as LocaleMessages,
      )
    } else {
      target[key] = cloneMessageValue(sourceValue)
    }
  }
  return target
}
