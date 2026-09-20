<template>
  <q-page class="q-pa-md">
    <PageHeader help-key="skills" :help-text="$t('contextHelpPages.skills')" :icon="navigationIcon('psychology')" :title="t('nav.skills')" :description="t('nav.skills_desc')" />

    <q-tabs
      v-model="tab"
      align="left"
      class="text-primary"
      active-color="primary"
      indicator-color="primary"
    >
      <q-tab name="skills" icon="psychology" :label="t('skills.tabSkills')" />
      <q-tab
        v-if="learningEnabled"
        name="learned"
        icon="school"
        :label="t('skills.tabLearned')"
      />
      <q-tab
        v-if="canAssign"
        name="authorizations"
        icon="shield"
        :label="t('skills.tabAuthorizations')"
      />
    </q-tabs>
    <q-separator />

    <q-tab-panels v-model="tab" animated keep-alive class="bg-transparent">
      <q-tab-panel name="skills" class="q-px-none">
    <div class="row justify-end q-gutter-sm q-mb-md">
      <q-btn
        v-if="canEdit"
        outline
        color="primary"
        icon="category"
        :label="t('skills.categories.manage')"
        @click="categoryManagerDialog = true"
      />
      <q-btn
        v-if="canEdit"
        outline
        color="primary"
        icon="refresh"
        :label="t('skills.rescan')"
        :loading="store.loading"
        @click="rescan"
      />
      <q-btn
        v-if="canEdit"
        outline
        color="primary"
        icon="upload_file"
        :label="t('skills.import')"
        @click="openImport"
      />
      <q-btn
        v-if="canEdit"
        color="primary"
        icon="add"
        :label="t('skills.create')"
        @click="openCreate"
      />
    </div>

    <div class="row q-col-gutter-md q-mb-md">
      <div class="col-12 col-md-8">
        <q-input v-model="search" outlined dense clearable :label="t('skills.search')">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
      <div class="col-12 col-md-4">
        <q-select
          v-model="filterCategoryId"
          :options="filterCategoryOptions"
          outlined
          dense
          clearable
          emit-value
          map-options
          :label="t('skills.categories.filter')"
        />
      </div>
    </div>

    <div v-if="store.loading && groupedSkills.length === 0" class="row justify-center q-pa-xl">
      <q-spinner color="primary" size="42px" />
    </div>
    <div v-else-if="groupedSkills.length > 0">
      <section v-for="group in groupedSkills" :key="group.key" class="q-mb-lg">
        <div class="row items-center q-gutter-sm q-mb-sm skill-category-heading">
          <q-icon name="category" color="primary" size="sm" />
          <div class="text-h6">{{ group.label }}</div>
          <q-badge color="primary" :label="group.skills.length" />
        </div>
        <q-table
          :rows="group.skills"
          :columns="columns"
          :grid="$q.screen.lt.md"
          row-key="id"
          :loading="store.loading"
          :pagination="defaultPagination"
          :rows-per-page-options="[10, 20, 50, 100, 500]"
          class="skills-table"
          flat
          bordered
        >
      <template #body-cell-label="props">
        <q-td :props="props">
          <div class="row items-center q-gutter-xs">
            <span class="text-weight-medium">{{ props.row.label }}</span>
            <q-chip
              v-if="props.row.system"
              dense
              square
              color="blue-1"
              text-color="primary"
              icon="verified_user"
            >
              {{ t('skills.system') }}
            </q-chip>
          </div>
          <code class="text-caption text-grey-7">{{ props.row.code }}</code>
        </q-td>
      </template>
      <template #body-cell-description="props">
        <q-td :props="props">
          <span class="skill-description">{{ props.row.description || '—' }}</span>
        </q-td>
      </template>
      <template #body-cell-status="props">
        <q-td :props="props">
          <q-chip
            dense
            :color="statusColor(props.row)"
            text-color="white"
            :icon="props.row.valid ? 'check_circle' : 'warning'"
          >
            {{ statusLabel(props.row) }}
            <q-tooltip v-if="props.row.validation_error">{{ props.row.validation_error }}</q-tooltip>
          </q-chip>
        </q-td>
      </template>
      <template #body-cell-files="props">
        <q-td :props="props">
          {{ props.row.file_count }} · {{ formatSize(props.row.total_size) }}
        </q-td>
      </template>
      <template #body-cell-actions="props">
        <q-td :props="props" class="skill-actions-cell">
          <div class="skill-actions">
          <q-btn flat round color="primary" icon="visibility" size="sm" @click="openViewer(props.row)">
            <q-tooltip>{{ t('skills.view') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="canEdit && !props.row.system" flat round color="primary" icon="edit" size="sm" @click="openEdit(props.row)">
            <q-tooltip>{{ t('skills.edit') }}</q-tooltip>
          </q-btn>
          <q-btn
            v-if="canEdit"
            flat
            round
            color="primary"
            icon="drive_file_move"
            size="sm"
            :loading="assigningSkillId === props.row.id"
          >
            <q-tooltip>{{ t('skills.categories.assign') }}</q-tooltip>
            <q-menu>
              <q-list dense style="min-width: 220px">
                <q-item
                  clickable
                  v-close-popup
                  :active="props.row.category_id === null"
                  @click="onCategoryChange(props.row, null)"
                >
                  <q-item-section avatar>
                    <q-icon :name="props.row.category_id === null ? 'check' : 'folder_off'" />
                  </q-item-section>
                  <q-item-section>{{ t('skills.categories.none') }}</q-item-section>
                </q-item>
                <q-item
                  v-for="category in store.categories"
                  :key="category.id"
                  clickable
                  v-close-popup
                  :active="props.row.category_id === category.id"
                  @click="onCategoryChange(props.row, category.id)"
                >
                  <q-item-section avatar>
                    <q-icon :name="props.row.category_id === category.id ? 'check' : 'folder'" />
                  </q-item-section>
                  <q-item-section>{{ category.label }}</q-item-section>
                </q-item>
              </q-list>
            </q-menu>
          </q-btn>
          <q-btn flat round color="primary" icon="download" size="sm" @click="downloadSkill(props.row)">
            <q-tooltip>{{ t('skills.download') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="canEdit && !props.row.system" flat round color="negative" icon="delete" size="sm" @click="confirmDelete(props.row)">
            <q-tooltip>{{ t('skills.delete') }}</q-tooltip>
          </q-btn>
          </div>
        </q-td>
      </template>
      <template #item="props">
        <div class="q-table__grid-item col-12">
          <q-card flat bordered class="skill-mobile-card">
            <q-card-section class="q-gutter-md">
              <div class="row items-start no-wrap q-gutter-sm">
                <div class="col skill-mobile-heading">
                  <div class="row items-center q-gutter-xs">
                    <span class="text-weight-medium text-subtitle1">{{ props.row.label }}</span>
                    <q-chip
                      v-if="props.row.system"
                      dense
                      square
                      color="blue-1"
                      text-color="primary"
                      icon="verified_user"
                    >
                      {{ t('skills.system') }}
                    </q-chip>
                  </div>
                  <code class="text-caption text-grey-7 skill-mobile-code">{{ props.row.code }}</code>
                </div>
                <q-chip
                  dense
                  :color="statusColor(props.row)"
                  text-color="white"
                  :icon="props.row.valid ? 'check_circle' : 'warning'"
                >
                  {{ statusLabel(props.row) }}
                  <q-tooltip v-if="props.row.validation_error">{{ props.row.validation_error }}</q-tooltip>
                </q-chip>
              </div>

              <div>
                <div class="skill-mobile-label">{{ t('skills.description') }}</div>
                <div class="skill-description">{{ props.row.description || '—' }}</div>
              </div>

              <div class="row items-center justify-between q-gutter-sm">
                <div>
                  <div class="skill-mobile-label">{{ t('skills.files') }}</div>
                  <div>{{ props.row.file_count }} · {{ formatSize(props.row.total_size) }}</div>
                </div>
                <div class="skill-mobile-actions">
                  <q-btn flat round color="primary" icon="visibility" size="sm" :aria-label="t('skills.view')" @click="openViewer(props.row)">
                    <q-tooltip>{{ t('skills.view') }}</q-tooltip>
                  </q-btn>
                  <q-btn v-if="canEdit && !props.row.system" flat round color="primary" icon="edit" size="sm" :aria-label="t('skills.edit')" @click="openEdit(props.row)">
                    <q-tooltip>{{ t('skills.edit') }}</q-tooltip>
                  </q-btn>
                  <q-btn
                    v-if="canEdit"
                    flat
                    round
                    color="primary"
                    icon="drive_file_move"
                    size="sm"
                    :loading="assigningSkillId === props.row.id"
                    :aria-label="t('skills.categories.assign')"
                  >
                    <q-tooltip>{{ t('skills.categories.assign') }}</q-tooltip>
                    <q-menu>
                      <q-list dense style="min-width: 220px">
                        <q-item
                          clickable
                          v-close-popup
                          :active="props.row.category_id === null"
                          @click="onCategoryChange(props.row, null)"
                        >
                          <q-item-section avatar>
                            <q-icon :name="props.row.category_id === null ? 'check' : 'folder_off'" />
                          </q-item-section>
                          <q-item-section>{{ t('skills.categories.none') }}</q-item-section>
                        </q-item>
                        <q-item
                          v-for="category in store.categories"
                          :key="category.id"
                          clickable
                          v-close-popup
                          :active="props.row.category_id === category.id"
                          @click="onCategoryChange(props.row, category.id)"
                        >
                          <q-item-section avatar>
                            <q-icon :name="props.row.category_id === category.id ? 'check' : 'folder'" />
                          </q-item-section>
                          <q-item-section>{{ category.label }}</q-item-section>
                        </q-item>
                      </q-list>
                    </q-menu>
                  </q-btn>
                  <q-btn flat round color="primary" icon="download" size="sm" :aria-label="t('skills.download')" @click="downloadSkill(props.row)">
                    <q-tooltip>{{ t('skills.download') }}</q-tooltip>
                  </q-btn>
                  <q-btn v-if="canEdit && !props.row.system" flat round color="negative" icon="delete" size="sm" :aria-label="t('skills.delete')" @click="confirmDelete(props.row)">
                    <q-tooltip>{{ t('skills.delete') }}</q-tooltip>
                  </q-btn>
                </div>
              </div>
            </q-card-section>
          </q-card>
        </div>
      </template>
        </q-table>
      </section>
    </div>
    <div v-else class="text-center text-grey-7 q-pa-xl">
      {{ t('skills.empty') }}
    </div>
      </q-tab-panel>

      <q-tab-panel v-if="canAssign" name="authorizations" class="q-px-none">
        <SkillAuthorizationManager />
      </q-tab-panel>
      <q-tab-panel v-if="learningEnabled" name="learned" class="q-px-none">
        <LearnedSkillManager />
      </q-tab-panel>
    </q-tab-panels>

    <!-- Markdown creation and editing. -->
    <q-dialog v-model="editorDialog">
      <q-card class="column no-wrap skill-editor-dialog">
        <q-toolbar class="galaris-dialog-title bg-primary text-white">
          <q-toolbar-title>
            {{ editingSkill ? t('skills.editTitle', { label: editingSkill.label }) : t('skills.createTitle') }}
          </q-toolbar-title>
          <q-btn
            v-close-popup
            flat
            round
            dense
            icon="close"
            :aria-label="t('skills.cancel')"
          />
        </q-toolbar>
        <q-card-section class="row q-col-gutter-md skill-editor-fields">
          <div class="col-12 col-md-4">
            <q-input
              v-model="editorForm.code"
              outlined
              dense
              hide-bottom-space
              :readonly="editingSkill !== null"
              :label="t('skills.code')"
              :rules="[requiredRule, codeRule]"
            />
          </div>
          <div class="col-12 col-md-4">
            <q-input
              v-model="editorForm.label"
              outlined
              dense
              hide-bottom-space
              :label="t('skills.label')"
              :rules="[requiredRule]"
            />
          </div>
          <div class="col-12 col-md-4">
            <q-select
              v-model="editorForm.category_id"
              :options="categoryOptions"
              outlined
              dense
              clearable
              emit-value
              map-options
              :label="t('skills.categories.category')"
            />
          </div>
        </q-card-section>
        <q-tabs
          v-model="editorTab"
          dense
          inline-label
          class="text-primary"
          align="left"
        >
          <q-tab name="source" icon="code" :label="t('skills.source')" />
          <q-tab name="preview" icon="visibility" :label="t('skills.preview')" />
        </q-tabs>
        <q-separator />
        <q-tab-panels v-model="editorTab" animated class="col scroll">
          <q-tab-panel name="source">
            <CodeEditor v-model="editorForm.markdown" language="markdown" :visible-lines="30" />
          </q-tab-panel>
          <q-tab-panel name="preview">
            <Markdown :content="editorForm.markdown" compact-frontmatter />
          </q-tab-panel>
        </q-tab-panels>
        <q-separator />
        <q-card-actions align="right" class="q-px-md q-py-sm galaris-dialog-actions">
          <q-btn flat :label="t('skills.cancel')" v-close-popup />
          <q-btn
            v-if="canEdit"
            color="primary"
            icon="save"
            :label="t('skills.save')"
            :loading="store.loading"
            @click="saveEditor"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Full package viewer. -->
    <q-dialog v-model="viewerDialog" maximized transition-show="slide-up" transition-hide="slide-down">
      <q-card class="column no-wrap">
        <q-toolbar class="galaris-dialog-title bg-primary text-white">
          <q-toolbar-title>{{ t('skills.viewTitle', { label: store.currentSkill?.label || '' }) }}</q-toolbar-title>
          <q-btn flat icon="download" :label="t('skills.download')" @click="store.currentSkill && downloadSkill(store.currentSkill)" />
          <q-btn
            flat
            round
            dense
            icon="close"
            v-close-popup
            :aria-label="t('skills.cancel')"
          />
        </q-toolbar>
        <q-splitter v-model="splitter" class="col">
          <template #before>
            <q-scroll-area class="fit q-pa-sm">
              <q-tree
                :nodes="fileTree"
                node-key="key"
                label-key="label"
                v-model:selected="selectedTreeKey"
                default-expand-all
                no-transition
                @update:selected="onTreeSelect"
              />
            </q-scroll-area>
          </template>
          <template #after>
            <q-inner-loading :showing="store.contentLoading" />
            <div v-if="selectedFile" class="column fit">
              <q-toolbar class="bg-grey-2">
                <q-icon :name="selectedFile.text ? 'description' : 'data_object'" class="q-mr-sm" />
                <q-toolbar-title class="text-subtitle1">{{ selectedFile.path }}</q-toolbar-title>
                <span class="text-caption text-grey-7 q-mr-md">{{ formatSize(selectedFile.size) }}</span>
                <q-btn flat round icon="download" @click="downloadSelectedFile">
                  <q-tooltip>{{ t('skills.download') }}</q-tooltip>
                </q-btn>
              </q-toolbar>
              <q-separator />
              <template v-if="selectedFile.text">
                <q-tabs v-if="isMarkdown" v-model="viewerTab" dense align="left" class="text-primary">
                  <q-tab name="preview" :label="t('skills.preview')" icon="visibility" />
                  <q-tab name="source" :label="t('skills.source')" icon="code" />
                </q-tabs>
                <q-tab-panels v-if="isMarkdown" v-model="viewerTab" class="col scroll">
                  <q-tab-panel name="preview"><Markdown :content="store.currentContent" compact-frontmatter /></q-tab-panel>
                  <q-tab-panel name="source">
                    <CodeEditor :model-value="store.currentContent" language="markdown" readonly :visible-lines="30" />
                  </q-tab-panel>
                </q-tab-panels>
                <div v-else class="q-pa-md col scroll">
                  <CodeEditor :model-value="store.currentContent" :language="selectedLanguage" readonly :visible-lines="30" />
                </div>
              </template>
              <div v-else class="col row flex-center text-grey-7 q-gutter-sm">
                <q-icon name="draft" size="3em" />
                <span>{{ t('skills.binaryFile') }}</span>
              </div>
            </div>
            <div v-else class="fit row flex-center text-grey-7">{{ t('skills.noFile') }}</div>
          </template>
        </q-splitter>
      </q-card>
    </q-dialog>

    <!-- ZIP / Markdown drag and drop import. -->
    <q-dialog v-model="importDialog" @hide="resetImport">
      <q-card class="column no-wrap" style="width: 680px; max-width: 95vw; max-height: 90vh">
        <q-toolbar class="galaris-dialog-title bg-primary text-white">
          <q-toolbar-title>{{ t('skills.importTitle') }}</q-toolbar-title>
          <q-btn
            v-close-popup
            flat
            round
            dense
            icon="close"
            :aria-label="t('skills.cancel')"
          />
        </q-toolbar>
        <q-card-section class="import-dialog-content">
          <div
            class="drop-zone column flex-center text-center"
            :class="importFiles.length ? 'q-pa-md' : 'q-pa-xl'"
            tabindex="0"
            role="button"
            @click="fileInput?.click()"
            @keydown.enter="fileInput?.click()"
            @dragover.prevent
            @drop.prevent="onDrop"
          >
            <q-icon name="archive" :size="importFiles.length ? '2.5em' : '4em'" color="primary" />
            <div :class="importFiles.length ? 'text-subtitle1 q-mt-xs' : 'text-h6 q-mt-md'">
              {{ t('skills.dropTitle') }}
            </div>
            <div v-if="!importFiles.length" class="text-body2 text-grey-7">
              {{ t('skills.dropHint') }}
            </div>
            <q-btn flat color="primary" class="q-mt-sm" :label="t('skills.selectFiles')" />
            <q-list
              v-if="importFiles.length"
              bordered
              separator
              class="selected-files-list rounded-borders q-mt-sm bg-white text-left"
              @click.stop
              @keydown.stop
            >
              <q-item-label header class="text-primary">
                {{ t('skills.selectedFiles', { count: importFiles.length }) }}
              </q-item-label>
              <q-item v-for="(file, index) in importFiles" :key="importFileKey(file, index)" dense>
                <q-item-section avatar>
                  <q-icon :name="file.name.toLowerCase().endsWith('.zip') ? 'archive' : 'description'" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ file.name }}</q-item-label>
                  <q-item-label caption>{{ formatSize(file.size) }}</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-btn
                    flat
                    round
                    icon="close"
                    :disable="importing"
                    :aria-label="t('skills.removeSelectedFile', { name: file.name })"
                    @click.stop="removeImportFile(index)"
                  />
                </q-item-section>
              </q-item>
            </q-list>
            <input
              ref="fileInput"
              type="file"
              accept=".zip,.md,.markdown"
              multiple
              hidden
              @change="onFileInput"
            />
          </div>
          <div v-if="importFiles.length === 1" class="import-field-grid">
            <q-input
              v-model="importOptions.code"
              outlined
              :disable="importing"
              :label="t('skills.optionalCode')"
            />
            <q-input
              v-model="importOptions.label"
              outlined
              :disable="importing"
              :label="t('skills.optionalLabel')"
            />
          </div>
          <q-banner v-else-if="importFiles.length > 1" dense rounded class="bg-blue-1 text-primary">
            {{ t('skills.batchMetadataHint') }}
          </q-banner>
          <q-select
            v-model="importOptions.category_id"
            :options="categoryOptions"
            outlined
            clearable
            emit-value
            map-options
            :disable="importing"
            :label="t('skills.categories.category')"
          />
          <q-toggle
            v-model="importOptions.overwrite"
            :disable="importing"
            :label="t('skills.overwrite')"
          />
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="t('skills.cancel')" v-close-popup />
          <q-btn
            v-if="canEdit"
            color="primary"
            icon="upload"
            :label="t('skills.import')"
            :disable="!importFiles.length"
            :loading="importing"
            @click="submitImport"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <SkillCategoryManager v-model="categoryManagerDialog" />

  </q-page>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, onMounted, reactive, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { isAxiosError } from 'axios'
import type { QTableProps } from 'quasar'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { privileges } from '@/core/authorize'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'
import { PageHeader, formatFileSize } from '@/core/util'
import CodeEditor from '@/core/util/components/CodeEditor.vue'
import Markdown from '@/core/util/components/Markdown.vue'
import SkillAuthorizationManager from '../components/SkillAuthorizationManager.vue'
import SkillCategoryManager from '../components/SkillCategoryManager.vue'
import LearnedSkillManager from '../components/LearnedSkillManager.vue'
import { skillService, type Skill, type SkillFile } from '../services/skillService'
import { useSkillStore } from '../stores/skillStore'

type CodeLanguage = 'json' | 'yaml' | 'xml' | 'markdown' | 'text' | 'javascript' | 'typescript' | 'python' | 'sql' | 'html' | 'css'
interface FileTreeNode {
  key: string
  label: string
  icon: string
  selectable?: boolean
  children?: FileTreeNode[]
}
interface SkillGroup {
  key: string
  label: string
  skills: Skill[]
}

const $q = useQuasar()
const { t, locale } = useI18n()
const route = useRoute()
const store = useSkillStore()
const privilegeStore = usePrivilegeStore()
const fileInput = useTemplateRef<HTMLInputElement>('fileInput')

const canEdit = computed(() => (
  privilegeStore.hasPrivilege(privileges.SKILL_EDIT)
  && privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL)
))
const canAssign = computed(() => privilegeStore.hasPrivilege(privileges.SKILL_ASSIGN))
const learningEnabled = ref(false)
const allowedTabs = ['skills', 'learned', 'authorizations']
const tab = ref(
  typeof route.query.tab === 'string' && allowedTabs.includes(route.query.tab)
    ? route.query.tab
    : 'skills'
)

watch(canAssign, allowed => {
  if (!allowed && tab.value === 'authorizations') tab.value = 'skills'
}, { immediate: true })

async function loadLearningStatus(): Promise<void> {
  const response = await skillService.getLearnedSkillStatus()
  learningEnabled.value = response.data.enabled
  if (!learningEnabled.value && tab.value === 'learned') tab.value = 'skills'
}

const search = ref('')
const filterCategoryId = ref<number | 'uncategorized' | null>(null)
const defaultPagination = { page: 1, rowsPerPage: 50 }
const categoryManagerDialog = ref(false)
const assigningSkillId = ref<number | null>(null)
const editorDialog = ref(false)
const editingSkill = ref<Skill | null>(null)
const editorOriginalMarkdown = ref('')
const editorTab = ref<'source' | 'preview'>('source')
const editorForm = reactive({ code: '', label: '', markdown: '', category_id: null as number | null })
const viewerDialog = ref(false)
const viewerTab = ref<'preview' | 'source'>('preview')
const splitter = ref(27)
const selectedTreeKey = ref<string | null>(null)
const importDialog = ref(false)
const importFiles = shallowRef<File[]>([])
const importing = ref(false)
const importOptions = reactive({
  code: '',
  label: '',
  overwrite: false,
  category_id: null as number | null,
})

const categoryOptions = computed(() =>
  store.categories.map(category => ({ label: category.label, value: category.id }))
)
const filterCategoryOptions = computed(() => [
  { label: t('skills.categories.none'), value: 'uncategorized' as const },
  ...categoryOptions.value,
])

const filteredSkills = computed(() => {
  const query = search.value.trim().toLowerCase()
  return store.skills.filter(skill => {
    if (filterCategoryId.value === 'uncategorized' && skill.category_id !== null) return false
    if (typeof filterCategoryId.value === 'number' && skill.category_id !== filterCategoryId.value) return false
    if (!query) return true
    return [skill.code, skill.label, skill.description || '', skill.category_label || '']
      .some(value => value.toLowerCase().includes(query))
  })
})

const groupedSkills = computed<SkillGroup[]>(() => {
  const skillsByCategory = new Map<number | null, Skill[]>()
  for (const skill of filteredSkills.value) {
    const skills = skillsByCategory.get(skill.category_id) ?? []
    skills.push(skill)
    skillsByCategory.set(skill.category_id, skills)
  }

  const groups = store.categories.flatMap(category => {
    const skills = skillsByCategory.get(category.id)
    if (!skills?.length) return []
    skillsByCategory.delete(category.id)
    return [{ key: `category-${category.id}`, label: category.label, skills }]
  })

  for (const [categoryId, skills] of skillsByCategory) {
    if (categoryId === null) continue
    groups.push({
      key: `category-${categoryId}`,
      label: skills[0]?.category_label || t('skills.categories.none'),
      skills,
    })
  }

  const uncategorized = skillsByCategory.get(null)
  if (uncategorized?.length) {
    groups.push({
      key: 'uncategorized',
      label: t('skills.categories.none'),
      skills: uncategorized,
    })
  }
  return groups
})

const columns = computed<QTableProps['columns']>(() => [
  {
    name: 'label',
    label: t('skills.label'),
    field: 'label',
    align: 'left',
    sortable: true,
    style: 'vertical-align: top; width: 220px;',
    headerStyle: 'width: 220px;',
  },
  {
    name: 'description',
    label: t('skills.description'),
    field: 'description',
    align: 'left',
    style: 'white-space: normal; overflow-wrap: anywhere; vertical-align: top;',
  },
  {
    name: 'status',
    label: t('skills.status'),
    field: 'valid',
    align: 'center',
    sortable: true,
    style: 'vertical-align: top; width: 130px;',
    headerStyle: 'width: 130px;',
  },
  {
    name: 'files',
    label: t('skills.files'),
    field: 'file_count',
    align: 'right',
    sortable: true,
    style: 'vertical-align: top; width: 140px;',
    headerStyle: 'width: 140px;',
  },
  {
    name: 'actions',
    label: t('skills.actions'),
    field: 'actions',
    align: 'right',
    style: 'vertical-align: top; width: 200px; min-width: 200px;',
    headerStyle: 'width: 200px; min-width: 200px;',
  },
])

const selectedFile = computed(() =>
  store.currentFiles.find(file => file.path === selectedTreeKey.value) || null
)
const isMarkdown = computed(() => selectedFile.value?.path.toLowerCase().endsWith('.md') ?? false)
const selectedLanguage = computed<CodeLanguage>(() => languageFor(selectedFile.value?.path || ''))
const fileTree = computed<FileTreeNode[]>(() => buildFileTree(store.currentFiles))

watch(() => editorForm.code, (code, previous) => {
  if (editingSkill.value) return
  const oldName = previous || 'new-skill'
  const newName = code || 'new-skill'
  editorForm.markdown = editorForm.markdown.replace(
    new RegExp(`^name:\\s*${escapeRegExp(oldName)}\\s*$`, 'm'),
    `name: ${newName}`,
  )
})

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function statusColor(skill: Skill): string {
  if (!skill.available) return 'grey-7'
  return skill.valid ? 'positive' : 'negative'
}

function statusLabel(skill: Skill): string {
  if (!skill.available) return t('skills.missing')
  return skill.valid ? t('skills.valid') : t('skills.invalid')
}

async function onCategoryChange(skill: Skill, categoryId: number | null): Promise<void> {
  if (skill.category_id === categoryId) return
  assigningSkillId.value = skill.id
  try {
    const { synchronized } = await store.assignCategory(skill.id, categoryId)
    $q.notify({ type: 'positive', message: t('skills.categories.assigned') })
    if (!synchronized) {
      $q.notify({ type: 'warning', message: t('skills.auth.syncError') })
    }
  } catch (error) {
    console.error('Error assigning skill category:', error)
    notifyError(error)
  } finally {
    assigningSkillId.value = null
  }
}

function formatSize(bytes: number): string {
  return formatFileSize(bytes, locale.value)
}

function requiredRule(value: string): true | string {
  return Boolean(value?.trim()) || t('skills.required')
}

function codeRule(value: string): true | string {
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) || t('skills.invalidCode')
}

