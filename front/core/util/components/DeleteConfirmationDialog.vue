<template>
  <q-dialog data-confirmation v-model="open" :aria-labelledby="titleId">
    <q-card class="confirm-dialog galaris-dialog-card">
      <DialogHeader :title="title" :title-id="titleId" :close-label="t('common.close')" />
      <q-separator />
      <q-card-section class="galaris-dialog-body">{{ message }}</q-card-section>
      <q-card-actions align="right" class="q-px-md q-pb-md galaris-dialog-actions">
        <!-- eslint-disable-next-line galaris/ui-conventions -- Preserve the borderless cancellation in conversation details. -->
        <q-btn v-close-popup flat :label="t('common.cancel')" />
        <q-btn data-autofocus color="negative" icon="delete" :label="t('common.delete')" :loading="busy" @click="emit('confirm')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { useId } from 'vue'
import { useI18n } from 'vue-i18n'
import DialogHeader from './DialogHeader.vue'

const open = defineModel<boolean>({ required: true })
defineProps<{ title: string; message: string; busy: boolean }>()
const emit = defineEmits<{ confirm: [] }>()
const { t } = useI18n()
const titleId = useId()
</script>

<style scoped>
.confirm-dialog {
  width: min(480px, 92vw);
  max-width: 92vw;
}
</style>
