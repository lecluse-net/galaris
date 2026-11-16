import { useI18n } from 'vue-i18n'
import type { MemoryFinding, MemoryFindingKind } from './types'

export function useFindingPresentation() {
  const { t, locale } = useI18n()
  return {
    findingIcon: (kind: MemoryFindingKind): string => ({ duplicate: 'content_copy', contradiction: 'compare_arrows', aging: 'history' })[kind],
    findingColor: (kind: MemoryFindingKind): string => ({ duplicate: 'solaire-orange', contradiction: 'solaire-red', aging: 'solaire-gray' })[kind],
    findingLabel(finding: MemoryFinding): string {
      const label = t(`memory.findings.kinds.${finding.kind}`)
      return finding.score === null ? label : `${label} · ${new Intl.NumberFormat(locale.value, { style: 'percent', maximumFractionDigits: 1 }).format(finding.score)}`
    },
  }
}
