<template>
  <q-dialog v-model="open">
    <q-card class="bulk-dialog galaris-dialog-card">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <div class="text-h6">{{ t('documents.bulk.title', { count: entries.length }) }}</div>
        <q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section class="galaris-dialog-body q-gutter-md">
        <q-select v-model="action" outlined emit-value map-options :options="actions" :label="t('documents.bulk.operation')" :disable="busy" />
        <template v-if="action === 'sharing'">
          <div>{{ t('documents.bulk.sharingHint') }}</div>
          <q-banner v-if="optionsError" role="alert">{{ t('documents.bulk.optionsError') }}
            <q-btn outline :label="t('documents.retry')" @click="loadOptions" />
          </q-banner>
          <q-select v-model="recipientKey" outlined emit-value map-options use-input input-debounce="0"
            :options="recipientOptions" :label="t('documents.bulk.recipient')" :loading="loading" :disable="busy || loading" @filter="filterRecipients" />
          <q-select v-model="access" outlined emit-value map-options :options="accessOptions" :label="t('documents.bulk.access')" :disable="busy" />
          <div class="text-caption">{{ t('documents.bulk.inheritedHint') }}</div>
        </template>
        <template v-else-if="action === 'keywordsAdd' || action === 'keywordsRemove'">
          <q-select v-model="keywords" outlined multiple use-chips use-input new-value-mode="add-unique" hide-dropdown-icon
            :label="t('documents.bulk.keywords')" :hint="t('documents.bulk.keywordsHint')" :disable="busy" />
        </template>
        <template v-else-if="action === 'owner'">
          <q-banner v-if="optionsError" role="alert">{{ t('documents.ownerLoadError') }}<q-btn outline :label="t('documents.retry')" @click="loadOptions" /></q-banner>
          <OwnerSelect v-model="ownerKey" :options="owners" :loading="loading" :disable="busy || loading" @open="refreshOwners" />
        </template>
        <q-banner v-else-if="action === 'delete'">{{ t('documents.bulk.deleteHint', { count: entries.length }) }}</q-banner>
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-close-popup outline :label="t('documents.library.cancel')" />
        <q-btn :color="action === 'delete' ? 'negative' : 'primary'" :disable="!operation || loading || optionsError || busy"
          :loading="busy" :label="t(action === 'delete' ? 'documents.bulk.delete' : 'documents.library.apply')" @click="submit" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DocumentLibraryEntry, DocumentOwnerOption } from '../types'
import { OwnerSelect, type Collaborator } from '@/app/share'
import { memoryService } from '../services/memoryService'
import type { DocumentBulkOperation } from '../services/documentBulkService'

const open = defineModel<boolean>({ required: true })
const props = defineProps<{ entries: DocumentLibraryEntry[]; busy: boolean }>()
const emit = defineEmits<{ apply: [operation: DocumentBulkOperation] }>()
const { t } = useI18n()
const action = ref('keywordsAdd')
const keywords = ref<string[]>([])
const access = ref<'read' | 'write' | 'remove'>('read')
const recipientKey = ref('public')
const ownerKey = ref('')
const recipients = ref<Collaborator[]>([])
const owners = ref<DocumentOwnerOption[]>([])
const search = ref('')
const loading = ref(false)
const optionsError = ref(false)
let generation = 0
const key = (value: { kind: string; id: number }): string => `${value.kind}:${value.id}`
const actions = computed(() => ['keywordsAdd', 'keywordsRemove', 'sharing', 'owner', 'delete'].map(value => ({ value, label: t(`documents.bulk.${value}`) })))
const accessOptions = computed(() => ['read', 'write', 'remove'].map(value => ({ value, label: t(`documents.bulk.${value}`) })))
const recipientOptions = computed(() => [
  { value: 'public', label: t('resourceSharing.public') },
  ...recipients.value.map(value => ({ value: key(value), label: `${value.label} (${t(`documents.bulk.${value.kind}`)})` })),
].filter(value => value.label.toLocaleLowerCase().includes(search.value)))
const operation = computed<DocumentBulkOperation | null>(() => {
  if (action.value === 'delete') return { kind: 'delete' }
  if (action.value === 'keywordsAdd' || action.value === 'keywordsRemove') {
    const values = keywords.value.map(value => value.trim()).filter(Boolean)
    return values.length ? { kind: 'keywords', remove: action.value === 'keywordsRemove', values } : null
  }
  if (action.value === 'owner') {
    const owner = owners.value.find(value => key(value) === ownerKey.value)
    return owner ? { kind: 'owner', ownerKind: owner.kind, ownerId: owner.id } : null
  }
  const recipient = recipients.value.find(value => key(value) === recipientKey.value)
  return recipient || recipientKey.value === 'public'
    ? { kind: 'sharing', recipient: recipient ? { kind: recipient.kind, id: recipient.id } : null, access: access.value } : null
})
function filterRecipients(value: string, update: (callback: () => void) => void): void { update(() => { search.value = value.toLocaleLowerCase() }) }
async function refreshOwners(): Promise<void> {
  const current = ++generation
  try {
    const result = await memoryService.listDocumentOwnerOptions()
    if (current === generation && open.value) owners.value = [...result.users, ...result.agents]
  } catch { if (current === generation) optionsError.value = true }
}
async function loadOptions(): Promise<void> {
  const current = ++generation
  loading.value = true; optionsError.value = false; search.value = ''
  try {
    if (action.value === 'owner') {
      const result = await memoryService.listDocumentOwnerOptions()
      if (current !== generation) return
      owners.value = [...result.agents, ...result.users]
    } else if (action.value === 'sharing') {
      const choices = new Map<string, Collaborator>()
      for (const entry of props.entries) {
        const state = await memoryService.documentSharing(entry.item.id)
        if (current !== generation) return
        for (const value of [...state.options, ...state.grants]) choices.set(key(value), value)
      }
      recipients.value = [...choices.values()].sort((a, b) => a.label.localeCompare(b.label))
    }
  } catch { if (current === generation) optionsError.value = true }
  finally { if (current === generation) loading.value = false }
}
function submit(): void { if (operation.value && !props.busy) emit('apply', operation.value) }
watch([open, action], () => {
  ++generation
  loading.value = false; optionsError.value = false; search.value = ''
  if (open.value) void loadOptions()
})
watch(open, value => { if (value) { keywords.value = []; ownerKey.value = ''; recipientKey.value = 'public'; access.value = 'read' } })
onBeforeUnmount(() => { ++generation })
</script>

<style scoped>
.bulk-dialog { width: min(600px, calc(100vw - 24px)); }
</style>
