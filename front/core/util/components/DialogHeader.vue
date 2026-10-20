<template>
  <q-card-section class="galaris-dialog-title row items-center no-wrap">
    <q-icon v-if="icon" :name="icon" size="sm" class="q-mr-sm" aria-hidden="true" />
    <div :id="titleId" class="dialog-header-title text-h6"><slot name="title">{{ title }}</slot></div>
    <q-space />
    <slot name="actions" />
    <q-btn v-close-popup flat round dense icon="close" :aria-label="closeLabel || t('common.close')" />
  </q-card-section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ title: string; icon?: string; titleId?: string; closeLabel?: string }>()
const { t } = useI18n()
</script>

<style scoped>
.dialog-header-title { min-width: 0; overflow-wrap: anywhere; }
</style>
