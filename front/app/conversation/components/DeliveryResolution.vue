<template>
  <q-banner v-if="state === 'UNKNOWN'" class="bg-orange-1 text-dark q-ma-md" rounded>
    <div v-if="notification" class="text-weight-medium">
      {{ t(`conversation.delivery.${notification.kind}Notification`, { id: notification.kind === 'task' ? `galaris://task/${notification.target_id}` : notification.target_id }) }}
    </div>
    {{ t('conversation.delivery.unknown') }}
    <template #action>
      <q-btn v-if="editable" flat color="primary" :label="t('conversation.delivery.resolve')" @click="show = true" />
    </template>
  </q-banner>
  <q-dialog v-model="show">
    <q-card style="width: 560px; max-width: 95vw">
      <q-card-section class="galaris-dialog-title row items-center">
        <span class="text-h6">{{ t('conversation.delivery.resolve') }}</span><q-space />
        <q-btn v-close-popup icon="close" flat round dense :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section>
        <p>{{ t('conversation.delivery.explanation') }}</p>
        <q-select v-model="decision" :options="options" emit-value map-options :label="t('conversation.delivery.decision')" />
        <q-input v-model="evidence" type="textarea" maxlength="2000" :label="t('conversation.delivery.evidence')" />
        <div v-if="error" role="alert" class="text-negative q-mt-sm">{{ error }}</div>
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-close-popup flat :label="t('common.cancel')" />
        <q-btn color="primary" :label="t('common.save')" :loading="saving" :disable="evidence.trim().length < 10" @click="save" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { conversationService } from '../services/conversationService'
import type { ConversationRoundDetail, ConversationUnknownNotification } from '../types'

const props = defineProps<{ roundId: string; state: string; editable: boolean; notification?: ConversationUnknownNotification }>()
const emit = defineEmits<{ resolved: [round: ConversationRoundDetail] }>()
const { t } = useI18n()
const show = ref(false)
const saving = ref(false)
const error = ref('')
const evidence = ref('')
const decision = ref<'DELIVERED' | 'SKIPPED'>('DELIVERED')
const options = computed(() => [
  { value: 'DELIVERED', label: t('conversation.delivery.delivered') },
  { value: 'SKIPPED', label: t('conversation.delivery.skipped') },
])
async function save(): Promise<void> {
  saving.value = true
  error.value = ''
  try {
    const updated = await conversationService.resolveDelivery(props.roundId, decision.value, evidence.value.trim(), props.notification)
    emit('resolved', updated)
    show.value = false
  } catch (failure) {
    error.value = apiErrorDetail(failure) || t('conversation.delivery.error')
  } finally { saving.value = false }
}
</script>
