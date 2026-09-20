<template>
  <q-form @submit="onSubmit" class="q-gutter-md">
    <div class="row no-wrap" style="gap: 16px">
      <div class="col">
        <AgentSelect
          v-model="form.agent_id"
          :options="agentOptions"
          :label="t('connection.agent')"
          filled
          emit-value
          map-options
        />
      </div>
      <div class="col">
        <q-select
          v-model="form.tool_id"
          :options="toolOptions"
          option-value="id"
          option-label="label"
          :label="t('connection.tool')"
          filled
          emit-value
          map-options
          @update:model-value="onToolChange"
        />
      </div>
    </div>

    <div v-if="selectedTool?.code === 'console'" class="q-mt-md">
      <div class="text-subtitle2 q-mb-sm">{{ t('connection.console.targetTitle') }}</div>
      <div class="row q-col-gutter-md">
        <div v-for="target in consoleTargets" :key="target.value" class="col-12 col-sm-6">
          <q-card
            flat
            bordered
            class="console-target full-height cursor-pointer"
            :class="{ 'console-target--selected': consoleTarget === target.value }"
            @click="consoleTarget = target.value"
          >
            <q-card-section class="row no-wrap items-start">
              <div class="col">
                <div class="text-weight-medium">{{ target.label }}</div>
                <div class="text-caption text-grey-7 q-mt-xs">{{ target.description }}</div>
              </div>
              <q-radio v-model="consoleTarget" :val="target.value" color="primary" />
            </q-card-section>
          </q-card>
        </div>
      </div>
    </div>

    <q-banner
      v-if="selectedTool?.code === 'console' && consoleTarget === 'embedded'"
      rounded
      class="bg-blue-1 text-blue-9 q-mt-md"
    >
      <template #avatar><q-icon name="verified_user" /></template>
      {{ selectedAgentIsInternal
        ? t('connection.console.embeddedHint')
        : t('connection.console.internalAgentRequired') }}
    </q-banner>

    <!-- Dynamic configuration parameter table -->
    <div v-if="showSchemaParameters" class="q-mt-md">
      <div class="text-subtitle2 q-mb-sm">
        <q-icon name="settings" class="q-mr-xs" />
        {{ t('connection.configParams') }}
      </div>
      <div class="schema-params-table">
        <div class="schema-params-header row items-center">
          <div class="col-param">{{ t('connection.param') }}</div>
          <div class="col-value">{{ t('connection.value') }}</div>
        </div>
        <div v-for="param in connectionParameters" :key="param.name" class="schema-params-row row items-center">
          <div class="col-param">
            <div class="param-name">{{ param.name }}</div>
            <div v-if="param.description" class="param-desc text-grey-7">{{ localizedParamDescription(param) }}</div>
            <q-btn
              v-if="hasGlobalValue(param.name) && !isGloballyForced(param.name)"
              flat color="secondary" icon="undo"
              :label="t('connection.useGlobalValue')"
              @click="disableParamOverride(param.name)"
            />
          </div>
          <div class="col-value">
            <q-input
              v-if="param.type === 'password'"
              v-model="paramValues[param.name]"
              dense filled type="password"
              :placeholder="param.default !== undefined ? '********' : ''"
            />
            <q-input
              v-else-if="param.type === 'integer'"
              v-model.number="paramValues[param.name]"
              type="number" dense filled
              :placeholder="param.default !== undefined ? String(param.default) : ''"
            />
            <q-toggle
              v-else-if="param.type === 'boolean'"
              :model-value="paramValues[param.name] === 'true'"
              :label="paramValues[param.name] === 'true' ? t('common.yes') : t('common.no')"
              color="primary"
              @update:model-value="value => setBooleanParam(param.name, value)"
            />
            <q-select
              v-else-if="param.type === 'user'"
              v-model="paramValues[param.name]"
              :options="approverOptions"
              emit-value
              map-options
              clearable
              dense
              filled
              :loading="approversLoading"
              :placeholder="t('connection.mail.selectApprover')"
            />
            <q-input
              v-else
              v-model="paramValues[param.name]"
              dense filled
              :placeholder="param.default !== undefined ? String(param.default) : ''"
            />
          </div>
        </div>
      </div>
    </div>

    <q-expansion-item
      v-if="inheritedParameters.length && (selectedTool?.code !== 'console' || consoleTarget === 'external')"
      dense
      icon="public"
      :label="t('connection.inheritedParams', { count: inheritedParameters.length })"
      class="q-mt-md"
    >
      <q-card flat bordered>
        <q-list separator>
          <q-item v-for="param in inheritedParameters" :key="param.name">
            <q-item-section>
              <q-item-label>{{ param.name }}</q-item-label>
              <q-item-label caption>{{ inheritedValueLabel(param) }}</q-item-label>
            </q-item-section>
            <q-item-section side>
              <q-chip v-if="isGloballyForced(param.name)" dense color="negative" text-color="white">
                {{ t('connection.globalForced') }}
              </q-chip>
              <q-btn
                v-else-if="canEdit"
                flat color="primary" icon="edit"
                :label="t('connection.customizeGlobal')"
                @click="enableParamOverride(param)"
              />
            </q-item-section>
          </q-item>
        </q-list>
      </q-card>
    </q-expansion-item>

    <q-banner v-else-if="form.tool_id && selectedTool?.code !== 'console' && !showSchemaParameters" class="bg-grey-2 text-grey-8" dense>
      <template v-slot:avatar>
        <q-icon name="info" color="grey-6" />
      </template>
      {{ t('connection.noConfigParams') }}
    </q-banner>

    <q-card v-if="selectedTool?.code === 'console' && consoleTarget === 'external'" flat bordered>
      <q-card-section>
        <div class="text-subtitle2 q-mb-sm">{{ t('connection.console.title') }}</div>
        <div class="text-caption text-grey-7 q-mb-sm">
          {{ t('connection.console.automaticModeHint') }}
        </div>
        <div class="row q-gutter-sm">
          <q-btn
            v-if="canEdit && !isGloballyForced('known_host_key')"
            outline
            icon="fingerprint"
            :label="t('connection.console.scanHostKey')"
            :loading="consoleAction === 'scan'"
            :disable="!effectiveParamValue('host')"
            @click="scanHostKey"
          />
          <q-btn
            v-if="canEdit && !isGloballyForced('private_key') && effectiveParamValue('host') !== 'ssh-executor'"
            outline
            icon="key"
            :label="t('connection.console.generateKey')"
            :loading="consoleAction === 'key'"
            :disable="!canPersistConsoleDraft"
            @click="generateKey"
          />
          <q-btn
            v-if="canTest"
            outline
            color="positive"
            icon="lan"
            :label="t('connection.console.test')"
            :loading="consoleAction === 'test'"
            :disable="!canPersistConsoleDraft || (!isEdit && !canEdit)"
            @click="testConsole"
          />
          <q-btn v-if="canEdit && canInstallHelper" outline color="primary" icon="system_update_alt" :label="t('connection.console.installHelper')" :loading="consoleAction === 'install'" @click="installHelper" />
        </div>
        <q-banner v-if="generatedPublicKey" dense rounded class="bg-blue-1 text-blue-9 q-mt-md">
          <div>{{ t('connection.console.installPublicKey') }}</div>
          <pre class="deployment-commands"><code>{{ deploymentCommands }}</code></pre>
          <div class="row justify-end q-gutter-sm q-mt-sm">
            <q-btn flat icon="key" :label="t('connection.console.copyPublicKey')" @click="copyPublicKey" />
            <q-btn flat icon="content_copy" :label="t('connection.console.copyCommands')" @click="copyDeploymentCommands" />
          </div>
        </q-banner>
      </q-card-section>
    </q-card>

    <q-card v-if="selectedTool?.code === 'mail'" flat bordered>
      <q-card-section>
        <div class="text-subtitle2 q-mb-sm">{{ t('connection.mail.title') }}</div>
        <q-banner dense rounded class="bg-blue-1 text-blue-9 q-mb-md">
          <template #avatar><q-icon name="smart_toy" /></template>
          {{ t('connection.mail.disclosure') }}
        </q-banner>
        <q-btn
          v-if="canTest && isEdit"
          outline
          color="positive"
          icon="mark_email_read"
          :label="t('connection.mail.test')"
          :loading="mailAction === 'test'"
          @click="testMail"
        />
        <div v-else-if="!isEdit" class="text-caption text-grey-7">
          {{ t('connection.mail.saveBeforeTest') }}
        </div>
      </q-card-section>
    </q-card>

    <CalendarConnectionEditor
      v-if="selectedTool?.code === 'calendar' && form.id !== null && form.agent_id !== null"
      :connection-id="form.id"
      :agent-id="form.agent_id"
    />
    <q-banner
      v-else-if="selectedTool?.code === 'calendar'"
      dense
      rounded
      class="bg-blue-1 text-blue-9"
    >
      <template #avatar><q-icon name="calendar_month" /></template>
      {{ t('calendars.saveConnectionFirst') }}
    </q-banner>

    <div class="row items-center q-mt-md">
      <q-toggle
        v-if="selectedTool?.code !== 'console' || consoleTarget === 'external'"
        v-model="form.active"
        :label="t('connection.activeConnection')"
        color="positive"
      />
      <q-space />
      <q-btn :label="t('common.cancel')" color="grey-6" v-close-popup @click="$emit('cancel')" class="q-mr-sm" />
      <q-btn
        v-if="canEdit"
        :label="selectedTool?.code === 'console' && consoleTarget === 'embedded'
          ? t('connection.console.useEmbedded')
          : isEdit ? t('common.edit') : t('common.create')"
        type="submit"
        color="primary"
        :loading="loading || consoleAction === 'embedded'"
        :disable="!isValidForm"
      />
    </div>
  </q-form>

  <q-dialog v-model="showHostKeyConfirmation" @hide="clearPendingHostKey">
    <q-card class="host-key-confirmation-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="fingerprint" size="sm" class="q-mr-sm" />
        <div class="text-h6">{{ t('connection.console.confirmHostKey') }}</div>
        <q-space />
        <q-btn
          v-close-popup
          flat
          round
          dense
          icon="close"
          :aria-label="t('common.close')"
        />
      </q-card-section>
      <q-separator />
      <q-card-section v-if="pendingHostKey" class="host-key-confirmation-content scroll">
        <q-banner rounded class="bg-orange-1 text-orange-10 q-mb-lg">
          <template #avatar><q-icon name="verified_user" color="orange-9" /></template>
          {{ t('connection.console.hostKeyVerificationHint') }}
        </q-banner>

        <div class="host-key-metadata q-mb-lg">
          <div>
            <div class="text-caption text-grey-7">{{ t('connection.console.hostKeyEndpoint') }}</div>
            <div class="text-body1 text-weight-medium host-key-value">
              {{ pendingHostKey.host }}:{{ pendingHostKey.port }}
            </div>
          </div>
          <div>
            <div class="text-caption text-grey-7">{{ t('connection.console.hostKeyFingerprint') }}</div>
            <div class="text-body1 text-weight-medium host-key-value">
              {{ pendingHostKey.fingerprint }}
            </div>
          </div>
        </div>

        <CodeEditor
          :model-value="pendingHostKey.key"
          language="text"
          :label="t('connection.console.hostKeyValue')"
          readonly
          :show-error="false"
          :visible-lines="5"
          :min-lines="3"
        />
      </q-card-section>
      <q-separator />
      <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
        <q-btn v-close-popup flat color="grey-7" :label="t('common.cancel')" />
        <q-btn
          color="primary"
          icon="verified"
          :label="t('connection.console.acceptHostKey')"
          @click="acceptPendingHostKey"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>

  <q-dialog v-model="showConsoleTestResult">
    <q-card class="console-test-result-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="lan" size="sm" class="q-mr-sm" />
        <div class="text-h6">{{ t('connection.console.testResult') }}</div>
        <q-space />
        <q-btn
          v-close-popup
          flat
          round
          dense
          icon="close"
          :aria-label="t('common.close')"
        />
      </q-card-section>
      <q-separator />
      <q-card-section class="console-test-result-content scroll">
        <pre class="console-test-result-json"><code>{{ consoleTestResult }}</code></pre>
      </q-card-section>
      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn
          v-if="canEdit && canInstallHelper"
          outline
          color="primary"
          icon="system_update_alt"
          :label="t('connection.console.installHelper')"
          :loading="consoleAction === 'install'"
          @click="installHelper"
        />
        <q-btn v-close-popup flat color="primary" :label="t('common.close')" />
      </q-card-actions>
    </q-card>
  </q-dialog>

  <q-dialog v-model="showMailTestResult">
    <q-card class="console-test-result-dialog">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="mark_email_read" size="sm" class="q-mr-sm" />
        <div class="text-h6">{{ t('connection.mail.testResult') }}</div>
        <q-space />
        <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
      </q-card-section>
      <q-separator />
      <q-card-section class="console-test-result-content scroll">
        <pre class="console-test-result-json"><code>{{ mailTestResult }}</code></pre>
      </q-card-section>
      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn v-close-popup flat color="primary" :label="t('common.close')" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar } from 'quasar'
