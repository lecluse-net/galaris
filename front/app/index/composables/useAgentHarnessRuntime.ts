import { computed, reactive, ref, watch, type Ref } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { agentService } from '@/app/agent/facade'
import type { Agent, ExecutorDriverInfo } from '@/app/agent/contracts'
import { useHarnessLogs } from '@/app/agent/interface'
import { harnessService, type HarnessAction, type HarnessCapability, type HarnessRuntimeState } from '@/app/harnesses'
import { sessionGeneration } from '@/core/api'
import { startVisiblePolling } from '@/core/util/facade'

interface AgentHarnessRuntimeOptions {
  agents: Readonly<Ref<Agent[]>>
  previewAgentId: Readonly<Ref<number | undefined>>
  canViewAgents: Readonly<Ref<boolean>>
  canEdit: Readonly<Ref<boolean>>
  canInspectAgent: (agent: Agent) => boolean
  canManageAgent: (agent: Agent) => boolean
  loadCatalogue: () => Promise<unknown>
}

export function useAgentHarnessRuntime({
  agents, previewAgentId, canViewAgents, canEdit, canInspectAgent, canManageAgent, loadCatalogue,
}: AgentHarnessRuntimeOptions) {
  const $q = useQuasar()
  const { t } = useI18n()
  const drivers = ref<ExecutorDriverInfo[]>([])
  const harnessStates = reactive<Record<number, HarnessRuntimeState>>({})
  const unavailableHarnessManagerAgentIds = reactive(new Set<number>())
  const harnessActionLoading = reactive<Record<number, HarnessAction | undefined>>({})
  const fleetRestarting = ref(false)
  const agentIds = computed(() => new Set(agents.value.map(agent => agent.id)))
  const statusRequests = new Map<number, symbol>()
  let context = 0

  function currentContext() {
    const generation = context
    const session = sessionGeneration()
    const preview = previewAgentId.value
    return () => canViewAgents.value && context === generation
      && sessionGeneration() === session && previewAgentId.value === preview
  }

  const isManagedRuntime = (agent: Agent): boolean => (
    canInspectAgent(agent) && (harnessStates[agent.id]?.managed
      ?? drivers.value.some(driver => driver.name === agent.agent_driver && driver.manages_runtime))
  )

  const managedAgents = computed(() => agents.value.filter(agent => (
    isManagedRuntime(agent) && canManageAgent(agent)
  )))

  const managedRuntimeAgents = computed(() => agents.value.filter(isManagedRuntime))

  const harnessManagerUnavailable = computed(() => managedRuntimeAgents.value.some(
    agent => unavailableHarnessManagerAgentIds.has(agent.id),
  ))

  function stateFor(agentId: number): HarnessRuntimeState {
    return harnessStates[agentId] ?? {
      status: 'loading',
      lifecycle_status: 'internal',
      managed: false,
      capabilities: [],
      last_error: null,
    }
  }

  const harnessState = (agent: Agent) => stateFor(agent.id)

  function markHarnessSelectionPending(agentId: number): void {
    statusRequests.delete(agentId)
    harnessStates[agentId] = { ...stateFor(agentId), status: 'loading', available_actions: [] }
  }

  const hasHarnessCapability = (agent: Agent, capability: HarnessCapability): boolean => (
    harnessState(agent).capabilities.includes(capability)
  )

  const harnessStatusLabel = (status: string): string => {
    if (['absent', 'provisioning', 'deprovisioning', 'error'].includes(status)) {
      return t(`agent.harness.lifecycle.${status}`)
    }
    return t(`agent.harness.status.${status || 'unknown'}`)
  }

  const harnessStatusColor = (status: string): string => {
    if (status === 'running') return 'positive'
    if (status === 'error') return 'negative'
    if (status === 'stopped') return 'grey-7'
    if (status === 'absent' || status === 'disabled') return 'grey-5'
    return 'warning'
  }

  const harnessStatusIcon = (status: string): string => {
    if (status === 'running') return 'check_circle'
    if (status === 'stopped') return 'stop_circle'
    if (status === 'absent' || status === 'disabled') return 'radio_button_unchecked'
    if (status === 'loading') return 'hourglass_top'
    return 'help_outline'
  }

  const hasHarnessAction = (agent: Agent, action: HarnessAction): boolean => (
    harnessState(agent).available_actions?.includes(action) ?? false
  )

  const harnessRestartLabel = (agent: Agent): string => (
    t(harnessState(agent).status === 'absent' ? 'agent.harness.createRuntime' : 'agent.harness.restart')
  )

  const harnessLifecycleBusy = (agent: Agent): boolean => (
    ['provisioning', 'deprovisioning'].includes(harnessState(agent).lifecycle_status)
  )

  async function fetchHarnessStatus(agent: Agent, silent = false): Promise<void> {
    if (!canViewAgents.value || !canInspectAgent(agent)) return
    if (!silent) markHarnessSelectionPending(agent.id)
    const inContext = currentContext()
    const request = Symbol()
    statusRequests.set(agent.id, request)
    const current = () => inContext() && statusRequests.get(agent.id) === request
      && agentIds.value.has(agent.id)
    try {
      const { data } = await harnessService.status(agent.id)
      if (!current()) return
      harnessStates[agent.id] = data
      unavailableHarnessManagerAgentIds.delete(agent.id)
    } catch (error: unknown) {
      if (!current()) return
      const serviceUnavailable = isAxiosError(error) && error.response?.status === 503
      let managed = isManagedRuntime(agent)
      if (serviceUnavailable && !managed) {
        try {
          managed = (await harnessService.selection(agent.id)).data.containerized
        } catch {
          // Keep the last known runtime kind when the persisted selection cannot be read.
        }
      }
      if (!current()) return
      if (managed && serviceUnavailable) {
        unavailableHarnessManagerAgentIds.add(agent.id)
      } else {
        unavailableHarnessManagerAgentIds.delete(agent.id)
      }
      harnessStates[agent.id] = {
        status: 'unknown',
        lifecycle_status: harnessState(agent).lifecycle_status,
        managed,
        capabilities: harnessState(agent).capabilities,
        last_error: harnessState(agent).last_error,
      }
    } finally {
      if (statusRequests.get(agent.id) === request) statusRequests.delete(agent.id)
    }
  }

  async function runHarnessAction(agent: Agent, action: HarnessAction): Promise<void> {
    if (!canManageAgent(agent) || harnessActionLoading[agent.id] || !hasHarnessAction(agent, action)) return
    const current = currentContext()
    statusRequests.delete(agent.id)
    harnessActionLoading[agent.id] = action
    try {
      await harnessService.action(agent.id, action)
      if (!current()) return
      const state = harnessState(agent)
      harnessStates[agent.id] = {
        ...state,
        available_actions: [],
        status: action === 'stop' ? state.status : 'provisioning',
        lifecycle_status: action === 'stop' ? state.lifecycle_status : 'provisioning',
        last_error: null,
      }
      $q.notify({ type: 'positive', message: t(`agent.harness.action.${action}Queued`) })
    } catch {
      if (!current()) return
      await fetchHarnessStatus(agent, true)
      if (current()) $q.notify({ type: 'negative', message: t(`agent.harness.action.${action}Error`) })
    } finally {
      if (current()) delete harnessActionLoading[agent.id]
    }
  }

  async function restartFleet(): Promise<void> {
    if (!canEdit.value || fleetRestarting.value) return
    const current = currentContext()
    fleetRestarting.value = true
    try {
      await Promise.all(
        managedAgents.value
          .filter(agent => hasHarnessAction(agent, 'restart'))
          .map(agent => runHarnessAction(agent, 'restart')),
      )
    } finally {
      if (current()) fleetRestarting.value = false
    }
  }

  const { showHarnessLogsDialog, harnessLogs, harnessLogsLoading, harnessLogsAgentName,
    fetchHarnessLogs, openHarnessLogs, closeHarnessLogs } = useHarnessLogs(
      async agentId => (await harnessService.logs(agentId)).data.lines,
      (agent, failed) => harnessState(agent).last_error || (failed
        ? t('agent.harness.logsError') : harnessStatusLabel(harnessState(agent).lifecycle_status)),
    )

  function harnessLogColor(line: string): string {
    if (/error|exception|traceback|critical/i.test(line)) return '#f28b82'
    if (/warning|warn/i.test(line)) return '#fdd663'
    if (/info/i.test(line)) return '#a8d8a8'
    return '#d4d4d4'
  }

  watch([canViewAgents, previewAgentId], async ([allowed], _, onCleanup) => {
    if (!allowed) return
    const current = currentContext()
    let stopPolling: (() => void) | undefined
    onCleanup(() => {
      context++
      stopPolling?.()
      closeHarnessLogs()
      statusRequests.clear()
      drivers.value = []
      unavailableHarnessManagerAgentIds.clear()
      for (const id of Object.keys(harnessStates)) delete harnessStates[Number(id)]
      for (const id of Object.keys(harnessActionLoading)) delete harnessActionLoading[Number(id)]
      fleetRestarting.value = false
    })
    await loadCatalogue()
    if (!current()) return
    const metadata = await agentService.getDrivers().then(response => response.data, () => [])
    if (!current()) return
    drivers.value = metadata
    // The shared network driver can represent container runtimes. Inspect the
    // internal driver if its metadata could not load.
    const agentsToInspect = agents.value.filter(agent => canInspectAgent(agent) && (agent.agent_driver !== 'internal'
      || drivers.value.find(driver => driver.name === agent.agent_driver)?.manages_runtime !== false))
    await Promise.all(agentsToInspect.map(agent => fetchHarnessStatus(agent)))
    if (!current()) return
    stopPolling = startVisiblePolling(async () => {
      if (!current()) return
      await Promise.all(managedRuntimeAgents.value
        .filter(agent => !harnessActionLoading[agent.id])
        .map(agent => fetchHarnessStatus(agent, true)))
    }, 5000)
  }, { immediate: true })

  return {
    isManagedRuntime, managedAgents, harnessManagerUnavailable, harnessState, harnessStatusColor, harnessStatusIcon,
    harnessStatusLabel, hasHarnessCapability, hasHarnessAction, harnessRestartLabel, harnessLifecycleBusy,
    harnessActionLoading, runHarnessAction, restartFleet, fleetRestarting, markHarnessSelectionPending,
    fetchHarnessStatus, showHarnessLogsDialog, harnessLogs, harnessLogsLoading, harnessLogsAgentName,
    fetchHarnessLogs, openHarnessLogs, closeHarnessLogs, harnessLogColor,
  }
}
