<template>
  <template v-if="toolbar">
    <EditorialToolButton v-if="kind === 'code'" flat dense color="primary" icon="code" :label="t('richEditor.codeTools.language')" :disable="readonly">
      <q-menu no-refocus :transition-duration="0" @hide="emit('focus-editor')"><q-list dense role="menu" :aria-label="t('richEditor.codeTools.language')" @mousedown.prevent>
        <q-item v-for="option in languages" :key="option.value" v-close-popup clickable role="menuitemradio" :aria-checked="language === option.value" @click="emit('language', option.value)">
          <q-item-section>{{ option.label }}</q-item-section>
        </q-item>
      </q-list></q-menu>
    </EditorialToolButton>
    <EditorialTableStyles v-if="kind === 'table'" :classes="tableClasses" @select="(palette, treatment) => emit('table-style', palette, treatment)" />
    <EditorialToolButton v-for="item in actions" :key="item.key" flat dense :icon="item.icon" :label="item.label" :disable="item.disabled" :color="['remove', 'deleteRow', 'deleteColumn', 'deleteTable'].includes(item.key) ? 'negative' : 'primary'" @click="emit('action', item.key)" />
  </template>
  <template v-else>
  <template v-if="kind === 'code'">
    <q-item clickable role="menuitem" :disable="readonly" :aria-label="t('richEditor.codeTools.language')">
      <q-item-section avatar><q-icon name="code" /></q-item-section>
      <q-item-section>{{ t('richEditor.codeTools.language') }}</q-item-section>
      <q-item-section side><q-icon name="chevron_right" /></q-item-section>
      <ContextSubmenu>
        <q-list dense role="menu" :aria-label="t('richEditor.codeTools.language')">
          <q-item v-for="option in languages" :key="option.value" clickable role="menuitemradio" :aria-checked="language === option.value" @click="emit('language', option.value)">
            <q-item-section avatar><q-icon v-if="language === option.value" name="check" /></q-item-section>
            <q-item-section>{{ option.label }}</q-item-section>
          </q-item>
        </q-list>
      </ContextSubmenu>
    </q-item>
  </template>
  <EditorialTableStyles v-if="kind === 'table'" :classes="tableClasses" menu-item @select="(palette, treatment) => emit('table-style', palette, treatment)" />
  <template v-for="item in actions" :key="item.key">
    <q-item clickable role="menuitem" :aria-label="item.label" :disable="item.disabled" @click="emit('action', item.key)">
      <q-item-section avatar><q-icon :name="item.icon" :style="item.key === 'remove' ? { color: solaireCss.red.accent } : undefined" /></q-item-section>
      <q-item-section>{{ item.label }}</q-item-section>
    </q-item>
  </template>
  </template>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { solaireCss } from '../solaireTheme'
import EditorialTableStyles from './EditorialTableStyles.vue'
import EditorialToolButton from './EditorialToolButton.vue'
import ContextSubmenu from './ContextSubmenu.vue'
import type { TablePalette, TableTreatment } from '../editorialTableStyles'

defineProps<{
  kind: string; readonly: boolean
  actions: Array<{ key: string; icon: string; label: string; disabled: boolean }>
  language: string; languages: Array<{ value: string; label: string }>; tableClasses: string | null
  toolbar?: boolean
}>()
const emit = defineEmits<{
  action: [key: string]; language: [value: string]; 'table-style': [palette?: TablePalette, treatment?: TableTreatment]; 'focus-editor': []
}>()
const { t } = useI18n()
</script>
