<template>
  <div>
    <p>{{ t('evaluation.comparison.caseEstimate', { cases: value.cases, observations: value.observations, mean: format(value.mean), lower: format(value.lower), upper: format(value.upper) }) }}</p>
    <p>{{ t(value.method === 'case-cluster-hoeffding/v1' ? 'evaluation.comparison.hoeffding' : 'evaluation.comparison.bootstrap') }}</p>
    <p v-if="!value.sufficient" role="status">{{ t('evaluation.comparison.insufficientCases') }}</p>
  </div>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CaseEstimate } from '../services/labWorkbenchService'
defineProps<{ value: CaseEstimate }>()
const { t, locale } = useI18n()
const format = (value: number | null) => value == null ? '—' : value.toLocaleString(locale.value, { maximumFractionDigits: 2 })
</script>
