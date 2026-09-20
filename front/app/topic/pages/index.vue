<template>
  <q-page class="q-pa-md">
    <PageHeader help-key="topics" :help-text="$t('contextHelpPages.topics')" :icon="navigationIcon('folder_copy')" :title="t('nav.topics')" :description="t('nav.topics_desc')">
      <template #title-after>
        <div class="topic-controls">
          <q-select
            :model-value="selectedMonth"
            :options="monthOptions"
            emit-value
            map-options
            dense
            outlined
            options-dense
            :label="t('topic.month')"
            class="topic-month-select"
            popup-content-class="topic-month-menu"
            @update:model-value="onMonthChange"
          >
            <template #prepend><q-icon name="calendar_month" /></template>
          </q-select>
          <q-btn
            round
            flat
            color="primary"
            icon="refresh"
            :loading="loading"
            :aria-label="t('topic.refresh')"
            @click="load"
          >
            <q-tooltip>{{ t('topic.refresh') }}</q-tooltip>
          </q-btn>
        </div>
      </template>
    </PageHeader>

    <div class="text-body2 text-grey-7 q-mb-lg">
      {{ t('topic.subtitle') }}
    </div>

    <q-banner v-if="error" rounded class="bg-red-1 text-negative q-mb-md">
      <template #avatar><q-icon name="error_outline" /></template>
      {{ error }}
    </q-banner>

    <q-card flat bordered class="topic-card">
      <q-card-section>
        <div class="row q-col-gutter-sm items-center">
          <div class="col-12 col-sm">
            <q-input
              v-model="search"
              outlined
              dense
              clearable
              debounce="300"
              :placeholder="t('topic.search')"
              @update:model-value="reloadFromStart"
            >
              <template #prepend><q-icon name="search" /></template>
            </q-input>
          </div>
          <div v-if="canEdit" class="col-12 col-sm-auto">
            <q-btn color="primary" icon="create_new_folder" :label="t('topic.create')" @click="openCreate" />
          </div>
        </div>
      </q-card-section>

      <q-table
        v-model:pagination="pagination"
        flat
        wrap-cells
        class="topic-table"
        :grid="$q.screen.lt.md"
        row-key="id"
        :rows="topics"
        :columns="columns"
        :loading="loading"
        :rows-per-page-options="[10, 20, 50, 100, 500]"
        :no-data-label="t('topic.noRows')"
        @request="onRequest"
      >
        <template #body-cell-title="props">
          <q-td :props="props">
            <div class="topic-title-cell row items-start no-wrap q-gutter-sm">
              <q-icon name="folder" color="primary" size="sm" />
              <div class="topic-title-copy">
                <router-link
                  :to="`/topic/${encodeURIComponent(props.row.id)}`"
                  class="text-weight-medium topic-title-link"
                >
                  {{ props.row.title }}
                </router-link>
                <div class="text-caption text-grey-7 topic-description">
                  {{ props.row.description }}
                </div>
              </div>
            </div>
          </q-td>
        </template>

        <template #body-cell-keywords="props">
          <q-td :props="props">
            <div v-if="props.row.keywords.length" class="topic-keywords row q-gutter-xs">
              <q-chip
                v-for="keyword in props.row.keywords"
                :key="keyword"
                dense
                color="blue-grey-1"
                text-color="blue-grey-9"
              >
                {{ keyword }}
              </q-chip>
            </div>
            <span v-else class="text-grey-6">{{ t('topic.noKeywords') }}</span>
          </q-td>
        </template>

        <template #body-cell-relations="props">
          <q-td :props="props">
            <TopicParticipants :topic="props.row" />
          </q-td>
        </template>

        <template #body-cell-activity="props">
          <q-td :props="props">
            <div class="topic-activity">
              <div v-if="props.row.memory_item_id" class="topic-activity-row text-positive">
                <q-icon name="public" size="xs" />
                <span>{{ t('topic.publicMemory') }}</span>
              </div>
              <div class="topic-activity-row">
                <q-icon name="payments" size="xs" color="amber-9" />
                <span class="topic-cost">{{ formatCurrency(props.row.inference_cost) }}</span>
                <q-tooltip>
                  {{ t('topic.inferenceCostHelp', { count: props.row.llm_calls }) }}
                </q-tooltip>
              </div>
              <div class="topic-activity-row text-grey-7">
                <q-icon name="schedule" size="xs" />
                <span>{{ formatDate(props.row.updated_at || props.row.created_at) }}</span>
              </div>
            </div>
          </q-td>
        </template>

        <template #body-cell-actions="props">
          <q-td :props="props" class="topic-actions-cell" @click.stop>
            <div v-if="canEdit" class="topic-actions">
              <q-btn flat round dense icon="edit" :aria-label="t('topic.edit')" @click="openEdit(props.row)">
                <q-tooltip>{{ t('topic.edit') }}</q-tooltip>
              </q-btn>
              <q-btn flat round dense icon="merge" :aria-label="t('topic.merge')" @click="openMerge(props.row)">
                <q-tooltip>{{ t('topic.merge') }}</q-tooltip>
              </q-btn>
              <q-btn flat round dense icon="call_split" :aria-label="t('topic.split')" @click="openSplit(props.row)">
                <q-tooltip>{{ t('topic.split') }}</q-tooltip>
              </q-btn>
              <q-btn flat round dense color="negative" icon="delete" :aria-label="t('topic.delete')" @click="openDelete(props.row)">
                <q-tooltip>{{ t('topic.delete') }}</q-tooltip>
              </q-btn>
            </div>
          </q-td>
        </template>

        <template #item="props">
          <div class="q-table__grid-item col-12">
            <q-card flat bordered class="topic-mobile-card">
              <q-card-section class="q-gutter-md">
                <div class="topic-title-cell row items-start no-wrap q-gutter-sm">
                  <q-icon name="folder" color="primary" size="sm" />
                  <div class="topic-title-copy">
                    <div class="text-weight-medium text-subtitle1">{{ props.row.title }}</div>
                    <div class="text-body2 text-grey-7 topic-description">
                      {{ props.row.description }}
                    </div>
                  </div>
                </div>

                <div>
                  <div class="topic-mobile-label">{{ t('topic.keywords') }}</div>
                  <div v-if="props.row.keywords.length" class="topic-keywords row q-gutter-xs">
                    <q-chip
                      v-for="keyword in props.row.keywords"
                      :key="keyword"
                      dense
                      color="blue-grey-1"
                      text-color="blue-grey-9"
                    >
                      {{ keyword }}
                    </q-chip>
                  </div>
                  <span v-else class="text-grey-6">{{ t('topic.noKeywords') }}</span>
                </div>

                <div>
                  <div class="topic-mobile-label">{{ t('topic.relations') }}</div>
                  <TopicParticipants :topic="props.row" />
                </div>

                <div class="row items-end justify-between q-gutter-md">
                  <div>
                    <div class="topic-mobile-label">{{ t('topic.activity') }}</div>
                    <div class="topic-activity">
                      <div v-if="props.row.memory_item_id" class="topic-activity-row text-positive">
                        <q-icon name="public" size="xs" />
                        <span>{{ t('topic.publicMemory') }}</span>
                      </div>
                      <div class="topic-activity-row">
                        <q-icon name="payments" size="xs" color="amber-9" />
                        <span class="topic-cost">{{ formatCurrency(props.row.inference_cost) }}</span>
                        <q-tooltip>{{ t('topic.inferenceCostHelp', { count: props.row.llm_calls }) }}</q-tooltip>
                      </div>
                      <div class="topic-activity-row text-grey-7">
                        <q-icon name="schedule" size="xs" />
                        <span>{{ formatDate(props.row.updated_at || props.row.created_at) }}</span>
                      </div>
                    </div>
                  </div>
                  <div v-if="canEdit" class="topic-actions">
                    <q-btn flat round dense icon="edit" :aria-label="t('topic.edit')" @click="openEdit(props.row)">
                      <q-tooltip>{{ t('topic.edit') }}</q-tooltip>
                    </q-btn>
                    <q-btn flat round dense icon="merge" :aria-label="t('topic.merge')" @click="openMerge(props.row)">
                      <q-tooltip>{{ t('topic.merge') }}</q-tooltip>
                    </q-btn>
                    <q-btn flat round dense icon="call_split" :aria-label="t('topic.split')" @click="openSplit(props.row)">
                      <q-tooltip>{{ t('topic.split') }}</q-tooltip>
                    </q-btn>
                    <q-btn flat round dense color="negative" icon="delete" :aria-label="t('topic.delete')" @click="openDelete(props.row)">
                      <q-tooltip>{{ t('topic.delete') }}</q-tooltip>
                    </q-btn>
                  </div>
                </div>
              </q-card-section>
            </q-card>
          </div>
        </template>
      </q-table>
    </q-card>

    <q-dialog v-model="formDialog">
      <q-card class="topic-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ editingTopic ? t('topic.editTitle') : t('topic.createTitle') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('topic.cancel')" />
        </q-card-section>
        <q-form @submit.prevent="saveTopic">
          <q-card-section class="q-gutter-md">
            <q-input v-model="topicForm.title" outlined autofocus :label="t('topic.title')" :rules="[requiredRule]" />
            <q-input v-model="topicForm.description" outlined type="textarea" autogrow :label="t('topic.description')" />
            <q-select
              v-model="topicForm.keywords"
              outlined
              multiple
              use-input
              use-chips
              input-debounce="0"
              :options="filteredKeywordOptions"
              :max-values="20"
              :loading="loadingKeywordOptions"
              :label="t('topic.keywords')"
              :hint="t('topic.keywordsHelp')"
              @filter="filterKeywordOptions"
              @new-value="addKeyword"
            >
              <template #no-option>
                <q-item>
                  <q-item-section class="text-grey-7">{{ t('topic.keywordsEmpty') }}</q-item-section>
                </q-item>
              </template>
            </q-select>
          </q-card-section>
          <q-separator />
          <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
            <q-btn v-close-popup flat :label="t('topic.cancel')" />
            <q-btn color="primary" type="submit" icon="save" :label="t('topic.save')" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="mergeDialog">
      <q-card class="topic-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('topic.mergeTitle', { title: activeTopic?.title || '' }) }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('topic.cancel')" />
        </q-card-section>
        <q-card-section class="q-gutter-md">
          <q-banner rounded class="bg-blue-1 text-primary">{{ t('topic.mergeHelp') }}</q-banner>
          <TopicSelect
            v-if="mergeDialog"
            v-model="mergeTargetId"
            allow-create
            outlined
            :exclude-ids="activeTopic ? [activeTopic.id] : []"
            :label="t('topic.mergeTarget')"
            :disable="saving"
          />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn v-close-popup flat :label="t('topic.cancel')" />
          <q-btn color="primary" icon="merge" :label="t('topic.confirm')" :disable="!mergeTargetId" :loading="saving" @click="confirmMerge" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="splitDialog">
      <q-card class="topic-split-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('topic.splitTitle', { title: activeTopic?.title || '' }) }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('topic.cancel')" />
        </q-card-section>
        <q-card-section>
          <q-banner rounded class="bg-blue-1 text-primary">{{ t('topic.splitHelp') }}</q-banner>
          <q-card flat bordered class="topic-split-editor q-mt-md">
            <q-card-section>
              <div class="row q-col-gutter-md">
                <div class="col-12 col-md-6"><q-input v-model="splitForm.title" outlined :label="t('topic.title')" :rules="[requiredRule]" /></div>
                <div class="col-12"><q-input v-model="splitForm.description" outlined type="textarea" autogrow :label="t('topic.description')" /></div>
                <div class="col-12">
                  <q-select
                    v-model="splitForm.keywords"
                    outlined
                    multiple
                    use-input
                    use-chips
                    input-debounce="0"
                    :options="filteredKeywordOptions"
                    :max-values="20"
                    :loading="loadingKeywordOptions"
                    :label="t('topic.keywords')"
                    :hint="t('topic.keywordsHelp')"
                    @filter="filterKeywordOptions"
                    @new-value="addKeyword"
                  >
                    <template #no-option>
                      <q-item>
                        <q-item-section class="text-grey-7">{{ t('topic.keywordsEmpty') }}</q-item-section>
                      </q-item>
                    </template>
                  </q-select>
                </div>
              </div>
            </q-card-section>
            <q-separator />
            <q-card-section class="q-py-sm">
              <div class="text-subtitle2">{{ t('topic.splitSelection') }}</div>
            </q-card-section>
            <q-separator />
            <q-table
              v-model:selected="selectedMemories"
              flat
              wrap-cells
              class="topic-table topic-split-memory-table"
              selection="multiple"
              row-key="id"
              :rows="linkedMemories"
              :columns="memoryColumns"
              :loading="loadingMemories"
              :rows-per-page-options="[10, 20, 50, 100, 500]"
              v-model:pagination="splitPagination"
              :no-data-label="t('topic.splitEmpty')"
            >
              <template #body-cell-owner="props">
                <q-td :props="props">{{ props.row.owner_agent_id ?? t('topic.globalMemory') }}</q-td>
              </template>
            </q-table>
          </q-card>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn v-close-popup flat :label="t('topic.cancel')" />
          <q-btn color="primary" icon="call_split" :label="t('topic.confirm')" :disable="!canSubmitSplit" :loading="saving" @click="confirmSplit" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="deleteDialog">
      <q-card class="topic-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('topic.deleteTitle', { title: activeTopic?.title || '' }) }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('topic.cancel')" />
        </q-card-section>
        <q-card-section>{{ t('topic.deleteHelp') }}</q-card-section>
        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn v-close-popup flat :label="t('topic.cancel')" />
          <q-btn color="negative" icon="delete" :label="t('topic.delete')" :loading="saving" @click="confirmDelete" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTableColumn, type QTableProps } from 'quasar'
