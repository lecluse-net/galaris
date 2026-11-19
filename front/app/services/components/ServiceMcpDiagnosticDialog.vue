<template>
  <q-dialog v-model="open" :aria-labelledby="titleId">
    <q-card class="mcp-test-dialog galaris-dialog-card">
      <DialogHeader :title="$t('services.testMcpTitle')" :title-id="titleId" />

      <q-card-section class="q-gutter-y-md mcp-test-dialog__body galaris-dialog-body">
        <div class="text-body2 text-grey-7">{{ $t('services.testMcpIntro') }}</div>

        <div v-if="connectionParameters.length" class="q-gutter-y-sm">
          <div class="text-subtitle2">{{ $t('services.testMcpParameters') }}</div>
          <div v-for="param in connectionParameters" :key="param.name">
            <ConnectionParamInput :model-value="mcpTestParams[param.name]" :name="param.name" :definition="param" :tool-code="code" @update:model-value="updateParameter(param.name, $event)" />
            <code v-if="connectionParamLabel(code, param.name, param, t, te) !== param.name" class="text-caption">{{ param.name }}</code>
            <div v-if="param.description" class="text-caption">{{ param.description }}</div>
          </div>
        </div>

        <div v-if="transport !== 'stdio'" class="q-gutter-y-sm">
          <ManagedAgentSelect v-model="candidateAgentId" :label="$t('services.candidateAgent')" />
          <q-btn outline color="primary" :label="$t('services.candidatePrepare')"
            :disable="!canEdit || !candidateAgentId || preparingCandidate" :loading="preparingCandidate" @click="prepareCandidate" />
          <q-input v-if="candidateReference" :model-value="candidateReference" readonly outlined
            :label="$t('services.candidateReference')" :hint="$t('services.candidateExpiry')" />
          <div class="text-caption">{{ $t('services.candidateHint') }}</div>
          <q-banner v-if="candidateError" rounded class="bg-solaire-red-light text-negative">{{ candidateError }}</q-banner>
        </div>

        <q-banner
          v-if="mcpTestResult"
          rounded
          :class="mcpTestResult.success ? 'bg-solaire-green-light text-positive' : 'bg-solaire-red-light text-negative'"
        >
          <template #avatar>
            <q-icon :name="mcpTestResult.success ? 'check_circle' : 'error'" />
          </template>
          {{ mcpTestResult.message }}
        </q-banner>

        <q-banner v-else-if="mcpTestError" rounded class="bg-solaire-red-light text-negative">
          <template #avatar><q-icon name="error" /></template>
          {{ mcpTestError }}
        </q-banner>

        <q-list v-if="mcpTestResult?.diagnostics.length" bordered separator>
          <q-item
            v-for="(diagnostic, index) in mcpTestResult.diagnostics"
            :key="`${diagnostic.stage}-${index}`"
          >
            <q-item-section avatar>
              <q-icon
                :name="mcpDiagnosticIcon(diagnostic.status)"
                :color="mcpDiagnosticColor(diagnostic.status)"
                size="sm"
              />
            </q-item-section>
            <q-item-section>
              <q-item-label class="row items-center q-gutter-x-sm">
                <span class="text-weight-medium">
                  {{ $t(`services.testMcpStages.${diagnostic.stage}`) }}
                </span>
                <q-badge
                  outline
                  :color="mcpDiagnosticColor(diagnostic.status)"
                  :label="$t(`services.testMcpStatuses.${diagnostic.status}`)"
                />
              </q-item-label>
              <q-item-label caption>{{ diagnostic.message }}</q-item-label>
            </q-item-section>
            <q-item-section v-if="diagnostic.duration_ms !== null" side>
              <q-badge
                color="grey-7"
                :label="$t('services.testMcpDuration', { duration: diagnostic.duration_ms })"
              />
            </q-item-section>
          </q-item>
        </q-list>

        <div v-if="mcpTestResult?.tools.length">
          <div class="text-subtitle2 q-mb-sm">
            {{ $t('services.testMcpFunctionsFound', { count: mcpTestResult.tools.length }) }}
          </div>
          <q-list bordered separator>
            <q-item v-for="tool in mcpTestResult.tools" :key="tool.name">
              <q-item-section>
                <q-item-label class="text-weight-medium">{{ tool.name }}</q-item-label>
                <q-item-label v-if="tool.description" caption>{{ tool.description }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </div>
      </q-card-section>

      <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
        <q-btn outline color="primary"  :label="$t('common.close')" v-close-popup />
        <q-btn
          v-if="canEdit"
          color="secondary"
          icon="lan"
          :label="$t('services.testMcpRun')"
          :loading="testingMcp"
          @click="testMcpConnection"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, onScopeDispose, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail, sessionGeneration } from '@/core/api'
