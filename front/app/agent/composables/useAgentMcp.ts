import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTableColumn } from 'quasar'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { showConfirmationDialog } from '@/core/util/facade'
import { mcpTokenService, type AgentMcpToken } from '../services/mcpTokenService'

/** Agent-scoped credentials never survive closing or changing the edited agent. */
export function useAgentMcp(agent: () => { id: number | null; code: string }, canManage: () => boolean, active: () => boolean) {
  const { t, locale } = useI18n(), $q = useQuasar()
  const mcpTokens = ref<AgentMcpToken[]>([]), pending = ref(0)
  const mcpTokensError = ref(false)
  const mcpTokensLoading = computed(() => pending.value > 0)
  const showCreateMcpTokenDialog = ref(false), newMcpTokenLabel = ref('')
  const showNewMcpTokenDialog = ref(false), newMcpTokenValue = ref('')
  let context = 0, read = 0
  function reset(): void {
    context++; read++; pending.value = 0; mcpTokens.value = []
    mcpTokensError.value = false
    showCreateMcpTokenDialog.value = false; showNewMcpTokenDialog.value = false
    newMcpTokenLabel.value = ''; newMcpTokenValue.value = ''
  }
  watch([() => agent().id, active, canManage], reset, { flush: 'sync' })
  let session = sessionGeneration()
  function sessionChanged(): void {
    const next = sessionGeneration()
    if (session !== next) { session = next; reset() }
  }
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged)
  onBeforeUnmount(() => { reset(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, sessionChanged) })
  watch(showNewMcpTokenDialog, open => { if (!open) newMcpTokenValue.value = '' }, { flush: 'sync' })
  const mcpEndpointUrl = computed(() => `${window.location.origin}/api/mcp/${agent().code || ''}`)
  const mcpConfigSnippet = computed(() => JSON.stringify({ mcpServers: {
    [agent().code || 'agent']: { type: 'http', url: mcpEndpointUrl.value, headers: { Authorization: 'Bearer <TOKEN>' } },
  } }, null, 2))
  const mcpTokenColumns = computed<QTableColumn[]>(() => [
    { name: 'label', label: t('agent.mcp.colLabel'), field: 'label', align: 'left' },
    { name: 'token', label: t('agent.mcp.colToken'), field: 'token', align: 'left' },
    { name: 'enabled', label: t('agent.mcp.colState'), field: 'enabled', align: 'center' },
    { name: 'created_at', label: t('agent.mcp.colCreatedAt'), field: 'created_at', align: 'left' },
    { name: 'actions', label: t('common.actions'), field: 'actions', align: 'right' },
  ])
  function capture() {
    const id = agent().id, generation = context, session = sessionGeneration()
    if (id === null || !active() || !canManage()) return null
    return { id, current: () => generation === context && session === sessionGeneration() && active() && canManage() }
  }
  function formatDateTime(value: string): string { return new Date(value).toLocaleString(locale.value) }
  function copyText(value: string): void {
    void navigator.clipboard.writeText(value).then(() => $q.notify({ type: 'positive', message: t('agent.mcp.copied') }))
      .catch(() => $q.notify({ type: 'negative', message: t('agent.mcp.copyFailed') }))
  }
  async function loadMcpTokens(): Promise<void> {
    const request = capture(), sequence = ++read
    if (!request) return
    mcpTokensError.value = false
    pending.value++
    try {
      const { data } = await mcpTokenService.listTokens(request.id)
      if (request.current() && sequence === read) mcpTokens.value = data
    } catch {
      if (request.current() && sequence === read) mcpTokensError.value = true
    } finally { if (request.current()) pending.value-- }
  }
  function openCreateMcpToken(): void {
    if (!capture()) return
    newMcpTokenLabel.value = ''; showCreateMcpTokenDialog.value = true
  }
  async function confirmCreateMcpToken(): Promise<void> {
    const request = capture()
    if (!request || mcpTokensLoading.value) return
    pending.value++; read++
    try {
      const { data } = await mcpTokenService.createToken(request.id, newMcpTokenLabel.value ? { label: newMcpTokenLabel.value } : {})
      if (!request.current()) return
      newMcpTokenValue.value = data.token; showCreateMcpTokenDialog.value = false; showNewMcpTokenDialog.value = true
      await loadMcpTokens()
    } catch {
      if (request.current()) $q.notify({ type: 'negative', message: t('agent.mcp.createError') })
    } finally { if (request.current()) pending.value-- }
  }
  async function toggleMcpToken(token: AgentMcpToken): Promise<void> {
    const request = capture()
    if (!request || mcpTokensLoading.value) return
    pending.value++; read++
    try {
      const { data } = await mcpTokenService.updateToken(request.id, token.id, { enabled: !token.enabled })
      if (!request.current()) return
      read++
      mcpTokens.value = mcpTokens.value.map(item => item.id === token.id ? data : item)
    } catch {
      if (request.current()) $q.notify({ type: 'negative', message: t('agent.mcp.toggleError') })
    } finally { if (request.current()) pending.value-- }
  }
  function deleteMcpToken(token: AgentMcpToken): void {
    const request = capture()
    if (!request || mcpTokensLoading.value) return
    showConfirmationDialog({ title: t('common.deleteConfirmTitle'), message: t('agent.mcp.deleteConfirm'), cancel: true,
      ok: { label: t('common.delete'), color: 'negative' },
    }).onOk(async () => {
      if (!request.current() || mcpTokensLoading.value) return
      pending.value++; read++
      try {
        await mcpTokenService.deleteToken(request.id, token.id)
        if (!request.current()) return
        read++; mcpTokens.value = mcpTokens.value.filter(item => item.id !== token.id)
        $q.notify({ type: 'positive', message: t('agent.mcp.deleted') })
      } catch {
        if (request.current()) $q.notify({ type: 'negative', message: t('agent.mcp.deleteError') })
      } finally { if (request.current()) pending.value-- }
    })
  }
  return { mcpTokens, mcpTokensLoading, mcpTokensError, showCreateMcpTokenDialog, newMcpTokenLabel, showNewMcpTokenDialog, newMcpTokenValue,
    mcpEndpointUrl, mcpConfigSnippet, mcpTokenColumns, formatDateTime, copyText, loadMcpTokens, openCreateMcpToken,
    confirmCreateMcpToken, toggleMcpToken, deleteMcpToken }
}
