<template>
  <q-page class="q-pa-md">
    <PageHeader :icon="navigationIcon('contacts')" :title="t('nav.contacts')" :description="t('nav.contacts_desc')">
      <template #title-after>
        <q-btn
          round
          flat
          color="primary"
          icon="refresh"
          :loading="loading"
          :aria-label="t('contacts.refresh')"
          @click="load"
        >
          <q-tooltip>{{ t('contacts.refresh') }}</q-tooltip>
        </q-btn>
      </template>
    </PageHeader>

    <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error_outline" /></template>
      {{ t('contacts.loadError') }}
    </q-banner>

    <q-card flat bordered>
      <q-card-section class="row q-col-gutter-sm items-center">
        <div class="col-12 col-md-4">
          <AgentSelect
            v-model="selectedAgentId"
            :options="agentOptions"
            behavior="menu"
            emit-value
            map-options
            outlined
            dense
            options-dense
            :label="t('contacts.agent')"
            :loading="agentStore.loading"
          />
        </div>
        <div class="col-12 col-md">
          <q-input
            class="contact-search-filter"
            v-model="search"
            outlined
            dense
            clearable
            debounce="350"
            :placeholder="t('contacts.search')"
            @update:model-value="reloadFromStart"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </div>
        <div v-if="canEdit" class="col-12 col-md-auto">
          <q-btn
            color="primary"
            icon="merge"
            :label="t('contacts.merge')"
            :disable="selected.length !== 2"
            @click="openMerge"
          />
        </div>
      </q-card-section>

      <q-separator />

      <q-table
        v-model:selected="selected"
        v-model:pagination="pagination"
        flat
        wrap-cells
        row-key="memory_item_id"
        selection="multiple"
        :grid="$q.screen.lt.md"
        :rows="contacts"
        :columns="columns"
        :loading="loading"
        :rows-per-page-options="[10, 20, 50, 100, 500]"
        :no-data-label="selectedAgentId === null ? t('contacts.selectAgent') : t('contacts.noRows')"
        @request="onRequest"
      >
        <template #body-cell-name="props">
          <q-td :props="props">
            <div class="text-weight-medium">{{ props.row.display_name }}</div>
            <div class="text-caption text-grey-7">{{ props.row.memory_title }}</div>
          </q-td>
        </template>

        <template #body-cell-identities="props">
          <q-td :props="props">
            <div v-if="props.row.identities.length" class="row q-gutter-xs">
              <q-chip
                v-for="identity in props.row.identities"
                :key="identity.id"
                dense
                :icon="identity.kind === 'galaris_user' ? 'person' : 'alternate_email'"
                :color="identity.kind === 'galaris_user' ? 'blue-1' : 'blue-grey-1'"
                text-color="blue-grey-9"
              >
                {{ identityLabel(identity) }}
                <q-tooltip v-if="identity.display_name">{{ identity.display_name }}</q-tooltip>
              </q-chip>
            </div>
            <span v-else class="text-grey-6">{{ t('contacts.noIdentity') }}</span>
          </q-td>
        </template>

        <template #body-cell-memory="props">
          <q-td :props="props">
            <q-btn
              flat
              dense
              color="primary"
              icon="memory"
              :label="String(props.row.linked_memory_count)"
              :to="memoryLink(props.row)"
              :aria-label="t('contacts.openMemory', { name: props.row.display_name })"
            />
          </q-td>
        </template>

        <template #body-cell-actions="props">
          <q-td :props="props">
            <q-btn
              v-if="canEdit"
              flat
              round
              dense
              color="negative"
              icon="person_remove"
              :aria-label="t('contacts.forgetNamed', { name: props.row.display_name })"
              @click="openForget(props.row)"
            >
              <q-tooltip>{{ t('contacts.forget') }}</q-tooltip>
            </q-btn>
          </q-td>
        </template>

        <template #item="props">
          <div class="q-pa-xs col-12 col-sm-6">
            <q-card flat bordered>
              <q-card-section class="row items-start no-wrap q-gutter-sm">
                <q-checkbox v-if="canEdit" v-model="props.selected" dense />
                <div class="col contact-mobile-content">
                  <div class="text-weight-medium">{{ props.row.display_name }}</div>
                  <div class="text-caption text-grey-7">{{ props.row.memory_title }}</div>
                  <div class="row q-gutter-xs q-mt-sm">
                    <q-chip
                      v-for="identity in props.row.identities"
                      :key="identity.id"
                      dense
                      :icon="identity.kind === 'galaris_user' ? 'person' : 'alternate_email'"
                    >
                      {{ identityLabel(identity) }}
                    </q-chip>
                  </div>
                  <q-btn
                    flat
                    dense
                    color="primary"
                    icon="memory"
                    :label="String(props.row.linked_memory_count)"
                    :to="memoryLink(props.row)"
                    :aria-label="t('contacts.openMemory', { name: props.row.display_name })"
                  />
                </div>
                <q-btn
                  v-if="canEdit"
                  flat
                  round
                  dense
                  color="negative"
                  icon="person_remove"
                  :aria-label="t('contacts.forgetNamed', { name: props.row.display_name })"
                  @click="openForget(props.row)"
                >
                  <q-tooltip>{{ t('contacts.forget') }}</q-tooltip>
                </q-btn>
              </q-card-section>
            </q-card>
          </div>
        </template>
      </q-table>
    </q-card>

    <div v-if="canEdit" class="text-caption text-grey-7 q-mt-sm">
      {{ selectionHint }}
    </div>

    <q-dialog v-model="mergeDialog">
      <q-card class="contact-merge-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('contacts.mergeTitle') }}</div>
          <q-space />
          <q-btn flat round dense icon="close" v-close-popup :aria-label="t('contacts.close')" />
        </q-card-section>
        <q-card-section>
          <p class="q-mt-none">{{ t('contacts.mergeHelp') }}</p>
          <div class="text-subtitle2 q-mb-sm">{{ t('contacts.canonical') }}</div>
          <q-list bordered separator>
            <q-item
              v-for="contact in selected"
              :key="contact.memory_item_id"
              clickable
              @click="canonicalContactItemId = contact.memory_item_id"
            >
              <q-item-section avatar>
                <q-radio
                  v-model="canonicalContactItemId"
                  :val="contact.memory_item_id"
                  color="primary"
                />
              </q-item-section>
              <q-item-section>
                <q-item-label>{{ contact.display_name }}</q-item-label>
                <q-item-label caption>
                  {{ contact.identities.map(identityLabel).join(' · ') }}
                </q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="t('contacts.cancel')" v-close-popup />
          <q-btn
            color="primary"
            icon="merge"
            :label="t('contacts.mergeConfirm')"
            :loading="merging"
            :disable="canonicalContactItemId === null"
            @click="confirmMerge"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="forgetDialog">
      <q-card class="contact-forget-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('contacts.forgetTitle') }}</div>
          <q-space />
          <q-btn flat round dense icon="close" v-close-popup :aria-label="t('contacts.close')" />
        </q-card-section>
        <q-card-section v-if="contactToForget">
          <p class="q-mt-none">
            {{ t('contacts.forgetHelp', {
              name: contactToForget.display_name,
              count: contactToForget.linked_memory_count,
            }) }}
          </p>
          <q-banner rounded class="bg-red-1 text-negative">
            <template #avatar><q-icon name="warning" /></template>
            {{ t('contacts.forgetWarning') }}
          </q-banner>
        </q-card-section>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="t('contacts.cancel')" v-close-popup />
          <q-btn
            color="negative"
            icon="person_remove"
            :label="t('contacts.forgetConfirm')"
            :loading="forgetting"
            @click="confirmForget"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTableProps } from 'quasar'
