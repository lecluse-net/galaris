<template>
  <section class="code-workspace-pane" :aria-label="t('code.title')">
    <q-toolbar>
      <q-icon name="code" class="q-mr-sm" />
      <q-toolbar-title class="text-body2 ellipsis">{{ editor?.session.workspace.label ?? t('code.title') }}</q-toolbar-title>
      <slot name="actions" />
      <q-btn flat round dense icon="close" :aria-label="t('code.hide')" @click="emit('hide')" />
    </q-toolbar>
    <q-banner v-if="editor?.error" class="code-error" role="alert">{{ t('code.connectionLost') }}
      <q-btn flat :label="t('code.retry')" @click="retry" />
    </q-banner>
    <q-banner v-if="editor?.recoveryUrl" class="code-error" role="status">
      {{ t(editor.showRecovery ? 'code.recoveredWindow' : 'code.previousWindow') }}
      <q-btn flat :label="t(editor.showRecovery ? 'code.showPrevious' : 'code.showRecovered')"
        @click="editor.showRecovery = !editor.showRecovery" />
    </q-banner>
    <div ref="anchor" class="code-workspace-anchor"><q-inner-loading :showing="!(editor?.showRecovery ? editor.recoveryLoaded : editor?.loaded)" /></div>
    <q-dialog v-model="confirmReload" :aria-label="t('code.reloadTitle')">
      <q-card style="max-width: 560px">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ t('code.reloadTitle') }}</div><q-space />
          <q-btn flat round dense icon="close" v-close-popup :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>{{ t('code.reloadWarning') }}</q-card-section>
        <q-card-actions align="right">
          <q-btn flat :label="t('common.cancel')" v-close-popup />
          <q-btn flat :label="t('code.reloadConfirm')" @click="reload" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { useCodeStore } from '../stores/codeStore'
import { codeErrorTranslationKey } from '../services/codeService'
const props = defineProps<{ workspaceId: string }>()
const emit = defineEmits<{ hide: [] }>()
const store = useCodeStore()
const { t } = useI18n()
const $q = useQuasar()
const anchor = ref<HTMLElement | null>(null)
const confirmReload = ref(false)
const editor = computed(() => store.editors.find(item => item.session.workspace.id === props.workspaceId))
watch([anchor, () => props.workspaceId], ([element, id]) => { store.anchor = element; store.activeId = id }, { immediate: true, flush: 'post' })
onBeforeUnmount(() => { if (store.anchor === anchor.value) store.hide() })
async function retry(): Promise<void> {
  try { await store.recover(props.workspaceId) }
  catch (error) {
    if (error instanceof Error && error.message === 'code_recovery_reload_required') confirmReload.value = true
    else $q.notify({ type: 'negative', message: t(codeErrorTranslationKey(error)) })
  }
}
function reload(): void { store.reloadRecovery(props.workspaceId); confirmReload.value = false }
</script>

<style scoped>
.code-workspace-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; overflow: hidden; }
.code-workspace-anchor { flex: 1; position: relative; min-height: 0; }
.code-error { background: var(--solaire-orange-light); }
body.body--dark .code-error { background: var(--solaire-orange-dark); }
</style>
