import { markRaw } from 'vue'
import api, { sessionGeneration } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import type { AgentSelectionOption } from '@/app/agent'
import type { Composer } from 'vue-i18n'
import ActionAuthorizations from '../components/ActionAuthorizations.vue'
import connectionService, { saveFunctionPolicy, type FunctionState, type EffectiveFunctionState } from './connectionService'
import { answerPermission, deletePermission, listPermissions, revokeRuntimePermission } from './permissionService'
import { filterPermissionEntries, type PermissionControl, type PermissionEntry, type PermissionPanelDefinition, type PermissionQuery } from './permissionDashboard'

interface CatalogueConnection {
  tool_id: number; tool_code: string; tool_label: string; description: string; connection_id: number | null
  active: boolean; can_disable: boolean; parameters: Record<string, string | null>
  parameter_sources?: Record<string, string>
  management_scope?: { value: string; configured: string | null; default: string; description: string; options: { value: string; label: string }[] } | null
}
interface CatalogueCapability {
  id: string; tool_id: number; tool_label: string; connection_id: number | null; name: string; description: string
  capability_kind: 'tool' | 'resource' | 'prompt'; connection_state: FunctionState; global_state: FunctionState
  default_state: EffectiveFunctionState; effective_state: EffectiveFunctionState; policy_state: EffectiveFunctionState
  policy_source: string; available: boolean; runtime_supported: boolean
}
interface Catalogue { connections: CatalogueConnection[]; capabilities: CatalogueCapability[]; unavailable_catalogs: string[] }
interface RuntimePolicy {
  id: string; agent_id: number; runtime: string; capability_name: string; allowed: boolean | null
  remembered_allowed: boolean | null; active: boolean; remembered: boolean; can_decide: boolean; can_revoke: boolean
}

