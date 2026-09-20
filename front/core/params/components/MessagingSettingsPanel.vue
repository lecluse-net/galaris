<template>
    <div>
        <div class="text-h6 text-primary q-mb-sm">{{ t('configuration.messaging.title') }}</div>
        <div class="text-body2 text-grey-7 q-mb-lg">{{ t('configuration.messaging.subtitle') }}</div>

        <q-banner rounded class="configuration-guide q-mb-lg">
            <template #avatar>
                <q-avatar color="primary" text-color="white" icon="hub" />
            </template>
            <div class="text-subtitle1 text-weight-medium">{{ t('configuration.messaging.simultaneousTitle') }}</div>
            <div class="text-body2 q-mt-xs">{{ t('configuration.messaging.simultaneousHint') }}</div>
            <div class="row q-gutter-sm q-mt-sm">
                <q-chip
                    v-for="bridge in messagingBridgeSettings"
                    :key="bridge.kind"
                    outline
                    :color="isBridgeEnabled(bridge.kind) ? 'positive' : 'grey-7'"
                    :icon="bridge.icon"
                >
                    {{ bridge.label }}
                    <q-badge
                        class="q-ml-sm"
                        :color="isBridgeEnabled(bridge.kind) ? 'positive' : 'grey-7'"
                        :label="isBridgeEnabled(bridge.kind) ? t('configuration.messaging.active') : t('configuration.messaging.inactive')"
                    />
                </q-chip>
            </div>
        </q-banner>

        <div class="text-subtitle1 text-weight-medium">{{ t('configuration.messaging.providerSettings') }}</div>
        <div class="text-caption text-grey-7 q-mb-sm">{{ t('configuration.messaging.providerSettingsHint') }}</div>
        <q-tabs
            v-model="selectedKind"
            align="left"
            inline-label
            no-caps
            outside-arrows
            mobile-arrows
            active-color="primary"
            indicator-color="primary"
            class="provider-tabs text-grey-7 q-mb-lg"
        >
            <q-tab
                v-for="bridge in messagingBridgeSettings"
                :key="bridge.kind"
                :name="bridge.kind"
                :icon="bridge.icon"
                :label="bridge.label"
            >
                <q-badge
                    floating
                    rounded
                    :color="isBridgeEnabled(bridge.kind) ? 'positive' : 'grey-6'"
                />
            </q-tab>
        </q-tabs>

        <template v-if="selectedBridge">
            <q-banner rounded class="configuration-guide q-mb-lg">
                <template #avatar>
                    <q-avatar color="primary" text-color="white" :icon="selectedBridge.icon" />
                </template>
                <div class="row items-center justify-between q-gutter-md">
                    <div class="text-subtitle1 text-weight-medium">{{ selectedBridge.label }}</div>
                    <q-toggle
                        :model-value="isBridgeEnabled(selectedBridge.kind)"
                        :label="isBridgeEnabled(selectedBridge.kind) ? t('configuration.messaging.active') : t('configuration.messaging.inactive')"
                        :disable="savingActivation || !canEdit"
                        color="positive"
                        @update:model-value="value => selectedBridge && setBridgeEnabled(selectedBridge.kind, value)"
                    />
                </div>
                <div class="text-caption text-grey-7 q-mt-xs">
                    {{ t('configuration.messaging.activationHint') }}
                </div>
                <div class="text-body2 q-mt-xs">{{ t(selectedBridge.guideKey) }}</div>
            </q-banner>

            <SettingsBlock v-if="selectedBridge.fields.length" :title="selectedBridge.label" :icon="selectedBridge.icon">
                <SettingsFields :key="selectedBridge.kind" :fields="selectedBridge.fields" :columns="2" />
            </SettingsBlock>

            <SettingsBlock :key="`guide-${selectedBridge.kind}`" :title="t('configuration.layout.setupGuide')" icon="help_outline" advanced>
                <ol class="q-pl-lg q-mb-sm">
                    <li v-for="step in setupSteps" :key="step" class="q-mb-xs">{{ step }}</li>
                </ol>
                <div class="row q-gutter-sm">
                    <q-btn
                        :href="selectedBridge.docsUrl"
                        target="_blank"
                        rel="noopener noreferrer"
                        outline
                        color="primary"
                        icon="open_in_new"
                        :label="t('configuration.openDocumentation')"
                        no-caps
                    />
                    <q-btn
                        v-if="canConfigureTools"
                        to="/tools"
                        outline
                        color="primary"
                        icon="link"
                        :label="t('configuration.messaging.configureAgents')"
                        no-caps
                    />
                </div>
            </SettingsBlock>

            <SettingsBlock :title="t('configuration.layout.connectionCheck')" icon="health_and_safety">
            <div class="row items-center q-gutter-sm">
                <q-btn
                    v-if="canEdit"
                    color="primary"
                    icon="mark_chat_read"
                    :label="t('configuration.messaging.test')"
                    :loading="testing"
                    no-caps
                    @click="runTest"
                />
                <span class="text-caption text-grey-7">{{ t('configuration.messaging.testHint') }}</span>
            </div>

            <q-banner
                v-if="testResult"
                rounded
                :class="testResult.ok ? 'bg-green-1 text-positive' : 'bg-orange-1 text-warning'"
                class="q-mt-md"
            >
                <div class="text-weight-medium">
                    {{ testResult.ok ? t('configuration.testSuccess') : t('configuration.testNeedsAttention') }}
                </div>
                <div v-if="!testResult.connections.length" class="text-body2 q-mt-xs">
                    {{ t('configuration.messaging.noConnections') }}
                </div>
                <q-list v-else dense class="q-mt-sm">
                    <q-item v-for="connection in testResult.connections" :key="connection.connection_id">
                        <q-item-section avatar>
                            <q-icon :name="connection.ok ? 'check_circle' : 'error'" :color="connection.ok ? 'positive' : 'negative'" />
                        </q-item-section>
                        <q-item-section>
                            <q-item-label>
                                {{ t('configuration.messaging.agentConnection', { agent: connection.agent_id, connection: connection.connection_id, provider: providerLabel(connection.provider) }) }}
                            </q-item-label>
                            <q-item-label caption>{{ connection.detail || connection.identity }}</q-item-label>
                            <q-item-label
                                caption
                                :class="connection.receiving === false ? 'text-negative' : connection.receiving === true ? 'text-positive' : ''"
                            >
                                {{ receptionStatus(connection.receiving) }}
                            </q-item-label>
                            <q-item-label v-if="connection.last_received_at" caption>
                                {{ t('configuration.messaging.lastReception', { date: formatDate(connection.last_received_at) }) }}
                            </q-item-label>
                        </q-item-section>
                    </q-item>
                </q-list>
            </q-banner>
            </SettingsBlock>
        </template>

        <SettingsBlock :title="t('configuration.messaging.common')"
            :description="t('configuration.messaging.commonHint')" icon="tune" advanced>
            <SettingsFields :fields="commonMessagingFields" :columns="2" :expand-advanced="false" />
        </SettingsBlock>
    </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { messagingBridgeSettings } from '../bridgeSettings'
