<template>
  <div>
    <div v-if="error" role="alert" class="q-pa-sm">{{ t(error) }}</div>
    <q-list dense>
      <q-item v-for="item in items" :key="item.path" clickable
        :active="item.path === activePath" active-class="repository--selected"
        :aria-current="item.path === activePath ? 'true' : undefined"
        @click="item.workspace ? emit('open', item.workspace.id) : emit('discoverOpen', item.path)">
        <q-item-section avatar><FolderIcon tone="red" :expanded="item.path === activePath" /></q-item-section>
        <q-item-section><q-item-label class="repository-path">{{ item.path }}</q-item-label></q-item-section>
      </q-item>
    </q-list>
    <div v-if="!loading && !error && !items.length" class="q-pa-sm" role="status">{{ t('code.noRepositories') }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { FolderIcon } from '@/core/util'
import { codeErrorTranslationKey, codeService } from '../services/codeService'
import type { CodeWorkspace } from '../types'

const props = defineProps<{ roomId: string; repositories: CodeWorkspace[]; canDiscover: boolean; activePath?: string | null }>()
const emit = defineEmits<{ open: [id: string]; discoverOpen: [path: string] }>()
const { t } = useI18n()
const paths = ref<string[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
let active: AbortController | null = null
const items = computed(() => {
  const known = new Map<string, CodeWorkspace>()
  for (const workspace of props.repositories) {
    if (!known.has(workspace.label)) known.set(workspace.label, workspace)
  }
  // Discovered paths resolve against the current Console, even if an older checkout
  // with that path was previously linked. Existing grants still work without discovery.
  const discovered = new Set(paths.value)
  return [...new Set([...known.keys(), ...discovered])].sort().map(path => ({ path,
    workspace: discovered.has(path) ? undefined : known.get(path) }))
})

async function load(): Promise<void> {
  active?.abort()
  if (!props.canDiscover) return
  const controller = new AbortController()
  active = controller
  loading.value = true
  error.value = null
  try {
    const result = await codeService.discover(props.roomId, controller.signal)
    if (controller.signal.aborted) return
    paths.value = result.paths
  } catch (reason) {
    if (!controller.signal.aborted) error.value = codeErrorTranslationKey(reason) === 'code.discoveryForbidden' ? 'code.discoveryForbidden' : 'code.discoveryError'
  } finally {
    if (active === controller) loading.value = false
  }
}
watch(() => [props.roomId, props.canDiscover], () => {
  active?.abort()
  paths.value = []
  error.value = null
  loading.value = false
  void load()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => active?.abort())
defineExpose({ refresh: load, loading })
</script>

<style scoped>
.repository-path { overflow-wrap: anywhere; }
.repository--selected { color: inherit; background: var(--solaire-blue-light); box-shadow: inset 3px 0 var(--solaire-blue-accent); }
.body--dark .repository--selected { background: var(--solaire-blue-dark); }
</style>
