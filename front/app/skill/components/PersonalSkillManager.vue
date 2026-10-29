<template>
  <div>
    <p class="text-body2">{{ t('skills.personal.hint') }}</p>
    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-4">
        <AgentSelect v-model="ownerId" :options="agentOptions" :load-agents="false" emit-value map-options clearable outlined dense
          :label="t('skills.learning.agentFilter')" />
      </div>
      <div class="col-12 col-md-8 order-first">
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
      :no-data-label="t('skills.personal.empty')" :table-row-class-fn="rowClasses" class="personal-skills-table"
      flat bordered @request="requestPage" @row-click="(_event, row) => openDetail(row)">
      <template #body-cell-label="props">
        <q-td :props="props">
          <ActionContextMenu target="tr" :actions="rowActions(props.row)" :label="props.row.label" />
          <div class="text-weight-medium">{{ props.row.label }}</div>
          <code class="text-caption personal-code">{{ props.row.code }}</code></q-td>
      </template>
      <template #body-cell-description="props">
        <q-td :props="props"><div class="personal-description">{{ props.row.description || '—' }}</div></q-td>
      </template>
      <template #body-cell-owner="props">
        <q-td :props="props">
          <div class="row no-wrap items-start q-gutter-xs"><q-icon name="person" color="primary" size="18px" /><span>{{ props.row.owner_label }}</span></div>
          <div class="personal-meta q-mt-sm">{{ t('skills.personal.modified') }}<br>{{ formatDate(props.row.updated_at) }}</div>
        </q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props"><PersonalSkillStatus :skill="props.row" /></q-td>
      </template>
      <template #body-cell-files="props">
        <q-td :props="props"><q-icon name="folder_open" color="primary" size="18px" class="q-mr-xs" />{{ props.row.file_count }}</q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props"><q-btn flat round icon="visibility" color="primary"
          :aria-label="t('skills.view')" @click.stop="openDetail(props.row)"><q-tooltip>{{ t('skills.view') }}</q-tooltip></q-btn></q-td>
      </template>
      <template #item="props">
        <div class="q-table__grid-item col-12">
          <q-card flat bordered class="personal-mobile-card cursor-pointer" :class="{ 'personal-mobile-card--disabled': !props.row.enabled }" @click="openDetail(props.row)">
            <ActionContextMenu target=".personal-mobile-card" :actions="rowActions(props.row)" :label="props.row.label" />
            <q-card-section class="q-gutter-md">
              <div class="row items-start no-wrap q-gutter-sm">
                <div class="col personal-mobile-heading"><div class="text-subtitle1 text-weight-medium">{{ props.row.label }}</div>
                  <code class="text-caption personal-code">{{ props.row.code }}</code></div>
                <PersonalSkillStatus :skill="props.row" class="personal-mobile-status" />
              </div>
              <div><div class="personal-meta text-weight-medium q-mb-xs">{{ t('skills.description') }}</div>
                <div class="personal-description">{{ props.row.description || '—' }}</div></div>
              <div class="row no-wrap items-start q-gutter-xs"><q-icon name="person" color="primary" size="18px" />
                <span>{{ props.row.owner_label }}</span></div>
              <div class="row items-end no-wrap justify-between q-gutter-sm">
                <div class="col personal-mobile-heading">
                  <div><q-icon name="folder_open" color="primary" size="18px" class="q-mr-xs" />{{ t('skills.files') }}: {{ props.row.file_count }}</div>
                  <div class="personal-meta q-mt-xs">{{ t('skills.personal.modified') }}: {{ formatDate(props.row.updated_at) }}</div>
                </div>
                <q-btn flat round color="primary" icon="visibility" :aria-label="t('skills.view')" @click.stop="openDetail(props.row)"><q-tooltip>{{ t('skills.view') }}</q-tooltip></q-btn>
              </div>
            </q-card-section>
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
          <AgentSelect v-if="selected && canEdit" v-model="ownerDraft" :options="ownerOptions" :load-agents="false"
            outlined :label="t('skills.personal.owner')" :disable="saving || detailLoading" class="q-mb-md"
            :hint="ownerChanged && (editing || labelChanged) ? t('skills.personal.transferHint') : undefined" />
          <q-banner v-if="mutationError" role="alert" class="q-mb-md">{{ mutationError }}</q-banner>
          <div v-if="selected?.learning" class="q-mb-md">
            <PersonalSkillStatus :skill="selected" />
            <p class="q-mt-sm">{{ t('skills.learning.summary', { count: selected.learning.evidence_count, score: Math.round(selected.learning.score * 100) }) }}</p>
            <q-expansion-item v-if="learningEvidence.length" icon="history" :label="t('skills.learning.evidence')">
              <q-list bordered separator>
                <q-item v-for="item in learningEvidence" :key="item.id">
                  <q-item-section>
                    <q-item-label>{{ t(item.polarity === 'positive' ? 'skills.learning.positive' : 'skills.learning.negative') }}</q-item-label>
                    <q-item-label>{{ item.rationale }}</q-item-label>
                    <q-item-label caption>{{ item.source_ref }} · {{ formatDate(item.created_at) }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-expansion-item>
          </div>
          <template v-if="selected && canEdit">
            <q-input v-model="labelDraft" outlined class="q-mb-md" :label="t('skills.label')" :readonly="saving" maxlength="255" />
          </template>
          <q-banner v-if="detailError" role="alert" class="q-mb-md">
            {{ t('skills.error') }}
            <template #action><q-btn outline color="primary" :label="t('skills.personal.retry')" @click="retryDetail" /></template>
          </q-banner>
          <q-select v-model="filePath" :options="files.map(file => file.path)" outlined dense
            :label="t('skills.selectFile')" :disable="editing || saving" class="q-mb-md" />
          <div v-if="detailLoading" class="row justify-center q-pa-lg"><q-spinner color="primary" size="32px" /></div>
          <template v-else-if="content !== null">
            <template v-if="editing && isTextFile">
              <CodeEditor v-model="draft" :language="editorLanguage" :label="t('skills.source')" :readonly="saving" :visible-lines="20" />
            </template>
            <template v-else>
              <Markdown v-if="filePath.endsWith('.md')" :content="content" compact-frontmatter />
              <pre v-else class="personal-source">{{ content }}</pre>
            </template>
          </template>
        </q-card-section>
        <q-card-actions v-if="canEdit" align="right" class="no-wrap">
          <template v-if="editing || labelChanged">
            <q-btn outline color="primary" :label="t('skills.cancel')" :disable="saving" @click="cancelEditing" />
            <q-btn color="primary" :label="t('skills.save')" :loading="saving" :disable="!labelDraft.trim() || detailLoading" @click="saveChanges" />
            <q-btn v-if="!editing" outline color="primary" icon="edit" :label="t('skills.edit')"
              :disable="saving || detailLoading || detailError || content === null" @click="beginEditing" />
          </template>
          <template v-else-if="selected">
            <q-btn v-if="ownerChanged" outline color="primary" :label="t('skills.cancel')" :disable="saving" @click="cancelEditing" />
            <q-btn color="primary" icon="edit" :label="t('skills.edit')" :disable="saving || detailLoading || detailError || content === null" @click="beginEditing" />
            <template v-if="!ownerChanged">
            <q-btn :flat="$q.screen.lt.md" :outline="!$q.screen.lt.md" :dense="$q.screen.lt.md" color="primary"
              :icon="selected.enabled ? 'pause' : 'play_arrow'"
              :label="$q.screen.lt.md ? undefined : t(selected.enabled ? 'skills.personal.disable' : 'skills.personal.enable')"
              :aria-label="t(selected.enabled ? 'skills.personal.disable' : 'skills.personal.enable')" :disable="saving" @click="toggleEnabled">
              <q-tooltip>{{ t(selected.enabled ? 'skills.personal.disable' : 'skills.personal.enable') }}</q-tooltip>
            </q-btn>
            <q-btn v-if="canRelease" :flat="$q.screen.lt.md" :outline="!$q.screen.lt.md" :dense="$q.screen.lt.md" color="primary" icon="publish"
              :label="$q.screen.lt.md ? undefined : t('skills.personal.release')" :aria-label="t('skills.personal.release')"
              :disable="saving" @click="prepareConfirmation('release')"><q-tooltip>{{ t('skills.personal.release') }}</q-tooltip></q-btn>
            <q-btn :flat="$q.screen.lt.md" :dense="$q.screen.lt.md" color="negative" icon="delete"
              :label="$q.screen.lt.md ? undefined : t('skills.delete')" :aria-label="t('skills.delete')"
              :disable="saving" @click="prepareConfirmation('delete')"><q-tooltip>{{ t('skills.delete') }}</q-tooltip></q-btn>
            </template>
          </template>
          <q-btn v-if="ownerChanged" :flat="$q.screen.lt.md" color="primary" icon="swap_horiz"
            :label="$q.screen.lt.md ? undefined : t('skills.personal.transfer')" :aria-label="t('skills.personal.transfer')"
            :disable="saving || editing || labelChanged || detailLoading" @click="prepareConfirmation('transfer')">
            <q-tooltip>{{ t('skills.personal.transfer') }}</q-tooltip>
          </q-btn>
        </q-card-actions>
      </q-card>
    </q-dialog>
    <q-dialog v-model="confirmationOpen">
      <q-card class="galaris-dialog-card">
        <q-toolbar class="galaris-dialog-title bg-primary text-white">
          <q-toolbar-title>{{ t(confirmationTitle) }}</q-toolbar-title>
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('skills.cancel')" />
        </q-toolbar>
        <q-card-section class="galaris-dialog-body">
          <p>{{ t(confirmationMessage, { label: selected?.label, owner: ownerOptions.find(option => option.value === ownerDraft)?.label ?? '' }) }}</p>
          <q-input v-if="action !== 'delete'" v-model="newCode" outlined :label="t('skills.code')" :disable="saving" />
          <q-banner v-if="mutationError" role="alert">{{ mutationError }}</q-banner>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline color="primary" :label="t('skills.cancel')" :disable="saving" />
          <q-btn :color="action === 'delete' ? 'negative' : 'primary'" :label="t(confirmationTitle)" :loading="saving" :disable="action !== 'delete' && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(newCode)" @click="confirmMutation" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QTableProps } from 'quasar'
