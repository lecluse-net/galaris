import type { SettingField } from '@/core/params'

export const managedComposeFields: SettingField[] = [{
  name: 'harness.default.compose',
  labelKey: 'harnesses.catalog.composeLabel',
  input: 'code',
  codeLanguage: 'yaml',
  visibleLines: 16,
}]
