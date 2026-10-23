<template>
  <div>
    <p class="text-body2">{{ t('skills.personal.hint') }}</p>
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-6">
        <AgentSelect v-model="ownerId" :options="agentOptions" :load-agents="false" emit-value map-options clearable outlined dense
          :label="t('skills.learning.agentFilter')" />
      </div>
      <div class="col-12 col-md-6">
        <q-input v-model="search" :debounce="250" outlined dense clearable :label="t('skills.search')">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
    </div>
    <q-banner v-if="error" class="q-mb-md" role="alert">
      {{ t('skills.error') }}
      <template #action><q-btn outline color="primary" :label="t('skills.personal.retry')" @click="reload" /></template>
    </q-banner>
    <q-table v-model:pagination="pagination" :rows="rows" :columns="columns" row-key="id"
      :loading="loading" :grid="$q.screen.lt.md" :rows-per-page-options="[10, 20, 50, 100, 500]"
      :no-data-label="t('skills.personal.empty')" flat bordered @request="requestPage">
      <template #body-cell-label="props">
        <q-td :props="props"><div>{{ props.row.label }}</div><code>{{ props.row.code }}</code>
          <div class="text-caption personal-description">{{ props.row.description }}</div></q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">{{ status(props.row) }}</q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props"><q-btn flat round icon="visibility" color="primary"
          :aria-label="t('skills.view')" @click="openDetail(props.row)"><q-tooltip>{{ t('skills.view') }}</q-tooltip></q-btn></q-td>
      </template>
      <template #item="props">
        <div class="col-12 q-pa-xs">
          <q-card flat bordered>
            <q-card-section><div class="text-subtitle1">{{ props.row.label }}</div><code>{{ props.row.code }}</code>
              <div>{{ props.row.owner_label }}</div><div>{{ status(props.row) }}</div>
              <p class="personal-description">{{ props.row.description }}</p>
              <div>{{ t('skills.files') }}: {{ props.row.file_count }}</div>
              <div>{{ t('skills.personal.modified') }}: {{ formatDate(props.row.updated_at) }}</div>
            </q-card-section>
            <q-card-actions align="right"><q-btn outline color="primary" :label="t('skills.view')" @click="openDetail(props.row)" /></q-card-actions>
          </q-card>
        </div>
      </template>
    </q-table>
    <q-dialog v-model="detailOpen" @hide="closeDetail">
      <q-card class="personal-detail galaris-dialog-card column no-wrap">
        <q-toolbar class="galaris-dialog-title bg-primary text-white">
          <q-toolbar-title>{{ selected?.label }}</q-toolbar-title>
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('skills.cancel')" />
        </q-toolbar>
        <q-card-section class="galaris-dialog-body scroll">
          <div class="q-mb-md">{{ selected?.owner_label }}</div>
          <q-banner v-if="detailError" role="alert" class="q-mb-md">
            {{ t('skills.error') }}
            <template #action><q-btn outline color="primary" :label="t('skills.personal.retry')" @click="retryDetail" /></template>
          </q-banner>
          <q-select v-model="filePath" :options="files.map(file => file.path)" outlined dense
            :label="t('skills.selectFile')" class="q-mb-md" />
          <div v-if="detailLoading" class="row justify-center q-pa-lg"><q-spinner color="primary" size="32px" /></div>
          <template v-else-if="content !== null">
            <Markdown v-if="filePath.endsWith('.md')" :content="content" compact-frontmatter />
            <pre v-else class="personal-source">{{ content }}</pre>
          </template>
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableProps } from 'quasar'
import { AgentSelect } from '@/app/agent'
import { Markdown } from '@/core/util'
import { skillService, type PersonalSkill, type SkillAgent, type SkillFile } from '../services/skillService'

