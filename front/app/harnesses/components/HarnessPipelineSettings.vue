<template>
  <SettingsBlock v-for="block in blocks" :key="block.key" :title="t(`harnesses.preferences.${block.key}`)"
    :description="t(`harnesses.preferences.${block.key}Hint`)" :icon="block.key === 'planner' ? 'account_tree' : 'description'">
    <p>{{ t('harnesses.preferences.eligibleHarnesses') }}</p>
    <ul>
      <li v-for="harness in block.harnesses" :key="harness.provider_code">
        {{ te(harness.label) ? t(harness.label) : harness.label }}
      </li>
    </ul>
    <SettingsFields :fields="block.fields" :columns="2" />
  </SettingsBlock>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { SettingsBlock, SettingsFields } from '@/core/params'
import { plannerFields, briefingFields } from '../runtimeSettings'
import type { HarnessExecutionConfiguration } from '../services/harnessService'

const { configurations } = defineProps<{ configurations: HarnessExecutionConfiguration[] }>()
const { t, te } = useI18n()
const blocks = computed(() => [
  {
    key: 'planner', fields: plannerFields,
    harnesses: configurations.filter(item => item.pipeline_policy?.use_planner),
  },
  {
    key: 'briefing', fields: briefingFields,
    harnesses: configurations.filter(item => item.pipeline_policy?.use_briefing
      && item.pipeline_policy.briefing_efforts.length > 0),
  },
].filter(block => block.harnesses.length > 0))
</script>