import { connectionParamMessageKey, sortedConnectionParamEntries } from '@/app/tools/presentation'
import { AgentSelect } from '@/app/agent'
import { consoleService, type ConsoleConnectionStatus } from '@/app/console/services/consoleService'
import { mailService, type MailApproverOption } from '@/app/connection/services/mailService'
import CalendarConnectionEditor from './CalendarConnectionEditor.vue'
import { authorizedKeysDeploymentCommands } from '@/app/console/sshKeyDeployment'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { CodeEditor } from '@/core/util'

const { t } = useI18n()
const $q = useQuasar()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.CONNECTION_EDIT))
const canTest = computed(() => (
  canEdit.value || privilegeStore.hasPrivilege(privileges.CONNECTION_ACCESS)
))

interface AgentOption {
  value: number
  label: string
  agentDriver: string
}

interface ToolOption {
  id: number
  label: string
}

interface Tool {
  id: number
  code: string
  label: string
  has_mcp?: boolean
  connection_schema?: {
    params?: Record<string, {
      type?: string
      description?: string
      default?: unknown
      required?: boolean
      order?: number | null
    }>
  }
  global_params?: Record<string, {
    value?: string | null
    configured?: boolean
    secret?: boolean
    forced?: boolean
  }>
}

interface Connection {
  id: number
  agent_id: number
  tool_id: number
  active: boolean
}

