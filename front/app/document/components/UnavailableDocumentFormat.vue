<template>
  <section>
    <q-banner dense role="status">{{ t('documents.formatUnavailable') }}</q-banner>
    <pre class="unavailable-format-source">{{ modelValue }}</pre>
  </section>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
defineOptions({ inheritAttrs: false })
defineProps<{ modelValue: string }>()
const { t } = useI18n()
</script>
<style scoped>
.unavailable-format-source { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
