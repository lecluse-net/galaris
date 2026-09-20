<template>
    <div>
        <div class="text-h6 text-primary q-mb-sm">{{ t('dreamSettings.title') }}</div>
        <div class="text-body2 text-grey-7 q-mb-lg">{{ t('dreamSettings.subtitle') }}</div>

        <q-banner rounded class="dream-guide q-mb-lg">
            <template #avatar>
                <q-icon name="bedtime" color="primary" size="md" />
            </template>
            {{ t('dreamSettings.priorityHint') }}
        </q-banner>

        <SettingsBlock :title="t('configuration.layout.activity')" icon="bedtime">
            <SettingsFields :fields="dreamActivityFields" />
        </SettingsBlock>
        <SettingsBlock :title="t('configuration.layout.topics')" icon="topic">
            <SettingsFields :fields="dreamTopicFields" />
        </SettingsBlock>
        <SettingsBlock :title="t('configuration.layout.learning')" icon="school">
            <SettingsFields :fields="dreamLearningFields" :columns="2" />
        </SettingsBlock>

        <SettingsBlock :title="t('dreamSettings.attachments.title')"
            :description="t('dreamSettings.attachments.hint')" icon="attach_file">
            <q-banner rounded class="attachment-cost-warning q-mb-md">
                <template #avatar><q-icon name="warning" /></template>
                {{ t('dreamSettings.attachments.costWarning') }}
            </q-banner>
            <SettingsFields :fields="dreamAttachmentFields" />
        </SettingsBlock>

        <SettingsBlock :title="t('dreamSettings.linkReconciliation.title')"
            :description="t('dreamSettings.linkReconciliation.subtitle')" icon="link">
            <SettingsFields :fields="dreamLinkReconciliationFields" :columns="2" />

            <q-card flat bordered class="link-reconciliation-card q-mt-lg">
                <q-card-section>
                    <div class="row items-start justify-between q-col-gutter-md">
                        <div class="col-12 col-md">
                            <div class="text-subtitle2">
                                {{ t('dreamSettings.linkReconciliation.executionTitle') }}
                            </div>
                            <div class="text-body2 text-grey-7 q-mt-xs">
                                {{ t('dreamSettings.linkReconciliation.idleHint') }}
                            </div>

                            <div v-if="status" class="row q-gutter-xs q-mt-md">
                                <q-chip
                                    dense
                                    :color="status.after_dream_enabled ? 'primary' : 'grey-6'"
                                    text-color="white"
                                    icon="bedtime"
                                >
                                    {{ status.after_dream_enabled
                                        ? t('dreamSettings.linkReconciliation.afterDreamEnabled')
                                        : t('dreamSettings.linkReconciliation.afterDreamDisabled') }}
                                </q-chip>
                                <q-chip
                                    dense
                                    :color="status.scheduled_enabled ? 'secondary' : 'grey-6'"
                                    text-color="white"
                                    icon="schedule"
                                >
                                    {{ status.scheduled_enabled
                                        ? t('dreamSettings.linkReconciliation.scheduledEvery', { hours: status.interval_hours })
                                        : t('dreamSettings.linkReconciliation.scheduledDisabled') }}
                                </q-chip>
                            </div>

                            <q-list v-if="status" dense class="q-mt-md link-reconciliation-dates">
                                <q-item v-if="status.next_scheduled_at">
                                    <q-item-section avatar><q-icon name="event" color="secondary" /></q-item-section>
                                    <q-item-section>
                                        <q-item-label>{{ t('dreamSettings.linkReconciliation.nextScheduled') }}</q-item-label>
                                        <q-item-label caption>{{ formatDate(status.next_scheduled_at) }}</q-item-label>
                                    </q-item-section>
                                </q-item>
                                <q-item>
                                    <q-item-section avatar><q-icon name="task_alt" color="positive" /></q-item-section>
                                    <q-item-section>
                                        <q-item-label>{{ t('dreamSettings.linkReconciliation.lastCompleted') }}</q-item-label>
                                        <q-item-label caption>
                                            {{ status.last_completed_at
                                                ? formatDate(status.last_completed_at)
                                                : t('dreamSettings.linkReconciliation.neverCompleted') }}
                                        </q-item-label>
                                    </q-item-section>
                                </q-item>
                                <q-item v-if="status.latest_job_status">
                                    <q-item-section avatar>
                                        <q-icon
                                            :name="jobVisual.icon"
                                            :color="jobVisual.color"
                                        />
                                    </q-item-section>
                                    <q-item-section>
                                        <q-item-label>
                                            {{ t('dreamSettings.linkReconciliation.latestJob', {
                                                status: t(`dreamSettings.linkReconciliation.statuses.${status.latest_job_status}`),
                                            }) }}
                                        </q-item-label>
                                        <q-item-label v-if="status.latest_job_created_at" caption>
                                            {{ formatDate(status.latest_job_created_at) }}
                                        </q-item-label>
                                    </q-item-section>
                                </q-item>
                            </q-list>

                            <q-banner v-if="statusError" rounded class="bg-red-1 text-negative q-mt-md">
                                {{ t('dreamSettings.linkReconciliation.statusError') }}
                            </q-banner>

                            <q-banner
                                v-if="lastManualResult"
                                rounded
                                class="bg-green-1 text-positive q-mt-md"
                            >
                                <template #avatar><q-icon name="check_circle" /></template>
                                {{ t('dreamSettings.linkReconciliation.completed', {
                                    created: lastManualResult.created,
                                    updated: lastManualResult.updated,
                                    removed: lastManualResult.removed,
                                    unchanged: lastManualResult.unchanged,
                                }) }}
                            </q-banner>
                        </div>

                        <div class="col-12 col-md-auto row justify-end q-gutter-sm">
                            <q-btn
                                flat
                                round
                                color="primary"
                                icon="refresh"
                                :loading="statusLoading"
                                :aria-label="t('dreamSettings.linkReconciliation.refresh')"
                                @click="refreshStatus"
                            >
                                <q-tooltip>{{ t('dreamSettings.linkReconciliation.refresh') }}</q-tooltip>
                            </q-btn>
                            <q-btn
                                color="primary"
                                icon="sync"
                                no-caps
                                :label="t('dreamSettings.linkReconciliation.launch')"
                                :loading="launching"
                                :disable="!canLaunch"
                                @click="launchReconciliation"
                            >
                                <q-tooltip v-if="!canLaunch">
                                    {{ t('dreamSettings.linkReconciliation.privilegeRequired') }}
                                </q-tooltip>
                            </q-btn>
                        </div>
                    </div>
                </q-card-section>
            </q-card>
        </SettingsBlock>
        <SettingsBlock :title="t('configuration.layout.backgroundExecution')" icon="tune" advanced>
            <SettingsFields :fields="dreamRuntimeFields" :columns="2" :expand-advanced="false" />
        </SettingsBlock>
    </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import {
    configurationService,
    type MemoryLinkReconciliationRunResult,
    type MemoryLinkReconciliationStatus,
} from '../services/configurationService'
import { dreamAttachmentFields, dreamLinkReconciliationFields } from '../settingsCatalog'
import { dreamActivityFields, dreamLearningFields, dreamRuntimeFields, dreamTopicFields } from '../settingsLayout'
import { useParamsStore } from '../stores/paramsStore'
import SettingsFields from './SettingsFields.vue'
import SettingsBlock from './SettingsBlock.vue'