import { AgentSelect, getAgentSelection } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { apiErrorDetail } from '@/core/api'
import { ActionContextMenu, CodeEditor, Markdown, type ContextAction } from '@/core/util'
import { languageForSkillFile } from '../fileLanguage'
import PersonalSkillStatus from './PersonalSkillStatus.vue'
import { skillService, type PersonalSkill, type SkillAgent, type SkillFile, type SkillLearningEvidence } from '../services/skillService'

const { active } = defineProps<{ active: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { t, locale } = useI18n()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.SKILL_EDIT))
const canRelease = computed(() => canEdit.value && privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL))
const ownerId = ref<number | null>(null)
const search = ref<string | null>('')
const rows = ref<PersonalSkill[]>([])
const learningEvidence = ref<SkillLearningEvidence[]>([])
const agents = ref<SkillAgent[]>([])
const ownerOptions = ref<{ value: number; label: string; hasAvatar: boolean }[]>([])
const ownerDraft = ref<number | null>(null)
const agentOptions = computed(() => agents.value.map(agent => ({ value: agent.id, label: agent.label })))
const loading = ref(false)
const error = ref(false)
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
let generation = 0
const columns = computed<QTableProps['columns']>(() => [
  { name: 'label', label: t('skills.label'), field: 'label', align: 'left', style: 'width: 22%', headerStyle: 'width: 22%' },
  { name: 'description', label: t('skills.description'), field: 'description', align: 'left' },
  { name: 'owner', label: t('skills.personal.owner'), field: 'owner_label', align: 'left', style: 'width: 18%', headerStyle: 'width: 18%' },
  { name: 'status', label: t('skills.status'), field: 'enabled', align: 'left', style: 'width: 120px', headerStyle: 'width: 120px' },
  { name: 'files', label: t('skills.files'), field: 'file_count', align: 'right', style: 'width: 72px', headerStyle: 'width: 72px' },
  { name: 'actions', label: t('skills.actions'), field: 'id', align: 'right', style: 'width: 80px', headerStyle: 'width: 80px' },
])
function formatDate(value: string): string { return new Date(value).toLocaleString(locale.value) }
function rowClasses(row: PersonalSkill): string {
  return `cursor-pointer personal-row--${row.enabled ? 'enabled' : 'disabled'}`
}
async function reload(): Promise<void> {
  const request = ++generation
  rows.value = []
  loading.value = true
  error.value = false
  try {
    const [catalogue, owners, selection] = await Promise.all([
      skillService.getPersonalSkills({ owner_agent_id: ownerId.value, search: search.value || '',
        page: pagination.value.page, page_size: pagination.value.rowsPerPage }),
      skillService.getAgents(),
      canEdit.value ? getAgentSelection('management') : Promise.resolve([]),
    ])
    if (request !== generation) return
    rows.value = catalogue.data.items
    pagination.value.rowsNumber = catalogue.data.total
    agents.value = owners.data
    ownerOptions.value = selection.map(agent => ({ value: agent.id, label: agent.label, hasAvatar: agent.has_avatar }))
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
const isTextFile = computed(() => files.value.find(file => file.path === filePath.value)?.text === true)
const editorLanguage = computed(() => languageForSkillFile(filePath.value))
const detailLoading = ref(false)
const detailError = ref(false)
const editing = ref(false), saving = ref(false), mutationError = ref(''), draft = ref(''), labelDraft = ref('')
const labelChanged = computed(() => selected.value !== null && labelDraft.value !== selected.value.label)
const ownerChanged = computed(() => selected.value !== null && ownerDraft.value !== null && ownerDraft.value !== selected.value.owner_agent_id)
const confirmationOpen = ref(false), action = ref<'delete' | 'release' | 'transfer'>('delete'), newCode = ref('')
const confirmationTitle = computed(() => action.value === 'delete' ? 'skills.delete' : `skills.personal.${action.value}`)
const confirmationMessage = computed(() => action.value === 'delete' ? 'skills.deleteConfirm' : `skills.personal.${action.value}Confirm`)
let releaseOperation: { code: string; id: string } | null = null
let detailGeneration = 0
let editOnLoad = false
function rowActions(row: PersonalSkill): ContextAction[] {
  return [
    { key: 'view', label: t('skills.view'), icon: 'visibility', run: () => openDetail(row) },
    ...(canEdit.value ? [
      { key: 'edit', label: t('skills.edit'), icon: 'edit', disabled: saving.value, run: () => openDetail(row, true) },
      { key: 'enabled', label: t(row.enabled ? 'skills.personal.disable' : 'skills.personal.enable'),
        icon: row.enabled ? 'pause' : 'play_arrow', disabled: saving.value, run: () => toggleRow(row) },
      ...(canRelease.value ? [{ key: 'release', label: t('skills.personal.release'), icon: 'publish',
        disabled: saving.value, run: () => confirmRow(row, 'release') }] : []),
      { key: 'delete', label: t('skills.delete'), icon: 'delete', negative: true, separator: true,
        disabled: saving.value, run: () => confirmRow(row, 'delete') },
    ] : []),
  ]
}
async function toggleRow(row: PersonalSkill): Promise<void> {
  if (saving.value || !canEdit.value) return
  saving.value = true
  try {
    await skillService.setPersonalSkillEnabled(row.id, !row.enabled, row.revision)
    await reload()
  } finally { saving.value = false }
}
function confirmRow(row: PersonalSkill, operation: 'delete' | 'release'): void {
  if (!canEdit.value || saving.value || (operation === 'release' && !canRelease.value)) return
  closeDetail()
  selected.value = row
  prepareConfirmation(operation)
}
async function openDetail(row: PersonalSkill, edit = false): Promise<void> {
  closeDetail()
  editOnLoad = edit
  selected.value = row
  labelDraft.value = row.label
  ownerDraft.value = row.owner_agent_id
  detailOpen.value = true
  const request = ++detailGeneration
  detailLoading.value = true
  try {
    const response = await skillService.getPersonalSkill(row.id)
    if (request !== detailGeneration) return
    selected.value = response.data.skill
    learningEvidence.value = response.data.learning_evidences ?? []
    ownerDraft.value = response.data.skill.owner_agent_id
    if (labelDraft.value === row.label) labelDraft.value = response.data.skill.label
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
    detailLoading.value = false
    if (editOnLoad) { editOnLoad = false; beginEditing() }
    return
  }
  detailLoading.value = true
  try {
    const response = await skillService.getPersonalSkillContent(selected.value.id, filePath.value)
    if (request === detailGeneration) {
      content.value = response.data.content
    }
  } catch {
    if (request === detailGeneration) detailError.value = true
  } finally {
    if (request === detailGeneration) {
      detailLoading.value = false
      if (editOnLoad && content.value !== null) { editOnLoad = false; beginEditing() }
    }
  }
}
function retryDetail(): void {
  if (!files.value.length && selected.value) void openDetail(selected.value, editOnLoad)
  else void readContent()
}
function closeDetail(): void {
  ++detailGeneration
  editOnLoad = false
  selected.value = null
  learningEvidence.value = []
  ownerDraft.value = null
  files.value = []
  filePath.value = ''
  content.value = null
  detailError.value = false
  detailLoading.value = false
  editing.value = false
  mutationError.value = ''
  confirmationOpen.value = false
}
async function mutate(operation: (row: PersonalSkill) => Promise<void>): Promise<void> {
  const row = selected.value
  if (!row || saving.value || !canEdit.value) return
  const generation = detailGeneration
  saving.value = true; mutationError.value = ''
  try { await operation(row) }
  catch (reason) {
    if (generation === detailGeneration) mutationError.value = apiErrorDetail(reason) ?? t('skills.error')
  } finally { saving.value = false }
}
function beginEditing(): void {
  if (!selected.value || saving.value || detailLoading.value || content.value === null) return
  draft.value = content.value ?? ''
  editing.value = true
}
function cancelEditing(): void {
  labelDraft.value = selected.value?.label ?? ''
  ownerDraft.value = selected.value?.owner_agent_id ?? null
  draft.value = content.value ?? ''
  editing.value = false
  mutationError.value = ''
}
async function saveChanges(): Promise<void> {
  const path = filePath.value, text = draft.value, label = labelDraft.value.trim(), generation = detailGeneration
  if (!label) return
  await mutate(async row => {
    const textFile = editing.value && isTextFile.value
    const response = textFile
      ? await skillService.writePersonalSkill(row.id, path, text, row.revision, label)
      : await skillService.renamePersonalSkill(row.id, label, row.revision)
    if (generation !== detailGeneration) return
    row.revision = response.data.revision; row.label = label
    labelDraft.value = label
    if (textFile) content.value = text
    editing.value = false
    await reload()
  })
}
async function toggleEnabled(): Promise<void> {
  const generation = detailGeneration
  await mutate(async row => {
    const response = await skillService.setPersonalSkillEnabled(row.id, !row.enabled, row.revision)
    if (generation !== detailGeneration) return
    row.enabled = !row.enabled; row.revision = response.data.revision; await reload()
  })
}
function prepareConfirmation(value: 'delete' | 'release' | 'transfer'): void {
  action.value = value; newCode.value = selected.value?.code ?? ''; releaseOperation = null
  mutationError.value = ''; confirmationOpen.value = true
}
async function confirmMutation(): Promise<void> {
  const generation = detailGeneration
  const operation = action.value, code = newCode.value
  await mutate(async row => {
    if (operation === 'delete') await skillService.deletePersonalSkill(row.id, row.revision)
    else {
      if (operation === 'release' && !canRelease.value) return
      if (operation === 'transfer' && (ownerDraft.value === null || editing.value || labelChanged.value)) return
      if (!releaseOperation || releaseOperation.code !== code) releaseOperation = { code, id: crypto.randomUUID() }
      const result = operation === 'transfer'
        ? await skillService.transferPersonalSkill(row.id, ownerDraft.value!, row.revision, releaseOperation.id, code)
        : await skillService.releasePersonalSkill(row.id, row.revision, releaseOperation.id, code)
      if (result.data.cleanup_pending) {
        if (generation === detailGeneration) mutationError.value = t('skills.personal.cleanupPending')
        return
      }
    }
    if (generation !== detailGeneration) return
    detailOpen.value = false; closeDetail(); emit('changed'); await reload()
  })
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
.personal-code { overflow-wrap: anywhere; }
.personal-description { white-space: normal; }
.personal-meta { font-size: 0.75rem; line-height: 1.5; overflow-wrap: anywhere; }
.personal-mobile-card, .personal-mobile-heading { min-width: 0; }
.personal-mobile-card--disabled { background: var(--solaire-gray-light); color: var(--solaire-gray-accent); }
.personal-mobile-status { flex: 0 1 auto; max-width: 48%; }
.personal-skills-table { --personal-inactive-background: var(--solaire-gray-light); }
:deep(.personal-skills-table .q-table) { table-layout: fixed; width: 100%; }
:deep(.personal-skills-table .q-table th), :deep(.personal-skills-table .q-table td) {
  padding: 12px; white-space: normal; overflow-wrap: anywhere; vertical-align: top;
}
:deep(.personal-skills-table .personal-row--disabled td) { background: var(--personal-inactive-background); color: var(--solaire-gray-accent); }
:deep(.personal-skills-table .q-table__grid-content) { width: 100%; margin: 0; }
:deep(.personal-skills-table .q-table__grid-item) { min-width: 0; max-width: 100%; padding: 8px 0; }
.body--dark .personal-mobile-card--disabled { background: var(--solaire-gray-dark); }
.body--dark .personal-skills-table { --personal-inactive-background: var(--solaire-gray-dark); }
</style>