import { privileges } from '@/core/authorize'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'
import { PageHeader } from '@/core/util'
import { topicService } from '../services/topicService'
import TopicParticipants from '../components/TopicParticipants.vue'
import TopicSelect from '../components/TopicSelect.vue'
import type { Topic, TopicInput, TopicLinkedMemory, TopicMonthlyUsage } from '../types'

type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]

const { t, locale } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => (
  privilegeStore.hasPrivilege(privileges.TOPIC_EDIT)
  && privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL)
))
const topics = ref<TopicMonthlyUsage[]>([])
const search = ref('')
const loading = ref(false)
const error = ref('')
const selectedMonth = ref(currentMonth())
const availableMonths = ref<string[]>([selectedMonth.value])
const pagination = ref({ page: 1, rowsPerPage: 50, rowsNumber: 0 })
const saving = ref(false)
const activeTopic = ref<Topic | null>(null)
const editingTopic = ref<Topic | null>(null)
const formDialog = ref(false)
const mergeDialog = ref(false)
const splitDialog = ref(false)
const deleteDialog = ref(false)
const mergeTargetId = ref<string | null>(null)
const linkedMemories = ref<TopicLinkedMemory[]>([])
const selectedMemories = ref<TopicLinkedMemory[]>([])
const loadingMemories = ref(false)
const splitPagination = ref({ page: 1, rowsPerPage: 50 })