import { apiErrorDetail } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { PageHeader } from '@/core/util'
import { AgentSelect, useAgentStore } from '@/app/agent'
import { contactService } from '../services/contactService'
import type { Contact, ContactIdentity } from '../types'

const { t, locale } = useI18n()
const $q = useQuasar()
const agentStore = useAgentStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_EDIT))
const contacts = ref<Contact[]>([])
const selected = ref<Contact[]>([])
const selectedAgentId = ref<number | null>(null)
const search = ref('')
const loading = ref(false)
const merging = ref(false)
const forgetting = ref(false)
const error = ref<unknown>(null)
const mergeDialog = ref(false)
const forgetDialog = ref(false)
const contactToForget = ref<Contact | null>(null)
const canonicalContactItemId = ref<string | null>(null)
const pagination = ref({
  page: 1,
  rowsPerPage: 50,
  rowsNumber: 0,
  sortBy: null as string | null,
  descending: false,
})

type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]

const agentOptions = computed(() => agentStore.agents.map(agent => ({
  value: agent.id,
  label: `${agent.first_name} ${agent.last_name}`.trim() || agent.code,
})))

const selectionHint = computed(() => {
  if (selected.value.length === 2) {
    return t('contacts.selectedCount', { count: selected.value.length })
  }
  return t('contacts.selectTwo')
})

