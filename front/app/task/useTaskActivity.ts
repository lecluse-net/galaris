import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { BaseRoom, websocket } from '@/core/websocket'
import { callExecutionResult, llmCallService, type LLMCall } from '@/app/llm'
import { taskService } from './services/taskService'
import { applyTaskLiveRunEvent, completedTaskAIResult, emptyAIResult, reconcileTaskAIResult, taskRunId, type TaskLiveRunEvent, type TaskLiveRunState } from './aiResult'
import { roomReferences, type TaskActivitySnapshot } from './activity'
import type { AIResult, Task } from './types'

class TaskRunRoom extends BaseRoom { readonly className = 'TaskRunRoom' }
const rooms = roomReferences(
  id => websocket.joinRoom(new TaskRunRoom(id)),
  id => websocket.leaveRoom(new TaskRunRoom(id)),
)

export function useTaskActivity(tasks: () => readonly Task[]) {
  const { t } = useI18n()
  const snapshots = ref<Record<string, TaskActivitySnapshot>>({})
  const live = ref<Record<string, TaskLiveRunState>>({})
  const fallback = ref<Record<string, AIResult>>({})
  const unavailable = ref(false)
  const observedActivity = new Map<string, { runId: string; attemptId: string | null; at: string }>()
  let ids = new Set<string>()
  let joined = new Set<string>()
  let generation = 0
  let selection = ''
  let disposed = false
  let inFlight = false
  let refreshPending = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let buffered: TaskLiveRunEvent[] | null = null

  function expectedRunId(task: Task): string | null {
    const snapshot = snapshots.value[task.id]
    // Run activation can be persisted after the Task event that opened the row.
    // The authorized activity read carries the identity even before a new Task event.
    if (snapshot && snapshot.revision >= task.revision) return snapshot.run_id
    return taskRunId(task)
  }

  function streamsNative(task: Task): boolean {
    const snapshot = snapshots.value[task.id]
    if (snapshot?.run_id === expectedRunId(task)) return snapshot.streams_ai_messages
    const identity = task.data?._agent_run_identity as { execution_target?: { metadata?: { streams_ai_messages?: boolean } } } | undefined
    return identity?.execution_target?.metadata?.streams_ai_messages !== false
  }

  function receive(event: TaskLiveRunEvent) {
    const task = tasks().find(item => item.id === event.task_id)
    if (!task || !streamsNative(task)) return
    const current = live.value[task.id] ?? null
    const next = applyTaskLiveRunEvent(current, event, null, expectedRunId(task),
      snapshots.value[task.id]?.latest_attempt?.id ?? null)
    if (next) {
      live.value[task.id] = next
      if (next !== current) {
        observedActivity.set(task.id, { runId: next.runId, attemptId: next.attemptId ?? null, at: new Date().toISOString() })
        const snapshot = snapshots.value[task.id]
        if (snapshot) applyObservedActivity(snapshot)
      }
    }
  }
  function applyObservedActivity(snapshot: TaskActivitySnapshot) {
    const observed = observedActivity.get(snapshot.task_id)
    if (observed?.runId === snapshot.run_id
      && observed.attemptId === (snapshot.latest_attempt?.id ?? null)
      && (!snapshot.last_activity_at || Date.parse(observed.at) > Date.parse(snapshot.last_activity_at))) {
      snapshot.last_activity_at = observed.at
    }
  }
  function onEvent(payload: { data?: TaskLiveRunEvent }) {
    const event = payload.data
    if (!event || !ids.has(event.task_id)) return
    if (buffered) buffered.push(event)
    // HTTP reconciliation must never hold up already-authorized live progress.
    receive(event)
    if (event.kind !== 'message') schedule()
  }
  function schedule() {
    if (disposed) return
    if (inFlight) { refreshPending = true; return }
    // A continuous stream must not postpone reconciliation indefinitely.
    timer ??= setTimeout(() => { timer = undefined; void refresh() }, 250)
  }
  function onCall(payload: { data?: Partial<LLMCall> }) {
    if (payload.data?.task_id && ids.has(payload.data.task_id)
      && snapshots.value[payload.data.task_id]?.streams_ai_messages === false) schedule()
  }
  function onCallProgress(payload: { data?: Partial<LLMCall> }) {
    const data = payload.data
    const taskId = data?.task_id
    if (!data || !taskId || !ids.has(taskId)) return
    const snapshot = snapshots.value[taskId]
    if (!snapshot?.run_id || snapshot.streams_ai_messages !== false || data.agent_run_id !== snapshot.run_id) return
    if (data.updated_at && (!snapshot.last_activity_at || Date.parse(data.updated_at) > Date.parse(snapshot.last_activity_at))) {
      observedActivity.set(taskId, { runId: snapshot.run_id, attemptId: snapshot.latest_attempt?.id ?? null, at: data.updated_at })
      applyObservedActivity(snapshot)
    }
    // Task text waits for a completed call. Only changed tools need another
    // HTTP projection; text-only progress can update the silence clock locally.
    if (data.tool_calls) schedule()
  }
  async function refresh() {
    if (disposed) return
    if (inFlight) { refreshPending = true; return }
    if (timer) clearTimeout(timer)
    timer = undefined
    if (!ids.size) {
      snapshots.value = {}
      unavailable.value = false
      return
    }
    const request = generation
    inFlight = true
    refreshPending = false
    buffered ??= []
    const selected = [...ids]
    try {
      const values: TaskActivitySnapshot[] = []
      for (let offset = 0; offset < selected.length; offset += 50) {
        values.push(...await taskService.getActivity(selected.slice(offset, offset + 50)))
      }
      if (disposed || request !== generation) return
      const events = buffered ?? []
      buffered = null
      const next: Record<string, TaskActivitySnapshot> = {}
      for (const value of values) {
        applyObservedActivity(value)
        next[value.task_id] = value
        // Replace before replaying events buffered across the HTTP snapshot.
        if (value.live) {
          const current = live.value[value.task_id]
          if (current?.runId !== value.live.run_id || (current.attemptId ?? null) !== (value.live.attempt_id ?? null)
            || current.sequence <= value.live.sequence) {
            live.value[value.task_id] = {
              runId: value.live.run_id, attemptId: value.live.attempt_id, sequence: value.live.sequence, result: value.live.result,
            }
          }
        } else if (live.value[value.task_id]?.runId !== value.run_id
          || (live.value[value.task_id]?.attemptId ?? null) !== (value.latest_attempt?.id ?? null)) {
          delete live.value[value.task_id]
        }
      }
      snapshots.value = next
      for (const event of events) receive(event)
      unavailable.value = values.length !== selected.length
      const custom = values.filter(value => !value.streams_ai_messages && value.run_id)
      const projected: Record<string, AIResult> = {}
      for (let offset = 0; offset < custom.length; offset += 50) {
        const batch = custom.slice(offset, offset + 50)
        const calls = await llmCallService.getByRuns(batch.map(item => item.task_id), batch.map(item => item.run_id!))
        if (disposed || request !== generation) return
        for (const value of batch) {
          value.calls_limited = calls.length >= 500
          const result = emptyAIResult()
          result.messages = calls.filter(call => call.task_id === value.task_id && call.agent_run_id === value.run_id)
            .flatMap(call => (callExecutionResult(call, t('task.activity.toolPending')).messages ?? [])
              .filter(message => Boolean(call.completed_at)
                || message.type !== 'text' && !(message.type === 'tool' && message.tool_name === 'thinking')))
          projected[value.task_id] = result
        }
      }
      if (!disposed && request === generation) fallback.value = projected
    } catch {
      if (!disposed && request === generation) {
        unavailable.value = true
        const events = buffered ?? []
        buffered = null
        for (const event of events) receive(event)
      }
    } finally {
      inFlight = false
      if (refreshPending && !disposed) schedule()
    }
  }
  function resultFor(task: Task): AIResult | null {
    const activity = snapshots.value[task.id]
    const run = live.value[task.id]
    const expected = expectedRunId(task)
    const native = streamsNative(task)
    const result = !native
      ? activity?.run_id === expected ? fallback.value[task.id] ?? null : null
      : run?.runId === expected ? run.result : null
    if (!native) {
      return { ...(task.execution_result ?? emptyAIResult()), messages: result?.messages ?? [] }
    }
    return completedTaskAIResult(reconcileTaskAIResult(task, result), ['SUCCESS', 'ERROR'].includes(task.status))
  }

  websocket.createWebsocket()
  websocket.onEvent('agent_run', 'event', onEvent)
  websocket.onEvent('llm_call', 'create', onCall)
  websocket.onEvent('llm_call', 'update', onCall)
  websocket.onEvent('llm_call', 'progress', onCallProgress)
  websocket.onEvent('llm_call', 'delete', schedule)
  websocket.onEvent('llm_call', 'cleanup', schedule)
  websocket.onConnect(schedule)
  const poll = setInterval(() => { if (joined.size) schedule() }, 15_000)
  watch(() => tasks().map(task => `${task.id}:${task.revision}:${task.status}:${taskRunId(task)}`).join('|'), () => {
    const nextSelection = tasks().map(task => `${task.id}:${taskRunId(task)}`).join('|')
    if (nextSelection !== selection) {
      selection = nextSelection
      generation++
      buffered = null
    }
    const next = new Set(tasks().map(task => task.id))
    const active = new Set(tasks().filter(task => !['SUCCESS', 'ERROR'].includes(task.status)).map(task => task.id))
    for (const id of joined) if (!active.has(id)) rooms.release(id)
    for (const id of active) if (!joined.has(id)) rooms.retain(id)
    for (const id of ids) if (!next.has(id)) {
      delete snapshots.value[id]; delete live.value[id]; delete fallback.value[id]; observedActivity.delete(id)
    }
    joined = active
    ids = next
    schedule()
  }, { immediate: true })
  onBeforeUnmount(() => {
    disposed = true
    generation++
    if (timer) clearTimeout(timer)
    clearInterval(poll)
    for (const id of joined) rooms.release(id)
    websocket.offEvent('agent_run', 'event', onEvent)
    websocket.offEvent('llm_call', 'create', onCall)
    websocket.offEvent('llm_call', 'update', onCall)
    websocket.offEvent('llm_call', 'progress', onCallProgress)
    websocket.offEvent('llm_call', 'delete', schedule)
    websocket.offEvent('llm_call', 'cleanup', schedule)
    websocket.offConnect(schedule)
  })
  return { snapshots, unavailable, resultFor, refresh }
}
