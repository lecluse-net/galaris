<template>
    <q-page class="preferences-section q-pa-md">
        <PageHeader :icon="navigationIcon(currentSection.icon)"
            :title="t('configuration.pageTitle', { name: t(currentSection.titleKey) })"
            :description="t(currentSection.descriptionKey)"
        />

        <div v-if="paramsStore.loading && !paramsStore.params.length" class="row justify-center q-pa-lg">
            <q-spinner color="primary" size="3em" />
        </div>

        <div v-else class="params-form" :class="{ 'params-form--harnesses': section === 'harnesses' }">
            <q-card flat :bordered="section !== 'harnesses'" class="settings-content">
                <q-tab-panels :model-value="section" class="settings-panels">
                    <q-tab-panel name="system" class="settings-panel">
                        <SettingsFields :fields="systemFields" />
                    </q-tab-panel>
                    <q-tab-panel name="language" class="settings-panel">
                        <div class="text-h6 text-primary q-mb-sm">{{ t('languageSettings.title') }}</div>
                        <div class="text-body2 text-grey-7 q-mb-lg">{{ t('languageSettings.subtitle') }}</div>
                        <SettingsFields :fields="languageFields" :columns="2" />
                    </q-tab-panel>

                    <q-tab-panel name="messaging" class="settings-panel">
                        <MessagingSettingsPanel />
                    </q-tab-panel>

                    <q-tab-panel name="memory" class="settings-panel">
                        <MemorySettingsPanel />
                    </q-tab-panel>

                    <q-tab-panel name="dream" class="settings-panel">
                        <DreamSettingsPanel />
                    </q-tab-panel>

                    <q-tab-panel name="voice" class="settings-panel">
                        <div class="text-h6 text-primary q-mb-sm">{{ t('voiceSettings.title') }}</div>
                        <div class="text-body2 text-grey-7 q-mb-md">{{ t('voiceSettings.subtitle') }}</div>
                        <q-banner rounded class="settings-guide q-mb-lg">
                            <template #avatar><q-icon name="record_voice_over" color="primary" size="md" /></template>
                            {{ t('voiceSettings.providerHint') }}
                        </q-banner>
                        <SettingsBlock :title="t('configuration.layout.calls')" icon="call">
                            <SettingsFields :fields="voiceFields.filter(field => !field.advanced)" />
                        </SettingsBlock>
                        <SettingsBlock :title="t('configuration.advanced')" icon="tune" advanced>
                            <SettingsFields :fields="voiceFields.filter(field => field.advanced)" :columns="2" :expand-advanced="false" />
                        </SettingsBlock>
                    </q-tab-panel>

                    <q-tab-panel name="audio" class="settings-panel">
                        <div class="text-h6 text-primary q-mb-sm">{{ t('audioSettings.title') }}</div>
                        <div class="text-body2 text-grey-7 q-mb-md">{{ t('audioSettings.subtitle') }}</div>
                        <q-banner rounded class="settings-guide q-mb-lg">
                            <template #avatar><q-icon name="security" color="primary" size="md" /></template>
                            {{ t('audioSettings.defaultHint') }}
                        </q-banner>
                        <SettingsBlock :title="t('audioSettings.meetingTitle')" :description="t('audioSettings.meetingHint')" icon="groups">
                            <SettingsFields :fields="audioSummaryFields(audioMeetingSummaryFields)" />
                        </SettingsBlock>
                        <SettingsBlock :title="t('audioSettings.videoTitle')" :description="t('audioSettings.videoHint')" icon="movie">
                            <SettingsFields :fields="audioSummaryFields(audioVideoSummaryFields)" />
                        </SettingsBlock>
                    </q-tab-panel>

                    <q-tab-panel name="process" class="settings-panel">
                        <div class="text-h6 text-primary q-mb-sm">{{ t('processSettings.title') }}</div>
                        <div class="text-body2 text-grey-7 q-mb-lg">{{ t('processSettings.subtitle') }}</div>
                        <SettingsBlock :title="t('processSettings.fields.engine')" icon="account_tree">
                            <SettingsFields :fields="processGeneralFields" />
                        </SettingsBlock>
                        <BridgeSettingsPanel
                            v-if="processBridge"
                            :contribution="processBridge"
                            organized
                        />
                        <SettingsBlock :title="t('configuration.tuning')" icon="tune" advanced class="q-mt-lg">
                            <div v-for="group in processTuningGroups" :key="group.key" class="q-mb-md">
                                <h3 class="text-subtitle2">{{ t(`configuration.layout.${group.key}`) }}</h3>
                                <SettingsFields :fields="group.fields" :columns="2" :expand-advanced="false" />
                            </div>
                        </SettingsBlock>
                    </q-tab-panel>

                    <q-tab-panel name="tasks" class="settings-panel">
                        <TaskSettingsPanel />
                    </q-tab-panel>

                    <q-tab-panel name="harnesses" class="settings-panel settings-panel--harnesses">
                        <template v-if="!harnessOverview">
                            <div class="text-h6 text-primary q-mb-sm">{{ t('harnessSettings.title') }}</div>
                            <div class="text-body2 text-grey-7 q-mb-lg">{{ t('harnessSettings.subtitle') }}</div>
                        </template>

                        <BridgeSettingsPanel
                            v-if="harnessOverview"
                            :contribution="harnessOverview"
                            :show-guide="false"
                            organized
                        />

                        <PreferencesMenuGrid
                            v-else-if="harnessMenuItems.length"
                            :items="harnessMenuItems"
                        />

                        <q-banner v-else rounded class="settings-guide">
                            {{ t('harnessSettings.noProviders') }}
                        </q-banner>
                    </q-tab-panel>

                    <q-tab-panel name="search" class="settings-panel">
                        <div class="text-h6 text-primary q-mb-sm">{{ t('searchSettings.title') }}</div>
                        <div class="text-body2 text-grey-7 q-mb-lg">{{ t('searchSettings.subtitle') }}</div>
                        <SettingsFields :fields="searchFields" :columns="2" />
                    </q-tab-panel>

                    <q-tab-panel name="janus" class="settings-panel">
                        <div class="text-h6 text-primary q-mb-md">{{ t('params.janus') }}</div>
                        <q-banner rounded class="settings-guide q-mb-lg">
                            <template #avatar><q-avatar color="primary" text-color="white" icon="hub" /></template>
                            <div class="text-subtitle1 text-weight-medium">{{ t('params.janusGuideTitle') }}</div>
                            <div class="text-body2 q-mt-xs">{{ t('params.janusGuideDescription') }}</div>
                            <div class="janus-api-url q-mt-md">
                                <code>{{ janusApiUrl }}</code>
                                <q-btn flat round dense icon="content_copy" @click="copyJanusApiUrl">
                                    <q-tooltip>{{ t('params.janusCopyApiUrl') }}</q-tooltip>
                                </q-btn>
                            </div>
                            <q-btn
                                to="/user/tokens"
                                outline
                                color="primary"
                                icon="key"
                                :label="t('params.janusTokensLink')"
                                no-caps
                                class="q-mt-md"
                            />
                        </q-banner>
                        <q-input
                            v-model="paramValues['janus.aliases']"
                            outlined
                            dense
                            clearable
                            :label="paramLabel('janus.aliases')"
                            :readonly="!canEdit"
                            @blur="onParamBlur('janus.aliases')"
                        />
                        <div class="text-caption text-grey-7 q-mt-xs">{{ paramDescription('janus.aliases') }}</div>
                    </q-tab-panel>

                    <q-tab-panel name="instructions" class="settings-panel">
                        <div class="text-h6 text-primary q-mb-xs">{{ t('params.executorInstructions') }}</div>
                        <div class="text-body2 text-grey-7 q-mb-lg">{{ t('params.executorInstructionsHelp') }}</div>
                        <SettingsBlock v-for="field in executorInstructionFields" :key="field.name"
                            :title="t(field.labelKey)" :description="field.descriptionKey ? t(field.descriptionKey) : undefined"
                            icon="description" advanced>
                            <SettingsFields :fields="[field]" />
                        </SettingsBlock>
                    </q-tab-panel>

                    <q-tab-panel name="logs" class="settings-panel">
                        <SettingsBlock :title="t('params.logs.retentionTitle')"
                            :description="t('params.logs.retentionHint')" icon="history">
                            <SettingsFields :fields="traceRetentionFields" :columns="2" />
                        </SettingsBlock>
                        <LogCleanupPanel />
                    </q-tab-panel>
                </q-tab-panels>
            </q-card>
        </div>
        <div class="q-mt-md">
            <q-btn flat color="primary" icon="arrow_back" :label="t('common.back')" to="/params" />
        </div>
    </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted, ref } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import { harnessBridgeSettings, harnessOverviewSettings, processBridgeSettings } from '../bridgeSettings'
