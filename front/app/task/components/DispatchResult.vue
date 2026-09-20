<template>
    <q-expansion-item v-if="dispatchResult" icon="psychology" :label="$t('task.dispatch.title')"
        header-class="text-purple text-subtitle2" class="dispatch-expansion q-mt-md" dense toggle-indicator expanded>
        <template v-slot:header>
            <q-item-section avatar>
                <q-icon name="psychology" color="purple" />
            </q-item-section>
            <q-item-section>
                <q-item-label>{{ $t('task.dispatch.title') }}</q-item-label>
            </q-item-section>
            <q-item-section side v-if="dispatchResult">
                <div class="row q-gutter-xs">
                    <StatusBadge
                        :tone="dispatchResult.success ? 'success' : 'error'"
                        :icon="dispatchResult.success ? 'check_circle' : 'error'"
                        :label="dispatchResult.success ? $t('task.dispatch.success') : $t('task.dispatch.failure')"
                    />
                    <q-badge color="blue" size="sm">
                        <q-icon name="timer" size="xs" class="q-mr-xs" />
                        {{ formatExecutionTime(dispatchResult.execution_time) }}
                    </q-badge>
                    <q-badge color="purple" size="sm">
                        <q-icon name="attach_money" size="xs" class="q-mr-xs" />
                        {{ formatCostShort(dispatchResult.cost) }}
                    </q-badge>
                </div>
            </q-item-section>
        </template>
        <q-card flat bordered class="q-mt-sm">
            <q-card-section>
                <q-tabs v-model="activeTab" dense class="text-grey" active-color="primary" indicator-color="primary"
                    align="left" narrow-indicator>
                    <q-tab name="data">
                        <div class="row items-center no-wrap">
                            <q-icon name="analytics" class="q-mr-xs" />
                            <span>{{ $t('task.dispatch.data') }}</span>
                        </div>
                    </q-tab>
                    <q-tab name="prompt">
                        <div class="row items-center no-wrap">
                            <q-icon name="message" class="q-mr-xs" />
                            <span>{{ $t('task.dispatch.prompt') }}</span>
                        </div>
                    </q-tab>
                    <q-tab name="system-prompt">
                        <div class="row items-center no-wrap">
                            <q-icon name="settings" class="q-mr-xs" />
                            <span>{{ $t('task.dispatch.systemPrompt') }}</span>
                        </div>
                    </q-tab>
                </q-tabs>

                <q-separator />

                <q-tab-panels v-model="activeTab" animated>
                    <!-- Data tab -->
                    <q-tab-panel name="data">
                        <!-- Decision & Metrics on single line - 2 columns -->
                        <!-- Decision column -->
                        <div class="col-12 col-md-6" v-if="dispatchResult?.decision">

                            <!-- TITLE -->
                            <div class="text-h6 q-mb-md flex items-center">
                                <q-icon name="route" class="q-mr-sm" />
                                {{ $t('task.dispatch.decision') }}
                            </div>

                            <!-- SINGLE ROW OF COLUMNS -->
                            <div class="row q-col-gutter-md items-center">
                                <!-- ROUTE -->
                                <div class="col-auto info-item">
                                    <div class="info-label">{{ $t('task.dispatch.route') }}</div>
                                    <q-badge color="blue" class="text-bold">
                                        <q-icon :name="getRouteIcon(dispatchResult.decision.route)" size="xs" class="q-mr-xs" />
                                        {{ dispatchResult.decision.route }}
                                    </q-badge>
                                </div>

                                <!-- EFFORT -->
                                <div class="col-auto info-item" v-if="dispatchResult.decision.effort">
                                    <div class="info-label">{{ $t('task.dispatch.effort') }}</div>
                                    <q-badge :color="getEffortColor(dispatchResult.decision.effort)" class="text-bold">
                                        <q-icon name="speed" size="xs" class="q-mr-xs" />
                                        {{ $t(`task.dispatch.effortLevels.${dispatchResult.decision.effort}`) }}
                                    </q-badge>
                                </div>
                                <!-- LANGUE -->
                                <div class="col-auto info-item" v-if="dispatchResult.decision.language">
                                    <div class="info-label">{{ $t('task.dispatch.language') }}</div>
                                    <q-badge color="pink" class="text-bold">
                                        <q-icon name="translate" size="xs" class="q-mr-xs" />
                                        {{ dispatchResult.decision.language.toUpperCase() }}
                                    </q-badge>
                                </div>

                            </div>

                        </div>


                        <!-- Full width details -->
                        <div v-if="dispatchResult?.decision" class="q-mb-lg">
                            <div class="info-item">
                                <div class="info-label">{{ $t('task.dispatch.reasoning') }}</div>
                                <div class="text-body2 bg-grey-1 q-pa-sm rounded-borders">
                                    {{ dispatchResult.decision.reasoning }}
                                </div>
                            </div>
                        </div>
                    </q-tab-panel>

                    

                    <!-- Prompt Tab -->
                    <q-tab-panel name="prompt">
                        <div v-if="dispatchResult?.prompt" class="text-body2 q-pa-sm rounded-borders">
                            <Markdown :content="dispatchResult.prompt" />
                        </div>
                        <div v-else class="text-grey text-center q-pa-md">
                            {{ $t('task.dispatch.noPrompt') }}
                        </div>
                    </q-tab-panel>

                    <!-- System Prompt Tab -->
                    <q-tab-panel name="system-prompt">
                        <div v-if="dispatchResult?.system_prompt" class="text-body2 q-pa-sm rounded-borders">
                            <Markdown :content="dispatchResult.system_prompt" />
                        </div>
                        <div v-else class="text-grey text-center q-pa-md">
                            {{ $t('task.dispatch.noSystemPrompt') }}
                        </div>
                    </q-tab-panel>
                </q-tab-panels>
            </q-card-section>
        </q-card>
    </q-expansion-item>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { DispatchResult } from '../types'
