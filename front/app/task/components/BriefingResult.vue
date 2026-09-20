<template>
    <q-expansion-item
        v-if="briefing || briefingResult"
        icon="manage_search"
        header-class="text-amber-9 text-subtitle2"
        class="q-mt-md"
        dense
        toggle-indicator
        :expanded="briefing"
    >
        <template #header>
            <q-item-section avatar>
                <q-spinner v-if="briefing" color="amber-9" size="sm" />
                <q-icon v-else name="manage_search" color="amber-9" />
            </q-item-section>
            <q-item-section>
                <q-item-label>{{ $t('task.briefing.title') }}</q-item-label>
                <q-item-label v-if="briefing" caption>{{ $t('task.briefing.running') }}</q-item-label>
            </q-item-section>
            <q-item-section v-if="briefingResult" side>
                <div class="row q-gutter-xs">
                    <StatusBadge
                        :tone="briefingResult.success ? 'success' : 'error'"
                        :icon="briefingResult.success ? 'check_circle' : 'error'"
                        :label="briefingResult.success ? $t('task.dispatch.success') : $t('task.dispatch.failure')"
                    />
                    <q-badge color="blue">{{ formatTime(briefingResult.execution_time) }}</q-badge>
                    <q-badge color="purple">{{ formatCost(briefingResult.cost) }}</q-badge>
                </div>
            </q-item-section>
        </template>

        <q-card flat bordered class="q-mt-sm">
            <q-card-section>
                <q-tabs v-model="activeTab" dense align="left" active-color="amber-9" indicator-color="amber-9">
                    <q-tab name="result" icon="fact_check" :label="$t('task.briefing.result')" />
                    <q-tab name="prompt" icon="message" :label="$t('task.briefing.prompt')" />
                    <q-tab name="system-prompt" icon="settings" :label="$t('task.briefing.systemPrompt')" />
                </q-tabs>
                <q-separator />
                <q-tab-panels v-model="activeTab" animated>
                    <q-tab-panel name="result">
                        <Markdown v-if="briefingResult?.result" :content="briefingResult.result" />
                        <div class="text-subtitle2 q-mt-md q-mb-sm">{{ $t('task.briefing.choices') }}</div>
                        <q-list v-if="briefingResult?.choices?.length" bordered separator>
                            <q-item v-for="choice in briefingResult.choices" :key="`${choice.kind}:${choice.identifier}`">
                                <q-item-section>
                                    <q-item-label>{{ choice.label || choice.identifier }}</q-item-label>
                                    <q-item-label caption>{{ choice.kind }} · {{ choice.identifier }}</q-item-label>
                                    <q-item-label v-if="choice.reason" caption>{{ choice.reason }}</q-item-label>
                                </q-item-section>
                                <q-item-section v-if="choice.score != null" side>
                                    <q-badge color="blue-grey">{{ choice.score }}</q-badge>
                                </q-item-section>
                            </q-item>
                        </q-list>
                        <div v-else class="text-grey">{{ $t('task.briefing.noChoices') }}</div>
                    </q-tab-panel>
                    <q-tab-panel name="prompt">
                        <Markdown v-if="briefingResult?.prompt" :content="briefingResult.prompt" />
                        <div v-else class="text-grey text-center q-pa-md">{{ $t('task.briefing.noPrompt') }}</div>
                    </q-tab-panel>
                    <q-tab-panel name="system-prompt">
                        <Markdown v-if="briefingResult?.system_prompt" :content="briefingResult.system_prompt" />
                        <div v-else class="text-grey text-center q-pa-md">{{ $t('task.briefing.noSystemPrompt') }}</div>
                    </q-tab-panel>
                </q-tab-panels>
            </q-card-section>
        </q-card>
    </q-expansion-item>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { BriefingResult } from '../types'
import Markdown from '@/core/util/components/Markdown.vue'
import { StatusBadge } from '@/core/util'

const props = defineProps<{
    briefingResult: BriefingResult | null
    briefing: boolean
}>()

const activeTab = ref('result')
const formatTime = (seconds: number): string => seconds < 1 ? `${Math.round(seconds * 1000)}ms` : `${seconds.toFixed(2)}s`
const formatCost = (cost: number): string => `$${cost.toFixed(6)}`
</script>