const { active } = defineProps<{ active: boolean }>()
const { t, locale } = useI18n()
const ownerId = ref<number | null>(null)
const search = ref<string | null>('')
const rows = ref<PersonalSkill[]>([])
const agents = ref<SkillAgent[]>([])
const agentOptions = computed(() => agents.value.map(agent => ({ value: agent.id, label: agent.label })))
const loading = ref(false)
const error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
const columns = computed<QTableProps['columns']>(() => [
  { name: 'label', label: t('skills.label'), field: 'label', align: 'left' },
  { name: 'owner', label: t('skills.personal.owner'), field: 'owner_label', align: 'left' },
  { name: 'status', label: t('skills.status'), field: 'enabled', align: 'left' },
  { name: 'files', label: t('skills.files'), field: 'file_count', align: 'left' },
  { name: 'updated', label: t('skills.personal.modified'), field: 'updated_at', format: formatDate, align: 'left' },
  { name: 'actions', label: t('skills.actions'), field: 'id', align: 'right' },
])
function formatDate(value: string): string { return new Date(value).toLocaleString(locale.value) }
function status(row: PersonalSkill): string {
  if (!row.available) return t('skills.missing')
  if (!row.valid) return t('skills.invalid')
  return t(row.enabled ? 'skills.personal.enabled' : 'skills.personal.disabled')
}
async function reload(): Promise<void> {
  const request = ++generation
  rows.value = []
  loading.value = true
  error.value = false
  try {
    const [catalogue, owners] = await Promise.all([
      skillService.getPersonalSkills({ owner_agent_id: ownerId.value, search: search.value || '',
        page: pagination.value.page, page_size: pagination.value.rowsPerPage }),
      skillService.getAgents(),
    ])
    if (request !== generation) return
    rows.value = catalogue.data.items
    pagination.value.rowsNumber = catalogue.data.total
    agents.value = owners.data
  } catch {
    if (request === generation) error.value = true
  } finally {
    if (request === generation) loading.value = false
  }
}
function requestPage(event: { pagination: { page: number; rowsPerPage: number } }): void {
  pagination.value = { ...pagination.value, ...event.pagination }
  void reload()
}
const detailOpen = ref(false)
const selected = ref<PersonalSkill | null>(null)
const files = ref<SkillFile[]>([])
const filePath = ref('')
const content = ref<string | null>(null)
const detailLoading = ref(false)
const detailError = ref(false)
let detailGeneration = 0
async function openDetail(row: PersonalSkill): Promise<void> {
  closeDetail()
  selected.value = row
  detailOpen.value = true
  const request = ++detailGeneration
  detailLoading.value = true
  try {
    const response = await skillService.getPersonalSkill(row.id)
    if (request !== detailGeneration) return
    files.value = response.data.files
    filePath.value = files.value.find(file => file.path === 'SKILL.md')?.path || files.value[0]?.path || ''
  } catch {
    if (request === detailGeneration) detailError.value = true
  } finally {
    if (request === detailGeneration) detailLoading.value = false
  }
}
async function readContent(): Promise<void> {
  const request = ++detailGeneration
  content.value = null
  detailError.value = false
  if (!selected.value || !filePath.value || !detailOpen.value) return
  if (!files.value.find(file => file.path === filePath.value)?.text) {
    content.value = t('skills.binaryFile')
    return
  }
  detailLoading.value = true
  try {
    const response = await skillService.getPersonalSkillContent(selected.value.id, filePath.value)
    if (request === detailGeneration) content.value = response.data.content
  } catch {
    if (request === detailGeneration) detailError.value = true
  } finally {
    if (request === detailGeneration) detailLoading.value = false
  }
}
function retryDetail(): void {
  if (!files.value.length && selected.value) void openDetail(selected.value)
  else void readContent()
}
function closeDetail(): void {
  ++detailGeneration
  selected.value = null
  files.value = []
  filePath.value = ''
  content.value = null
  detailError.value = false
  detailLoading.value = false
}
watch(filePath, path => { if (path) void readContent() })
watch([ownerId, search], () => {
  detailOpen.value = false
  closeDetail()
  pagination.value.page = 1
  if (active) void reload()
})
watch(() => active, value => {
  if (value) void reload()
  else { ++generation; detailOpen.value = false; closeDetail() }
}, { immediate: true })
onBeforeUnmount(() => { ++generation; closeDetail() })
</script>

<style scoped>
.personal-detail { width: 900px; max-width: 95vw; max-height: 90vh; }
.personal-description, .personal-source { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
