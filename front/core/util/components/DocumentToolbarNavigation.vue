<template>
  <div v-if="fullscreen && (workspace || fullscreenExit)" class="editorial-toolbar-group"
    role="group" :aria-label="t('richEditor.groups.navigation')">
    <span class="editorial-toolbar-title">{{ t('richEditor.groups.navigation') }}</span>
    <div class="editorial-toolbar-row">
      <DocumentNavigationButtons v-if="workspace" toolbar
        :can-go-back="workspace.canGoBack()" :can-go-forward="workspace.canGoForward()"
        @back="workspace.navigateHistory(-1)" @forward="workspace.navigateHistory(1)" />
      <q-btn v-if="fullscreenExit" flat dense icon="fullscreen_exit"
        :aria-label="t('fullscreenPreview.exitFullscreen')" aria-pressed="true" @click="exitFullscreen" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { documentFullscreenKey, documentWorkspaceViewKey } from '../documentFullscreen'
import DocumentNavigationButtons from './DocumentNavigationButtons.vue'

defineProps<{ fullscreenExit?: boolean }>()

const { t } = useI18n()
const fullscreen = inject(documentFullscreenKey, null)
const workspace = inject(documentWorkspaceViewKey, null)
function exitFullscreen(): void {
  if (fullscreen) fullscreen.value = false
}
</script>
