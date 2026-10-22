<template>
  <div class="col-12 q-pa-sm">
    <q-card flat bordered>
      <q-card-section class="q-gutter-sm">
        <div class="text-subtitle2">{{ delivery.subject || t('mailJournal.noSubject') }}</div>
        <div><strong>{{ t('mailJournal.agent') }}:</strong> {{ delivery.agent_label }}</div>
        <div style="overflow-wrap: anywhere"><strong>{{ t('mailJournal.recipients') }}:</strong> {{ delivery.to_addresses.join(', ') }}</div>
        <div><strong>{{ t('mailJournal.requestedAt') }}:</strong> {{ requestedAt }}</div>
        <slot name="status" />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn
          outline
          color="primary"
          :icon="delivery.can_review ? 'approval' : 'visibility'"
          :label="t(delivery.can_review ? 'mailJournal.review' : 'mailJournal.view')"
          @click="emit('open', delivery)"
        />
      </q-card-actions>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { MailDeliveryListItem } from '../services/mailService'

defineProps<{ delivery: MailDeliveryListItem; requestedAt: string }>()
const emit = defineEmits<{ open: [delivery: MailDeliveryListItem] }>()
const { t } = useI18n()
</script>
