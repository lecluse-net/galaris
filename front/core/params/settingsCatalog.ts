import type { SettingField } from './settingsTypes'

export const systemFields: SettingField[] = [
    { name: 'ALLOW_USER_REGISTRATION', labelKey: 'systemSettings.allowRegistration', descriptionKey: 'systemSettings.allowRegistrationHint', input: 'boolean' },
    { name: 'HTTP_RATE_LIMIT_PER_MINUTE', labelKey: 'systemSettings.rateLimit', descriptionKey: 'systemSettings.rateLimitHint', input: 'integer', min: 1 },
    { name: 'LOGFIRE_TOKEN', labelKey: 'observabilitySettings.token', descriptionKey: 'observabilitySettings.tokenHint', input: 'secret' },
]

export const memoryStorageFields: SettingField[] = [
    { name: 'MEMORY_RESOURCE_MAX_BYTES', labelKey: 'storageSettings.memoryResourceMaxBytes', input: 'integer', sizeUnit: 'bytes', min: 1024 },
]

export const languageFields: SettingField[] = [
    {
        name: 'DEFAULT_LANGUAGE',
        labelKey: 'languageSettings.fields.defaultLanguage',
        descriptionKey: 'languageSettings.fields.defaultLanguageHint',
        input: 'select',
        options: [
            { value: '', labelKey: 'languageSettings.languages.automatic' },
            { value: 'en', labelKey: 'languageSettings.languages.en' },
            { value: 'fr', labelKey: 'languageSettings.languages.fr' },
            { value: 'zh', labelKey: 'languageSettings.languages.zh' },
        ],
    },
    {
        name: 'LOCALIZATION',
        labelKey: 'languageSettings.fields.localization',
        descriptionKey: 'languageSettings.fields.localizationHint',
    },
]

export const executorInstructionFields: SettingField[] = [
    {
        name: 'ai.executor-system-prompt',
        labelKey: 'params.def.ai_executor_system_prompt.label',
        descriptionKey: 'params.def.ai_executor_system_prompt.description',
        input: 'prompt',
    },
    {
        name: 'ai.conversation-executor-system-prompt',
        labelKey: 'params.def.ai_conversation_executor_system_prompt.label',
        descriptionKey: 'params.def.ai_conversation_executor_system_prompt.description',
        input: 'prompt',
    },
    {
        name: 'ai.voice-executor-system-prompt',
        labelKey: 'params.def.ai_voice_executor_system_prompt.label',
        descriptionKey: 'params.def.ai_voice_executor_system_prompt.description',
        input: 'prompt',
    },
    {
        name: 'ai.conversation-action-policy',
        labelKey: 'params.def.ai_conversation_action_policy.label',
        descriptionKey: 'params.def.ai_conversation_action_policy.description',
        input: 'prompt',
    },
]

export const audioMeetingSummaryFields: SettingField[] = [
    {
        name: 'audio.summary-meeting-segment-system-prompt',
        labelKey: 'audioSettings.fields.meetingSegment',
        descriptionKey: 'audioSettings.fields.meetingSegmentHint',
        input: 'prompt',
    },
    {
        name: 'audio.summary-meeting-reduce-system-prompt',
        labelKey: 'audioSettings.fields.meetingReduce',
        descriptionKey: 'audioSettings.fields.meetingReduceHint',
        input: 'prompt',
    },
    {
        name: 'audio.summary-meeting-final-system-prompt',
        labelKey: 'audioSettings.fields.meetingFinal',
        descriptionKey: 'audioSettings.fields.meetingFinalHint',
        input: 'prompt',
    },
]

