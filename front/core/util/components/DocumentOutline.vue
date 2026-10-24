<template>
  <nav class="document-outline" :aria-label="t('richEditor.outline')">
    <div class="row items-center no-wrap q-pa-sm">
      <span class="text-subtitle2 col">{{ t('richEditor.outline') }}</span>
      <q-btn flat round dense icon="close" :aria-label="t('richEditor.hideOutline')" @click="emit('close')" />
    </div>
    <ol v-if="headings.length" class="document-outline-headings">
      <li v-for="heading in headings" :key="heading.position" :style="{ paddingInlineStart: heading.depth + 'em' }">
        <q-item tag="a" href="#" clickable dense :active="selected === heading.position" active-class="document-outline-active"
          :aria-current="selected === heading.position ? 'location' : undefined" @click.prevent="navigate(heading.position)">
          <q-item-section>{{ heading.label }}</q-item-section>
        </q-item>
      </li>
    </ol>
    <p v-else class="q-pa-sm text-caption">{{ t('richEditor.outlineEmpty') }}</p>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Editor } from '@tiptap/core'
const { editor, revision } = defineProps<{ editor: Editor; revision: number }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
interface Heading { position: number; label: string; depth: number }
const headings = computed(() => {
  void revision
  const values: Heading[] = []
  const levels: number[] = []
  editor.state.doc.descendants((node, position) => {
    if (node.type.name !== 'heading') return
    const level = Number(node.attrs.level)
    while (levels.length && levels.at(-1)! >= level) levels.pop()
    values.push({ position, label: node.textContent || t('richEditor.outlineUntitled'), depth: levels.length })
    levels.push(level)
  })
  return values
})
const selected = computed(() => {
  void revision
  return [...headings.value].reverse().find(heading => heading.position <= editor.state.selection.from)?.position ?? null
})
function navigate(position: number | null): void {
  if (position === null) return
  editor.chain().focus().setTextSelection(position + 1).run()
  const element = editor.view.nodeDOM(position)
  if (element instanceof HTMLElement) element.scrollIntoView({ block: 'center', inline: 'nearest' })
}
</script>

<style scoped>
.document-outline { flex: 0 0 300px; align-self: flex-start; position: sticky; top: var(--editorial-toolbar-height, 0px); max-height: calc(100dvh - var(--editorial-toolbar-height, 0px) - 100px); overflow: auto; border: 1px solid var(--rich-editor-border); background: var(--rich-background); color: var(--rich-foreground); }
.document-outline-headings { list-style: none; margin: 0; padding: 0 8px 8px; }
.document-outline-headings a { color: inherit; text-decoration: none; overflow-wrap: anywhere; }
.document-outline-headings a:focus-visible { outline: 2px solid var(--solaire-blue-accent); outline-offset: -2px; }
.document-outline-active { color: var(--rich-foreground) !important; background: var(--solaire-blue-light); font-weight: 600; }
:global(body.body--dark) .document-outline-active { background: var(--solaire-blue-dark); }
@media (max-width: 1023px) { .document-outline { flex-basis: auto; width: 100%; position: static; max-height: 35dvh; } }
</style>
