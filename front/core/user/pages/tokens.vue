<template>
  <q-page class="tokens-page q-pa-md">
    <PageHeader :icon="navigationIcon('security')" :title="$t('nav.apiTokens')" :description="$t('nav.apiTokens_desc')" />

    <q-banner rounded class="api-access-guide q-mb-lg">
      <div class="api-guide-heading row items-start no-wrap q-gutter-md">
        <q-avatar color="primary" text-color="white" icon="key" />
        <div class="col api-guide-copy">
          <div class="text-subtitle1 text-weight-medium">
            {{ $t('tokens.guideTitle') }}
          </div>
          <div class="text-body2 q-mt-xs">
            {{ $t('tokens.guideDescription') }}
          </div>
        </div>
      </div>

      <div class="text-body2 q-mt-sm">
        {{ $t('tokens.openAiClientHint') }}
      </div>

      <div class="api-endpoint-grid q-mt-md">
        <div
          v-for="endpoint in openAiEndpoints"
          :key="endpoint.key"
          class="api-endpoint-card"
        >
          <div class="row items-center no-wrap q-gutter-sm">
            <q-icon :name="endpoint.icon" color="primary" size="sm" />
            <div class="text-subtitle2 text-weight-medium">{{ endpoint.label }}</div>
          </div>
          <div class="text-caption q-mt-xs">{{ endpoint.description }}</div>
          <div class="api-endpoint-url q-mt-sm">
            <code>{{ endpoint.url }}</code>
            <q-btn
              flat
              round
              dense
              size="sm"
              icon="content_copy"
              :aria-label="$t('tokens.copyApiUrl')"
              @click="copyApiUrl(endpoint.url)"
            >
              <q-tooltip>{{ $t('tokens.copyApiUrl') }}</q-tooltip>
            </q-btn>
          </div>
          <div class="text-caption text-grey-7 q-mt-xs">
            {{ endpoint.routesText }}
          </div>
        </div>
      </div>

      <div class="auth-hint row items-center q-gutter-sm q-mt-md">
        <q-icon name="security" color="primary" size="sm" />
        <span class="text-body2">{{ $t('tokens.authHint') }}</span>
      </div>
      <template #action>
        <component
          v-for="action in tokenActions"
          :key="action.name"
          :is="action.component"
        />
      </template>
    </q-banner>

    <q-banner v-if="loadError" rounded class="bg-red-1 text-negative q-mb-md">
      {{ $t('tokens.loadError') }}
      <template #action>
        <q-btn flat color="negative" :label="$t('common.retry')" @click="loadTokens" />
      </template>
    </q-banner>

    <div class="token-toolbar row justify-end q-mb-md">
      <q-btn
        color="primary"
        icon="add"
        :label="$t('tokens.newToken')"
        :loading="tokenStore.loading"
        @click="openCreateDialog"
      />
    </div>

    <q-table
      :rows="tokenStore.tokens"
      :columns="columns"
      :grid="$q.screen.lt.md"
      row-key="id"
      :loading="tokenStore.loading"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      :pagination="{ rowsPerPage: 50 }"
      :no-data-label="$t('tokens.empty')"
      :rows-per-page-label="$t('tokens.rowsPerPage')"
      :pagination-label="paginationLabel"
      class="tokens-table"
    >
      <template v-slot:body-cell-label="props">
        <q-td :props="props">
          <div v-if="editingLabelId === props.row.id" class="row items-center q-gutter-xs">
            <q-input
              v-model="editingLabelValue"
              dense
              outlined
              autofocus
              @keyup.enter="saveLabel(props.row.id)"
              @keyup.esc="cancelEditLabel"
            />
            <q-btn flat dense icon="check" color="positive" size="sm" @click="saveLabel(props.row.id)" />
            <q-btn flat dense icon="close" color="grey" size="sm" @click="cancelEditLabel" />
          </div>
          <div v-else class="row items-center q-gutter-xs">
            <span class="text-grey-8">{{ props.row.label || '-' }}</span>
            <q-btn flat dense icon="edit" color="primary" size="sm" @click="startEditLabel(props.row)">
              <q-tooltip>{{ $t('tokens.editLabel') }}</q-tooltip>
            </q-btn>
          </div>
        </q-td>
      </template>

      <template v-slot:body-cell-token="props">
        <q-td :props="props">
          <code>{{ props.row.token }}</code>
        </q-td>
      </template>

      <template v-slot:body-cell-enabled="props">
        <q-td :props="props">
          <q-badge :color="props.row.enabled ? 'positive' : 'grey'">
            {{ props.row.enabled ? $t('user.active') : $t('user.inactive') }}
          </q-badge>
        </q-td>
      </template>

      <template v-slot:body-cell-created_at="props">
        <q-td :props="props">
          {{ formatDate(props.row.created_at) }}
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn
            flat
            round
            :color="props.row.enabled ? 'grey' : 'positive'"
            :icon="props.row.enabled ? 'block' : 'check_circle'"
            size="sm"
            @click="onToggle(props.row)"
          >
            <q-tooltip>{{ props.row.enabled ? $t('tokens.disable') : $t('tokens.enable') }}</q-tooltip>
          </q-btn>
          <q-btn flat round color="negative" icon="delete" size="sm" @click="onDelete(props.row)">
            <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>

      <template #item="props">
        <div class="q-table__grid-item col-12 token-grid-item">
          <q-card flat bordered class="token-mobile-card">
            <q-card-section class="q-pa-md">
              <div class="row items-start no-wrap q-gutter-sm">
                <div class="col token-mobile-heading">
                  <div class="text-caption text-grey-7">#{{ props.row.id }}</div>
                  <template v-if="editingLabelId === props.row.id">
                    <q-input
                      v-model="editingLabelValue"
                      dense
                      outlined
                      autofocus
                      class="q-mt-xs"
                      @keyup.enter="saveLabel(props.row.id)"
                      @keyup.esc="cancelEditLabel"
                    >
                      <template #after>
                        <q-btn
                          flat
                          round
                          dense
                          icon="check"
                          color="positive"
                          :aria-label="$t('common.save')"
                          @click="saveLabel(props.row.id)"
                        />
                        <q-btn
                          flat
                          round
                          dense
                          icon="close"
                          color="grey"
                          :aria-label="$t('common.cancel')"
                          @click="cancelEditLabel"
                        />
                      </template>
                    </q-input>
                  </template>
                  <div v-else class="text-subtitle1 text-weight-medium token-mobile-label">
                    {{ props.row.label || '-' }}
                  </div>
                </div>
                <q-badge :color="props.row.enabled ? 'positive' : 'grey'">
                  {{ props.row.enabled ? $t('user.active') : $t('user.inactive') }}
                </q-badge>
              </div>

              <div class="token-mobile-fields q-mt-md">
                <div class="token-mobile-field token-mobile-field--wide">
                  <div class="token-mobile-field-label">{{ $t('tokens.colToken') }}</div>
                  <code class="token-mobile-value">{{ props.row.token }}</code>
                </div>
                <div class="token-mobile-field token-mobile-field--wide">
                  <div class="token-mobile-field-label">{{ $t('tokens.colCreatedAt') }}</div>
                  <div class="token-mobile-value">{{ formatDate(props.row.created_at) }}</div>
                </div>
              </div>
            </q-card-section>

            <q-separator />
            <q-card-actions align="right" class="q-px-sm q-py-xs">
              <q-btn
                flat
                round
                color="primary"
                icon="edit"
                size="sm"
                :aria-label="$t('tokens.editLabel')"
                @click="startEditLabel(props.row)"
              />
              <q-btn
                flat
                round
                :color="props.row.enabled ? 'grey' : 'positive'"
                :icon="props.row.enabled ? 'block' : 'check_circle'"
                size="sm"
                :aria-label="props.row.enabled ? $t('tokens.disable') : $t('tokens.enable')"
                @click="onToggle(props.row)"
              />
              <q-btn
                flat
                round
                color="negative"
                icon="delete"
                size="sm"
                :aria-label="$t('common.delete')"
                @click="onDelete(props.row)"
              />
            </q-card-actions>
          </q-card>
        </div>
      </template>
    </q-table>

    <!-- Token creation dialog with a label. -->
    <q-dialog v-model="showCreateDialog">
      <q-card class="token-dialog token-dialog--small">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ $t('tokens.newToken') }}</div>
          <q-space />
          <q-btn
            flat
            round
            dense
            icon="close"
            :aria-label="$t('common.close')"
            v-close-popup
          />
        </q-card-section>
        <q-card-section>
          <q-input
            v-model="newTokenLabel"
            :label="$t('tokens.labelOptional')"
            outlined
            dense
            :placeholder="$t('tokens.labelPlaceholder')"
            @keyup.enter="confirmCreate"
          />
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="$t('common.cancel')" color="primary" v-close-popup />
          <q-btn flat :label="$t('common.create')" color="positive" @click="confirmCreate" :loading="tokenStore.loading" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Dialog displaying the newly created token. -->
    <q-dialog v-model="showNewTokenDialog">
      <q-card class="token-dialog">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ $t('tokens.createdTitle') }}</div>
          <q-space />
          <q-btn
            flat
            round
            dense
            icon="close"
            :aria-label="$t('common.close')"
            v-close-popup
          />
        </q-card-section>
        <q-card-section>
          <p class="text-body2">
            {{ $t('tokens.copyHint') }}
          </p>
          <q-input
            v-model="newTokenValue"
            readonly
            outlined
            type="textarea"
            autogrow
          >
            <template v-slot:append>
              <q-btn flat round icon="content_copy" @click="copyToken(newTokenValue)" />
            </template>
          </q-input>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="$t('common.close')" color="primary" v-close-popup @click="showNewTokenDialog = false" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="showDeleteDialog">
      <q-card class="token-dialog token-dialog--small">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ $t('common.deleteConfirmTitle') }}</div>
          <q-space />
          <q-btn
            flat
            round
            dense
            icon="close"
            :aria-label="$t('common.close')"
            v-close-popup
          />
        </q-card-section>
        <q-card-section>
          {{ $t('tokens.deleteConfirm') }}
          <br />
          <code class="q-mt-sm block">{{ tokenToDelete ? maskToken(tokenToDelete.token) : '' }}</code>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="$t('common.cancel')" color="primary" v-close-popup />
          <q-btn flat :label="$t('common.delete')" color="negative" @click="confirmDelete" v-close-popup />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { navigationIcon } from '@/core/navigation'