interface SchemaParam {
  name: string
  type: string
  description?: string
  default?: unknown
  required: boolean
}

interface ConnectionSubmitPayload {
  id: number | null
  data: {
    agent_id: number
    tool_id: number
    active: boolean
  }
  params: Record<string, string | null>
}

interface PendingHostKey {
  host: string
  port: number
  key: string
  fingerprint: string
}

const props = defineProps<{
  connection?: Connection | null
  connectionParams?: Record<string, unknown> | null
  configuredParams?: string[]
  loading?: boolean
  agentOptions: AgentOption[]
  toolOptions: ToolOption[]
  tools: Tool[]
  defaultAgentId?: number | null
  defaultToolId?: number | null
  persistForAction?: (payload: ConnectionSubmitPayload) => Promise<Connection>
}>()

const emit = defineEmits<{
  submit: [payload: ConnectionSubmitPayload]
  configured: []
  cancel: []
}>()

const form = ref({
  id: null as number | null,
  agent_id: null as number | null,
  tool_id: null as number | null,
  active: true,
})

const paramValues = ref<Record<string, string>>({})
const paramOverrides = ref<Record<string, boolean>>({})
type ConsoleTarget = 'embedded' | 'external'

const consoleAction = ref<'embedded' | 'scan' | 'key' | 'install' | 'test' | null>(null)
const consoleTarget = ref<ConsoleTarget>('embedded')
const generatedPublicKey = ref('')
const newlyConfiguredParams = ref(new Set<string>())
const showHostKeyConfirmation = ref(false)
const pendingHostKey = ref<PendingHostKey | null>(null)
const deploymentCommands = computed(() => authorizedKeysDeploymentCommands(generatedPublicKey.value))
const showConsoleTestResult = ref(false)
const consoleTestResult = ref('')
const consoleTestStatus = ref<ConsoleConnectionStatus | null>(null)
const mailAction = ref<'test' | null>(null)
const showMailTestResult = ref(false)
const mailTestResult = ref('')
const approvers = ref<MailApproverOption[]>([])
const approversLoading = ref(false)
const approverOptions = computed(() => approvers.value.map(user => ({
  value: String(user.id),
  label: user.label === user.email ? user.email : `${user.label} · ${user.email}`,
})))