interface TopicFormState {
  title: string
  description: string
  keywords: string[]
}

type NewKeywordDone = (
  value?: string,
  mode?: 'add' | 'add-unique' | 'toggle',
) => void

const emptyForm = (): TopicFormState => ({ title: '', description: '', keywords: [] })
const topicForm = reactive<TopicFormState>(emptyForm())
const splitForm = reactive<TopicFormState>(emptyForm())
const keywordOptions = ref<string[]>([])
const filteredKeywordOptions = ref<string[]>([])
const loadingKeywordOptions = ref(false)
let loadRequestId = 0

function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

const monthOptions = computed(() => availableMonths.value.map(month => ({
  value: month,
  label: formatMonth(month),
})))

const columns = computed<QTableColumn<TopicMonthlyUsage>[]>(() => [
  { name: 'title', label: t('topic.title'), field: 'title', align: 'left', style: 'width: 27%', headerStyle: 'width: 27%' },
  { name: 'keywords', label: t('topic.keywords'), field: 'keywords', align: 'left', classes: 'gt-md', headerClasses: 'gt-md' },
  { name: 'relations', label: t('topic.relations'), field: row => row.agents.length + row.users.length + row.teams.length, align: 'left', style: 'width: 30%', headerStyle: 'width: 30%' },
  { name: 'activity', label: t('topic.activity'), field: 'inference_cost', align: 'left', style: 'width: 13rem', headerStyle: 'width: 13rem' },
  { name: 'actions', label: '', field: 'id', align: 'right', style: 'width: 9rem', headerStyle: 'width: 9rem' },
])

