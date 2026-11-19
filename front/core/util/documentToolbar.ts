interface CommandBase {
  id: string
  label: string
  disabled?: boolean
  /** Actions that can run on a read-only document must opt in. */
  readOnly?: boolean
}

export interface DocumentToolbarButton extends CommandBase {
  kind: 'button' | 'toggle'
  icon: string
  pressed?: boolean
  showLabel?: boolean
  primary?: boolean
  busy?: boolean
  /** Put this button in More tools below the desktop breakpoint. */
  secondary?: boolean
}

export type DocumentToolbarCommand = DocumentToolbarButton | (CommandBase & (
  { kind: 'color'; value: string } |
  { kind: 'range'; value: number; min: number; max: number; step?: number }
))

export interface DocumentToolbarGroup {
  id: string
  label: string
  commands: readonly DocumentToolbarCommand[]
}