function errorText(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map(item => {
          if (!item || typeof item !== 'object') return null
          const message = 'message' in item ? item.message : 'msg' in item ? item.msg : null
          return typeof message === 'string' ? message : null
        })
        .filter((message): message is string => Boolean(message))
      if (messages.length) return messages.join('\n')
    }
  }
  return t('skills.error')
}

function notifyError(error: unknown): void {
  $q.notify({ type: 'negative', message: errorText(error) })
}

function defaultMarkdown(): string {
  return '---\nname: new-skill\ndescription: Décrivez brièvement ce que fait cette compétence.\n---\n\n# Nouvelle compétence\n\n## Quand utiliser cette compétence\n\nDécrivez les situations pertinentes.\n\n## Procédure\n\n1. Première étape.\n'
}

function openCreate(): void {
  editingSkill.value = null
  editorOriginalMarkdown.value = ''
  Object.assign(editorForm, {
    code: '',
    label: '',
    markdown: defaultMarkdown(),
    category_id: null,
  })
  editorTab.value = 'source'
  editorDialog.value = true
}

async function openEdit(skill: Skill): Promise<void> {
  try {
    editingSkill.value = skill
    await store.openSkill(skill)
    editorOriginalMarkdown.value = store.currentContent
    Object.assign(editorForm, {
      code: skill.code,
      label: skill.label,
      markdown: store.currentContent,
      category_id: skill.category_id,
    })
    editorTab.value = 'source'
    editorDialog.value = true
  } catch (error) {
    notifyError(error)
  }
}

