<template>
  <SkillViewerDialog :label="label" :files="files" :path="path" :content="content" :loading="loading" :error="error"
    @close="emit('close')" @select="selectFile" @retry="retry" @download-file="downloadFile" />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { SkillViewerDialog } from '@/app/skill/interface'
import { browserResourceKind, saveBlobAsResource } from '@/core/util'
import { fileBrowserService, type FileEntry } from '@/app/file_share/interface'

const { uri, label, agentId } = defineProps<{ uri: string; label: string; agentId: number }>()
const emit = defineEmits<{ close: [] }>()
const $q = useQuasar()
const { t } = useI18n()
const entries = ref<FileEntry[]>([])
const path = ref<string | null>(null)
const content = ref(''), loading = ref(false), error = ref(false)
const listed = ref(false)
let request: AbortController | undefined
let active = true
const downloads = new Set<AbortController>()
function filePath(file: FileEntry): string {
  return typeof file.metadata?.path === 'string' ? file.metadata.path : decodeURIComponent(file.uri.slice(uri.length))
}
const files = computed(() => entries.value.map(file => ({
  path: filePath(file), name: file.name, size: file.size ?? 0,
  text: ['markdown', 'text', 'html'].includes(browserResourceKind(file.media_type, file.name) ?? ''),
})))
async function selectFile(selected: string): Promise<void> {
  request?.abort()
  const current = new AbortController(); request = current
  path.value = selected; content.value = ''; error.value = false; loading.value = true
  try {
    const file = entries.value.find(file => filePath(file) === selected)
    if (file && files.value.find(file => file.path === selected)?.text) {
      const blob = await fileBrowserService.content(agentId, file.uri, false, current.signal)
      const text = await blob.text()
      if (!current.signal.aborted) content.value = text
    }
  } catch { if (!current.signal.aborted) error.value = true }
  finally { if (!current.signal.aborted) loading.value = false }
}
async function load(): Promise<void> {
  request?.abort()
  const current = new AbortController(); request = current
  entries.value = []; path.value = null; content.value = ''; listed.value = false
  loading.value = true; error.value = false
  try {
    const collected: FileEntry[] = [], cursors = new Set<string>()
    let cursor: string | null = null
    do {
      const result = await fileBrowserService.list(agentId, uri, cursor, current.signal)
      if (current.signal.aborted) return
      collected.push(...result.entries.filter(file => !file.is_collection))
      cursor = result.next_cursor
      if (result.truncated && (!cursor || cursors.has(cursor))) throw new Error('Incomplete skill listing')
      if (cursor) cursors.add(cursor)
    } while (cursor)
    entries.value = collected; listed.value = true
    const first = files.value.find(file => file.path === 'SKILL.md') ?? files.value[0]
    if (first) await selectFile(first.path)
  } catch { if (!current.signal.aborted) error.value = true }
  finally { if (!current.signal.aborted) loading.value = false }
}
function retry(): void { if (listed.value && path.value) void selectFile(path.value); else void load() }
async function downloadFile(file: { path: string; name: string }): Promise<void> {
  const selected = entries.value.find(entry => filePath(entry) === file.path)
  if (!selected) return
  const current = new AbortController(); downloads.add(current)
  try {
    const blob = await fileBrowserService.content(agentId, selected.uri, false, current.signal)
    if (active && !current.signal.aborted) saveBlobAsResource(blob, file.name)
  } catch { if (!current.signal.aborted) $q.notify({ type: 'negative', message: t('skills.error') }) }
  finally { downloads.delete(current) }
}
watch([() => uri, () => agentId], () => { void load() }, { immediate: true })
onBeforeUnmount(() => { active = false; request?.abort(); downloads.forEach(request => request.abort()) })
</script>
