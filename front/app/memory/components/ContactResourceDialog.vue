<template>
  <ContactEditDialog v-if="contact" :key="contact.memory_item_id" :contact="contact" :readonly="!canEdit" @close="emit('close')" @saved="emit('changed'); emit('close')" />
  <q-dialog v-else :model-value="true" @update:model-value="!$event && emit('close')">
    <q-card class="galaris-dialog-card" style="width: 600px; max-width: 95vw">
      <DialogHeader :title="t('contacts.detailsTitle')" icon="contacts" />
      <q-card-section class="galaris-dialog-body">
        <div v-if="loading" role="status" class="flex flex-center q-pa-lg"><q-spinner color="primary" size="32px" /></div>
        <q-banner v-else-if="error" role="alert">
          {{ t('contacts.loadError') }}
          <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="refresh" /></template>
        </q-banner>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { DialogHeader } from '@/core/util'
import ContactEditDialog from './ContactEditDialog.vue'
import { useContactResource } from '../useContactResource'
const { contactId } = defineProps<{ contactId: string }>()
const emit = defineEmits<{ close: []; changed: [] }>()
const { t } = useI18n()
const { contact, loading, error, canEdit, refresh } = useContactResource(() => contactId, false)
</script>