const isEdit = computed(() => !!form.value.id)

const selectedTool = computed(() =>
  form.value.tool_id ? props.tools.find(t => t.id === form.value.tool_id) ?? null : null
)

const selectedAgent = computed(() =>
  form.value.agent_id ? props.agentOptions.find(agent => agent.value === form.value.agent_id) ?? null : null
)

const selectedAgentIsInternal = computed(() => selectedAgent.value?.agentDriver === 'internal')
const canPersistConsoleDraft = computed(() => (
  form.value.agent_id !== null
  && form.value.tool_id !== null
  && selectedTool.value?.code === 'console'
  && consoleTarget.value === 'external'
))

const CONSOLE_MANAGED_PARAMS = new Set([
  'known_host_key',
  'private_key',
  'private_key_passphrase',
])

function isConsoleManagedParam(name: string): boolean {
  return selectedTool.value?.code === 'console' && CONSOLE_MANAGED_PARAMS.has(name)
}

const consoleTargets = computed(() => [
  {
    value: 'embedded' as const,
    label: t('connection.console.embedded'),
    description: t('connection.console.embeddedDescription'),
  },
  {
    value: 'external' as const,
    label: t('connection.console.external'),
    description: t('connection.console.externalDescription'),
  },
])

const schemaParameters = computed((): SchemaParam[] => {
  const tool = selectedTool.value
  if (!tool?.connection_schema?.params) return []
  return sortedConnectionParamEntries(tool.connection_schema.params)
    .filter(([name]) => tool.code !== 'console' || name !== 'mode')
    .map(([name, config]) => ({
      name,
      type: config.type || 'string',
      description: config.description,
      default: config.default,
      required: config.required ?? true,
    }))
})