const { t } = useI18n()
const $q = useQuasar()
const paramsStore = useParamsStore()
const privilegeStore = usePrivilegeStore()
const status = ref<MemoryLinkReconciliationStatus | null>(null)
const statusLoading = ref(false)
const statusError = ref(false)
const launching = ref(false)
const lastManualResult = ref<MemoryLinkReconciliationRunResult | null>(null)
const canLaunch = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN))
const scheduleSignature = computed(() => [
    paramsStore.getParamValue('MEMORY_LINK_RECONCILIATION_TRIGGER_MODE'),
    paramsStore.getParamValue('MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS'),
].join(':'))
const jobVisual = computed(() => {
    switch (status.value?.latest_job_status) {
        case 'running': return { icon: 'sync', color: 'primary' }
        case 'success': return { icon: 'check_circle', color: 'positive' }
        case 'error': return { icon: 'error', color: 'negative' }
        default: return { icon: 'schedule', color: 'warning' }
    }
})

function formatDate(value: string): string {
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(new Date(value))
}

async function refreshStatus(): Promise<void> {
    if (statusLoading.value) return
    statusLoading.value = true
    statusError.value = false
    try {
        status.value = (await configurationService.getMemoryLinkReconciliationStatus()).data
    } catch {
        statusError.value = true
    } finally {
        statusLoading.value = false
    }
}

async function launchReconciliation(): Promise<void> {
    if (!canLaunch.value || launching.value) return
    launching.value = true
    lastManualResult.value = null
    try {
        lastManualResult.value = (
            await configurationService.launchMemoryLinkReconciliation()
        ).data
        $q.notify({
            type: 'positive',
            message: t('dreamSettings.linkReconciliation.completedShort'),
        })
        await refreshStatus()
    } catch {
        $q.notify({
            type: 'negative',
            message: t('dreamSettings.linkReconciliation.launchError'),
        })
    } finally {
        launching.value = false
    }
}

watch(scheduleSignature, (_current, previous) => {
    if (previous !== undefined) void refreshStatus()
})

onMounted(() => void refreshStatus())
</script>

<style scoped>
.attachment-cost-warning {
    background: var(--solaire-orange-light);
}

body.body--dark .attachment-cost-warning {
    background: var(--solaire-orange-dark);
}

.dream-guide {
    color: inherit;
    background: var(--solaire-violet-light);
}

.link-reconciliation-card {
    background: var(--solaire-gray-light);
}
body.body--dark .dream-guide { background: var(--solaire-violet-dark); }
body.body--dark .link-reconciliation-card { background: var(--solaire-gray-dark); }

.link-reconciliation-dates {
    max-width: 620px;
}
</style>
