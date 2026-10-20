<template>
  <template v-if="kind === 'code'">
    <q-item v-if="menu" clickable role="menuitem" :disable="readonly" :aria-label="t('richEditor.codeTools.language')">
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
    <q-select v-else dense outlined emit-value map-options :model-value="language" :options="languages" :label="t('richEditor.codeTools.language')" :disable="readonly" @update:model-value="value => emit('language', value)" />
  </template>
  <EditorialTableStyles v-if="kind === 'table'" :classes="tableClasses" :menu-item="menu" @select="(palette, treatment) => emit('table-style', palette, treatment)" />
  <template v-for="item in actions" :key="item.key">
    <q-item v-if="menu" clickable role="menuitem" :aria-label="item.label" :disable="item.disabled" @click="emit('action', item.key)">
      <q-item-section avatar><q-icon :name="item.icon" /></q-item-section>
      <q-item-section>{{ item.label }}</q-item-section>
    </q-item>
    <EditorialToolButton v-else flat dense :icon="item.icon" :label="item.label" :disable="item.disabled" @click="emit('action', item.key)" />
  </template>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import EditorialToolButton from './EditorialToolButton.vue'
import EditorialTableStyles from './EditorialTableStyles.vue'
import ContextSubmenu from './ContextSubmenu.vue'
import type { TablePalette, TableTreatment } from '../editorialTableStyles'

defineProps<{
  kind: string; menu?: boolean; readonly: boolean
  actions: Array<{ key: string; icon: string; label: string; disabled: boolean }>
  language: string; languages: Array<{ value: string; label: string }>; tableClasses: string | null
}>()
const emit = defineEmits<{
  action: [key: string]; language: [value: string]; 'table-style': [palette?: TablePalette, treatment?: TableTreatment]
}>()
const { t } = useI18n()
</script>