import { commonMessagingFields } from '../settingsCatalog'
import { useParamsStore } from '../stores/paramsStore'
import { configurationService, type MessengerConfigurationCheck } from '../services/configurationService'
import SettingsFields from './SettingsFields.vue'
import SettingsBlock from './SettingsBlock.vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'

const { t, tm } = useI18n()
const $q = useQuasar()
const paramsStore = useParamsStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.PARAMS_EDIT))
const canConfigureTools = computed(() => (
    privilegeStore.hasPrivilege(privileges.TOOL_ACCESS)
    || privilegeStore.hasPrivilege(privileges.TOOL_EDIT)
))
const selectedKind = ref(messagingBridgeSettings[0]?.kind ?? '')
const enabledKinds = ref<string[]>([])
const savingActivation = ref(false)
const testing = ref(false)
const testResult = ref<MessengerConfigurationCheck | null>(null)

const selectedBridge = computed(() => messagingBridgeSettings.find(item => item.kind === selectedKind.value))
const setupSteps = computed(() => {
    if (!selectedBridge.value) return []
    const translated = tm(selectedBridge.value.stepsKey)
    return Array.isArray(translated) ? translated.map(step => String(step)) : []
})

function bridgeFor(kind: string): (typeof messagingBridgeSettings)[number] | undefined {
    return messagingBridgeSettings.find(item => item.kind === kind)
}

function normalizedEnabledKinds(raw: string | null): string[] {
    const available = messagingBridgeSettings.map(item => item.kind)
    if (raw === null) return available
    let parsed: unknown
    try {
        parsed = JSON.parse(raw)
    } catch {
        parsed = []
    }
    if (!Array.isArray(parsed)) return []
    return [...new Set(parsed.filter(
        (item): item is string => typeof item === 'string' && available.includes(item),
    ))]
}

function isBridgeEnabled(kind: string): boolean {
    return enabledKinds.value.includes(kind)
}

watch(
    () => paramsStore.getParamValue('MESSENGER_ENABLED_CHANNELS'),
    raw => { enabledKinds.value = normalizedEnabledKinds(raw) },
    { immediate: true },
)

async function setBridgeEnabled(kind: string, enabled: boolean): Promise<void> {
    if (!canEdit.value || savingActivation.value || enabled === isBridgeEnabled(kind)) return
    const previous = [...enabledKinds.value]
    const available = messagingBridgeSettings.map(item => item.kind)
    enabledKinds.value = enabled
        ? available.filter(item => item === kind || previous.includes(item))
        : previous.filter(item => item !== kind)
    savingActivation.value = true
    testResult.value = null
    try {
        await paramsStore.updateParam(
            'MESSENGER_ENABLED_CHANNELS',
            JSON.stringify(enabledKinds.value),
        )
        $q.notify({
            type: 'positive',
            message: t(enabled
                ? 'configuration.messaging.activationSaved'
                : 'configuration.messaging.deactivationSaved'),
        })
    } catch {
        enabledKinds.value = previous
        $q.notify({ type: 'negative', message: t('configuration.saveError') })
    } finally {
        savingActivation.value = false
    }
}

function providerLabel(kind: string): string {
    return bridgeFor(kind)?.label ?? kind
}

async function runTest(): Promise<void> {
    if (!canEdit.value) return
    testing.value = true
    try {
        testResult.value = (await configurationService.testMessenger()).data
    } catch {
        testResult.value = null
        $q.notify({ type: 'negative', message: t('configuration.testError') })
    } finally {
        testing.value = false
    }
}

function formatDate(value: string): string {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

function receptionStatus(receiving: boolean | null): string {
    if (receiving === true) return t('configuration.messaging.receptionActive')
    if (receiving === false) return t('configuration.messaging.receptionInactive')
    return t('configuration.messaging.receptionUnknown')
}
</script>

<style scoped>
.provider-tabs {
    border-bottom: 1px solid color-mix(in srgb, currentColor 16%, transparent);
}

.configuration-guide {
    color: inherit;
    background: var(--solaire-blue-light);
}
body.body--dark .configuration-guide { background: var(--solaire-blue-dark); }
</style>
