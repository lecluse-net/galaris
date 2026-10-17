import { computed, ref, watch } from 'vue'
import { useInterval } from 'quasar'
import { useI18n } from 'vue-i18n'
import { isRunTerminal, runDurationSeconds, type RunTiming } from '../runTiming'

export function useRunTiming(runs: () => readonly RunTiming[]) {
  const { locale } = useI18n()
  const now = ref(Date.now())
  const { registerInterval, removeInterval } = useInterval()
  const active = computed(() => runs().some(run => run.started_at && !run.finished_at && !isRunTerminal(run.status)))
  watch(active, value => {
    removeInterval()
    now.value = Date.now()
    if (value) registerInterval(() => { now.value = Date.now() }, 1000)
  }, { immediate: true })

  function formatStart(value?: string | null): string {
    if (!value || !Number.isFinite(Date.parse(value))) return '—'
    return new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value))
  }
  function formatDuration(run: RunTiming): string {
    const seconds = runDurationSeconds(run, now.value)
    if (seconds === null) return '—'
    const unit = (value: number, name: 'hour' | 'minute' | 'second') => new Intl.NumberFormat(locale.value, {
      style: 'unit', unit: name, unitDisplay: 'short', maximumFractionDigits: name === 'second' && seconds < 60 ? 1 : 0,
    }).format(value)
    if (seconds < 60) return unit(seconds, 'second')
    const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds % 3600 / 60)
    return [hours ? unit(hours, 'hour') : '', minutes ? unit(minutes, 'minute') : '', unit(Math.floor(seconds % 60), 'second')].filter(Boolean).join(' ')
  }
  return { formatStart, formatDuration }
}