import {
    audioMeetingSummaryFields,
    audioVideoSummaryFields,
    executorInstructionFields,
    languageFields,
    processAdvancedFields,
    processGeneralFields,
    searchFields,
    systemFields,
    traceRetentionFields,
    voiceFields,
} from '../settingsCatalog'
import { useParamsStore } from '../stores/paramsStore'
import BridgeSettingsPanel from './BridgeSettingsPanel.vue'
import DreamSettingsPanel from './DreamSettingsPanel.vue'
import LogCleanupPanel from './LogCleanupPanel.vue'
import MemorySettingsPanel from './MemorySettingsPanel.vue'
import MessagingSettingsPanel from './MessagingSettingsPanel.vue'
import PreferencesMenuGrid from './PreferencesMenuGrid.vue'
import SettingsFields from './SettingsFields.vue'
import SettingsBlock from './SettingsBlock.vue'
import type { SettingField } from '../settingsTypes'
import TaskSettingsPanel from './TaskSettingsPanel.vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { harnessSettingsPath, preferenceSections, type PreferenceSectionKey } from '../presentation'

const { section } = defineProps<{ section: PreferenceSectionKey }>()

const { t } = useI18n()
const $q = useQuasar()
const paramsStore = useParamsStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const currentSection = computed(() => preferenceSections.find(item => item.key === section) ?? preferenceSections[0])
const paramValues = ref<Record<string, string | null>>({})
const originalValues = ref<Record<string, string | null>>({})
const janusApiUrl = `${window.location.origin}/api/janus/openai`
const retentionFields = processAdvancedFields.filter(field => field.name.startsWith('PROCESS_RETENTION_'))
const processTuningGroups = [
    { key: 'execution', fields: processAdvancedFields.filter(field => !retentionFields.includes(field)) },
    { key: 'retention', fields: retentionFields },
]
function audioSummaryFields(fields: SettingField[]): SettingField[] {
    return fields.map(field => ({ ...field, advanced: !field.name.includes('-final-') }))
}
const processBridge = computed(() => processBridgeSettings[0])
const harnessOverview = computed(() => harnessOverviewSettings[0])
const harnessMenuItems = computed(() => harnessBridgeSettings
    .filter(contribution => contribution.isAvailable?.() ?? true)
    .map(contribution => ({
        key: contribution.kind,
        title: contribution.label,
        description: t('harnessSettings.providerSubtitle', { name: contribution.label }),
        icon: contribution.icon,
        to: harnessSettingsPath(contribution.kind),
    })))

