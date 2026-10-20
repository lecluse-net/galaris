export interface ContextAction {
  key: string
  label: string
  icon: string
  run: () => unknown
  disabled?: boolean
  negative?: boolean
  separator?: boolean
  shortcut?: string
}