const memoryColumns = computed<QTableColumn<TopicLinkedMemory>[]>(() => [
  { name: 'title', label: t('topic.title'), field: 'title', align: 'left' },
  { name: 'excerpt', label: t('topic.memoryExcerpt'), field: 'excerpt', align: 'left' },
  { name: 'memoryType', label: t('topic.memoryType'), field: 'memory_type', align: 'left', classes: 'gt-sm', headerClasses: 'gt-sm' },
  { name: 'owner', label: t('topic.owner'), field: 'owner_agent_id', align: 'left', classes: 'gt-sm', headerClasses: 'gt-sm' },
])

const canSubmitSplit = computed(() => (
  splitForm.title.trim().length > 0 && selectedMemories.value.length > 0
))

const requiredRule = (value: string): true | string => Boolean(value.trim()) || t('topic.required')

async function load(): Promise<void> {
  const requestId = ++loadRequestId
  const month = selectedMonth.value
  loading.value = true
  error.value = ''
  try {
    const page = await topicService.list({
      skip: (pagination.value.page - 1) * pagination.value.rowsPerPage,
      limit: pagination.value.rowsPerPage,
      search: search.value,
      month,
    })
    if (requestId !== loadRequestId) return
    topics.value = page.items
    pagination.value.rowsNumber = page.total
    selectedMonth.value = page.month
    availableMonths.value = page.available_months
  } catch {
    if (requestId !== loadRequestId) return
    topics.value = []
    pagination.value.rowsNumber = 0
    error.value = t('topic.loadError')
  } finally {
    if (requestId === loadRequestId) loading.value = false
  }
}