function globalParam(name: string) {
  return selectedTool.value?.global_params?.[name]
}

function hasGlobalValue(name: string): boolean {
  return globalParam(name)?.configured === true
}

function isGloballyForced(name: string): boolean {
  return hasGlobalValue(name) && globalParam(name)?.forced === true
}

const connectionParameters = computed(() => schemaParameters.value.filter(param => (
  !isConsoleManagedParam(param.name)
  && !isGloballyForced(param.name)
  && (!hasGlobalValue(param.name) || paramOverrides.value[param.name] === true)
)))

const inheritedParameters = computed(() => schemaParameters.value.filter(param => (
  !isConsoleManagedParam(param.name)
  && (
    isGloballyForced(param.name)
    || (hasGlobalValue(param.name) && paramOverrides.value[param.name] !== true)
  )
)))

const canInstallHelper = computed(() => Boolean(
  isEdit.value
  && selectedTool.value?.code === 'console'
  && consoleTarget.value === 'external'
  && consoleTestStatus.value?.reachable
  && consoleTestStatus.value.authenticated
  && consoleTestStatus.value.host_key_verified
  && consoleTestStatus.value.home_writable
  && consoleTestStatus.value.sftp_available
  && !consoleTestStatus.value.operation_recovery_available,
))

const showSchemaParameters = computed(() => (
  connectionParameters.value.length > 0
  && (selectedTool.value?.code !== 'console' || consoleTarget.value === 'external')
))

function localizedParamDescription(param: SchemaParam): string {
  const toolCode = selectedTool.value?.code
  const key = toolCode ? connectionParamMessageKey(toolCode, param.name) : null
  return key ? t(key) : param.description ?? ''
}

function inheritedValueLabel(param: SchemaParam): string {
  const global = globalParam(param.name)
  if (global?.secret) return t('connection.globalSecretConfigured')
  return t('connection.globalValueUsed', { value: global?.value ?? '' })
}

function enableParamOverride(param: SchemaParam): void {
  paramOverrides.value[param.name] = true
  const global = globalParam(param.name)
  if (!global?.secret && global?.value !== null && global?.value !== undefined) {
    paramValues.value[param.name] = String(global.value)
  } else {
    paramValues.value[param.name] = ''
  }
}

function disableParamOverride(name: string): void {
  paramOverrides.value[name] = false
  paramValues.value[name] = ''
}