function paramI18nKey(name: string): string {
    return name.replace(/[.-]/g, '_')
}

function paramLabel(name: string): string {
    return t(`params.def.${paramI18nKey(name)}.label`)
}

function paramDescription(name: string): string {
    return t(`params.def.${paramI18nKey(name)}.description`)
}

function syncParamValues(): void {
    const values: Record<string, string | null> = {}
    for (const param of paramsStore.params) {
        if (!param.secret) values[param.name] = param.value
    }
    paramValues.value = { ...values }
    originalValues.value = { ...values }
}

async function onParamBlur(name: string): Promise<void> {
    if (!canEdit.value) return
    const value = paramValues.value[name] ?? null
    if (value === originalValues.value[name]) return
    try {
        await paramsStore.updateParam(name, value)
        originalValues.value[name] = value
        $q.notify({ type: 'positive', message: t('params.updated', { name: paramLabel(name) }), timeout: 1600 })
    } catch {
        paramValues.value[name] = originalValues.value[name] ?? null
        $q.notify({ type: 'negative', message: t('params.updateError', { name: paramLabel(name) }) })
    }
}

async function copyJanusApiUrl(): Promise<void> {
    await copyToClipboard(janusApiUrl)
    $q.notify({ type: 'positive', message: t('params.janusApiCopied'), timeout: 1500 })
}

onMounted(async () => {
    await Promise.all([
        paramsStore.fetchParams(),
        ...harnessBridgeSettings.map(contribution => contribution.refreshAvailability?.()),
    ])
    syncParamValues()
})
</script>

<style scoped>
.params-form {
    max-width: 1280px;
}

.settings-content {
    min-width: 0;
}
.params-form--harnesses { max-width: none; }
.settings-panel.settings-panel--harnesses { padding: 0; }

.settings-panels {
    background: transparent;
}

.settings-panel {
    padding: 24px;
}

.settings-guide {
    color: inherit;
    background: var(--solaire-blue-light);
}
body.body--dark .settings-guide { background: var(--solaire-blue-dark); }

.janus-api-url {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px;
    border-radius: 6px;
    background: rgba(0, 0, 0, 0.06);
}

.janus-api-url code {
    overflow-wrap: anywhere;
}

@media (max-width: 1023px) {
    .preferences-section {
        padding: 12px;
    }

    .settings-panel {
        padding: 16px;
    }
}

@media (max-width: 599px) {
    .preferences-section {
        padding: 8px;
    }

    .settings-panel {
        padding: 12px;
    }
}
</style>