function onRequest(request: TableRequest): void {
  pagination.value = {
    page: request.pagination.page,
    rowsPerPage: request.pagination.rowsPerPage,
    rowsNumber: pagination.value.rowsNumber,
  }
  void load()
}

function reloadFromStart(): void {
  pagination.value.page = 1
  void load()
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function formatMonth(month: string): string {
  const [year = 0, monthNumber = 1] = month.split('-').map(Number)
  return new Intl.DateTimeFormat(locale.value, {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, monthNumber - 1, 1)))
}

function formatCurrency(value: number): string {
  return Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: 2,
    maximumFractionDigits: value < 1 ? 4 : 2,
  }).format(value)
}

function onMonthChange(month: string | null): void {
  if (!month || month === selectedMonth.value) return
  selectedMonth.value = month
  pagination.value.page = 1
  void load()
}

function assignForm(target: TopicFormState, topic: Topic | null = null): void {
  Object.assign(target, topic ? {
    title: topic.title,
    description: topic.description,
    keywords: [...topic.keywords],
  } : emptyForm())
}

function payload(form: TopicFormState): TopicInput {
  return {
    title: form.title.trim(),
    description: form.description.trim(),
    keywords: [...new Set(
      form.keywords.map(value => value.trim().slice(0, 80)).filter(Boolean),
    )].slice(0, 20),
  }
}

async function loadKeywordOptions(): Promise<void> {
  loadingKeywordOptions.value = true
  try {
    keywordOptions.value = await topicService.listKeywords()
    filteredKeywordOptions.value = keywordOptions.value
  } catch {
    const fallback = topics.value.flatMap(topic => topic.keywords)
    keywordOptions.value = [...new Set(fallback)].sort((left, right) => (
      left.localeCompare(right, locale.value)
    ))
    filteredKeywordOptions.value = keywordOptions.value
  } finally {
    loadingKeywordOptions.value = false
  }
}

function filterKeywordOptions(
  value: string,
  update: (callback: () => void) => void,
): void {
  update(() => {
    const needle = value.trim().toLocaleLowerCase(locale.value)
    filteredKeywordOptions.value = needle
      ? keywordOptions.value.filter(option => (
        option.toLocaleLowerCase(locale.value).includes(needle)
      ))
      : keywordOptions.value
  })
}

function addKeyword(value: string, done: NewKeywordDone): void {
  const normalized = value.trim().slice(0, 80)
  done(normalized || undefined, normalized ? 'add-unique' : undefined)
}

function notifyError(key = 'topic.operationError'): void {
  $q.notify({ type: 'negative', message: t(key) })
}

function openCreate(): void {
  editingTopic.value = null
  assignForm(topicForm)
  formDialog.value = true
  void loadKeywordOptions()
}

function openEdit(topic: Topic): void {
  editingTopic.value = topic
  assignForm(topicForm, topic)
  formDialog.value = true
  void loadKeywordOptions()
}

async function saveTopic(): Promise<void> {
  if (!topicForm.title.trim()) return
  saving.value = true
  try {
    if (editingTopic.value) {
      await topicService.update(editingTopic.value, payload(topicForm))
      $q.notify({ type: 'positive', message: t('topic.updateSuccess') })
    } else {
      await topicService.create(payload(topicForm))
      $q.notify({ type: 'positive', message: t('topic.createSuccess') })
    }
    formDialog.value = false
    await load()
  } catch {
    notifyError()
  } finally {
    saving.value = false
  }
}

function openMerge(topic: Topic): void {
  activeTopic.value = topic
  mergeTargetId.value = null
  mergeDialog.value = true
}