function effectiveParamValue(name: string): string {
  if (paramOverrides.value[name] || !hasGlobalValue(name)) {
    return paramValues.value[name] ?? ''
  }
  return String(globalParam(name)?.value ?? '')
}

const isValidForm = computed(() => {
  if (form.value.agent_id === null || form.value.tool_id === null) return false
  if (
    selectedTool.value?.code === 'mail'
    && effectiveParamValue('approval_required') === 'true'
    && !effectiveParamValue('approver_user_id')
  ) return false
  return selectedTool.value?.code !== 'console'
    || consoleTarget.value === 'external'
    || selectedAgentIsInternal.value
})

function setBooleanParam(name: string, value: boolean): void {
  paramValues.value[name] = value ? 'true' : 'false'
}

async function loadApprovers(): Promise<void> {
  if (approvers.value.length || approversLoading.value) return
  approversLoading.value = true
  try {
    approvers.value = (await mailService.listApprovers()).data
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: `${t('connection.mail.approversError')}: ${consoleErrorMessage(error)}`,
    })
  } finally {
    approversLoading.value = false
  }
}

function initParamsFromSchema() {
  const values: Record<string, string> = {}
  for (const param of schemaParameters.value) {
    values[param.name] = param.default !== undefined ? String(param.default) : ''
  }
  paramValues.value = values
  paramOverrides.value = {}
}

function onToolChange() {
  consoleTarget.value = 'embedded'
  initParamsFromSchema()
}

function resetForm() {
  consoleTestStatus.value = null
  consoleTestResult.value = ''
  showConsoleTestResult.value = false
  showMailTestResult.value = false
  mailTestResult.value = ''
  mailAction.value = null
  newlyConfiguredParams.value = new Set()
  showHostKeyConfirmation.value = false
  pendingHostKey.value = null
  form.value = {
    id: null,
    agent_id: props.defaultAgentId ?? null,
    tool_id: props.defaultToolId ?? null,
    active: true,
  }
  paramValues.value = {}
  paramOverrides.value = {}
  if (form.value.tool_id !== null) {
    onToolChange()
  }
}

function initForm(connection?: Connection, params?: Record<string, unknown> | null) {
  consoleTestStatus.value = null
  consoleTestResult.value = ''
  showConsoleTestResult.value = false
  showMailTestResult.value = false
  mailTestResult.value = ''
  mailAction.value = null
  newlyConfiguredParams.value = new Set()
  showHostKeyConfirmation.value = false
  pendingHostKey.value = null
  if (connection) {
    form.value = {
      id: connection.id,
      agent_id: connection.agent_id,
      tool_id: connection.tool_id,
      active: connection.active,
    }
    const values: Record<string, string> = Object.fromEntries(
      schemaParameters.value.map(param => [
        param.name,
        param.default !== undefined ? String(param.default) : '',
      ])
    )
    if (params) {
      for (const [key, val] of Object.entries(params)) {
        values[key] = val !== null && val !== undefined ? String(val) : ''
      }
    }
    paramValues.value = values
    const configured = new Set(props.configuredParams ?? [])
    paramOverrides.value = Object.fromEntries(
      schemaParameters.value.map(param => {
        const local = params?.[param.name]
        const present = local !== null && local !== undefined && String(local) !== ''
        return [param.name, present || configured.has(param.name)]
      })
    )
    consoleTarget.value = selectedTool.value?.code === 'console' && params?.host === 'ssh-executor'
      ? 'embedded'
      : 'external'
  } else {
    resetForm()
  }
}

function buildSubmitPayload(active: boolean = form.value.active): ConnectionSubmitPayload | null {
  if (form.value.agent_id === null || form.value.tool_id === null) return null
  const filteredParams: Record<string, string | null> = {}
  const configured = new Set([
    ...(props.configuredParams ?? []),
    ...newlyConfiguredParams.value,
  ])
  for (const definition of schemaParameters.value) {
    const key = definition.name
    const value = paramValues.value[key] ?? ''
    if (isGloballyForced(key)) {
      if (paramOverrides.value[key]) filteredParams[key] = null
      continue
    }
    if (hasGlobalValue(key) && !paramOverrides.value[key]) {
      if (isEdit.value && (configured.has(key) || props.connectionParams?.[key])) {
        filteredParams[key] = null
      }
      continue
    }
    if (isEdit.value && definition.type === 'password' && value === '' && configured.has(key)) {
      continue
    }
    filteredParams[key] = value !== '' ? value : null
  }

  return {
    id: form.value.id,
    data: {
      agent_id: form.value.agent_id,
      tool_id: form.value.tool_id,
      active,
    },
    params: filteredParams,
  }
}

