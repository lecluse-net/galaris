import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { useConsoleStore } from './stores/consoleStore'

function isEmbeddedExecutorInUse(): boolean {
  const store = useConsoleStore()
  void store.loadAvailability()
  return store.availability === true
}

const navigation: NavigationTree = {
  admin: {
    children: {
      executor: {
        label: 'nav.executor',
        description: 'nav.executor_desc',
        icon: 'terminal',
        to: '/console/executor',
        order: 30,
        privileges: [privileges.CONSOLE_ACCESS],
        visible: isEmbeddedExecutorInUse,
      },
    },
  },
}

export default navigation