export const audioVideoSummaryFields: SettingField[] = [
    {
        name: 'audio.summary-video-segment-system-prompt',
        labelKey: 'audioSettings.fields.videoSegment',
        descriptionKey: 'audioSettings.fields.videoSegmentHint',
        input: 'prompt',
    },
    {
        name: 'audio.summary-video-reduce-system-prompt',
        labelKey: 'audioSettings.fields.videoReduce',
        descriptionKey: 'audioSettings.fields.videoReduceHint',
        input: 'prompt',
    },
    {
        name: 'audio.summary-video-final-system-prompt',
        labelKey: 'audioSettings.fields.videoFinal',
        descriptionKey: 'audioSettings.fields.videoFinalHint',
        input: 'prompt',
    },
]

export const commonMessagingFields: SettingField[] = [
    { name: 'MESSENGER_MAX_INLINE_MB', labelKey: 'configuration.fields.inlineMaxMb', descriptionKey: 'configuration.fields.inlineMaxMbHint', input: 'number', sizeUnit: 'mebibytes', min: 1_000_000 / 1_048_576, max: 1_000, step: 1_000_000 / 1_048_576, advanced: true },
    { name: 'MESSENGER_CONTENT_MAX_MB', labelKey: 'configuration.fields.contentMaxMb', input: 'integer', min: 1, max: 1_000, advanced: true },
    { name: 'MESSENGER_VOICE_MAX_DURATION_MINUTES', labelKey: 'configuration.fields.voiceMaxDuration', input: 'integer', min: 1, max: 120, advanced: true },
]

export const memorySessionFields: SettingField[] = [
    {
        name: 'MESSENGER_SESSION_MAX_MESSAGES',
        labelKey: 'memorySettings.fields.sessionMessages',
        descriptionKey: 'memorySettings.fields.sessionMessagesHint',
        input: 'integer',
        min: 1,
        max: 500,
    },
    {
        name: 'MESSENGER_SESSION_MAX_CHARS',
        labelKey: 'memorySettings.fields.sessionChars',
        descriptionKey: 'memorySettings.fields.sessionCharsHint',
        input: 'integer',
        min: 1_000,
        max: 500_000,
    },
]

