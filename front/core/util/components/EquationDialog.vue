<template>
  <q-dialog :model-value="true" no-refocus :aria-label="t('richEditor.equation.title')" @update:model-value="value => { if (!value) emit('close') }" @show="initialize" @before-hide="dispose">
    <q-card class="galaris-dialog-card rich-editor equation-dialog">
      <q-card-section class="galaris-dialog-title row items-center">
        <div class="text-h6">{{ t('richEditor.equation.title') }}</div><q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-card-section class="galaris-dialog-body q-gutter-md">
        <div>{{ t(kind === 'inline' ? 'richEditor.equation.inline' : 'richEditor.equation.block') }}</div>
        <div v-if="loading" role="status"><q-spinner /> {{ t('common.loading') }}</div>
        <div v-if="failed" role="alert">{{ t('richEditor.equation.loadFailed') }} <q-btn outline color="primary" :label="t('common.retry')" @click="initialize" /></div>
        <div ref="host" class="equation-field" />
        <q-input v-if="field" :model-value="draft" outlined autogrow :label="t('richEditor.equation.latex')" @update:model-value="value => updateLatex(String(value ?? ''))" />
        <div v-if="invalid" role="alert">{{ t('richEditor.equation.invalid') }}</div>
        <div ref="keyboardHost" class="equation-keyboard" />
      </q-card-section>
      <q-card-actions align="right">
        <q-btn v-close-popup outline color="primary" :label="t('common.cancel')" />
        <q-btn color="primary" :label="t('richEditor.apply')" :disable="!field || !draft.trim() || invalid" @click="emit('apply', draft)" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>
<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, shallowRef, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MathfieldElement } from 'mathlive'
import { loadMathLive, type MathKind } from '../mathRendering'

const { latex, kind } = defineProps<{ latex: string; kind: MathKind }>()
const emit = defineEmits<{ apply: [latex: string]; close: [] }>()
const { t, locale } = useI18n()
const host = useTemplateRef('host'), keyboardHost = useTemplateRef('keyboardHost')
const field = shallowRef<MathfieldElement>(), draft = ref(latex), invalid = ref(false), failed = ref(false), loading = ref(false)
let disposed = false, events: AbortController | undefined, restoreKeyboard: (() => void) | undefined

function sync(): void {
  if (!field.value) return
  draft.value = field.value.value
  invalid.value = field.value.errors.length > 0 || draft.value.length > 10_000
}
function updateLatex(value: string): void {
  if (!field.value) return
  if (value.length > 10_000) { draft.value = value; invalid.value = true; return }
  field.value.value = value
  sync()
}
async function initialize(): Promise<void> {
  if (loading.value || field.value || disposed) return
  failed.value = false; loading.value = true
  try {
    const { MathfieldElement } = await loadMathLive()
    if (disposed || !host.value || !keyboardHost.value) return
    MathfieldElement.locale = locale.value
    const mathfield = new MathfieldElement()
    mathfield.setAttribute('aria-label', t('richEditor.equation.input'))
    mathfield.mathVirtualKeyboardPolicy = 'manual'
    mathfield.value = draft.value
    // Keep the keyboard inside Quasar's focus trap, including nested/fullscreen editors.
    const keyboard = window.mathVirtualKeyboard, container = keyboardHost.value
    const previous = keyboard.container
    keyboard.container = container
    const resize = () => { container.style.height = keyboard.boundingRect.height + 'px' }
    events = new AbortController()
    keyboard.addEventListener('geometrychange', resize, { signal: events.signal })
    mathfield.addEventListener('input', sync, { signal: events.signal })
    mathfield.addEventListener('focus', () => keyboard.show(), { signal: events.signal })
    // MathLive's keyboard EventTarget ignores AbortSignal options.
    restoreKeyboard = () => { keyboard.removeEventListener('geometrychange', resize); keyboard.hide(); keyboard.container = previous }
    host.value.append(mathfield)
    field.value = mathfield
    sync()
    await nextTick()
    if (disposed) return
    mathfield.focus()
    keyboard.show()
  } catch { releaseField(); if (!disposed) failed.value = true }
  finally { loading.value = false }
}
function releaseField(): void {
  events?.abort(); restoreKeyboard?.(); restoreKeyboard = undefined
  field.value?.remove(); field.value = undefined
  host.value?.replaceChildren()
}
function dispose(): void { disposed = true; releaseField() }
onBeforeUnmount(dispose)
</script>
<style scoped>
.equation-dialog { width: 720px; max-width: 96vw; }
.equation-field :deep(math-field) { display: block; width: 100%; min-height: 64px; padding: 12px; border: 1px solid var(--rich-editor-border); border-radius: 4px; color: var(--rich-foreground); background: var(--rich-background); --primary-color: var(--solaire-blue-accent); --caret-color: var(--solaire-blue-accent); --selection-background-color: var(--solaire-blue-light); }
.equation-keyboard {
  position: relative; isolation: isolate; width: 100%; margin-inline: 0;
  --keyboard-background: var(--rich-surface); --keyboard-toolbar-text: var(--rich-foreground);
  --keycap-background: var(--rich-background); --keycap-text: var(--rich-foreground);
  --keycap-primary-background: var(--solaire-blue-light); --keycap-primary-text: var(--solaire-blue-dark);
  --keycap-background-hover: var(--solaire-blue-light); --keycap-text-hover: var(--solaire-blue-dark);
  --keycap-background-pressed: var(--solaire-blue-dark); --keycap-text-pressed: var(--solaire-blue-light);
}
</style>