const columns = computed<QTableProps['columns']>(() => [
  { name: 'name', label: t('contacts.name'), field: 'display_name', align: 'left' },
  { name: 'identities', label: t('contacts.identities'), field: 'identities', align: 'left' },
  { name: 'memory', label: t('contacts.memories'), field: 'linked_memory_count', align: 'center' },
  {
    name: 'updated',
    label: t('contacts.updated'),
    field: (row: Contact) => row.updated_at ?? row.created_at,
    format: (value: string) => new Intl.DateTimeFormat(locale.value, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value)),
    align: 'left',
  },
  {
    name: 'actions',
    label: t('contacts.actions'),
    field: 'memory_item_id',
    align: 'right',
  },
])

function identityLabel(identity: ContactIdentity): string {
  if (identity.kind === 'galaris_user') {
    return t('contacts.galarisUser', { id: identity.galaris_user_id })
  }
  return `${identity.namespace} · ${identity.external_id}`
}

function memoryLink(contact: Contact): { path: string, query: Record<string, string> } {
  return {
    path: '/memory',
    query: {
      agent: String(contact.owner_agent_id),
      contact: contact.memory_item_id,
    },
  }
}

async function load(): Promise<void> {
  if (selectedAgentId.value === null) {
    contacts.value = []
    pagination.value.rowsNumber = 0
    return
  }
  loading.value = true
  error.value = null
  try {
    const page = await contactService.list({
      agentId: selectedAgentId.value,
      query: search.value,
      limit: pagination.value.rowsPerPage,
      offset: (pagination.value.page - 1) * pagination.value.rowsPerPage,
    })
    contacts.value = page.items
    pagination.value.rowsNumber = page.total
    selected.value = []
  } catch (caught) {
    error.value = caught
  } finally {
    loading.value = false
  }
}

function reloadFromStart(): void {
  pagination.value.page = 1
  void load()
}

function onRequest(request: TableRequest): void {
  pagination.value.page = request.pagination.page
  pagination.value.rowsPerPage = request.pagination.rowsPerPage
  void load()
}

function openMerge(): void {
  if (selected.value.length !== 2) return
  canonicalContactItemId.value = selected.value[0]?.memory_item_id ?? null
  mergeDialog.value = true
}

async function confirmMerge(): Promise<void> {
  const targetId = canonicalContactItemId.value
  const source = selected.value.find(contact => contact.memory_item_id !== targetId)
  if (targetId === null || source === undefined) return
  merging.value = true
  try {
    await contactService.merge(source.memory_item_id, targetId)
    mergeDialog.value = false
    selected.value = []
    $q.notify({ type: 'positive', message: t('contacts.mergeDone') })
    await load()
  } catch (caught) {
    const detail = apiErrorDetail(caught)
    $q.notify({
      type: 'negative',
      message: detail ? `${t('contacts.mergeError')} ${detail}` : t('contacts.mergeError'),
      multiLine: true,
    })
  } finally {
    merging.value = false
  }
}

function openForget(contact: Contact): void {
  contactToForget.value = contact
  forgetDialog.value = true
}

async function confirmForget(): Promise<void> {
  const contact = contactToForget.value
  if (contact === null) return
  forgetting.value = true
  try {
    const result = await contactService.forget(contact.memory_item_id)
    forgetDialog.value = false
    contactToForget.value = null
    selected.value = []
    $q.notify({
      type: 'positive',
      message: t('contacts.forgetDone', { count: result.forgotten_memories }),
    })
    await load()
  } catch (caught) {
    const detail = apiErrorDetail(caught)
    $q.notify({
      type: 'negative',
      message: detail ? `${t('contacts.forgetError')} ${detail}` : t('contacts.forgetError'),
      multiLine: true,
    })
  } finally {
    forgetting.value = false
  }
}

watch(selectedAgentId, reloadFromStart)

onMounted(async () => {
  await agentStore.fetchAgents()
  selectedAgentId.value = agentStore.agents[0]?.id ?? null
})
</script>

<style scoped>
.contact-merge-dialog {
  width: min(680px, calc(100vw - 32px));
  max-width: 680px;
}

.contact-forget-dialog {
  width: min(600px, calc(100vw - 32px));
  max-width: 600px;
}

.contact-mobile-content {
  min-width: 0;
}

:deep(.contact-search-filter .q-field__control),
:deep(.contact-search-filter .q-field__marginal) {
  height: 44px;
  min-height: 44px;
}
</style>