async function onSubmit() {
  if (!canEdit.value) return
  if (!isValidForm.value) return

  if (selectedTool.value?.code === 'console' && consoleTarget.value === 'embedded') {
    const agentId = form.value.agent_id
    if (agentId === null) return
    consoleAction.value = 'embedded'
    try {
      const { data } = await consoleService.provision(agentId)
      $q.notify({
        type: 'positive',
        message: t('connection.console.embeddedProvisioned', { code: data.agent_code }),
      })
      emit('configured')
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: `${t('connection.console.actionError')}: ${consoleErrorMessage(error)}`,
      })
    } finally {
      consoleAction.value = null
    }
    return
  }

  const payload = buildSubmitPayload()
  if (payload) emit('submit', payload)
}

function consoleErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = (error as { response?: { data?: { detail?: string } } }).response
    if (response?.data?.detail) return response.data.detail
  }
  return error instanceof Error ? error.message : String(error)
}

async function persistConsoleDraft(): Promise<Connection> {
  if (!canEdit.value && form.value.id !== null) {
    return {
      id: form.value.id,
      agent_id: form.value.agent_id!,
      tool_id: form.value.tool_id!,
      active: form.value.active,
    }
  }
  const payload = buildSubmitPayload(false)
  if (!payload || !props.persistForAction) {
    throw new Error(t('connection.saveError'))
  }
  const connection = await props.persistForAction(payload)
  form.value.id = connection.id
  return connection
}

async function scanHostKey(): Promise<void> {
  const host = effectiveParamValue('host').trim()
  if (!host) return
  consoleAction.value = 'scan'
  try {
    const port = Number(effectiveParamValue('port') || 22)
    const { data } = await consoleService.scanHostKey(host, port)
    pendingHostKey.value = data
    showHostKeyConfirmation.value = true
  } catch (error) {
    $q.notify({ type: 'negative', message: `${t('connection.console.actionError')}: ${consoleErrorMessage(error)}` })
  } finally { consoleAction.value = null }
}

function clearPendingHostKey(): void {
  pendingHostKey.value = null
}

function acceptPendingHostKey(): void {
  if (!pendingHostKey.value) return
  paramValues.value.known_host_key = pendingHostKey.value.key
  paramOverrides.value.known_host_key = true
  showHostKeyConfirmation.value = false
}

async function generateKey(): Promise<void> {
  consoleAction.value = 'key'
  try {
    const connection = await persistConsoleDraft()
    const { data } = await consoleService.generateKey(connection.id)
    generatedPublicKey.value = data.public_key
    newlyConfiguredParams.value = new Set(newlyConfiguredParams.value).add('private_key')
    paramOverrides.value.private_key = true
    $q.notify({ type: 'positive', message: t('connection.console.keyGenerated') })
  } catch (error) {
    $q.notify({ type: 'negative', message: `${t('connection.console.actionError')}: ${consoleErrorMessage(error)}` })
  } finally { consoleAction.value = null }
}

async function testConsole(): Promise<void> {
  consoleAction.value = 'test'
  try {
    const connection = await persistConsoleDraft()
    const { data } = await consoleService.testConnection(connection.id)
    consoleTestStatus.value = data.status
    consoleTestResult.value = JSON.stringify(data, null, 2)
    showConsoleTestResult.value = true
  } catch (error) {
    $q.notify({ type: 'negative', message: `${t('connection.console.actionError')}: ${consoleErrorMessage(error)}` })
  } finally { consoleAction.value = null }
}

async function testMail(): Promise<void> {
  if (!form.value.id) return
  mailAction.value = 'test'
  try {
    const { data } = await mailService.testConnection(form.value.id)
    mailTestResult.value = JSON.stringify(data, null, 2)
    showMailTestResult.value = true
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: `${t('connection.mail.actionError')}: ${consoleErrorMessage(error)}`,
    })
  } finally {
    mailAction.value = null
  }
}

