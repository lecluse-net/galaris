export const labSections = [
  {
    key: 'tasks',
    slug: 'ai-evaluations',
    icon: 'manage_search',
    color: 'green',
    titleKey: 'evaluation.tabs.taskAnalysis',
    descriptionKey: 'evaluation.sectionInfo.taskAnalysis',
  },
  {
    key: 'dispatcher',
    slug: 'dispatcher',
    icon: 'alt_route',
    color: 'blue',
    titleKey: 'evaluation.tabs.dispatcher',
    descriptionKey: 'evaluation.sectionInfo.dispatcher',
  },
  {
    key: 'briefing',
    slug: 'briefing',
    icon: 'assignment',
    color: 'orange',
    titleKey: 'evaluation.tabs.briefing',
    descriptionKey: 'evaluation.mechanismInfo.briefing',
  },
  {
    key: 'planner',
    slug: 'planner',
    icon: 'account_tree',
    color: 'yellow',
    titleKey: 'evaluation.tabs.planner',
    descriptionKey: 'evaluation.mechanismInfo.planner',
  },
  {
    key: 'topic_classification',
    slug: 'topic-detection',
    icon: 'topic',
    color: 'salmon',
    titleKey: 'evaluation.tabs.topicClassification',
    descriptionKey: 'evaluation.mechanismInfo.topicClassification',
  },
  {
    key: 'memory_extraction',
    slug: 'memory-extraction',
    icon: 'psychology_alt',
    color: 'iris',
    titleKey: 'evaluation.tabs.memoryExtraction',
    descriptionKey: 'evaluation.mechanismInfo.memoryExtraction',
  },
  {
    key: 'outcome_reflection',
    slug: 'learning',
    icon: 'model_training',
    color: 'violet',
    titleKey: 'evaluation.tabs.learning',
    descriptionKey: 'evaluation.mechanismInfo.learning',
  },
  {
    key: 'goal_tracking',
    slug: 'goal-tracking',
    icon: 'track_changes',
    color: 'green',
    titleKey: 'evaluation.tabs.goalTracking',
    descriptionKey: 'evaluation.mechanismInfo.goalTracking',
  },
  {
    key: 'task_executor',
    slug: 'task-executor',
    icon: 'smart_toy',
    color: 'blue',
    titleKey: 'evaluation.tabs.taskExecutor',
    descriptionKey: 'evaluation.mechanismInfo.taskExecutor',
  },
  {
    key: 'conversation_executor',
    slug: 'conversation-executor',
    icon: 'forum',
    color: 'cyan',
    titleKey: 'evaluation.tabs.conversationExecutor',
    descriptionKey: 'evaluation.mechanismInfo.conversationExecutor',
  },
  {
    key: 'voice_executor',
    slug: 'voice-executor',
    icon: 'record_voice_over',
    color: 'fuchsia',
    titleKey: 'evaluation.tabs.voiceExecutor',
    descriptionKey: 'evaluation.mechanismInfo.voiceExecutor',
  },
] as const

export type LabSectionKey = (typeof labSections)[number]['key']

export function labSectionPath(slug: string): string {
  return `/lab/${slug}`
}

export function findLabSectionBySlug(slug: string) {
  return labSections.find(section => section.slug === slug)
}
