<template>
  <DocumentToolbarFrame :label="label" sticky>
      <div v-for="group in visibleGroups" :key="group.id" class="editorial-toolbar-group"
        role="group" :aria-label="group.label">
        <span class="editorial-toolbar-title">{{ group.label }}</span>
        <div class="editorial-toolbar-row">
          <template v-for="command in group.commands" :key="command.id">
            <label v-if="command.kind === 'color'" class="document-toolbar-field">
              <span>{{ command.label }}</span>
              <input type="color" :value="command.value" :disabled="unavailable(command)" @input="input(command, $event)">
            </label>
            <label v-else-if="command.kind === 'range'" class="document-toolbar-field">
              <span>{{ command.label }}</span>
              <input type="range" :value="command.value" :min="command.min" :max="command.max" :step="command.step ?? 1"
                :disabled="unavailable(command)" @input="input(command, $event)">
            </label>
            <EditorialToolButton v-else dense no-caps
              :flat="!command.showLabel" :outline="command.showLabel && !command.primary" :icon="command.icon"
              :label="command.label" :aria-pressed="command.kind === 'toggle' ? Boolean(command.pressed) : undefined"
              :class="{ 'editorial-alignment-active': command.kind === 'toggle' && command.pressed }"
              :color="command.showLabel || command.pressed ? 'primary' : undefined"
              :disable="unavailable(command)" :loading="command.busy" @click="dispatch(command)">
              {{ command.showLabel ? command.label : undefined }}
            </EditorialToolButton>
          </template>
        </div>
      </div>
      <EditorialToolButton v-if="extraButtons.length" flat dense icon="more_horiz" :label="t('richEditor.moreTools')">
        <q-menu>
          <q-list dense :aria-label="t('richEditor.moreTools')">
            <q-item v-for="command in extraButtons" :key="command.id" v-close-popup clickable
              :role="command.kind === 'toggle' ? 'menuitemcheckbox' : 'menuitem'"
              :aria-checked="command.kind === 'toggle' ? Boolean(command.pressed) : undefined"
              :disable="unavailable(command)" @click="dispatch(command)">
              <q-item-section avatar><q-icon :name="command.pressed ? 'check' : command.icon" /></q-item-section>
              <q-item-section>{{ command.label }}</q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </EditorialToolButton>
  </DocumentToolbarFrame>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import DocumentToolbarFrame from './DocumentToolbarFrame.vue'
import EditorialToolButton from './EditorialToolButton.vue'
import type { DocumentToolbarButton, DocumentToolbarCommand, DocumentToolbarGroup } from '../documentToolbar'

const { label, groups, readonly = false } = defineProps<{
  label: string
  groups: readonly DocumentToolbarGroup[]
  readonly?: boolean
}>()
const emit = defineEmits<{ command: [id: string, value?: string | number] }>()
const { t } = useI18n()
const $q = useQuasar()

function isSecondary(command: DocumentToolbarCommand): command is DocumentToolbarButton {
  return (command.kind === 'button' || command.kind === 'toggle') && command.secondary === true
}

const visibleGroups = computed(() => $q.screen.lt.md
  ? groups.map(group => ({ ...group, commands: group.commands.filter(command => !isSecondary(command)) }))
    .filter(group => group.commands.length > 0)
  : groups)
const extraButtons = computed(() => $q.screen.lt.md
  ? groups.flatMap(group => group.commands.filter(isSecondary))
  : [])

function unavailable(command: DocumentToolbarCommand): boolean {
  return Boolean(command.disabled || (readonly && !command.readOnly) || ('busy' in command && command.busy))
}

function dispatch(command: DocumentToolbarCommand, value?: string | number): void {
  if (!unavailable(command)) emit('command', command.id, value)
}

function input(command: DocumentToolbarCommand, event: Event): void {
  if (!(event.target instanceof HTMLInputElement)) return
  dispatch(command, command.kind === 'range' ? event.target.valueAsNumber : event.target.value)
}

</script>

<style scoped>
.document-toolbar-field { display: inline-flex; align-items: center; gap: 4px; padding-inline: 4px; }
.document-toolbar-field input { min-height: 32px; accent-color: var(--solaire-blue-accent); }
.document-toolbar-field input[type="color"] { width: 32px; }
.document-toolbar-field input[type="range"] { width: clamp(64px, 20vw, 112px); }
</style>
