<template>
  <q-dialog :model-value="true" maximized transition-show="slide-up" transition-hide="slide-down" @update:model-value="!$event && emit('close')">
    <q-card class="column no-wrap galaris-dialog-card">
      <q-toolbar class="galaris-dialog-title bg-primary text-white">
        <q-toolbar-title>{{ t('skills.viewTitle', { label }) }}</q-toolbar-title>
        <q-btn v-if="packageDownload" outline color="white" icon="download" :label="t('skills.download')" @click="emit('download')" />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('skills.cancel')" />
      </q-toolbar>
      <q-banner v-if="error" role="alert" class="q-ma-md">
        {{ t('skills.error') }}
        <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="emit('retry')" /></template>
      </q-banner>
      <q-splitter v-model="splitter" class="col galaris-dialog-body--contained galaris-dialog-body">
        <template #before>
          <q-scroll-area class="fit q-pa-sm">
            <q-tree v-if="files.length" :nodes="fileTree" node-key="key" label-key="label" :selected="path" default-expand-all no-transition
              @update:selected="$event && emit('select', $event)" />
          </q-scroll-area>
        </template>
        <template #after>
          <q-inner-loading :showing="loading" />
          <div v-if="selectedFile" class="column fit">
            <q-toolbar class="bg-grey-2">
              <q-icon :name="selectedFile.text ? 'description' : 'data_object'" class="q-mr-sm" />
              <q-toolbar-title class="text-subtitle1">{{ selectedFile.path }}</q-toolbar-title>
              <span class="text-caption text-grey-7 q-mr-md">{{ formatFileSize(selectedFile.size, locale) }}</span>
              <q-btn flat round color="primary" icon="download" :aria-label="t('skills.download')" @click="emit('download-file', selectedFile)">
                <q-tooltip>{{ t('skills.download') }}</q-tooltip>
              </q-btn>
            </q-toolbar>
            <q-separator />
            <template v-if="selectedFile.text && !error">
              <q-tabs v-if="isMarkdown" v-model="viewerTab" dense align="left" class="text-primary">
                <q-tab name="preview" :label="t('skills.preview')" icon="visibility" />
                <q-tab name="source" :label="t('skills.source')" icon="code" />
              </q-tabs>
              <q-tab-panels v-if="isMarkdown" v-model="viewerTab" class="col scroll">
                <q-tab-panel name="preview"><Markdown :content="content" compact-frontmatter /></q-tab-panel>
                <q-tab-panel name="source"><CodeEditor :model-value="content" language="markdown" readonly :visible-lines="30" /></q-tab-panel>
              </q-tab-panels>
              <div v-else class="q-pa-md col scroll">
                <CodeEditor :model-value="content" :language="languageFor(selectedFile.path)" readonly :visible-lines="30" />
              </div>
            </template>
            <div v-else-if="!selectedFile.text" class="col row flex-center text-grey-7 q-gutter-sm">
              <q-icon name="draft" size="3em" /><span>{{ t('skills.binaryFile') }}</span>
            </div>
          </div>
          <div v-else-if="!loading && !error" class="fit row flex-center text-grey-7">{{ t('skills.noFile') }}</div>
        </template>
      </q-splitter>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CodeEditor, Markdown, formatFileSize } from '@/core/util'
import type { SkillFile } from '../services/skillService'
import { languageForSkillFile as languageFor } from '../fileLanguage'

const { label, files, path, content, loading = false, error = false, packageDownload = false } = defineProps<{
  label: string; files: SkillFile[]; path: string | null; content: string; loading?: boolean; error?: boolean; packageDownload?: boolean
}>()
const emit = defineEmits<{ close: []; select: [path: string]; retry: []; download: []; 'download-file': [file: SkillFile] }>()
const { t, locale } = useI18n()
const splitter = ref(27)
const viewerTab = ref('preview')
const selectedFile = computed(() => files.find(file => file.path === path))
const isMarkdown = computed(() => path?.toLowerCase().endsWith('.md') ?? false)
watch(() => path, () => { viewerTab.value = isMarkdown.value ? 'preview' : 'source' })
interface FileTreeNode { key: string; label: string; icon: string; selectable: boolean; children?: FileTreeNode[] }
const fileTree = computed(() => {
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
        node = { key: currentPath, label: part, icon: isFile ? (file.text ? 'description' : 'draft') : 'folder', selectable: isFile,
          ...(isFile ? {} : { children: [] }) }
        children.push(node)
      }
      if (!isFile) children = node.children ?? []
    })
  }
  return roots
})
</script>
