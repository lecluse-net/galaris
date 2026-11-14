<template>
  <div class="calendar-mini-date">
    <div class="month-return row items-center q-pa-xs">
      <q-btn flat round dense color="primary" icon="arrow_back" :aria-label="t('common.back')" @click="closeMonths" />
      <div class="col text-center text-subtitle2">{{ navigation.year }}</div>
    </div>
    <q-date v-show="!yearsOpen" ref="datePicker" v-model="model" mask="YYYY-MM-DD" minimal flat no-unset
      :first-day-of-week="1" :locale="locale" @navigation="navigation = $event" @click.capture="openYears" />
    <q-card v-if="yearsOpen" flat class="year-picker">
      <div class="row items-center q-pa-xs">
        <q-btn flat round dense color="primary" icon="arrow_back" :aria-label="t('common.back')" @click="closeYears" />
        <div class="col text-center text-subtitle2">{{ navigation.year }}</div>
      </div>
      <div ref="yearList" class="year-list" role="list" @keydown="navigateYear">
        <div v-for="year in years" :key="year" role="listitem">
          <q-btn color="primary" :outline="year !== navigation.year" :label="String(year)" :aria-pressed="year === navigation.year" @click="selectYear(year)" />
        </div>
      </div>
    </q-card>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { QDate, QDateProps } from 'quasar'

const props = defineProps<{ locale: QDateProps['locale'] }>()
const model = defineModel<string>({ required: true })
const { t } = useI18n()
const datePicker = useTemplateRef<QDate>('datePicker')
const yearList = useTemplateRef<HTMLElement>('yearList')
const navigation = ref({ year: Number(model.value.slice(0, 4)), month: Number(model.value.slice(5, 7)) })
const yearsOpen = ref(false)
const currentYear = new Date().getFullYear()
const years = Array.from({ length: 401 }, (_, index) => currentYear - 200 + index)

function closeMonths(): void {
  datePicker.value?.setView('Calendar')
  void nextTick(() => {
    const root = datePicker.value?.$el as HTMLElement | undefined
    const month = props.locale?.months?.[navigation.value.month - 1]
    const button = [...(root?.querySelectorAll<HTMLButtonElement>('.q-date__navigation button') ?? [])]
      .find(button => button.textContent?.trim() === month)
    button?.focus({ preventScroll: true })
  })
}
function openYears(event: MouseEvent): void {
  const button = (event.target as HTMLElement).closest('button')
  if (!button?.closest('.q-date__navigation') || !/^\d{4}$/.test(button.textContent?.trim() ?? '')) return
  event.preventDefault()
  event.stopPropagation()
  yearsOpen.value = true
  void nextTick(() => {
    const list = yearList.value
    const active = list?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')
    if (list && active) {
      list.scrollTop += active.getBoundingClientRect().top - list.getBoundingClientRect().top - (list.clientHeight - active.clientHeight) / 2
      active.focus({ preventScroll: true })
    }
  })
}
function closeYears(): void {
  yearsOpen.value = false
  void nextTick(() => {
    const root = datePicker.value?.$el as HTMLElement | undefined
    const button = [...(root?.querySelectorAll<HTMLButtonElement>('.q-date__navigation button') ?? [])]
      .find(button => /^\d{4}$/.test(button.textContent?.trim() ?? ''))
    button?.focus({ preventScroll: true })
  })
}
function selectYear(year: number): void {
  datePicker.value?.setCalendarTo(year, navigation.value.month)
  closeYears()
}
function navigateYear(event: KeyboardEvent): void {
  if (event.key === 'Escape') { event.preventDefault(); closeYears(); return }
  const buttons = [...(yearList.value?.querySelectorAll<HTMLButtonElement>('button') ?? [])]
  const index = buttons.indexOf((event.target as HTMLElement).closest('button') as HTMLButtonElement)
  const next = event.key === 'ArrowDown' ? Math.min(index + 1, buttons.length - 1)
    : event.key === 'ArrowUp' ? Math.max(index - 1, 0)
      : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : null
  if (next !== null) { event.preventDefault(); buttons[next]?.focus() }
}
watch(model, value => {
  navigation.value = { year: Number(value.slice(0, 4)), month: Number(value.slice(5, 7)) }
})
</script>

<style scoped>
.calendar-mini-date { position: relative; }
.month-return { display: none; position: absolute; top: 0; left: 0; right: 0; z-index: 1; }
.calendar-mini-date:has(.q-date__months) > .month-return { display: flex; }
.calendar-mini-date :deep(.q-date) { width: 100%; min-width: 0; font-size: 12px; background: transparent; }
.calendar-mini-date :deep(.q-date__main), .calendar-mini-date :deep(.q-date__content) { min-width: 0; }
.calendar-mini-date :deep(.q-date__view) { padding-left: 0; padding-right: 0; }
.calendar-mini-date :deep(.q-date__calendar) { min-height: 0; padding-top: 0; padding-bottom: 0; }
.calendar-mini-date :deep(.q-date__navigation) { height: 32px; }
.calendar-mini-date :deep(.q-date__calendar-weekdays) { height: 24px; }
.calendar-mini-date :deep(.q-date__calendar-days-container) { height: 192px; min-height: 0; }
.calendar-mini-date :deep(.q-date__months) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; padding-top: 42px; }
.calendar-mini-date :deep(.q-date__months-item) { min-width: 0; }
.year-picker { height: 290px; display: flex; flex-direction: column; background: transparent; }
.year-list { position: relative; min-height: 0; overflow-y: scroll; scrollbar-gutter: stable; scrollbar-width: thin; scrollbar-color: var(--solaire-gray-accent) transparent; padding: 4px 16px; display: grid; gap: 4px; }
.year-list .q-btn { width: 100%; }
</style>