export const memoryContextFields: SettingField[] = [
    {
        name: 'MEMORY_CONTEXT_ENABLED',
        labelKey: 'memorySettings.fields.contextEnabled',
        descriptionKey: 'memorySettings.fields.contextEnabledHint',
        input: 'boolean',
    },
    {
        name: 'MEMORY_CONTEXT_MAX_ITEMS',
        labelKey: 'memorySettings.fields.contextItems',
        descriptionKey: 'memorySettings.fields.contextItemsHint',
        input: 'integer',
        min: 1,
        max: 50,
        advanced: true,
    },
    {
        name: 'MEMORY_CONTEXT_MAX_CHARS',
        labelKey: 'memorySettings.fields.contextChars',
        descriptionKey: 'memorySettings.fields.contextCharsHint',
        input: 'integer',
        min: 1_000,
        max: 200_000,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_CANDIDATE_LIMIT',
        labelKey: 'memorySettings.fields.recallCandidates',
        descriptionKey: 'memorySettings.fields.recallCandidatesHint',
        input: 'integer',
        min: 8,
        max: 200,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_SEMANTIC_QUERY_MAX_CHARS',
        labelKey: 'memorySettings.fields.semanticQueryChars',
        descriptionKey: 'memorySettings.fields.semanticQueryCharsHint',
        input: 'integer',
        min: 240,
        max: 4_000,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_SEMANTIC_WEIGHT',
        labelKey: 'memorySettings.fields.semanticWeight',
        descriptionKey: 'memorySettings.fields.weightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_LEXICAL_WEIGHT',
        labelKey: 'memorySettings.fields.lexicalWeight',
        descriptionKey: 'memorySettings.fields.weightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_TOPIC_WEIGHT',
        labelKey: 'memorySettings.fields.topicWeight',
        descriptionKey: 'memorySettings.fields.topicWeightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_GRAPH_WEIGHT',
        labelKey: 'memorySettings.fields.graphWeight',
        descriptionKey: 'memorySettings.fields.weightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_SUGGESTED_LINK_WEIGHT',
        labelKey: 'memorySettings.fields.suggestedLinkWeight',
        descriptionKey: 'memorySettings.fields.suggestedLinkWeightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_AUTHORITY_WEIGHT',
        labelKey: 'memorySettings.fields.authorityWeight',
        descriptionKey: 'memorySettings.fields.weightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_FRESHNESS_WEIGHT',
        labelKey: 'memorySettings.fields.freshnessWeight',
        descriptionKey: 'memorySettings.fields.weightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_CENTRALITY_WEIGHT',
        labelKey: 'memorySettings.fields.centralityWeight',
        descriptionKey: 'memorySettings.fields.weightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
    {
        name: 'MEMORY_RECALL_DIVERSITY_LAMBDA',
        labelKey: 'memorySettings.fields.diversityWeight',
        descriptionKey: 'memorySettings.fields.diversityWeightHint',
        input: 'number',
        min: 0,
        max: 1,
        step: 0.01,
        advanced: true,
    },
]

export const memoryCaptureFields: SettingField[] = [
    {
        name: 'MEMORY_CAPTURE_ENABLED',
        labelKey: 'memorySettings.fields.captureEnabled',
        descriptionKey: 'memorySettings.fields.captureEnabledHint',
        input: 'boolean',
    },
    {
        name: 'MEMORY_CAPTURE_MIN_CHARS',
        labelKey: 'memorySettings.fields.captureMinChars',
        descriptionKey: 'memorySettings.fields.captureMinCharsHint',
        input: 'integer',
        min: 20,
        max: 20_000,
        advanced: true,
    },
]

export const memoryAutomationFields: SettingField[] = [
    {
        name: 'MEMORY_DUPLICATE_MODE',
        labelKey: 'memorySettings.fields.duplicateMode',
        descriptionKey: 'memorySettings.fields.duplicateModeHint',
        input: 'select',
        options: [
            { value: 'off', labelKey: 'memorySettings.maintenanceModes.off' },
            { value: 'manual', labelKey: 'memorySettings.maintenanceModes.manual' },
            { value: 'automatic', labelKey: 'memorySettings.maintenanceModes.automatic' },
        ],
    },
    {
        name: 'MEMORY_DUPLICATE_SIMILARITY_THRESHOLD',
        labelKey: 'memorySettings.fields.duplicateThreshold',
        descriptionKey: 'memorySettings.fields.duplicateThresholdHint',
        input: 'percentage-slider', min: 80, max: 100, step: 1,
    },
    {
        name: 'MEMORY_CONTRADICTION_MODE',
        labelKey: 'memorySettings.fields.contradictionMode',
        descriptionKey: 'memorySettings.fields.contradictionModeHint',
        input: 'select',
        options: [
            { value: 'off', labelKey: 'memorySettings.maintenanceModes.off' },
            { value: 'manual', labelKey: 'memorySettings.maintenanceModes.manual' },
            { value: 'automatic', labelKey: 'memorySettings.maintenanceModes.automatic' },
        ],
    },
    {
        name: 'MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD',
        labelKey: 'memorySettings.fields.contradictionThreshold',
        descriptionKey: 'memorySettings.fields.contradictionThresholdHint',
        input: 'percentage-slider', min: 80, max: 100, step: 1,
    },
    {
        name: 'MEMORY_AGING_MODE',
        labelKey: 'memorySettings.fields.agingMode',
        descriptionKey: 'memorySettings.fields.agingModeHint',
        input: 'select',
        options: [
            { value: 'off', labelKey: 'memorySettings.maintenanceModes.off' },
            { value: 'manual', labelKey: 'memorySettings.maintenanceModes.manual' },
            { value: 'automatic', labelKey: 'memorySettings.maintenanceModes.automatic' },
        ],
    },
    {
        name: 'MEMORY_AGING_AFTER_DAYS',
        labelKey: 'memorySettings.fields.agingDays',
        descriptionKey: 'memorySettings.fields.agingDaysHint',
        input: 'integer', min: 1, max: 36_500,
    },
    {
        name: 'MEMORY_AUTOMATION_POLL_SECONDS',
        labelKey: 'memorySettings.fields.automationPoll',
        descriptionKey: 'memorySettings.fields.automationPollHint',
        input: 'number',
        min: 0.5,
        max: 300,
        step: 0.5,
    },
    {
        name: 'MEMORY_AUTOMATION_MAX_ATTEMPTS',
        labelKey: 'memorySettings.fields.automationAttempts',
        descriptionKey: 'memorySettings.fields.automationAttemptsHint',
        input: 'integer',
        min: 1,
        max: 50,
    },
]

export const dreamAttachmentFields: SettingField[] = [
    { name: 'DREAM_ATTACHMENT_TEXT_ENABLED', labelKey: 'dreamSettings.attachments.text', input: 'checkbox' },
    { name: 'DREAM_ATTACHMENT_DOCUMENT_ENABLED', labelKey: 'dreamSettings.attachments.document', input: 'checkbox' },
    { name: 'DREAM_ATTACHMENT_IMAGE_ENABLED', labelKey: 'dreamSettings.attachments.image', input: 'checkbox' },
    { name: 'DREAM_ATTACHMENT_VIDEO_ENABLED', labelKey: 'dreamSettings.attachments.video', input: 'checkbox' },
]

export const dreamFields: SettingField[] = [
    {
        name: 'DREAM_ENABLED',
        labelKey: 'dreamSettings.fields.enabled',
        descriptionKey: 'dreamSettings.fields.enabledHint',
        input: 'boolean',
    },
    {
        name: 'DREAM_TOPIC_CREATION_MODE',
        labelKey: 'dreamSettings.fields.topicCreationMode',
        descriptionKey: 'dreamSettings.fields.topicCreationModeHint',
        input: 'select',
        options: [
            { labelKey: 'dreamSettings.topicCreationModes.forbid', value: 'forbid' },
            { labelKey: 'dreamSettings.topicCreationModes.propose', value: 'propose' },
            { labelKey: 'dreamSettings.topicCreationModes.auto', value: 'auto' },
        ],
    },
    {
        name: 'ai.topic-continuity-system-prompt',
        labelKey: 'dreamSettings.fields.topicContinuitySystemPrompt',
        descriptionKey: 'dreamSettings.fields.topicContinuitySystemPromptHint',
        input: 'prompt',
        advanced: true,
    },
    {
        name: 'ai.topic-resolution-system-prompt',
        labelKey: 'dreamSettings.fields.topicResolutionSystemPrompt',
        descriptionKey: 'dreamSettings.fields.topicResolutionSystemPromptHint',
        input: 'prompt',
        advanced: true,
    },
    {
        name: 'ai.memory-extraction-system-prompt',
        labelKey: 'dreamSettings.fields.memoryExtractionSystemPrompt',
        descriptionKey: 'dreamSettings.fields.memoryExtractionSystemPromptHint',
        input: 'prompt',
        advanced: true,
    },
    {
        name: 'ai.topic-classification-system-prompt',
        labelKey: 'dreamSettings.fields.topicSystemPrompt',
        descriptionKey: 'dreamSettings.fields.topicSystemPromptHint',
        input: 'prompt',
        advanced: true,
    },
    {
        name: 'DREAM_SKILL_LEARNING_MODE',
        labelKey: 'dreamSettings.fields.skillLearningMode',
        descriptionKey: 'dreamSettings.fields.skillLearningModeHint',
        input: 'select',
        options: [
            { labelKey: 'dreamSettings.skillLearningModes.off', value: 'off' },
            { labelKey: 'dreamSettings.skillLearningModes.observe', value: 'observe' },
            { labelKey: 'dreamSettings.skillLearningModes.learn', value: 'learn' },
        ],
    },
    {
        name: 'DREAM_SKILL_MIN_EVIDENCE',
        labelKey: 'dreamSettings.fields.skillMinEvidence',
        descriptionKey: 'dreamSettings.fields.skillMinEvidenceHint',
        input: 'integer',
        min: 2,
        max: 100,
    },
    {
        name: 'DREAM_SKILL_ACTIVATION_SCORE',
        labelKey: 'dreamSettings.fields.skillActivationScore',
        descriptionKey: 'dreamSettings.fields.skillActivationScoreHint',
        input: 'number',
        min: 0.5,
        max: 0.99,
        step: 0.01,
    },
    {
        name: 'DREAM_SKILL_MAX_ACTIVE',
        labelKey: 'dreamSettings.fields.skillMaxActive',
        descriptionKey: 'dreamSettings.fields.skillMaxActiveHint',
        input: 'integer',
        min: 1,
        max: 100,
        advanced: true,
    },
    {
        name: 'DREAM_POLL_SECONDS',
        labelKey: 'dreamSettings.fields.poll',
        descriptionKey: 'dreamSettings.fields.pollHint',
        input: 'number',
        min: 1,
        max: 3_600,
        step: 1,
    },
    {
        name: 'DREAM_LEASE_SECONDS',
        labelKey: 'dreamSettings.fields.lease',
        descriptionKey: 'dreamSettings.fields.leaseHint',
        input: 'integer',
        min: 60,
        max: 7_200,
        advanced: true,
    },
    {
        name: 'DREAM_MAX_ATTEMPTS',
        labelKey: 'dreamSettings.fields.attempts',
        descriptionKey: 'dreamSettings.fields.attemptsHint',
        input: 'integer',
        min: 1,
        max: 50,
        advanced: true,
    },
]

export const dreamLinkReconciliationFields: SettingField[] = [
    {
        name: 'MEMORY_LINK_RECONCILIATION_TRIGGER_MODE',
        labelKey: 'dreamSettings.fields.linkReconciliationTriggerMode',
        descriptionKey: 'dreamSettings.fields.linkReconciliationTriggerModeHint',
        input: 'select',
        options: [
            { labelKey: 'dreamSettings.linkReconciliationModes.manualOnly', value: 'manual_only' },
            { labelKey: 'dreamSettings.linkReconciliationModes.afterDream', value: 'after_dream' },
            { labelKey: 'dreamSettings.linkReconciliationModes.scheduled', value: 'scheduled' },
            { labelKey: 'dreamSettings.linkReconciliationModes.afterDreamAndScheduled', value: 'after_dream_and_scheduled' },
        ],
    },
    {
        name: 'MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS',
        labelKey: 'dreamSettings.fields.linkReconciliationInterval',
        descriptionKey: 'dreamSettings.fields.linkReconciliationIntervalHint',
        input: 'integer',
        min: 1,
        max: 720,
    },
]

export const voiceFields: SettingField[] = [
    { name: 'VOICE_ENABLED', labelKey: 'configuration.fields.voiceEnabled', input: 'boolean' },
    { name: 'VOICE_AUTO_ANSWER_ENABLED', labelKey: 'configuration.fields.autoAnswer', input: 'boolean' },
    { name: 'VOICE_SAMPLE_RATE', labelKey: 'configuration.fields.sampleRate', input: 'integer', min: 8000, advanced: true },
    { name: 'VOICE_CHANNELS', labelKey: 'configuration.fields.channels', input: 'integer', min: 1, max: 2, advanced: true },
    { name: 'VOICE_AUTO_ANSWER_POLL_INTERVAL', labelKey: 'configuration.fields.autoAnswerPoll', input: 'number', min: 0.5, step: 0.5, advanced: true },
    { name: 'VOICE_AUTO_ANSWER_DISCOVERY_INTERVAL', labelKey: 'configuration.fields.autoAnswerDiscovery', input: 'number', min: 5, step: 1, advanced: true },
]

export const taskSchedulerFields: SettingField[] = [
    ...[
        ['TASK_SCHEDULER_FAIRNESS_SECONDS', 'fairnessSeconds'],
        ['TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER', 'userConcurrency'],
    ].map(([name, key]) => ({
        name,
        labelKey: `taskSettings.fields.${key}`,
        descriptionKey: `taskSettings.fields.${key}Hint`,
        input: 'integer' as const,
        min: 0,
        advanced: true,
    })),
    {
        name: 'TASK_SCHEDULER_MAX_CONCURRENCY',
        labelKey: 'taskSettings.fields.concurrency',
        descriptionKey: 'taskSettings.fields.concurrencyHint',
        input: 'integer',
        min: 1,
        max: 10,
    },
    {
        name: 'TASK_SCHEDULER_LEASE_SECONDS',
        labelKey: 'taskSettings.fields.lease',
        descriptionKey: 'taskSettings.fields.leaseHint',
        input: 'integer',
        min: 30,
        max: 3600,
    },
    {
        name: 'TASK_ACTION_TIMEOUT_SECONDS',
        labelKey: 'taskSettings.fields.actionTimeout',
        descriptionKey: 'taskSettings.fields.actionTimeoutHint',
        input: 'integer',
        min: 30,
        max: 86400,
    },
]

export const taskRetryFields: SettingField[] = [
    {
        name: 'TASK_ACTION_MAX_ATTEMPTS',
        labelKey: 'taskSettings.fields.actionAttempts',
        descriptionKey: 'taskSettings.fields.actionAttemptsHint',
        input: 'integer',
        min: 1,
        max: 20,
    },
    {
        name: 'TASK_ACTION_RETRY_BASE_SECONDS',
        labelKey: 'taskSettings.fields.actionRetryBase',
        descriptionKey: 'taskSettings.fields.actionRetryBaseHint',
        input: 'number',
        min: 0.1,
        max: 300,
        step: 0.1,
    },
    {
        name: 'TASK_NETWORK_MAX_ATTEMPTS',
        labelKey: 'taskSettings.fields.networkAttempts',
        descriptionKey: 'taskSettings.fields.networkAttemptsHint',
        input: 'integer',
        min: 2,
        max: 30,
    },
    {
        name: 'TASK_NETWORK_RETRY_BASE_SECONDS',
        labelKey: 'taskSettings.fields.networkRetryBase',
        descriptionKey: 'taskSettings.fields.networkRetryBaseHint',
        input: 'number',
        min: 1,
        max: 600,
        step: 1,
    },
    {
        name: 'TASK_NETWORK_RETRY_MAX_SECONDS',
        labelKey: 'taskSettings.fields.networkRetryMax',
        descriptionKey: 'taskSettings.fields.networkRetryMaxHint',
        input: 'number',
        min: 10,
        max: 3600,
        step: 1,
    },
]

export const taskCreationFields: SettingField[] = [
    {
        name: 'ai.task-objective-system-prompt',
        labelKey: 'taskSettings.fields.taskObjectiveSystemPrompt',
        descriptionKey: 'taskSettings.fields.taskObjectiveSystemPromptHint',
        input: 'prompt',
        advanced: true,
    },
]

export const taskBudgetFields: SettingField[] = [
    {
        name: 'TASK_BUDGET_SHARE_GOAL',
        labelKey: 'taskSettings.fields.shareGoal',
        descriptionKey: 'taskSettings.fields.shareGoalHint',
        input: 'boolean',
        advanced: true,
    },
    ...[
        ['TASK_ROOT_MAX_TOKENS', 'rootTokens', 'integer'],
        ['TASK_ROOT_MAX_COST', 'rootCost', 'number'],
        ['TASK_ROOT_MAX_SECONDS', 'rootSeconds', 'integer'],
        ['TASK_ROOT_RESERVE_TOKENS', 'reserveTokens', 'integer'],
        ['TASK_ROOT_RESERVE_COST', 'reserveCost', 'number'],
    ].map(([name, key, input]) => ({
        name,
        labelKey: `taskSettings.fields.${key}`,
        descriptionKey: `taskSettings.fields.${key}Hint`,
        input: input as 'integer' | 'number',
        min: name.includes('RESERVE') ? 0.01 : 0,
        advanced: true,
    })),
]

export const traceRetentionFields: SettingField[] = [
    ['INCIDENT_TRACE_RETENTION_DAYS', 'incidentRetention'],
    ['LLM_TRACE_RETENTION_DAYS', 'llmRetention'],
].map(([name, key]) => ({
    name,
    labelKey: `taskSettings.fields.${key}`,
    descriptionKey: `taskSettings.fields.${key}Hint`,
    input: 'integer',
    min: 0,
}))

export const taskCollaborationFields: SettingField[] = [
    {
        name: 'TASK_ASK_AGENT_TIMEOUT_SECONDS',
        labelKey: 'taskSettings.fields.askTimeout',
        descriptionKey: 'taskSettings.fields.askTimeoutHint',
        input: 'integer',
        min: 60,
    },
    {
        name: 'TASK_ASK_AGENT_MAX_ROUNDS',
        labelKey: 'taskSettings.fields.askRounds',
        descriptionKey: 'taskSettings.fields.askRoundsHint',
        input: 'integer',
        min: 1,
        max: 50,
    },
]

export const processGeneralFields: SettingField[] = [
    {
        name: 'PROCESS_ENGINE_DEFAULT',
        labelKey: 'processSettings.fields.engine',
        input: 'select',
        options: [{ value: 'n8n', labelKey: 'processSettings.n8nLabel' }],
    },
]

export const processAdvancedFields: SettingField[] = [
    ['PROCESS_FILE_REF_TTL_SECONDS', 'fileRefTtl', 'integer'],
    ['PROCESS_START_TIMEOUT_SECONDS', 'startTimeout', 'number'],
    ['PROCESS_REFRESH_TIMEOUT_SECONDS', 'refreshTimeout', 'number'],
    ['PROCESS_REFRESH_STALENESS_SECONDS', 'refreshStaleness', 'integer'],
    ['PROCESS_WAIT_MAX_SECONDS', 'waitMax', 'integer'],
    ['PROCESS_START_MAX_RETRIES', 'startRetries', 'integer'],
    ['PROCESS_START_RETRY_BACKOFF_SECONDS', 'retryBackoff', 'number'],
    ['PROCESS_IDEMPOTENCY_WINDOW_SECONDS', 'idempotencyWindow', 'integer'],
    ['PROCESS_REFRESH_MAX_FAILURES', 'refreshFailures', 'integer'],
    ['PROCESS_SANITIZE_MAX_BYTES', 'sanitizeMaxBytes', 'integer'],
    ['PROCESS_RETENTION_RAW_SNAPSHOT_DAYS', 'rawRetention', 'integer'],
    ['PROCESS_RETENTION_EVENTS_DAYS', 'eventRetention', 'integer'],
    ['PROCESS_RETENTION_OUTPUT_DAYS', 'outputRetention', 'integer'],
    ['PROCESS_RETENTION_RUN_DAYS', 'runRetention', 'integer'],
].map(([name, key, input]) => ({
    name,
    labelKey: `processSettings.fields.${key}`,
    input: input as 'integer' | 'number',
    sizeUnit: name === 'PROCESS_SANITIZE_MAX_BYTES' ? 'bytes' : undefined,
    min: 0,
    advanced: true,
}))

export const searchFields: SettingField[] = [
    { name: 'SEARCH_DEFAULT_LANGUAGE', labelKey: 'searchSettings.fields.language' },
    { name: 'SEARCH_TIMEOUT', labelKey: 'searchSettings.fields.timeout', input: 'integer', min: 1 },
]
