<template>
  <component :is="menuItem ? QItem : QBtn" v-bind="menuItem ? { clickable: true, role: 'menuitem' } : { flat: true, dense: true, icon: editorialIcon('tableStyles', 'palette') }" :aria-label="t('richEditor.tableStyles.title')">
    <template v-if="menuItem">
      <q-item-section avatar><q-icon :name="editorialIcon('tableStyles', 'palette')" /></q-item-section>
      <q-item-section>{{ t('richEditor.tableStyles.title') }}</q-item-section>
      <q-item-section side><q-icon name="chevron_right" /></q-item-section>
    </template>
    <q-tooltip v-else>{{ t('richEditor.tableStyles.title') }}</q-tooltip>
    <component :is="menuItem ? ContextSubmenu : QMenu" class="editorial-table-gallery" :anchor="menuItem ? 'top end' : 'bottom left'" :self="menuItem ? 'top start' : 'top left'" :offset="menuItem ? [0, 0] : [0, 8]" @before-show="browseCurrent">
      <div class="q-px-md q-pt-md text-subtitle2">{{ t('richEditor.tableStyles.title') }}</div>
      <q-tabs v-model="treatment" dense no-caps align="justify" class="q-mx-sm q-mt-sm" :aria-label="t('richEditor.tableStyles.presentation')">
        <q-tab v-for="kind in tableTreatments" :key="kind" :name="kind" :label="t('richEditor.tableStyles.' + kind)" />
      </q-tabs>
      <div class="editorial-table-gallery-grid q-pa-md" role="group" :aria-label="t('richEditor.tableStyles.colors')">
        <q-btn v-for="palette in tablePalettes" :key="palette" v-close-popup outline no-caps class="editorial-table-swatch" :class="{ 'editorial-table-swatch-selected': selected(palette) }" :aria-label="t('richEditor.tableStyles.' + palette)" :aria-pressed="selected(palette)" @click="emit('select', palette, treatment)">
          <span class="rich-content editorial-table-sample" aria-hidden="true">
            <table :class="withTableStyle(null, palette, treatment)"><tbody><tr v-for="row in 3" :key="row"><td v-for="column in 3" :key="column"><span /></td></tr></tbody></table>
          </span>
          <span class="editorial-table-swatch-label">{{ t('richEditor.tableStyles.' + palette) }}<q-icon v-if="selected(palette)" name="check" size="16px" /></span>
        </q-btn>
      </div>
      <q-separator />
      <div class="q-pa-sm"><q-btn v-close-popup outline no-caps icon="format_clear" :label="t('richEditor.tableStyles.reset')" class="full-width" @click="emit('select')" /></div>
    </component>
  </component>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { QBtn, QItem, QMenu } from 'quasar'
import ContextSubmenu from './ContextSubmenu.vue'
import { useI18n } from 'vue-i18n'
import { editorialIcon } from '../editorialIcons'
import { tablePalettes, tableTreatments, withTableStyle, type TablePalette, type TableTreatment } from '../editorialTableStyles'
const { classes, menuItem = false } = defineProps<{ classes: string | null; menuItem?: boolean }>()
const emit = defineEmits<{ select: [palette?: TablePalette, treatment?: TableTreatment] }>()
const { t } = useI18n()
const treatment = ref<TableTreatment>('contrast')
function browseCurrent(): void { treatment.value = tableTreatments.find(kind => classes?.split(/\s+/).includes(`galaris-table-${kind}`)) ?? 'contrast' }
function selected(palette: TablePalette): boolean { const values = classes?.split(/\s+/) ?? []; return values.includes(`galaris-table-${palette}`) && values.includes(`galaris-table-${treatment.value}`) }
</script>
<style>
.editorial-table-gallery { width: 392px; max-width: calc(100vw - 16px); }
.editorial-table-gallery-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.editorial-table-swatch { padding: 9px; color: var(--solaire-gray-accent); }
.editorial-table-swatch-selected { color: var(--q-primary); background: var(--solaire-blue-light); }
.body--dark .editorial-table-swatch-selected { background: var(--solaire-blue-dark); }
.editorial-table-swatch .q-btn__content { flex-direction: column; gap: 7px; width: 100%; }
.editorial-table-swatch-label { display: flex; align-items: center; justify-content: center; gap: 4px; color: var(--solaire-gray-dark); font-size: 12px; }
.body--dark .editorial-table-swatch-label { color: var(--solaire-gray-light); }
.editorial-table-sample.rich-content { width: 100%; background: transparent; line-height: 1; }
.editorial-table-sample.rich-content table { width: 100%; margin: 0; }
.editorial-table-gallery .editorial-table-sample.rich-content table > tbody > tr > td { min-width: 0; padding: 5px; }
.editorial-table-sample td span { display: block; width: 70%; height: 2px; background: currentColor; opacity: .45; }
@media (max-width: 420px) { .editorial-table-gallery-grid { gap: 8px; padding: 12px; } }
</style>