async function installHelper(): Promise<void> {
  if (!form.value.id || !canInstallHelper.value) return
  consoleAction.value = 'install'
  try {
    const { data } = await consoleService.installHelper(form.value.id)
    consoleTestStatus.value = data.status
    consoleTestResult.value = JSON.stringify(data, null, 2)
    showConsoleTestResult.value = true
    $q.notify({
      type: 'positive',
      message: t('connection.console.helperInstalled', { version: data.version }),
    })
  } catch (error) {
    $q.notify({
      type: 'negative',
      message: `${t('connection.console.helperInstallError')}: ${consoleErrorMessage(error)}`,
    })
  } finally { consoleAction.value = null }
}

async function copyPublicKey(): Promise<void> {
  await navigator.clipboard.writeText(generatedPublicKey.value)
  $q.notify({ type: 'positive', message: t('connection.console.publicKeyCopied') })
}

async function copyDeploymentCommands(): Promise<void> {
  await navigator.clipboard.writeText(deploymentCommands.value)
  $q.notify({ type: 'positive', message: t('connection.console.commandsCopied') })
}

watch(() => [props.connection, props.connectionParams] as const, ([newConnection, newParams]) => {
  initForm(newConnection || undefined, newParams as Record<string, unknown> | null | undefined)
}, { immediate: true })

watch(() => selectedTool.value, () => {
  if (!props.connection) initParamsFromSchema()
  if (selectedTool.value?.code === 'mail') void loadApprovers()
}, { immediate: true })

defineExpose({ initForm, resetForm })
</script>

<style scoped>
.schema-params-table {
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  overflow: hidden;
}

.schema-params-header {
  background-color: #f5f5f5;
  font-weight: 500;
  padding: 4px 8px;
  border-bottom: 1px solid #e0e0e0;
  font-size: 12px;
  color: #666;
}

.schema-params-header > div { padding: 0 8px; }

.schema-params-row {
  padding: 8px;
  border-bottom: 1px solid #f0f0f0;
}

.schema-params-row:last-child { border-bottom: none; }
.schema-params-row > div { padding: 0 8px; }

body.body--dark .schema-params-table { border-color: #3a3f47; }
body.body--dark .schema-params-header { color: #b5b5b5; background-color: #2a2a2a; border-bottom-color: #3a3f47; }
body.body--dark .schema-params-row { border-bottom-color: #2e3238; }

.col-param { width: 40%; }
.col-value { width: 60%; }

.param-name { font-weight: 500; }
.param-desc { font-size: 11px; margin-top: 2px; }

.schema-params-row :deep(.q-field) { width: 100%; }
.deployment-commands {
  margin: 8px 0 0;
  max-width: 100%;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  background: rgb(0 0 0 / 8%);
  color: inherit;
  white-space: pre;
}
.host-key-confirmation-dialog {
  display: flex;
  flex-direction: column;
  width: min(960px, calc(100vw - 32px));
  max-width: 960px;
  max-height: 85vh;
}
.host-key-confirmation-content {
  flex: 1 1 auto;
  min-height: 0;
  padding: 24px;
}
.host-key-metadata {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  gap: 24px;
}
.host-key-value {
  overflow-wrap: anywhere;
}
.console-test-result-dialog {
  display: flex;
  flex-direction: column;
  width: min(720px, calc(100vw - 32px));
  max-width: 720px;
  max-height: 80vh;
}
.console-test-result-content { min-height: 0; }
.console-test-result-json {
  margin: 0;
  padding: 16px;
  border-radius: 4px;
  overflow: auto;
  background: rgb(0 0 0 / 6%);
  color: inherit;
  font-family: monospace;
  white-space: pre;
}
.console-target { transition: border-color 0.15s ease, background-color 0.15s ease; }
.console-target--selected { border-color: var(--q-primary); background: color-mix(in srgb, var(--q-primary) 7%, transparent); }

.text-subtitle2 { font-weight: bold; font-size: 16px; }

@media (max-width: 600px) {
  .host-key-metadata { grid-template-columns: 1fr; gap: 12px; }
  .host-key-confirmation-content { padding: 16px; }
}
</style>