async function saveEditor(): Promise<void> {
  if (
    requiredRule(editorForm.code) !== true
    || codeRule(editorForm.code) !== true
    || requiredRule(editorForm.label) !== true
  ) return
  try {
    if (editingSkill.value) {
      const markdownChanged = editorForm.markdown !== editorOriginalMarkdown.value
      await store.updateSkill(editingSkill.value.id, {
        label: editorForm.label,
        ...(markdownChanged ? { markdown: editorForm.markdown } : {}),
      })
      if (editorForm.category_id !== editingSkill.value.category_id) {
        await store.assignCategory(editingSkill.value.id, editorForm.category_id)
      }
      $q.notify({ type: 'positive', message: t('skills.updated') })
      if (markdownChanged) {
        const synchronized = await store.syncExternalAgents()
        if (!synchronized) {
          $q.notify({ type: 'warning', message: t('skills.auth.syncError') })
        }
      }
    } else {
      await store.createSkill({ ...editorForm })
      await store.fetchCategories()
      $q.notify({ type: 'positive', message: t('skills.created') })
    }
    editorDialog.value = false
  } catch (error) {
    notifyError(error)
  }
}

async function openViewer(skill: Skill): Promise<void> {
  try {
    await store.openSkill(skill)
    selectedTreeKey.value = store.currentPath
    viewerTab.value = 'preview'
    viewerDialog.value = true
  } catch (error) {
    notifyError(error)
  }
}

