<template>
  <q-dialog :model-value="true" @update:model-value="emit('close')">
    <q-card class="contact-edit-dialog galaris-dialog-card">
      <DialogHeader :title="t('contacts.editTitle')" icon="edit" />
      <q-form class="galaris-dialog-form" @submit="save">
        <q-card-section class="galaris-dialog-body contact-edit-body">
          <q-input
            v-model="displayName"
            outlined
            autofocus
            maxlength="500"
            hide-bottom-space
            :label="t('contacts.displayName')"
            :disable="saving"
            :rules="[(value: string) => !!value.trim() || t('contacts.nameRequired')]"
          >
            <template #prepend><q-icon name="person_outline" /></template>
          </q-input>
          <p class="contact-edit-hint q-mt-sm q-mb-lg">{{ t('contacts.editHelp') }}</p>
          <div class="row items-center justify-between q-mb-sm">
            <div class="text-subtitle2">{{ t('contacts.linkedAccounts') }}</div>
            <span class="contact-edit-hint">{{ contact.identities.length }}</span>
          </div>
          <q-list v-if="contact.identities.length" bordered separator class="contact-accounts">
            <q-item v-for="(identity, index) in contact.identities" :key="identity.id"
              role="group" :aria-label="t('contacts.identityNumber', { number: index + 1 })"
              class="contact-account" :class="{ 'contact-account--split': splitIds.includes(identity.id) }">
              <q-item-section avatar>
                <q-avatar class="contact-account-icon" size="36px">
                  <q-icon :name="identity.kind === 'galaris_user' ? 'person_outline' : identity.namespace === 'mail' ? 'mail_outline' : 'chat_bubble_outline'" size="20px" />
                </q-avatar>
              </q-item-section>
              <q-item-section class="contact-account-content">
                <q-item-label class="text-weight-medium contact-account-channel">{{ identity.kind === 'galaris_user' ? t('contacts.identityGalaris') : identity.namespace.replaceAll('_', ' ') }}</q-item-label>
                <q-item-label caption class="contact-identity-address">{{ identity.external_id }}</q-item-label>
                <q-item-label v-if="splitIds.includes(identity.id)" caption class="contact-account-status">{{ t('contacts.splitPending') }}</q-item-label>
              </q-item-section>
              <q-item-section side>
                <q-btn flat round color="primary" :icon="splitIds.includes(identity.id) ? 'undo' : 'call_split'"
                  :disable="saving || (!splitIds.includes(identity.id) && contact.identities.length - splitIds.length <= 1)"
                  :aria-label="t(splitIds.includes(identity.id) ? 'contacts.undoSplitIdentity' : 'contacts.splitIdentity', { number: index + 1 })"
                  @click="toggleSplit(identity.id)">
                  <q-tooltip>{{ t(splitIds.includes(identity.id) ? 'contacts.undoSplitIdentity' : 'contacts.splitIdentity', { number: index + 1 }) }}</q-tooltip>
                </q-btn>
              </q-item-section>
            </q-item>
          </q-list>
          <p v-else class="contact-edit-hint">{{ t('contacts.noIdentity') }}</p>
          <div class="contact-split-hint q-mt-md">
            <q-icon name="info_outline" size="16px" class="q-mt-xs" aria-hidden="true" />
            <span>{{ t('contacts.splitHelp') }}</span>
          </div>
          <q-banner v-if="error" rounded class="q-mt-md" role="alert">
            {{ error }}
          </q-banner>
        </q-card-section>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn outline :label="t('contacts.cancel')" v-close-popup />
          <q-btn
            color="primary"
            type="submit"
            :label="t('contacts.save')"
            :loading="saving"
            :disable="!displayName.trim()"
          />
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
import type { Contact, ContactUpdate } from '../types'

const { contact } = defineProps<{ contact: Contact }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const { t } = useI18n()
const displayName = ref(contact.display_name)
const splitIds = ref<string[]>([])
function toggleSplit(id: string): void {
  if (saving.value) return
  if (splitIds.value.includes(id)) splitIds.value = splitIds.value.filter(value => value !== id)
  else if (contact.identities.length - splitIds.value.length > 1) splitIds.value.push(id)
}
const saving = ref(false)
const error = ref('')
let active = true
onBeforeUnmount(() => { active = false })

async function save(): Promise<void> {
  if (saving.value || !displayName.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    const data: ContactUpdate = { display_name: displayName.value.trim() }
    if (splitIds.value.length) {
      data.split_identity_ids = splitIds.value
      data.expected_identity_ids = contact.identities.map(identity => identity.id)
    }
    await contactService.update(contact.memory_item_id, data)
    if (active) emit('saved')
  } catch (caught) {
    if (active) {
      const detail = apiErrorDetail(caught)
      error.value = detail ? `${t('contacts.editError')} ${detail}` : t('contacts.editError')
    }
  } finally {
    if (active) saving.value = false
  }
}
</script>

<style scoped>
.contact-edit-dialog {
  width: min(600px, calc(100vw - 32px));
  max-width: 600px;
}

.contact-edit-body { padding: 24px; }
.contact-edit-hint, .contact-split-hint { font-size: 12px; color: inherit; opacity: .72; }
.contact-accounts { border-radius: 12px; overflow: hidden; }
.contact-account { padding: 14px 16px; }
.contact-account-content { min-width: 0; }
.contact-account-channel { text-transform: capitalize; }
.contact-identity-address { overflow-wrap: anywhere; line-height: 1.5; }
.contact-account-icon { color: var(--solaire-blue-accent); background: var(--solaire-blue-light); }
.contact-account--split { background: var(--solaire-blue-light); }
.contact-account-status { color: inherit; font-weight: 500; line-height: 1.5; }
.contact-split-hint { display: flex; align-items: flex-start; gap: 8px; line-height: 1.6; }
:global(.body--dark) .contact-account-icon,
:global(.body--dark) .contact-account--split { background: var(--solaire-blue-dark); }

@media (max-width: 599px) {
  .contact-edit-body { padding: 20px 16px; }
  .contact-account { padding: 12px; }
}
</style>
