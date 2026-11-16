<template>
  <div class="q-gutter-y-md">
    <q-banner class="bg-info text-white" dense rounded>
      <template v-slot:avatar><q-icon name="hub" /></template>
      <div class="text-caption">{{ $t('agent.mcp.intro') }}</div>
    </q-banner>

    <!-- URL de l'endpoint MCP -->
    <q-input
      :model-value="mcpEndpointUrl"
      :label="$t('agent.mcp.endpointUrl')"
      filled
      readonly
      :hint="$t('agent.mcp.endpointHint')"
    >
      <template v-slot:append>
        <q-btn :aria-label="$t('agent.mcp.copy')" flat round dense icon="content_copy" @click="copyText(mcpEndpointUrl)">
          <q-tooltip>{{ $t('agent.mcp.copy') }}</q-tooltip>
        </q-btn>
      </template>
    </q-input>

    <!-- Client configuration snippet (mcpServers). -->
    <q-input
      :model-value="mcpConfigSnippet"
      :label="$t('agent.mcp.configSnippet')"
      filled
      readonly
      type="textarea"
      autogrow
      input-style="font-family: monospace; font-size: 12px"
    >
      <template v-slot:append>
        <q-btn :aria-label="$t('agent.mcp.copy')" flat round dense icon="content_copy" @click="copyText(mcpConfigSnippet)">
          <q-tooltip>{{ $t('agent.mcp.copy') }}</q-tooltip>
        </q-btn>
      </template>
    </q-input>

    <!-- Tokens -->
    <div class="row items-center q-mt-md">
      <div class="text-subtitle2 text-primary">{{ $t('agent.mcp.tokensTitle') }}</div>
      <q-space />
      <q-btn
        v-if="canManage"
        color="primary"
        icon="add"
        :label="$t('agent.mcp.newToken')"
        no-caps
        :loading="mcpTokensLoading"
        @click="openCreateMcpToken"
      />
    </div>
    <div class="text-caption text-grey-6">{{ $t('agent.mcp.tokensHint') }}</div>

    <q-banner v-if="mcpTokensError" role="alert">
      {{ $t('agent.mcp.loadError') }}
      <template #action><q-btn outline color="primary" :label="$t('common.retry')" @click="loadMcpTokens" /></template>
    </q-banner>

    <q-table
      :rows="mcpTokens"
      :columns="mcpTokenColumns"
      row-key="id"
      dense
      flat
      :loading="mcpTokensLoading"
      :rows-per-page-options="[0]"
      hide-bottom
      :no-data-label="$t('agent.mcp.noToken')"
    >
      <template v-slot:body-cell-label="props">
        <q-td :props="props">{{ props.row.label || '-' }}</q-td>
      </template>
      <template v-slot:body-cell-token="props">
        <q-td :props="props"><code>{{ props.row.token }}</code></q-td>
      </template>
      <template v-slot:body-cell-enabled="props">
        <q-td :props="props">
          <q-badge :color="props.row.enabled ? 'positive' : 'grey'">
            {{ props.row.enabled ? $t('user.active') : $t('user.inactive') }}
          </q-badge>
        </q-td>
      </template>
      <template v-slot:body-cell-created_at="props">
        <q-td :props="props">{{ formatDateTime(props.row.created_at) }}</q-td>
      </template>
      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn :aria-label="props.row.enabled ? $t('agent.mcp.disable') : $t('agent.mcp.enable')"
                 v-if="canManage"
                 flat round
                 :color="props.row.enabled ? 'grey' : 'positive'"
                 :icon="props.row.enabled ? 'block' : 'check_circle'"
                 @click="toggleMcpToken(props.row)"
          >
            <q-tooltip>{{ props.row.enabled ? $t('agent.mcp.disable') : $t('agent.mcp.enable') }}</q-tooltip>
          </q-btn>
          <q-btn :aria-label="$t('common.delete')" v-if="canManage" flat round color="negative" icon="delete" @click="deleteMcpToken(props.row)">
            <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
          </q-btn>
        </q-td>
      </template>
    </q-table>

    <div class="galaris-dialog-actions row justify-end q-mt-md q-pa-md">
      <q-btn outline :label="$t('common.close')" color="grey"  v-close-popup />
    </div>
  </div>
  <q-dialog v-model="showCreateMcpTokenDialog">
    <q-card class="galaris-dialog-card" style="min-width: 400px">
      <DialogHeader :title="$t('agent.mcp.newToken')" :close-label="$t('common.close')" />
      <q-card-section class="galaris-dialog-body">
        <q-input
          v-model="newMcpTokenLabel"
          :label="$t('agent.mcp.labelOptional')"
          outlined
          dense
          autofocus
          @keyup.enter="confirmCreateMcpToken()"
        />
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn outline  :label="$t('common.cancel')" color="primary" v-close-popup />
        <q-btn outline
               v-if="canManage"

               :label="$t('common.create')"
               color="positive"
               :loading="mcpTokensLoading"
               @click="confirmCreateMcpToken()"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>

  <q-dialog v-model="showNewMcpTokenDialog">
    <q-card class="galaris-dialog-card" style="min-width: 500px">
      <DialogHeader :title="$t('agent.mcp.createdTitle')" :close-label="$t('common.close')" />
      <q-card-section class="galaris-dialog-body">
        <p class="text-body2">{{ $t('agent.mcp.copyHint') }}</p>
        <q-input v-model="newMcpTokenValue" readonly outlined type="textarea" autogrow>
          <template #append>
            <q-btn flat round icon="content_copy" :aria-label="$t('common.copy')" @click="copyText(newMcpTokenValue)" />
          </template>
        </q-input>
      </q-card-section>
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn outline  :label="$t('common.close')" color="primary" v-close-popup />
      </q-card-actions>
    </q-card>
  </q-dialog>


</template>
<script setup lang="ts">
import { watch } from 'vue'
import { DialogHeader } from '@/core/util'
import { useAgentMcp } from '../composables/useAgentMcp'
const props = defineProps<{ agent: { id: number | null; code: string }; canManage: boolean }>()
const { mcpTokens, mcpTokensLoading, mcpTokensError, showCreateMcpTokenDialog, newMcpTokenLabel, showNewMcpTokenDialog, newMcpTokenValue,
  mcpEndpointUrl, mcpConfigSnippet, mcpTokenColumns, formatDateTime, copyText, loadMcpTokens, openCreateMcpToken,
  confirmCreateMcpToken, toggleMcpToken, deleteMcpToken } = useAgentMcp(() => props.agent, () => props.canManage, () => true)
watch([() => props.agent.id, () => props.canManage], () => { void loadMcpTokens() }, { immediate: true })
</script>
