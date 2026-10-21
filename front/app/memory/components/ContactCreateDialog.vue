<template>
  <q-dialog :model-value="true" @update:model-value="emit('close')">
    <q-card class="contact-create-dialog galaris-dialog-card">
      <DialogHeader :title="t('contacts.createTitle')" icon="person_add" />
      <q-form class="galaris-dialog-form" @submit="save">
        <q-card-section class="galaris-dialog-body">
          <q-input v-model="displayName" outlined autofocus maxlength="500"
            :label="t('contacts.displayName')" :disable="saving"
            :rules="[(value: string) => !!value.trim() || t('contacts.nameRequired')]" />
          <q-input v-model="email" outlined type="email" maxlength="320"
            :label="t('contacts.email')" :disable="saving"
            :rules="[(value: string) => !!value.trim() || t('contacts.emailRequired')]" />
          <p class="text-caption">{{ t('contacts.createHelp') }}</p>
          <q-banner v-if="error" role="alert">{{ error }}</q-banner>
        </q-card-section>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn outline :label="t('contacts.cancel')" v-close-popup />
          <q-btn color="primary" type="submit" :label="t('contacts.create')" :loading="saving"
            :disable="!displayName.trim() || !email.trim()" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { DialogHeader } from '@/core/util'
import { contactService } from '../services/contactService'

const { agentId } = defineProps<{ agentId: number }>()
const emit = defineEmits<{ close: []; created: [] }>()
const { t } = useI18n()
const displayName = ref('')
const email = ref('')
const saving = ref(false)
const error = ref('')
let active = true
onBeforeUnmount(() => { active = false })

async function save(): Promise<void> {
  if (saving.value || !displayName.value.trim() || !email.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    await contactService.create({ agent_id: agentId, display_name: displayName.value.trim(), email: email.value.trim() })
    if (active) emit('created')
  } catch (caught) {
    if (active) {
      const detail = apiErrorDetail(caught)
      error.value = detail ? `${t('contacts.createError')} ${detail}` : t('contacts.createError')
    }
  } finally {
    if (active) saving.value = false
  }
}
</script>

<style scoped>
.contact-create-dialog { width: min(520px, calc(100vw - 32px)); max-width: 520px; }
</style>
