<template>
  <div class="memory-decision-preview">
    <q-badge v-if="!operations.length" color="grey-7" class="decision-badge">
      IGNORE
    </q-badge>
    <div
      v-for="(operation, index) in operations"
      v-else
      :key="`${operation.action}-${operation.targetId || operation.label}-${index}`"
      class="decision-operation"
    >
      <div class="decision-heading">
        <q-badge :color="operation.action === 'CREATE' ? 'positive' : 'primary'" class="decision-badge">
          {{ operation.action }}
        </q-badge>
        <span class="decision-label">{{ operation.label }}</span>
        <span v-if="operation.meta" class="decision-meta">{{ operation.meta }}</span>
      </div>
      <div v-if="operation.reason" class="decision-reason">
        {{ operation.reason }}
        <q-tooltip max-width="560px">{{ operation.reason }}</q-tooltip>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EvaluationValue } from '../services/mechanismEvaluationService'

interface DecisionOperationPreview {
  action: 'CREATE' | 'LINK'
  label: string
  meta: string
  reason: string
  targetId: string
}

const { value, input = null } = defineProps<{
  value: EvaluationValue
  input?: EvaluationValue
}>()

const memoryLabels = computed(() => {
  const labels = new Map<string, string>()
  const memories = asRecord(input).existing_memories
  if (!Array.isArray(memories)) return labels
  for (const rawMemory of memories) {
    const memory = asRecord(rawMemory)
    const id = text(memory.id)
    if (id) labels.set(id, text(memory.title) || id)
  }
  return labels
})

const operations = computed<DecisionOperationPreview[]>(() => {
  const rawOperations = asRecord(value).operations
  if (!Array.isArray(rawOperations)) return []
  return rawOperations.flatMap<DecisionOperationPreview>(rawOperation => {
    const operation = asRecord(rawOperation)
    if (operation.action === 'LINK') {
      const targetId = text(operation.target_memory_id)
      const targetLabel = memoryLabels.value.get(targetId) || targetId || '—'
      return [{
        action: 'LINK' as const,
        label: targetLabel,
        meta: targetId && targetLabel !== targetId ? targetId : '',
        reason: text(operation.reason),
        targetId,
      }]
    }
    if (operation.action === 'CREATE') {
      return [{
        action: 'CREATE' as const,
        label: text(operation.title) || '—',
        meta: text(operation.memory_type),
        reason: text(operation.reason) || text(operation.content),
        targetId: '',
      }]
    }
    return []
  })
})

function asRecord(raw: unknown): Record<string, unknown> {
  if (typeof raw === 'string') {
    try {
      const parsed: unknown = JSON.parse(raw)
      return parsed != null && typeof parsed === 'object' && !Array.isArray(parsed)
        ? parsed as Record<string, unknown>
        : {}
    } catch {
      return {}
    }
  }
  return raw != null && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : {}
}

function text(raw: unknown): string {
  return typeof raw === 'string' ? raw.trim() : ''
}
</script>

<style scoped>
.memory-decision-preview {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.decision-operation {
  min-width: 0;
}

.decision-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.decision-badge {
  flex: 0 0 auto;
}

.decision-label {
  min-width: 0;
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.decision-meta {
  flex: 0 0 auto;
  color: #757575;
  font-family: monospace;
  font-size: 0.75rem;
}

.decision-reason {
  display: -webkit-box;
  margin-top: 2px;
  overflow: hidden;
  color: #616161;
  font-size: 0.75rem;
  line-height: 1.35;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
</style>