import Markdown from '@/core/util/components/Markdown.vue'
import { StatusBadge } from '@/core/util'

const props = defineProps<{
    dispatchResult: DispatchResult | null
}>()

const activeTab = ref('data')

const getRouteIcon = (route: string): string => {
    switch (route) {
        case 'EXEC': return 'play_arrow'
        case 'BRIEFING': return 'assignment'
        case 'PLAN': return 'account_tree'
        case 'END': return 'stop_circle'
        default: return 'help'
    }
}

const getEffortColor = (effort: string): string => {
    switch (effort) {
        case 'high': return 'deep-orange'
        case 'standard': return 'blue-grey'
        default: return 'grey'
    }
}

const formatExecutionTime = (time: number): string => {
    if (time < 1) {
        return `${Math.round(time * 1000)}ms`
    } else if (time < 60) {
        return `${time.toFixed(2)}s`
    } else {
        const minutes = Math.floor(time / 60)
        const seconds = (time % 60).toFixed(2)
        return `${minutes}m ${seconds}s`
    }
}

const formatCostShort = (cost: number): string => {
    if (cost === 0) return '$0.00'

    // Convert to a string to inspect decimals.
    const costStr = cost.toString()

    // Use the compact form for integers and short decimals.
    const decimalPart = costStr.split('.')[1]
    if (!decimalPart || decimalPart.length <= 2) {
        return `$${cost.toFixed(2)}`
    }

    // Count leading zeros after the decimal point.
    const leadingZeros = decimalPart.match(/^0*/)?.[0].length || 0

    // Show six decimal places after more than five leading zeros.
    if (leadingZeros >= 5) {
        return `$${cost.toFixed(6)}`
    }

    // Otherwise show up to six significant decimal places.
    const significantDigits = decimalPart.substring(leadingZeros)
    const totalDecimals = Math.min(leadingZeros + significantDigits.length, 6)

    return `$${cost.toFixed(totalDecimals)}`
}

</script>

<style scoped>
.result-pre {
    white-space: pre-wrap;
    word-break: break-word;
    font-family: 'Courier New', monospace;
    font-size: 0.85em;
    margin: 0;
}

.info-item {
    margin-bottom: 16px;
}

.info-label {
    font-size: 0.75rem;
    color: #666;
    text-transform: uppercase;
    font-weight: 500;
    margin-bottom: 4px;
}

body.body--dark .info-label {
    color: #9e9e9e;
}

.dispatch-expansion :deep(.q-expansion-item__container) {
    border-radius: 8px;
}

.dispatch-expansion :deep(.q-expansion-item__header) {
    border-radius: 8px;
}

.q-tab-panels {
    background: transparent;
}
</style>