import { ref, computed, onMounted } from 'vue'
import type { QTableProps } from 'quasar'
import { useTokenStore, type UserToken } from '../stores/tokenStore'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { PageHeader } from '@/core/util'
import { tokenActions } from '../tokenActions'

const $q = useQuasar()
const { t, locale } = useI18n()
const tokenStore = useTokenStore()

const showCreateDialog = ref(false)
const newTokenLabel = ref('')
const showNewTokenDialog = ref(false)
const newTokenValue = ref('')
const showDeleteDialog = ref(false)
const tokenToDelete = ref<UserToken | null>(null)
const loadError = ref(false)

const editingLabelId = ref<number | null>(null)
const editingLabelValue = ref('')
const apiOrigin = window.location.origin

const openAiEndpoints = computed(() => [
  {
    key: 'agents',
    icon: 'smart_toy',
    label: t('tokens.agentsApiLabel'),
    description: t('tokens.agentsApiDescription'),
    url: `${apiOrigin}/api/agent/openai`,
    routesText: t('tokens.openAiRoutes'),
  },
  {
    key: 'janus',
    icon: 'hub',
    label: t('tokens.janusApiLabel'),
    description: t('tokens.janusApiDescription'),
    url: `${apiOrigin}/api/janus/openai`,
    routesText: t('tokens.openAiRoutes'),
  },
  {
    key: 'llms',
    icon: 'memory',
    label: t('tokens.llmApiLabel'),
    description: t('tokens.llmApiDescription'),
    url: `${apiOrigin}/api/llm/openai`,
    routesText: t('tokens.openAiRoutes'),
  },
  {
    key: 'claude',
    icon: 'terminal',
    label: t('tokens.claudeApiLabel'),
    description: t('tokens.claudeApiDescription'),
    url: `${apiOrigin}/api/llm/anthropic`,
    routesText: t('tokens.anthropicRoutes'),
  },
  {
    key: 'profiles-openai',
    icon: 'tune',
    label: t('tokens.profilesOpenAiLabel'),
    description: t('tokens.profilesApiDescription'),
    url: `${apiOrigin}/api/profile/openai`,
    routesText: t('tokens.profilesOpenAiRoutes'),
  },
  {
    key: 'profiles-anthropic',
    icon: 'tune',
    label: t('tokens.profilesAnthropicLabel'),
    description: t('tokens.profilesApiDescription'),
    url: `${apiOrigin}/api/profile/anthropic`,
    routesText: t('tokens.anthropicRoutes'),
  },
])

