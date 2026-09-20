export const preferenceSections = [
  {
    key: 'system',
    slug: 'system',
    icon: 'tune',
    color: 'gray',
    titleKey: 'systemSettings.title',
    descriptionKey: 'systemSettings.subtitle',
  },
  {
    key: 'language',
    slug: 'language',
    icon: 'language',
    color: 'blue',
    titleKey: 'configuration.tabs.language',
    descriptionKey: 'languageSettings.subtitle',
  },
  {
    key: 'messaging',
    slug: 'messaging',
    icon: 'forum',
    color: 'cyan',
    titleKey: 'configuration.tabs.messaging',
    descriptionKey: 'configuration.messaging.subtitle',
  },
  {
    key: 'memory',
    slug: 'memory',
    icon: 'memory',
    color: 'iris',
    titleKey: 'configuration.tabs.memory',
    descriptionKey: 'memorySettings.subtitle',
  },
  {
    key: 'dream',
    slug: 'dream',
    icon: 'bedtime',
    color: 'violet',
    titleKey: 'configuration.tabs.dream',
    descriptionKey: 'dreamSettings.subtitle',
  },
  {
    key: 'voice',
    slug: 'voice',
    icon: 'call',
    color: 'fuchsia',
    titleKey: 'configuration.tabs.voice',
    descriptionKey: 'voiceSettings.subtitle',
  },
  {
    key: 'audio',
    slug: 'audio',
    icon: 'graphic_eq',
    color: 'salmon',
    titleKey: 'configuration.tabs.audio',
    descriptionKey: 'audioSettings.subtitle',
  },
  {
    key: 'process',
    slug: 'processes',
    icon: 'account_tree',
    color: 'orange',
    titleKey: 'configuration.tabs.process',
    descriptionKey: 'processSettings.subtitle',
  },
  {
    key: 'tasks',
    slug: 'tasks',
    icon: 'task_alt',
    color: 'green',
    titleKey: 'configuration.tabs.tasks',
    descriptionKey: 'taskSettings.subtitle',
  },
  {
    key: 'harnesses',
    slug: 'harnesses',
    icon: 'smart_toy',
    color: 'blue',
    titleKey: 'configuration.tabs.harnesses',
    descriptionKey: 'harnessSettings.subtitle',
  },
  {
    key: 'search',
    slug: 'search',
    icon: 'search',
    color: 'yellow',
    titleKey: 'configuration.tabs.search',
    descriptionKey: 'searchSettings.subtitle',
  },
  {
    key: 'janus',
    slug: 'janus',
    icon: 'hub',
    color: 'cyan',
    titleKey: 'params.janus',
    descriptionKey: 'params.janusGuideDescription',
  },
  {
    key: 'instructions',
    slug: 'instructions',
    icon: 'description',
    color: 'orange',
    titleKey: 'params.instructions',
    descriptionKey: 'params.executorInstructionsHelp',
  },
  {
    key: 'logs',
    slug: 'logs',
    icon: 'receipt_long',
    color: 'gray',
    titleKey: 'params.logs.tab',
    descriptionKey: 'params.logs.subtitle',
  },
] as const

export type PreferenceSectionKey = (typeof preferenceSections)[number]['key']

export function preferenceSectionPath(slug: string): string {
  return `/params/${slug}`
}

export function harnessSettingsPath(providerCode: string): string {
  return `/params/harnesses/${encodeURIComponent(providerCode)}`
}

export function findPreferenceSectionBySlug(slug: string) {
  return preferenceSections.find(section => section.slug === slug)
}