import { DialogHeader } from '@/core/util/facade'
import { ManagedAgentSelect } from '@/app/agent'
import ConnectionParamInput from './ConnectionParamInput.vue'
import { connectionParamLabel } from '../presentation'
import serviceApi from '../services/serviceApi'
import type { ConnectionParamDef, McpConfig, ServiceCreate, ServiceMcpTestDiagnosticStatus, ServiceMcpTestResponse } from '../services/serviceApi'

const open = defineModel<boolean>({ required: true })
const props = defineProps<{
  canEdit: boolean
  code: string
  transport: McpConfig['type']
  serviceId?: number
  parameters: readonly (ConnectionParamDef & { name: string })[]
  buildMcpConfig: () => McpConfig
  buildCandidateDefinition: () => ServiceCreate
}>()
const { t, te } = useI18n()
const titleId = useId()

const connectionParameters = computed(() => props.parameters.filter(param => param.name.trim() !== ''))
const mcpTestParams = ref<Record<string, string>>({})
const testingMcp = ref(false)
const mcpTestResult = ref<ServiceMcpTestResponse | null>(null)
const mcpTestError = ref('')
const candidateAgentId = ref<number | null>(null)
const candidateReference = ref('')
const preparingCandidate = ref(false)
const candidateError = ref('')
let diagnosticRequest = 0
let candidateRequest = 0

function clearDiagnostic(): void {
  diagnosticRequest++
  testingMcp.value = false
  mcpTestResult.value = null
  mcpTestError.value = ''
}

function clearCandidate(): void {
  candidateRequest++
  preparingCandidate.value = false
  candidateReference.value = ''
  candidateError.value = ''
}

watch(open, shown => {
  clearDiagnostic()
  clearCandidate()
  candidateAgentId.value = null
  mcpTestParams.value = shown ? Object.fromEntries(
    connectionParameters.value.map(param => [param.name, param.type === 'password' ? '' : param.default]),
  ) : {}
}, { immediate: true, flush: 'sync' })

watch(candidateAgentId, clearCandidate, { flush: 'sync' })
watch(() => props.canEdit, allowed => {
  if (!allowed) open.value = false
}, { flush: 'sync' })

onScopeDispose(() => {
  diagnosticRequest++
  candidateRequest++
})

function updateParameter(name: string, value: string | null | undefined): void {
  const normalized = value ?? ''
  if (mcpTestParams.value[name] === normalized) return
  mcpTestParams.value[name] = normalized
  clearDiagnostic()
  clearCandidate()
}

function requestParameters(): Record<string, string | null> {
  return Object.fromEntries(Object.entries(mcpTestParams.value).map(([name, value]) => [name, value === '' ? null : value]))
}

async function testMcpConnection(): Promise<void> {
  if (!open.value || !props.canEdit || testingMcp.value) return
  clearDiagnostic()
  const request = diagnosticRequest
  const session = sessionGeneration()
  const current = () => open.value && props.canEdit && diagnosticRequest === request && session === sessionGeneration()
  testingMcp.value = true
  try {
    const { data } = await serviceApi.testMcpConnection({
      service_id: props.serviceId,
      code: props.code.trim(),
      mcp_config: props.buildMcpConfig(),
      params: requestParameters(),
    })
    if (current()) mcpTestResult.value = data
  } catch (error) {
    if (current()) mcpTestError.value = apiErrorDetail(error) ?? t('services.testMcpError')
  } finally {
    if (current()) testingMcp.value = false
  }
}

async function prepareCandidate(): Promise<void> {
  const agentId = candidateAgentId.value
  if (!open.value || !props.canEdit || props.transport === 'stdio' || agentId === null || preparingCandidate.value) return
  clearCandidate()
  const request = candidateRequest
  const session = sessionGeneration()
  const current = () => open.value && props.canEdit && candidateRequest === request && session === sessionGeneration()
  preparingCandidate.value = true
  try {
    const { data } = await serviceApi.prepareMcpCandidate(agentId, props.buildCandidateDefinition(), requestParameters())
    if (current()) candidateReference.value = data.reference
  } catch {
    if (current()) candidateError.value = t('services.candidateError')
  } finally {
    if (current()) preparingCandidate.value = false
  }
}

function mcpDiagnosticIcon(status: ServiceMcpTestDiagnosticStatus): string {
  if (status === 'success') return 'check_circle'
  if (status === 'error') return 'cancel'
  if (status === 'warning') return 'warning'
  if (status === 'skipped') return 'remove_circle_outline'
  return 'info'
}

function mcpDiagnosticColor(status: ServiceMcpTestDiagnosticStatus): string {
  if (status === 'success') return 'positive'
  if (status === 'error') return 'negative'
  if (status === 'warning') return 'warning'
  if (status === 'skipped') return 'grey-6'
  return 'info'
}
</script>

<style scoped>
.mcp-test-dialog {
  width: 100%;
  max-width: 720px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.mcp-test-dialog__body {
  min-height: 0;
  overflow-y: auto;
}
</style>