async function confirmMerge(): Promise<void> {
  if (!activeTopic.value || !mergeTargetId.value) return
  saving.value = true
  try {
    const result = await topicService.merge(activeTopic.value.id, mergeTargetId.value)
    $q.notify({ type: 'positive', message: t('topic.mergeSuccess', { links: result.moved_memory_links }) })
    mergeDialog.value = false
    await load()
  } catch {
    notifyError()
  } finally {
    saving.value = false
  }
}

async function openSplit(topic: Topic): Promise<void> {
  activeTopic.value = topic
  assignForm(splitForm)
  linkedMemories.value = []
  selectedMemories.value = []
  splitPagination.value = { page: 1, rowsPerPage: 50 }
  splitDialog.value = true
  void loadKeywordOptions()
  loadingMemories.value = true
  try {
    linkedMemories.value = await topicService.linkedMemories(topic.id)
  } catch {
    notifyError('topic.linkedMemoriesError')
  } finally {
    loadingMemories.value = false
  }
}

async function confirmSplit(): Promise<void> {
  if (!activeTopic.value || !canSubmitSplit.value) return
  saving.value = true
  try {
    const result = await topicService.split(activeTopic.value.id, {
      ...payload(splitForm),
      memory_item_ids: selectedMemories.value.map(memory => memory.id),
    })
    $q.notify({ type: 'positive', message: t('topic.splitSuccess', { links: result.moved_memory_links }) })
    splitDialog.value = false
    await load()
  } catch {
    notifyError()
  } finally {
    saving.value = false
  }
}

function openDelete(topic: Topic): void {
  activeTopic.value = topic
  deleteDialog.value = true
}

async function confirmDelete(): Promise<void> {
  if (!activeTopic.value) return
  saving.value = true
  try {
    await topicService.remove(activeTopic.value.id)
    $q.notify({ type: 'positive', message: t('topic.deleteSuccess') })
    deleteDialog.value = false
    await load()
  } catch {
    notifyError()
  } finally {
    saving.value = false
  }
}

onMounted(() => void load())
</script>

<style scoped>
.topic-card {
  width: 100%;
  min-width: 0;
  overflow: hidden;
}

.topic-title-link {
  color: inherit;
  text-decoration: none;
}

.topic-title-link:hover,
.topic-title-link:focus-visible {
  color: var(--q-primary);
  text-decoration: underline;
}

.topic-controls {
  display: flex;
  flex: 0 0 auto;
  gap: 8px;
  align-items: center;
}

.topic-month-select {
  width: 210px;
}

.topic-month-select :deep(.q-field__control) {
  border-radius: 10px;
}

.topic-cost {
  color: #97640e;
  font-weight: 750;
  font-variant-numeric: tabular-nums;
}

.topic-activity {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.topic-activity-row {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
  white-space: nowrap;
}

.topic-table {
  width: 100%;
  min-width: 0;
}

.topic-table :deep(.q-table__middle) {
  overflow-x: hidden;
}

.topic-table :deep(.q-table) {
  width: 100%;
  table-layout: fixed;
}

.topic-table :deep(th),
.topic-table :deep(td) {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

.topic-table :deep(.q-table__bottom) {
  flex-wrap: wrap;
  row-gap: 0.5rem;
}

.topic-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.topic-table :deep(.q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
  padding: 8px 16px;
}

.topic-mobile-card {
  width: 100%;
  min-width: 0;
}

.topic-mobile-label {
  display: block;
  margin-bottom: 4px;
  color: #757575;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.topic-title-cell,
.topic-title-copy {
  min-width: 0;
}

.topic-description {
  white-space: normal;
}

.topic-keywords {
  min-width: 0;
}

.topic-keywords :deep(.q-chip) {
  max-width: 100%;
}

.topic-actions {
  display: flex;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 0.125rem;
  min-width: max-content;
  white-space: nowrap;
}

.topic-actions-cell {
  padding-right: 0.5rem;
  white-space: nowrap !important;
}

.topic-dialog-card {
  width: min(42rem, 92vw);
}

.topic-split-card {
  width: min(72rem, 96vw);
  max-width: 96vw;
}

.topic-split-editor {
  overflow: hidden;
}

.topic-split-memory-table {
  border-radius: 0;
}

@media (max-width: 599px) {
  .topic-actions {
    flex-wrap: wrap;
  }

  .topic-table :deep(.q-table__grid-item) {
    padding-right: 8px;
    padding-left: 8px;
  }
}
</style>