const columns = computed<QTableProps['columns']>(() => [
  { name: 'id', label: 'ID', field: 'id', sortable: true, align: 'left' },
  { name: 'label', label: t('tokens.colLabel'), field: 'label', sortable: true, align: 'left' },
  { name: 'token', label: t('tokens.colToken'), field: 'token', align: 'left' },
  { name: 'enabled', label: t('tokens.colState'), field: 'enabled', sortable: true, align: 'center' },
  { name: 'created_at', label: t('tokens.colCreatedAt'), field: 'created_at', sortable: true, align: 'left' },
  { name: 'actions', label: t('common.actions'), field: 'actions', align: 'right' }
])

function maskToken(token: string): string {
  if (token.length <= 12) return token
  return token.slice(0, 6) + '...' + token.slice(-6)
}

function copyToken(token: string): void {
  navigator.clipboard.writeText(token).then(() => {
    $q.notify({ type: 'positive', message: t('tokens.copied') })
  }).catch(() => {
    $q.notify({ type: 'negative', message: t('tokens.copyFailed') })
  })
}

function copyApiUrl(url: string): void {
  navigator.clipboard.writeText(url).then(() => {
    $q.notify({ type: 'positive', message: t('tokens.apiUrlCopied') })
  }).catch(() => {
    $q.notify({ type: 'negative', message: t('tokens.copyFailed') })
  })
}

