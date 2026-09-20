import type { InjectionKey } from 'vue'

/** Reactive account state supplied by the application at bootstrap. */
export interface ContextHelpState {
  readonly accountId: number | null
  readonly dismissed: string[]
  readonly pending: string[]
  readonly ready: boolean
  readonly loadError: boolean
  readonly saveErrors: string[]
  load(): Promise<void>
  dismiss(helpKey: string): Promise<void>
}

export const contextHelpKey: InjectionKey<ContextHelpState> = Symbol('context-help')