async function onTreeSelect(key: string | null): Promise<void> {
  if (!key) return
  const file = store.currentFiles.find(item => item.path === key)
  if (!file) return
  try {
    await store.openFile(file)
    viewerTab.value = file.path.toLowerCase().endsWith('.md') ? 'preview' : 'source'
  } catch (error) {
    notifyError(error)
  }
}

function buildFileTree(files: SkillFile[]): FileTreeNode[] {
  const roots: FileTreeNode[] = []
  for (const file of files) {
    const parts = file.path.split('/')
    let children = roots
    let currentPath = ''
    parts.forEach((part, index) => {
      currentPath = currentPath ? `${currentPath}/${part}` : part
      const isFile = index === parts.length - 1
      let node = children.find(item => item.key === currentPath)
      if (!node) {
        node = {
          key: currentPath,
          label: part,
          icon: isFile ? (file.text ? 'description' : 'draft') : 'folder',
          selectable: isFile,
          ...(isFile ? {} : { children: [] }),
        }
        children.push(node)
      }
      if (!isFile) children = node.children || []
    })
  }
  return roots
}

function languageFor(path: string): CodeLanguage {
  const extension = path.split('.').pop()?.toLowerCase()
  const languages: Record<string, CodeLanguage> = {
    json: 'json', yaml: 'yaml', yml: 'yaml', xml: 'xml', md: 'markdown',
    js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
    py: 'python', sql: 'sql', html: 'html', css: 'css',
  }
  return extension ? languages[extension] || 'text' : 'text'
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

async function downloadSkill(skill: Skill): Promise<void> {
  try {
    saveBlob((await skillService.downloadSkill(skill.id)).data, `${skill.code}.zip`)
  } catch (error) {
    notifyError(error)
  }
}

async function downloadSelectedFile(): Promise<void> {
  if (!store.currentSkill || !selectedFile.value) return
  try {
    const response = await skillService.downloadFile(store.currentSkill.id, selectedFile.value.path)
    saveBlob(response.data, selectedFile.value.name)
  } catch (error) {
    notifyError(error)
  }
}

function openImport(): void {
  resetImport()
  importDialog.value = true
}

function resetImport(): void {
  importFiles.value = []
  Object.assign(importOptions, { code: '', label: '', overwrite: false, category_id: null })
  if (fileInput.value) fileInput.value.value = ''
}

function acceptFiles(files: Iterable<File>): void {
  const selected = Array.from(files)
  const accepted = selected.filter(file => /\.(zip|md|markdown)$/i.test(file.name))
  if (accepted.length !== selected.length) {
    $q.notify({ type: 'warning', message: t('skills.dropTitle') })
  }
  importFiles.value = accepted
  if (accepted.length !== 1) {
    importOptions.code = ''
    importOptions.label = ''
  }
}

function onDrop(event: DragEvent): void {
  acceptFiles(event.dataTransfer?.files ?? [])
}

function onFileInput(event: Event): void {
  const input = event.target as HTMLInputElement
  acceptFiles(input.files ?? [])
  input.value = ''
}

function importFileKey(file: File, index: number): string {
  return `${file.name}-${file.size}-${file.lastModified}-${index}`
}

function removeImportFile(index: number): void {
  importFiles.value = importFiles.value.filter((_, fileIndex) => fileIndex !== index)
  if (importFiles.value.length !== 1) {
    importOptions.code = ''
    importOptions.label = ''
  }
}

async function submitImport(): Promise<void> {
  if (!importFiles.value.length || importing.value) return
  const files = [...importFiles.value]
  const singleFile = files.length === 1
  const options = {
    code: singleFile ? importOptions.code : undefined,
    label: singleFile ? importOptions.label : undefined,
    overwrite: importOptions.overwrite,
    categoryId: importOptions.category_id,
  }
  const imported: Array<{ file: File; result: Awaited<ReturnType<typeof store.importSkill>> }> = []
  const failures: Array<{ file: File; error: unknown }> = []
  importing.value = true
  try {
    for (const file of files) {
      try {
        const result = await store.importSkill(file, options)
        imported.push({ file, result })
      } catch (error) {
        failures.push({ file, error })
      }
    }

    let categoryFailures = 0
    let synchronizationFailed = false
    if (options.categoryId !== null) {
      for (const { result } of imported) {
        try {
          const assignment = await store.assignCategory(result.skill.id, options.categoryId)
          synchronizationFailed ||= !assignment.synchronized
        } catch (error) {
          categoryFailures += 1
          console.error('Error assigning category after skill import:', error)
        }
      }
    }

    if (failures.length) {
      importFiles.value = failures.map(({ file }) => file)
      $q.notify({
        type: imported.length ? 'warning' : 'negative',
        message: t('skills.importResult', {
          imported: imported.length,
          failed: failures.length,
        }),
        caption: failures.map(({ file, error }) => `${file.name}: ${errorText(error)}`).join('\n'),
        multiLine: true,
      })
    } else {
      importDialog.value = false
      $q.notify({
        type: 'positive',
        message: imported.length === 1
          ? t('skills.imported')
          : t('skills.importedMany', { count: imported.length }),
      })
    }

    if (categoryFailures) {
      $q.notify({
        type: 'warning',
        message: t('skills.importCategoryFailed', { count: categoryFailures }),
      })
    }
    if (synchronizationFailed) {
      $q.notify({ type: 'warning', message: t('skills.auth.syncError') })
    }
  } finally {
    importing.value = false
  }
}

async function rescan(): Promise<void> {
  try {
    const result = await store.rescan()
    $q.notify({
      type: result.invalid_directories.length ? 'warning' : 'positive',
      message: t('skills.scanResult', {
        created: result.created,
        restored: result.restored,
        invalid: result.invalid_directories.length,
      }),
    })
  } catch (error) {
    notifyError(error)
  }
}

function confirmDelete(skill: Skill): void {
  showConfirmationDialog({
    title: t('skills.delete'),
    message: t('skills.deleteConfirm', { label: skill.label }),
    cancel: t('skills.cancel'),
    ok: { label: t('skills.delete'), color: 'negative' },
  }).onOk(async () => {
    try {
      await store.deleteSkill(skill.id)
      await store.fetchCategories()
      $q.notify({ type: 'positive', message: t('skills.deleted') })
    } catch (error) {
      notifyError(error)
    }
  })
}

onMounted(async () => {
  try {
    await Promise.all([
      store.fetchSkills(),
      store.fetchAgents(),
      store.fetchCategories(),
      loadLearningStatus(),
    ])
  } catch (error) {
    learningEnabled.value = false
    if (tab.value === 'learned') tab.value = 'skills'
    notifyError(error)
  }
})
</script>

<style scoped>
.skill-editor-dialog {
  width: 1100px;
  max-width: 95vw;
  height: 85vh;
  max-height: 900px;
}

:deep(.skills-table .q-table) {
  table-layout: fixed;
  width: 100%;
}

:deep(.skills-table .q-table__middle) {
  overflow-x: hidden;
}

:deep(.skills-table .q-table__grid-content) {
  width: 100%;
  margin: 0;
}

:deep(.skills-table .q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
  padding: 8px 0;
}

.skill-mobile-card,
.skill-mobile-heading {
  min-width: 0;
}

.skill-mobile-code,
.skill-description {
  overflow-wrap: anywhere;
}

.skill-mobile-label {
  margin-bottom: 2px;
  color: #757575;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.skill-mobile-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 2px;
  white-space: nowrap;
}

.skill-actions-cell {
  white-space: nowrap;
}

.skill-actions {
  display: flex;
  flex-wrap: nowrap;
  justify-content: flex-end;
  gap: 2px;
  min-width: max-content;
  white-space: nowrap;
}

.skill-category-heading {
  min-height: 32px;
}

.skill-description {
  white-space: normal;
  overflow-wrap: anywhere;
}

.drop-zone {
  border: 2px dashed var(--q-primary);
  border-radius: 8px;
  cursor: pointer;
  background: rgba(25, 118, 210, 0.04);
  transition: background-color 0.2s ease;
}

.drop-zone:hover,
.drop-zone:focus {
  background: rgba(25, 118, 210, 0.1);
  outline: none;
}

.selected-files-list {
  width: 100%;
  max-height: 220px;
  overflow-y: auto;
  cursor: default;
}

.import-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
}

.import-field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 599px) {
  .import-field-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 1023px) {
  .skill-editor-fields {
    margin-top: 0;
  }

  .skill-editor-fields > [class*='col-'] {
    padding-top: 0;
  }
}
</style>
