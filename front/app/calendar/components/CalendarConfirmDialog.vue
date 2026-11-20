<template>
  <q-dialog data-confirmation :model-value="true" @update:model-value="!$event && emit('close')"><q-card class="galaris-dialog-card">
    <DialogHeader :title="title" :close-label="t('agenda.close')" :close-popup="false" @close="emit('close')" />
    <q-card-section class="galaris-dialog-body q-gutter-y-md"><p>{{ message }}</p><p v-if="hint" class="text-caption">{{ hint }}</p><slot />
      <q-banner v-if="error" role="alert">{{ error }}</q-banner></q-card-section>
    <q-card-actions class="galaris-dialog-actions" align="right"><q-btn outline color="primary" :label="t('agenda.cancel')" @click="emit('close')" /><q-btn data-autofocus :color="negative ? 'negative' : 'primary'" :label="confirm" :loading="busy" @click="emit('confirm')" /></q-card-actions>
  </q-card></q-dialog>
</template>
<script setup lang="ts">
import { DialogHeader } from '@/core/util'
import { useI18n } from 'vue-i18n'
defineProps<{ title: string; message: string; hint?: string; confirm: string; negative?: boolean; busy?: boolean; error?: string }>()
const emit = defineEmits<{ close: []; confirm: [] }>()
const { t } = useI18n()
</script>