function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(dateStr))
}

function paginationLabel(firstRowIndex: number, lastRowIndex: number, totalRowsNumber: number): string {
  return t('tokens.pagination', {
    first: firstRowIndex,
    last: lastRowIndex,
    total: totalRowsNumber,
  })
}

function openCreateDialog(): void {
  newTokenLabel.value = ''
  showCreateDialog.value = true
}

async function confirmCreate(): Promise<void> {
  try {
    const token = await tokenStore.createToken(newTokenLabel.value || undefined)
    newTokenValue.value = token.token
    showCreateDialog.value = false
    showNewTokenDialog.value = true
  } catch (error) {
    $q.notify({ type: 'negative', message: t('tokens.createError') })
  }
}

function startEditLabel(token: UserToken): void {
  editingLabelId.value = token.id
  editingLabelValue.value = token.label || ''
}

function cancelEditLabel(): void {
  editingLabelId.value = null
  editingLabelValue.value = ''
}

async function saveLabel(tokenId: number): Promise<void> {
  try {
    await tokenStore.updateTokenLabel(tokenId, editingLabelValue.value)
    $q.notify({ type: 'positive', message: t('tokens.labelUpdated') })
  } catch (error) {
    $q.notify({ type: 'negative', message: t('tokens.labelUpdateError') })
  } finally {
    editingLabelId.value = null
  }
}

async function onToggle(token: UserToken): Promise<void> {
  try {
    await tokenStore.toggleToken(token.id)
    $q.notify({
      type: 'positive',
      message: token.enabled ? t('tokens.toggledOff') : t('tokens.toggledOn')
    })
  } catch (error) {
    $q.notify({ type: 'negative', message: t('tokens.toggleError') })
  }
}

function onDelete(token: UserToken): void {
  tokenToDelete.value = token
  showDeleteDialog.value = true
}

async function confirmDelete(): Promise<void> {
  if (!tokenToDelete.value) return
  try {
    await tokenStore.deleteToken(tokenToDelete.value.id)
    $q.notify({ type: 'positive', message: t('tokens.deleted') })
  } catch (error) {
    $q.notify({ type: 'negative', message: t('tokens.deleteError') })
  } finally {
    tokenToDelete.value = null
  }
}

onMounted(async () => {
  await loadTokens()
})

async function loadTokens(): Promise<void> {
  loadError.value = false
  try {
    await tokenStore.fetchTokens()
  } catch {
    loadError.value = true
  }
}
</script>

<style scoped>
.api-access-guide {
  color: inherit;
  background: color-mix(in srgb, var(--q-primary) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--q-primary) 24%, transparent);
}

.api-guide-copy,
.token-mobile-card,
.token-mobile-heading,
.token-mobile-field {
  min-width: 0;
}

.api-endpoint-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.api-endpoint-card {
  min-width: 0;
  padding: 14px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
}

.api-endpoint-url {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.06);
}

.api-endpoint-url code {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 0.78rem;
}

.auth-hint {
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
}

.tokens-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.tokens-table :deep(.q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
}

.token-grid-item {
  padding: 8px 0;
}

.token-mobile-label,
.token-mobile-value {
  overflow-wrap: anywhere;
}

.token-mobile-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.token-mobile-field--wide {
  grid-column: 1 / -1;
}

.token-mobile-field-label {
  color: #757575;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.token-mobile-value {
  display: block;
  margin-top: 4px;
}

.token-dialog {
  width: min(500px, calc(100vw - 32px));
  max-width: calc(100vw - 32px);
}

.token-dialog--small {
  width: min(400px, calc(100vw - 32px));
}

body.body--dark .api-endpoint-card,
body.body--dark .auth-hint {
  background: rgba(0, 0, 0, 0.18);
}

body.body--dark .api-endpoint-url {
  background: rgba(255, 255, 255, 0.08);
}

@media (max-width: 1023px) {
  .api-endpoint-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 599px) {
  .tokens-page {
    padding: 12px;
  }

  .api-access-guide {
    padding: 12px;
  }

  .api-guide-heading {
    gap: 12px;
  }

  .api-guide-heading .q-avatar {
    font-size: 20px;
    height: 36px;
    width: 36px;
  }

  .api-endpoint-card {
    padding: 12px;
  }

  .auth-hint {
    align-items: flex-start;
  }

  .token-toolbar .q-btn {
    width: 100%;
  }

  .token-mobile-fields {
    grid-template-columns: 1fr;
  }

  .token-dialog,
  .token-dialog--small {
    width: calc(100vw - 24px);
    max-width: calc(100vw - 24px);
  }
}
</style>
