import { provide } from 'vue'
import { contextHelpKey } from '@/core/util'
import { useHelpStore } from './stores/helpStore'

export function provideContextHelp(): void {
  provide(contextHelpKey, useHelpStore())
}