export function createPermissionDashboard(t: Composer['t'], agents: AgentSelectionOption[]) {
  const authorize = usePrivilegeStore()
  const readPrivileges = [privileges.PERMISSION_ACCESS, privileges.PERMISSION_DECIDE, privileges.PERMISSION_REVOKE]
  const canDecide = () => authorize.hasPrivilege(privileges.PERMISSION_DECIDE)
  const canRevoke = () => authorize.hasPrivilege(privileges.PERMISSION_REVOKE)
  const canConfigure = () => authorize.hasPrivilege(privileges.CONNECTION_EDIT)
  const policyState = (state: EffectiveFunctionState): PermissionEntry['state'] => state === 'enabled' ? 'allowed' : state === 'disabled' ? 'denied' : 'ask'
  const policyLabel = (state: FunctionState) => t(`permissions.dashboard.policies.${state}`)
  const policyOptions = () => [
    { value: 'enabled', label: t('permissions.dashboard.allow'), disable: !canDecide() },
    { value: 'disabled', label: t('permissions.dashboard.deny'), disable: !canDecide() && !canRevoke() },
    { value: 'ask', label: t('permissions.dashboard.ask'), disable: !canDecide() && !canRevoke() },
  ]
  let catalogueKey = '', catalogueRequest: Promise<Catalogue> | undefined, controller: AbortController | undefined
  function invalidate() { controller?.abort(); catalogueRequest = undefined; catalogueKey = '' }
  async function catalogue(query: PermissionQuery): Promise<Catalogue> {
    const key = `${sessionGeneration()}:${query.agentId}`
    if (!catalogueRequest || key !== catalogueKey) {
      invalidate(); catalogueKey = key; controller = new AbortController()
      const request = api.get<Catalogue>(`/tools/agents/${query.agentId}/permissions`, { signal: controller.signal }).then(response => response.data)
      catalogueRequest = request
      void request.catch(() => { if (catalogueRequest === request) catalogueRequest = undefined })
    }
    const result = await catalogueRequest
    query.signal.throwIfAborted()
    return result
  }
  const panels: PermissionPanelDefinition[] = [
    { id: 'approvals', title: 'permissions.pendingApprovals', icon: 'pending_actions', order: 10, privileges: readPrivileges,
      component: markRaw(ActionAuthorizations), componentProps: { embedded: true, agents } },
    { id: 'functions', title: 'permissions.dashboard.functions', icon: 'hub', order: 60, privileges: readPrivileges,
      filterTools: true, groupTools: true,
      async load(query) {
        const data = await catalogue(query)
        const connections = data.connections.filter(row => row.connection_id !== null)
        const byId = new Map(connections.map(row => [row.tool_id, row]))
        const parents = connections.map((row): PermissionEntry => {
          const controls: PermissionControl[] = [{ id: 'connection', label: t('connection.activeConnection'), value: row.active ? 'enabled' : 'disabled',
            options: [{ value: 'enabled', label: t('connection.active') }, { value: 'disabled', label: t('connection.inactive') }],
            disabled: !canConfigure() || !row.can_disable,
            save: value => connectionService.updateConnection(row.connection_id!, { active: value === 'enabled' }) }]
          const scope = row.management_scope
          if (scope) controls.push({ id: 'scope', value: scope.configured ?? 'default',
            label: t('permissions.dashboard.editManagementScope', { tool: row.tool_label }),
            hint: scope.description ? t(scope.description) : t('permissions.dashboard.managementScopeHint'),
            options: [{ value: 'default', label: t('permissions.dashboard.defaultScope', { value: t(`permissions.dashboard.values.${scope.default}`) }) },
              ...scope.options.map(option => ({ value: option.value, label: option.label ? t(option.label) : t(`permissions.dashboard.values.${option.value}`) }))],
            disabled: !row.active || !canConfigure() || !authorize.hasPrivilege(privileges.AGENT_MANAGE_ALL),
            save: value => api.put(`/connections/${row.connection_id}/management-scope`, { value: value === 'default' ? null : value }) })
          const parameters = Object.entries(row.parameters).filter(([key]) => key !== 'tools.management_scope'
            && (!query.customizedOnly || row.parameter_sources?.[key] === 'connection')).map(([key, value]) => {
            const known = ['allow', 'ask', 'true', 'false', 'block', 'team', 'all', 'none', 'personal', 'usage']
            const display = value !== null && known.includes(value.toLowerCase()) ? t(`permissions.dashboard.values.${value.toLowerCase()}`) : value ?? '—'
            const source = row.parameter_sources?.[key]
            return `${t(`permissions.dashboard.parameters.${key.replaceAll('.', '_')}`)}: ${display}${source ? ` · ${t(`permissions.dashboard.origins.${source}`)}` : ''}`
          })
          return { id: String(row.tool_id), toolId: row.tool_id, title: row.tool_label, scope: row.tool_code,
            customized: (!row.active && row.can_disable) || (scope?.configured != null && scope.configured !== scope.default),
            description: parameters.join('\n'), state: row.active ? 'allowed' : 'denied',
            origin: t(row.can_disable ? 'permissions.dashboard.agentRule' : 'permissions.dashboard.systemRule'),
            note: row.active ? undefined : t('permissions.dashboard.connectionInactive'), controls }
        })
        const functions = data.capabilities.filter(row => row.connection_id !== null && byId.has(row.tool_id)).map((row): PermissionEntry => {
          const connection = byId.get(row.tool_id)!
          return { id: row.id, toolId: row.tool_id, title: row.name, description: row.description,
            customized: connection.active && row.policy_source === 'connection' && row.connection_state !== 'default'
              && row.connection_state !== (row.global_state === 'default' ? row.default_state : row.global_state),
            scope: `${row.tool_label} · ${t(`connection.auth.kind.${row.capability_kind}`)}`, state: policyState(row.effective_state),
            origin: `${t(`permissions.dashboard.origins.${row.policy_source}`)} · ${t('permissions.dashboard.global')}: ${policyLabel(row.global_state)}`,
            note: [!connection.active ? t('permissions.dashboard.connectionInactive') : '',
              !row.runtime_supported ? t('permissions.dashboard.runtimeUnsupported') : '',
              !row.available ? t('permissions.dashboard.catalogUnverified') : '',
              `${t('permissions.dashboard.configuredRule')}: ${policyLabel(row.policy_state)}`].filter(Boolean).join('\n'),
            controls: [{ id: 'policy', label: t('permissions.decision'), value: row.connection_state,
              options: [...policyOptions(), { value: 'default', label: t('permissions.dashboard.inherit'), disable: !canDecide() }],
              save: value => saveFunctionPolicy({ id: row.connection_id!, agent_id: query.agentId, tool_id: row.tool_id, active: connection.active },
                { name: row.name, capability_kind: row.capability_kind }, { scope: 'connection', state: value as FunctionState }) }] }
        })
        const allMatches = filterPermissionEntries([...parents, ...functions], { ...query, offset: 0, limit: parents.length + functions.length, state: 'all' })
        const parentIds = new Set(parents.map(row => row.id))
        const matchedParents = new Set(allMatches.items.filter(row => parentIds.has(row.id)).map(row => row.id))
        const matchedFunctions = new Set(allMatches.items.filter(row => !parentIds.has(row.id)).map(row => row.id))
        const groups = parents.map(parent => ({ ...parent, children: functions.filter(row => row.toolId === parent.toolId && matchedFunctions.has(row.id)
          && (query.state === 'all' || query.state === row.state)) }))
          .filter(parent => parent.children.length > 0 || (matchedParents.has(parent.id) && (query.state === 'all' || parent.state === query.state)))
        return { items: groups, total: groups.length, counts: allMatches.counts, customizedCount: allMatches.customizedCount,
          tools: connections.map(row => ({ value: row.tool_id, label: `${row.tool_label} (${row.tool_code})` })),
          warnings: data.unavailable_catalogs.length ? [t('permissions.dashboard.catalogUnavailable', { tools: data.unavailable_catalogs.join(', ') })] : [] }
      } },
    { id: 'runtime', title: 'permissions.runtimePermissions', icon: 'smart_toy', order: 40, privileges: readPrivileges,
      async load(query) {
        const policies = (await api.get<RuntimePolicy[]>('/tools/action-authorizations/runtime-policies', { params: { agent_id: query.agentId }, signal: query.signal })).data
        const rows = policies.map((row): PermissionEntry => ({ id: row.id, title: row.capability_name, scope: row.runtime,
          customized: row.remembered,
          state: row.allowed === null ? 'ask' : row.allowed ? 'allowed' : 'denied',
          origin: t(row.remembered && row.active ? 'permissions.dashboard.agentRule' : 'permissions.dashboard.softwareRule'),
          note: row.remembered && !row.active ? t('permissions.runtimePermissionStale') : undefined,
          controls: [{ id: 'policy', label: t('permissions.decision'), value: row.allowed === null ? 'ask' : row.allowed ? 'enabled' : 'disabled',
            options: [
              { value: 'enabled', label: t('permissions.dashboard.allow'), disable: !row.can_decide || !canDecide() },
              { value: 'disabled', label: t('permissions.dashboard.deny'), disable: !row.can_decide || !canDecide() },
              { value: 'ask', label: t('permissions.dashboard.ask'), disable: row.remembered && (!row.can_revoke || !canRevoke()) },
            ],
            save: value => value === 'ask' ? revokeRuntimePermission(row.id) : api.put('/tools/action-authorizations/runtime-policies',
              { agent_id: query.agentId, runtime: row.runtime, capability_name: row.capability_name, allowed: value === 'enabled' }) }] }))
        return { ...filterPermissionEntries(rows, query), warnings: [t('permissions.dashboard.runtimeDefault')] }
      } },
    { id: 'contacts-network', title: 'permissions.dashboard.contactsNetwork', icon: 'public', order: 50, privileges: readPrivileges,
      async load(query) {
        const page = await listPermissions({ agent_id: query.agentId, q: query.search, offset: query.offset, limit: query.limit,
          ...(query.customizedOnly ? { pending: false } : query.state === 'pending' ? { pending: true } : {}),
          ...(query.state === 'allowed' ? { allowed: true } : query.state === 'denied' ? { allowed: false } : {}),
        }, query.signal)
        const rows = page.items.map((row): PermissionEntry => {
          const control: PermissionControl = row.allowed === null ? {
            id: 'policy', label: t('permissions.decision'), value: 'pending',
            options: [{ value: 'pending', label: t('permissions.dashboard.states.pending'), disable: true },
              ...(row.options ?? []).map(option => ({ value: option.id, label: option.label, disable: !row.can_answer || !canDecide() }))],
            save: value => answerPermission(row.id, value),
          } : {
            id: 'policy', label: t('permissions.decision'), value: row.allowed ? 'enabled' : 'disabled',
            options: [
              { value: 'enabled', label: t('permissions.dashboard.allow'), disable: !row.can_decide || !canDecide() },
              { value: 'disabled', label: t('permissions.dashboard.deny'), disable: !row.can_decide || !canDecide() },
              { value: 'ask', label: t('permissions.dashboard.ask'), disable: !canRevoke() },
            ],
            save: value => value === 'ask' ? deletePermission(row.id) : api.put(`/messenger/permissions/${row.id}`, { allowed: value === 'enabled' }),
          }
          return { id: row.id, title: row.question, description: row.permission_key,
            scope: t(row.permission_key.startsWith('messenger-contact:') ? 'permissions.dashboard.contacts' : 'permissions.dashboard.network'),
            state: row.allowed === null ? 'pending' : row.allowed ? 'allowed' : 'denied',
            origin: row.approver_label, note: row.active === false ? t('permissions.runtimePermissionStale') : undefined, controls: [control] }
        })
        const hidden = query.state === 'ask' || (query.customizedOnly && query.state === 'pending')
        return { items: hidden ? [] : rows, total: hidden ? 0 : page.total,
          customizedCount: (page.counts?.allowed ?? 0) + (page.counts?.denied ?? 0),
          counts: { ...(page.counts ?? { [query.state === 'all' ? 'pending' : query.state]: page.total }), ...(query.customizedOnly ? { pending: 0 } : {}) } }
      } },
  ]
  return { panels: panels.sort((left, right) => left.order - right.order), invalidate, dispose: invalidate }
}
