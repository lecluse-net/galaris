<template>
  <div class="folder-thumbnail" aria-hidden="true"><LibraryIcon :icon="icon" size="80px" /></div>
</template>
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { LibraryIcon } from '@/core/util'
import { documentService } from '../services/documentService'
const { folderId, agentId = null } = defineProps<{ folderId: string; agentId?: number | null }>()
const icon = ref<string | null>(null), refresh = ref(0)
const sessionChanged = () => { refresh.value++ }
watch(() => [folderId, agentId, refresh.value] as const, async (_, _old, cleanup) => {
  const request = new AbortController(); cleanup(() => request.abort()); icon.value = null
  try {
    const page = await documentService.folderCollection(folderId, agentId, { metadata_only: true }, request.signal)
    if (!request.signal.aborted) icon.value = page.folder.metadata.icon ?? null
  } catch { /* Unavailable folders keep a generic icon without revealing metadata. */ }
}, { immediate: true })
onMounted(() => window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged))
onBeforeUnmount(() => window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged))
</script>
<style scoped>
.folder-thumbnail { width: 100%; height: 100%; display: grid; place-items: center; }
</style>
