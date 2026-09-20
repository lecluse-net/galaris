<template>
  <div>
    <div class="row justify-end q-gutter-sm q-mb-md tools-actions">
      <q-btn v-if="canEdit" outline color="secondary" icon="upload" :label="$t('tools.import')" @click="openImport" />
      <q-btn v-if="canEdit" color="primary" icon="add" :label="$t('tools.newTool')" @click="openCreate" />
    </div>

    <q-table
      :rows="toolStore.tools"
      :columns="columns"
      :grid="$q.screen.lt.md"
      row-key="id"
      :loading="toolStore.loading"
      :rows-per-page-options="[10, 20, 50, 100, 500]"
      :pagination="{ rowsPerPage: 50 }"
      class="tools-table"
      @row-click="(_event, row) => openDescription(row)"
      :table-row-class-fn="row => toolDescription(row) ? 'cursor-pointer' : ''"
    >
      <template v-slot:body-cell-label="props">
        <q-td :props="props">
          <button v-if="toolDescription(props.row)" class="tool-description-link" @click.stop="openDescription(props.row)">{{ localizedToolLabel(props.row) }}</button>
          <span v-else>{{ localizedToolLabel(props.row) }}</span>
          <SystemToolIcon v-if="props.row.can_disable === false" class="q-ml-xs" />
        </q-td>
      </template>
      <template v-slot:body-cell-has_mcp="props">
        <q-td :props="props">
          <q-chip v-if="props.row.has_mcp" dense color="positive" text-color="white" icon="check" size="sm">MCP</q-chip>
          <span v-else class="text-grey-5">—</span>
        </q-td>
      </template>

      <template v-slot:body-cell-has_file_share="props">
        <q-td :props="props">
          <q-chip v-if="props.row.has_file_share" dense color="deep-purple" text-color="white" icon="folder_shared" size="sm">
            {{ props.row.file_share_config?.service }}
          </q-chip>
          <span v-else class="text-grey-5">—</span>
        </q-td>
      </template>

      <template v-slot:body-cell-has_messenger="props">
        <q-td :props="props">
          <q-chip v-if="props.row.has_messenger" dense color="indigo" text-color="white" icon="forum" size="sm">
            {{ props.row.messenger_config?.service }}
          </q-chip>
          <span v-else class="text-grey-5">—</span>
        </q-td>
      </template>

      <template v-slot:body-cell-has_listener="props">
        <q-td :props="props">
          <q-chip v-if="props.row.has_listener" dense color="info" text-color="white" icon="check" size="sm">{{ $t('tools.listener') }}</q-chip>
          <span v-else class="text-grey-5">—</span>
        </q-td>
      </template>

      <template v-slot:body-cell-conversation_enabled="props">
        <q-td :props="props" @click.stop>
          <q-toggle
            :model-value="props.row.conversation_enabled"
            :disable="!canEdit || props.row.can_disable === false || conversationAccessLoading.has(props.row.id)"
            color="primary"
            :aria-label="$t('tools.conversationAccessFor', { name: localizedToolLabel(props.row) })"
            @update:model-value="value => updateConversationAccess(props.row, value)"
          >
            <q-tooltip>{{ $t('tools.conversationAccessHint') }}</q-tooltip>
          </q-toggle>
          <q-spinner
            v-if="conversationAccessLoading.has(props.row.id)"
            size="18px"
            color="primary"
            class="q-ml-xs"
          />
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props" class="q-gutter-x-xs" @click.stop>
          <q-btn flat round icon="download" size="sm" color="secondary" @click="exportTool(props.row)">
            <q-tooltip>{{ $t('tools.exportYaml') }}</q-tooltip>
          </q-btn>
          <q-btn
            v-if="canEdit && props.row.can_disable !== false && Object.keys(props.row.connection_schema?.params ?? {}).length"
            flat round icon="tune" size="sm" color="deep-purple"
            @click="openGlobalParams(props.row)"
          >
            <q-tooltip>{{ $t('tools.globalParams') }}</q-tooltip>
          </q-btn>
          <q-btn v-if="canEdit && props.row.can_edit && props.row.can_disable !== false" flat round icon="edit" size="sm" color="primary" @click="openEdit(props.row)" />
          <q-btn v-if="canEdit && props.row.can_edit && props.row.can_disable !== false" flat round icon="delete" size="sm" color="negative" @click="confirmDelete(props.row)" />
        </q-td>
      </template>

      <template #item="props">
        <div class="q-table__grid-item col-12">
          <q-card flat bordered class="tool-mobile-card">
            <q-card-section class="q-pa-md" :class="{ 'cursor-pointer': toolDescription(props.row) }" @click="openDescription(props.row)">
              <div class="row items-start no-wrap q-gutter-sm">
                <div class="col tool-mobile-heading">
                  <div class="text-weight-medium">
                    <button v-if="toolDescription(props.row)" class="tool-description-link" @click="openDescription(props.row)">{{ localizedToolLabel(props.row) }}</button>
                    <span v-else>{{ localizedToolLabel(props.row) }}</span>
                    <SystemToolIcon v-if="props.row.can_disable === false" class="q-ml-xs" />
                  </div>
                  <div class="text-caption text-grey-7 ellipsis">{{ props.row.code }}</div>
                </div>
              </div>

              <div class="row items-center no-wrap q-mt-sm tool-mobile-conversation" @click.stop>
                <span class="text-caption text-grey-7">{{ $t('tools.conversationAccess') }}</span>
                <q-space />
                <q-toggle
                  :model-value="props.row.conversation_enabled"
                  :disable="!canEdit || props.row.can_disable === false || conversationAccessLoading.has(props.row.id)"
                  color="primary"
                  size="sm"
                  :aria-label="$t('tools.conversationAccessFor', { name: localizedToolLabel(props.row) })"
                  @update:model-value="value => updateConversationAccess(props.row, value)"
                >
                  <q-tooltip>{{ $t('tools.conversationAccessHint') }}</q-tooltip>
                </q-toggle>
                <q-spinner
                  v-if="conversationAccessLoading.has(props.row.id)"
                  size="18px"
                  color="primary"
                />
              </div>

              <div class="row items-center q-gutter-xs q-mt-sm tool-mobile-capabilities">
                <q-chip v-if="props.row.has_mcp" dense color="positive" text-color="white" icon="check" size="sm">
                  MCP
                </q-chip>
                <q-chip v-if="props.row.has_file_share" dense color="deep-purple" text-color="white" icon="folder_shared" size="sm">
                  {{ props.row.file_share_config?.service || $t('tools.fileShare') }}
                </q-chip>
                <q-chip v-if="props.row.has_messenger" dense color="indigo" text-color="white" icon="forum" size="sm">
                  {{ props.row.messenger_config?.service || $t('tools.messenger') }}
                </q-chip>
                <q-chip v-if="props.row.has_listener" dense color="info" text-color="white" icon="hearing" size="sm">
                  {{ $t('tools.listener') }}
                </q-chip>
              </div>
            </q-card-section>

            <q-separator />
            <q-card-actions align="right" class="q-px-sm q-py-xs">
              <q-btn
                flat round icon="download" size="sm" color="secondary"
                :aria-label="$t('tools.exportYaml')"
                @click="exportTool(props.row)"
              >
                <q-tooltip>{{ $t('tools.exportYaml') }}</q-tooltip>
              </q-btn>
              <q-btn
                v-if="canEdit && props.row.can_disable !== false && Object.keys(props.row.connection_schema?.params ?? {}).length"
                flat round icon="tune" size="sm" color="deep-purple"
                :aria-label="$t('tools.globalParams')"
                @click="openGlobalParams(props.row)"
              >
                <q-tooltip>{{ $t('tools.globalParams') }}</q-tooltip>
              </q-btn>
              <q-btn
                v-if="canEdit && props.row.can_edit && props.row.can_disable !== false"
                flat round icon="edit" size="sm" color="primary"
                :aria-label="$t('common.edit')"
                @click="openEdit(props.row)"
              />
              <q-btn
                v-if="canEdit && props.row.can_edit && props.row.can_disable !== false"
                flat round icon="delete" size="sm" color="negative"
                :aria-label="$t('common.delete')"
                @click="confirmDelete(props.row)"
              />
            </q-card-actions>
          </q-card>
        </div>
      </template>
    </q-table>
    <q-dialog v-model="descriptionOpen">
      <q-card class="tool-description-dialog">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ descriptionTool ? localizedToolLabel(descriptionTool) : '' }}</div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup :aria-label="$t('common.close')" />
        </q-card-section>
        <q-card-section class="scroll">
          <p v-if="descriptionTool?.can_disable === false"><SystemToolIcon /> {{ $t('tools.systemServiceHint') }}</p>
          <Markdown :content="descriptionTool ? toolDescription(descriptionTool) : ''" />
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- ============================================================
         Dialog import YAML
    ============================================================ -->
    <input ref="fileInput" type="file" accept=".yaml,.yml" class="hidden" @change="onFileSelected" />

    <q-dialog v-model="importDialogOpen">
      <q-card style="min-width: 480px; max-width: 600px; width: 100%">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ $t('tools.importTool') }}</div>
          <q-space />
          <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup class="text-white" @click="resetImport" />
        </q-card-section>

        <!-- Step 1: file selection -->
        <template v-if="!importConflict">
          <q-card-section class="q-gutter-y-md">
            <!-- Drop and selection area -->
            <div
              class="import-dropzone column items-center justify-center q-pa-xl cursor-pointer"
              :class="{ 'import-dropzone--active': importPreview }"
              @click="triggerFilePicker"
              @dragover.prevent
              @drop.prevent="onFileDrop"
            >
              <template v-if="!importPreview">
                <q-icon name="upload_file" size="48px" color="grey-5" />
                <div class="text-body2 text-grey-6 q-mt-sm">{{ $t('tools.dropYaml') }}</div>
              </template>
              <template v-else>
                <q-icon name="check_circle" size="48px" color="positive" />
                <div class="text-body1 text-weight-bold q-mt-sm">{{ importPreview.code }}</div>
                <div class="text-caption text-grey-7">{{ importPreview.label }}</div>
                <div class="text-caption text-grey-5 q-mt-xs">{{ $t('tools.changeFile') }}</div>
              </template>
            </div>

            <div v-if="importError" class="text-negative text-caption">{{ importError }}</div>
          </q-card-section>

          <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
            <q-btn flat :label="$t('common.cancel')" v-close-popup @click="resetImport" />
            <q-btn
              v-if="canEdit"
              color="primary" :label="$t('tools.import')" icon="upload"
              :loading="importLoading" :disable="!importYaml.trim()"
              @click="doImport(false)"
            />
          </q-card-actions>
        </template>

        <!-- Step 2: overwrite confirmation -->
        <template v-else>
          <q-card-section>
            <q-banner class="bg-warning text-white q-mb-md" rounded>
              <template v-slot:avatar><q-icon name="warning" /></template>
              {{ $t('tools.overwriteTitle', { name: importConflict }) }}
            </q-banner>
            <p class="text-body2 text-grey-8">
              {{ $t('tools.overwriteText') }}
            </p>
          </q-card-section>
          <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
            <q-btn flat :label="$t('common.cancel')" @click="resetImport" v-close-popup />
            <q-btn flat :label="$t('tools.changeFile')" @click="importConflict = null" />
            <q-btn v-if="canEdit" color="warning" :label="$t('tools.replace')" icon="swap_horiz" :loading="importLoading" @click="doImport(true)" />
          </q-card-actions>
        </template>
      </q-card>
    </q-dialog>

    <q-dialog v-model="globalParamsDialogOpen">
      <q-card style="min-width: 620px; max-width: 820px; width: 100%; max-height: 90vh; overflow-y: auto">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ $t('tools.globalParamsFor', { name: globalParamsTool ? localizedToolLabel(globalParamsTool) : '' }) }}</div>
          <q-space />
          <q-btn icon="close" flat round dense v-close-popup class="text-white" :aria-label="$t('common.close')" />
        </q-card-section>

        <q-card-section>
          <q-banner dense rounded class="bg-blue-1 text-blue-9 q-mb-md">
            <template #avatar><q-icon name="info" /></template>
            {{ $t('tools.globalParamsHint') }}
          </q-banner>
          <div class="q-gutter-y-md">
            <div v-for="row in globalParamRows" :key="row.name" class="tool-section">
              <div class="row items-start q-col-gutter-md">
                <div class="col">
                  <div class="text-weight-medium">{{ row.name }}</div>
                  <div v-if="row.description" class="text-caption text-grey-7 q-mb-sm">
                    {{ localizedGlobalParamDescription(row) }}
                  </div>
                  <q-toggle
                    v-if="row.type === 'boolean'"
                    :model-value="row.value === 'true'"
                    :label="row.value === 'true' ? $t('common.yes') : $t('common.no')"
                    color="primary"
                    @update:model-value="value => setGlobalBoolean(row, value)"
                  />
                  <q-select
                    v-else-if="row.type === 'user'"
                    v-model="row.value"
                    :options="approverOptions"
                    emit-value
                    map-options
                    clearable
                    dense
                    outlined
                    :loading="approversLoading"
                    @update:model-value="row.clear = false"
                  />
                  <q-input
                    v-else
                    v-model="row.value"
                    :type="row.type === 'password' ? 'password' : row.type === 'integer' ? 'number' : 'text'"
                    dense outlined
                    :placeholder="row.secret && row.configured && !row.clear ? $t('tools.secretConfigured') : row.default"
                    @update:model-value="row.clear = false"
                  >
                    <template v-if="row.configured || row.value" #append>
                      <q-btn
                        flat round dense icon="close" size="sm"
                        :aria-label="$t('tools.clearGlobalParam')"
                        @click="clearGlobalParam(row)"
                      />
                    </template>
                  </q-input>
                </div>
                <q-toggle
                  v-model="row.forced"
                  :disable="row.clear || (!row.configured && !row.value && !row.default)"
                  :label="$t('tools.forceGlobalParam')"
                  color="negative"
                  class="col-auto q-mt-lg"
                  @update:model-value="setGlobalParamForced(row, $event)"
                />
              </div>
            </div>
          </div>
        </q-card-section>

        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn flat :label="$t('common.cancel')" v-close-popup />
          <q-btn color="primary" :label="$t('common.save')" :loading="savingGlobalParams" @click="saveGlobalParams" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- ============================================================
         Create or edit dialog
    ============================================================ -->
    <q-dialog v-model="dialogOpen" maximized>
      <q-card style="max-width: 860px; width: 100%; margin: auto; height: fit-content; max-height: 95vh; overflow-y: auto;">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ editingTool ? $t('tools.editTool') : $t('tools.newTool') }}</div>
          <q-space />
          <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup class="text-white" />
        </q-card-section>

        <q-card-section>
          <q-form @submit.prevent="saveTool" class="q-gutter-y-md">

            <section class="tool-section">
              <div class="text-subtitle2 text-grey-7 q-mb-xs">{{ $t('tools.mainFields') }}</div>
              <div class="row q-gutter-md tool-main-fields-row">
                <q-input v-model="form.code" :label="$t('tools.technicalName')" :readonly="!!editingTool" :disable="!!editingTool"
                  :hint="$t('tools.technicalNameHint')" dense outlined class="col tool-main-field" :rules="[v => !!v || $t('tools.required')]" />
                <q-input v-model="form.label" :label="$t('tools.label')" dense outlined class="col tool-main-field" :rules="[v => !!v || $t('tools.required')]" />
              </div>
              <q-input v-model="form.description" :label="$t('tools.descriptionMarkdown')" type="textarea" dense outlined autogrow />

              <!-- Section toggles grouped below the description -->
              <div class="row q-gutter-md q-mt-sm tool-capability-toggles">
                <q-toggle v-model="hasMcp" :label="$t('tools.enableMcp')" color="positive" dense />
                <q-toggle v-model="hasFileShare" :label="$t('tools.enableFileShare')" color="deep-purple" dense />
                <q-toggle v-model="hasMessenger" :label="$t('tools.enableMessenger')" color="indigo" dense />
                <q-toggle v-model="hasListener" :label="$t('tools.enableListener')" color="info" dense />
              </div>
            </section>

            <section class="tool-section">
              <div class="row items-center q-mb-sm">
                <div class="text-subtitle2 text-grey-7">{{ $t('tools.connectionParams') }}</div>
                <q-space />
                <q-btn v-if="canEdit" flat icon="add" :label="$t('tools.addParam')" color="primary" @click="addConnParam" />
              </div>
              <div v-for="(param, key) in connParams" :key="key" class="connection-param-row">
                <q-input v-model="param.name" :label="$t('tools.paramName')" dense outlined class="connection-param-name" />
                <q-select v-model="param.type" :options="paramTypeOptions" :label="$t('tools.type')" emit-value map-options dense outlined class="connection-param-type" />
                <q-input v-model="param.description" :label="$t('tools.descriptionMarkdown')" dense outlined class="connection-param-description" />
                <q-toggle v-model="param.required" :label="$t('tools.required')" dense class="connection-param-required" />
                <q-btn
                  v-if="canEdit"
                  flat
                  round
                  icon="delete"
                  color="negative"
                  class="connection-param-delete"
                  :aria-label="$t('common.delete')"
                  @click="removeConnParam(key)"
                />
              </div>
            </section>

            <section v-if="hasMcp || hasFileShare || hasMessenger || hasListener" class="tool-section tool-section--active">
              <q-tabs v-model="activeTab" dense align="left" class="text-grey-7"
                active-color="primary" indicator-color="primary" narrow-indicator>
                <q-tab v-if="hasMcp" name="mcp" label="MCP" />
                <q-tab v-if="hasFileShare" name="file_share" :label="$t('tools.fileShare')" />
                <q-tab v-if="hasMessenger" name="messenger" :label="$t('tools.messenger')" />
                <q-tab v-if="hasListener" name="listener" :label="$t('tools.listener')" />
              </q-tabs>
              <q-separator class="q-mb-md" />

              <q-tab-panels v-model="activeTab" animated>
                <!-- Rubrique MCP -->
                <q-tab-panel name="mcp" class="q-pa-none">
                  <div class="tool-section__body">
                    <div class="row q-gutter-md">
                      <q-select v-model="form.mcp_config.type" :options="['http', 'sse', 'stdio']" :label="$t('tools.transport')"
                        dense outlined class="col-auto" style="min-width: 120px" />
                      <q-input v-if="form.mcp_config.type !== 'stdio'" v-model="form.mcp_config.url" label="URL *"
                        dense outlined class="col" placeholder="https://..." />
                      <q-input v-else v-model="form.mcp_config.command" :label="$t('tools.command')" dense outlined class="col" placeholder="npx" />
                    </div>
                    <q-input v-if="form.mcp_config.type === 'stdio'" v-model="mcpArgsRaw" :label="$t('tools.argsPerLine')"
                      type="textarea" dense outlined autogrow />
                    <q-input v-if="form.mcp_config.type === 'stdio'" v-model="mcpEnvRaw" :label="$t('tools.envJson')"
                      type="textarea" dense outlined autogrow :hint="$t('tools.writeOnlyMappingHint')"
                      :placeholder="$t('tools.envPlaceholder')" />
                    <q-input v-model="form.mcp_config.timeout" :label="$t('tools.timeoutSeconds')" type="number" dense outlined style="max-width: 160px" />

                    <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ $t('tools.auth') }}</div>
                    <div class="row q-gutter-md items-start">
                      <q-select v-model="form.mcp_config.auth.type" :options="authTypeOptions" :label="$t('tools.authType')"
                        emit-value map-options dense outlined class="col-auto" style="min-width: 140px" />
                      <template v-if="form.mcp_config.auth.type === 'bearer'">
                        <q-select v-model="form.mcp_config.auth.param" :options="connParamNames" :label="$t('tools.tokenParam')"
                          dense outlined class="col" clearable use-input input-debounce="0"
                          :hint="$t('tools.tokenParamHint')" />
                      </template>
                      <template v-if="form.mcp_config.auth.type === 'header'">
                        <q-input v-model="form.mcp_config.auth.header_name" :label="$t('tools.headerName')" dense outlined class="col"
                          placeholder="X-Redmine-API-Key" />
                        <q-select v-model="form.mcp_config.auth.param" :options="connParamNames" :label="$t('tools.valueParam')"
                          dense outlined class="col" clearable use-input input-debounce="0" />
                      </template>
                      <template v-if="form.mcp_config.auth.type === 'basic'">
                        <q-select v-model="form.mcp_config.auth.login_param" :options="connParamNames" :label="$t('tools.loginParam')"
                          dense outlined class="col" clearable use-input input-debounce="0" />
                        <q-select v-model="form.mcp_config.auth.password_param" :options="connParamNames" :label="$t('tools.passwordParam')"
                          dense outlined class="col" clearable use-input input-debounce="0" />
                      </template>
                    </div>
                    <q-banner
                      v-if="form.mcp_config.auth.token_static_configured"
                      dense rounded class="bg-orange-1 text-orange-10 q-mt-sm"
                    >
                      <template #avatar><q-icon name="key" color="orange-9" /></template>
                      {{ $t('tools.legacyStaticTokenConfigured') }}
                      <template #action>
                        <q-btn
                          v-if="canEdit"
                          flat color="negative" :label="$t('tools.removeLegacySecret')"
                          @click="clearLegacyStaticToken"
                        />
                      </template>
                    </q-banner>
                    <q-input v-if="form.mcp_config.auth.type !== 'none' && form.mcp_config.auth.type !== 'basic' && form.mcp_config.type !== 'stdio'"
                      v-model="form.mcp_config.auth.url_param" :label="$t('tools.urlParam')"
                      dense outlined style="max-width: 280px" :hint="$t('tools.urlParamHint')" />
                    <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ $t('tools.staticHeaders') }}</div>
                    <q-input v-model="mcpHeadersRaw" :label="$t('tools.headersJson')" type="textarea" dense outlined autogrow
                      :placeholder="$t('tools.headersPlaceholder')" :hint="$t('tools.writeOnlyMappingHint')" />
                    <div class="row justify-end q-mt-md">
                      <q-btn
                        v-if="canEdit"
                        outline
                        color="secondary"
                        icon="lan"
                        :label="$t('tools.testMcpConnection')"
                        :disable="!form.code.trim()"
                        @click="openMcpTest"
                      />
                    </div>
                  </div>
                </q-tab-panel>

                <!-- File-sharing section. -->
                <q-tab-panel name="file_share" class="q-pa-none">
                  <div class="tool-section__body">
                    <div class="row q-gutter-md">
                      <q-select v-model="form.file_share_config.service" :options="fileShareBridgeOptions"
                        emit-value map-options :label="$t('tools.fileShareServiceLabel')"
                        dense outlined class="col-auto" style="min-width: 200px"
                        @update:model-value="onFileShareServiceChange" />
                      <q-input v-model="form.file_share_config.base_url" label="base_url *" dense outlined class="col"
                        placeholder="https://cloud.example.com" />
                    </div>

                    <template v-if="currentFileShareBridge">
                      <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ $t('tools.fileShareParamMap') }}</div>
                      <div v-for="p in currentFileShareBridge.params" :key="p.key" class="row q-gutter-md items-center">
                        <div class="col-3 text-body2">
                          {{ p.label }}<span v-if="p.required" class="text-negative"> *</span>
                        </div>
                        <q-select
                          v-model="form.file_share_config.param_map[p.key]"
                          :options="connParamNames" use-input input-debounce="0" clearable
                          :label="$t('tools.mapToParam')"
                          dense outlined class="col"
                        />
                      </div>
                      <q-banner dense class="bg-grey-2 text-grey-8 q-mt-sm" rounded>
                        <template v-slot:avatar><q-icon name="info" color="deep-purple" /></template>
                        {{ $t('tools.fileShareCredsHint') }}
                      </q-banner>
                    </template>
                  </div>
                </q-tab-panel>

                <!-- Messaging section, independent from File sharing. -->
                <q-tab-panel name="messenger" class="q-pa-none">
                  <div class="tool-section__body">
                    <q-select
                      v-model="form.messenger_config.service"
                      :options="messengerBridgeOptions"
                      emit-value map-options
                      :label="$t('tools.messengerServiceLabel')"
                      dense outlined
                      style="max-width: 320px"
                      @update:model-value="onMessengerServiceChange(true)"
                    />

                    <template v-if="currentMessengerBridge">
                      <div v-if="currentMessengerBridge.settings.length" class="q-gutter-y-sm">
                        <div class="text-caption text-grey-6">{{ $t('tools.messengerServerSettings') }}</div>
                        <q-input
                          v-for="setting in currentMessengerBridge.settings"
                          :key="setting.key"
                          v-model="form.messenger_config.settings[setting.key]"
                          :type="setting.type === 'password' ? 'password' : 'text'"
                          :label="`${setting.label}${setting.required ? ' *' : ''}`"
                          :hint="setting.description"
                          dense outlined
                        />
                      </div>

                      <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ $t('tools.messengerParamMap') }}</div>
                      <div v-for="p in currentMessengerBridge.params" :key="p.key" class="row q-gutter-md items-center">
                        <div class="col-3 text-body2">
                          {{ p.label }}<span v-if="p.required" class="text-negative"> *</span>
                        </div>
                        <q-select
                          v-model="form.messenger_config.param_map[p.key]"
                          :options="connParamNames"
                          use-input input-debounce="0" clearable
                          :label="$t('tools.mapToParam')"
                          dense outlined class="col"
                        />
                      </div>
                      <q-banner dense class="bg-grey-2 text-grey-8 q-mt-sm" rounded>
                        <template #avatar><q-icon name="info" color="indigo" /></template>
                        {{ $t('tools.messengerCredsHint') }}
                      </q-banner>
                    </template>
                  </div>
                </q-tab-panel>

                <!-- Rubrique Listener webhook -->
                <q-tab-panel name="listener" class="q-pa-none">
                  <div class="tool-section__body">
                    <div class="row q-gutter-md">
                      <q-input v-model="form.listener_config.connection_key" label="connection_key *" dense outlined class="col" />
                      <q-input v-model="form.listener_config.url" :label="$t('tools.urlOptional')" dense outlined class="col" />
                    </div>
                    <q-banner
                      v-if="form.listener_config.token_configured"
                      dense rounded class="bg-orange-1 text-orange-10 q-mt-sm"
                    >
                      <template #avatar><q-icon name="key" color="orange-9" /></template>
                      {{ $t('tools.legacyListenerTokenConfigured') }}
                      <template #action>
                        <q-btn
                          v-if="canEdit"
                          flat color="negative" :label="$t('tools.removeLegacySecret')"
                          @click="clearLegacyListenerToken"
                        />
                      </template>
                    </q-banner>
                    <q-separator class="q-my-sm" />
                    <div class="text-subtitle2 text-grey-7 q-mb-xs">{{ $t('tools.taskTemplate') }}</div>
                    <q-input v-model="form.task_config.label" :label="$t('tools.labelVariables')" dense outlined />
                    <q-input v-model="form.task_config.objective" :label="$t('tools.objectiveVariables')" type="textarea" dense outlined autogrow />
                  </div>
                </q-tab-panel>
              </q-tab-panels>
            </section>

            

          </q-form>
        </q-card-section>

        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn flat :label="$t('common.cancel')" v-close-popup />
          <q-btn v-if="canEdit" color="primary" :label="editingTool ? $t('common.save') : $t('common.create')" :loading="saving" @click="saveTool" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Non-persistent MCP connection test dialog. -->
    <q-dialog v-model="mcpTestDialogOpen" @hide="clearMcpTest">
      <q-card class="mcp-test-dialog" style="min-width: 480px; max-width: 720px; width: 100%">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ $t('tools.testMcpTitle') }}</div>
          <q-space />
          <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup class="text-white" />
        </q-card-section>

        <q-card-section class="q-gutter-y-md mcp-test-dialog__body">
          <div class="text-body2 text-grey-7">{{ $t('tools.testMcpIntro') }}</div>

          <div v-if="mcpTestConnectionParams.length" class="q-gutter-y-sm">
            <div class="text-subtitle2">{{ $t('tools.testMcpParameters') }}</div>
            <q-input
              v-for="param in mcpTestConnectionParams"
              :key="param.name"
              v-model="mcpTestParams[param.name]"
              :type="param.type === 'password' ? 'password' : param.type === 'integer' ? 'number' : 'text'"
              :label="`${param.name}${param.required ? ' *' : ''}`"
              :hint="param.description"
              dense
              outlined
            />
          </div>

          <q-banner
            v-if="mcpTestResult"
            rounded
            :class="mcpTestResult.success ? 'bg-green-1 text-positive' : 'bg-red-1 text-negative'"
          >
            <template #avatar>
              <q-icon :name="mcpTestResult.success ? 'check_circle' : 'error'" />
            </template>
            {{ mcpTestResult.message }}
          </q-banner>

          <q-banner v-else-if="mcpTestError" rounded class="bg-red-1 text-negative">
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
                    {{ $t(`tools.testMcpStages.${diagnostic.stage}`) }}
                  </span>
                  <q-badge
                    outline
                    :color="mcpDiagnosticColor(diagnostic.status)"
                    :label="$t(`tools.testMcpStatuses.${diagnostic.status}`)"
                  />
                </q-item-label>
                <q-item-label caption>{{ diagnostic.message }}</q-item-label>
              </q-item-section>
              <q-item-section v-if="diagnostic.duration_ms !== null" side>
                <q-badge
                  color="grey-7"
                  :label="$t('tools.testMcpDuration', { duration: diagnostic.duration_ms })"
                />
              </q-item-section>
            </q-item>
          </q-list>

          <div v-if="mcpTestResult?.tools.length">
            <div class="text-subtitle2 q-mb-sm">
              {{ $t('tools.testMcpFunctionsFound', { count: mcpTestResult.tools.length }) }}
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
          <q-btn flat :label="$t('common.close')" v-close-popup />
          <q-btn
            v-if="canEdit"
            color="secondary"
            icon="lan"
            :label="$t('tools.testMcpRun')"
            :loading="testingMcp"
            @click="testMcpConnection"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- Deletion dialog. -->
    <q-dialog v-model="deleteDialogOpen">
      <q-card style="min-width: 340px">
        <q-card-section class="galaris-dialog-title">
          <div class="text-h6">{{ $t('tools.deleteTool') }}</div>
          <q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="$t('common.close')" />
        </q-card-section>
        <q-card-section>
          {{ $t('tools.deleteMessage', { name: deletingTool ? localizedToolLabel(deletingTool) : '' }) }}
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="$t('common.cancel')" v-close-popup />
          <q-btn v-if="canEdit" color="negative" :label="$t('common.delete')" :loading="saving" @click="doDelete" />
        </q-card-actions>
      </q-card>
    </q-dialog>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { Markdown } from '@/core/util'
import SystemToolIcon from './SystemToolIcon.vue'
import { useQuasar } from 'quasar'
import { useToolStore } from '../stores/toolStore'
import toolService from '../services/toolService'
import type {
  Tool,
  McpAuth,
  McpConfig,
  FileShareConfig,
  FileShareBridge,
  MessengerConfig,
  MessengerBridge,
  ListenerConfig,
  ConnectionParamDef,
  TaskConfig,
  ToolMcpTestRequest,
  ToolMcpTestDiagnosticStatus,
  ToolMcpTestResponse,
  ToolGlobalParamUpdate,
} from '../services/toolService'
import api from '@/core/api'
import { useI18n } from 'vue-i18n'
import { connectionParamMessageKey, sortedConnectionParamEntries, toolMessageKey } from '../presentation'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { mailService, type MailApproverOption } from '@/app/connection'

const $q = useQuasar()
const { t } = useI18n()
const toolStore = useToolStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.TOOL_EDIT))
const conversationAccessLoading = ref<Set<number>>(new Set())

type GlobalParamRow = {
  name: string
  type: string
  description: string
  default: string
  secret: boolean
  configured: boolean
  forced: boolean
  clear: boolean
  value: string | null
}

const globalParamsDialogOpen = ref(false)
const globalParamsTool = ref<Tool | null>(null)
const globalParamRows = ref<GlobalParamRow[]>([])
const savingGlobalParams = ref(false)
const approvers = ref<MailApproverOption[]>([])
const approversLoading = ref(false)
const approverOptions = computed(() => approvers.value.map(user => ({
  value: String(user.id),
  label: user.label === user.email ? user.email : `${user.label} · ${user.email}`,
})))

function localizedGlobalParamDescription(row: GlobalParamRow): string {
  const key = globalParamsTool.value
    ? connectionParamMessageKey(globalParamsTool.value.code, row.name)
    : null
  return key ? t(key) : row.description
}

async function openGlobalParams(tool: Tool): Promise<void> {
  if (!canEdit.value || tool.can_disable === false) return
  const { data } = await toolService.getGlobalParams(tool.id)
  globalParamsTool.value = tool
  if (tool.code === 'mail' && approvers.value.length === 0) {
    approversLoading.value = true
    try {
      approvers.value = (await mailService.listApprovers()).data
    } catch (error) {
      $q.notify({
        type: 'negative',
        message: `${t('connection.mail.approversError')}: ${error instanceof Error ? error.message : String(error)}`,
      })
    } finally {
      approversLoading.value = false
    }
  }
  globalParamRows.value = sortedConnectionParamEntries(tool.connection_schema.params).map(([name, definition]) => {
    const current = data.params[name]
    return {
      name,
      type: definition.type,
      description: definition.description,
      default: definition.default || '',
      secret: definition.type === 'password',
      configured: current?.configured ?? false,
      forced: current?.forced ?? false,
      clear: false,
      value: current?.secret ? '' : current?.value ?? '',
    }
  })
  globalParamsDialogOpen.value = true
}

function setGlobalBoolean(row: GlobalParamRow, value: boolean): void {
  row.value = value ? 'true' : 'false'
  row.clear = false
}

function clearGlobalParam(row: GlobalParamRow): void {
  row.value = ''
  row.configured = false
  row.forced = false
  row.clear = true
}

function setGlobalParamForced(row: GlobalParamRow, forced: boolean): void {
  if (forced && !row.configured && !row.value && row.default) {
    row.value = row.default
    row.clear = false
  }
}

async function saveGlobalParams(): Promise<void> {
  if (!globalParamsTool.value || !canEdit.value) return
  savingGlobalParams.value = true
  try {
    const params: Record<string, ToolGlobalParamUpdate> = {}
    for (const row of globalParamRows.value) {
      const typedValue = row.value === '' ? null : row.value
      params[row.name] = {
        value: typedValue,
        forced: row.forced,
        clear: row.clear || (!row.secret && typedValue === null),
      }
    }
    await toolService.updateGlobalParams(globalParamsTool.value.id, params)
    await toolStore.fetchTools()
    globalParamsDialogOpen.value = false
    $q.notify({ type: 'positive', message: t('tools.globalParamsUpdated') })
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
    $q.notify({ type: 'negative', message: detail || t('tools.globalParamsError') })
  } finally {
    savingGlobalParams.value = false
  }
}

async function updateConversationAccess(tool: Tool, enabled: boolean): Promise<void> {
  if (tool.can_disable === false) return
  if (!canEdit.value || conversationAccessLoading.value.has(tool.id)) return
  conversationAccessLoading.value = new Set(conversationAccessLoading.value).add(tool.id)
  try {
    await toolService.updateConversationAccess(tool.id, enabled)
    await toolStore.fetchTools()
    $q.notify({ type: 'positive', message: t('tools.conversationAccessUpdated') })
  } catch (error: unknown) {
    const detail = (error as { response?: { data?: { detail?: string } } })
      .response?.data?.detail
    $q.notify({
      type: 'negative',
      message: detail || t('tools.conversationAccessError'),
    })
  } finally {
    const next = new Set(conversationAccessLoading.value)
    next.delete(tool.id)
    conversationAccessLoading.value = next
  }
}

const descriptionOpen = ref(false)
const descriptionTool = ref<Tool | null>(null)
function toolDescription(tool: Tool): string {
  if (!tool.description?.trim()) return ''
  const key = toolMessageKey(tool.code, 'description')
  return key && (!tool.can_edit || tool.description === t(key, {}, { locale: 'en' })) ? t(key) : tool.description
}
function openDescription(tool: Tool): void {
  if (!toolDescription(tool)) return
  descriptionTool.value = tool
  descriptionOpen.value = true
}

function localizedToolLabel(tool: Tool): string {
  const key = toolMessageKey(tool.code, 'label')
  return key && (!tool.can_edit || tool.label === t(key, {}, { locale: 'en' })) ? t(key) : tool.label
}

// =============================================================================
// Table
// =============================================================================

const columns = computed(() => [
  { name: 'code',        label: t('agent.colName'),     field: 'code',     align: 'left'   as const, sortable: true },
  { name: 'label', label: t('tools.labelColumn'), field: 'label', align: 'left' as const, sortable: true },
  { name: 'has_mcp',     label: 'MCP',     field: 'has_mcp',  align: 'center' as const },
  { name: 'has_file_share', label: t('tools.fileShare'), field: 'has_file_share', align: 'center' as const },
  { name: 'has_messenger', label: t('tools.messenger'), field: 'has_messenger', align: 'center' as const },
  { name: 'has_listener', label: t('tools.listener'), field: 'has_listener', align: 'center' as const },
  { name: 'conversation_enabled', label: t('tools.conversationAccess'), field: 'conversation_enabled', align: 'center' as const },
  { name: 'actions',     label: '',        field: 'actions',  align: 'right'  as const },
])

const authTypeOptions = computed(() => [
  { label: t('tools.authNone'), value: 'none' },
  { label: t('tools.authBearer'), value: 'bearer' },
  { label: t('tools.authHeader'), value: 'header' },
  { label: t('tools.authBasic'), value: 'basic' },
])

const paramTypeOptions = [
  { label: 'string', value: 'string' },
  { label: 'password', value: 'password' },
  { label: 'integer', value: 'integer' },
  { label: 'boolean', value: 'boolean' },
  { label: 'user', value: 'user' },
]

// Available file-share bridges returned by the backend drive the form.
const fileShareBridges = ref<FileShareBridge[]>([])
const fileShareBridgeOptions = computed(() =>
  fileShareBridges.value.map(b => ({ label: b.label, value: b.service }))
)
const currentFileShareBridge = computed<FileShareBridge | null>(() =>
  fileShareBridges.value.find(b => b.service === form.value.file_share_config.service) ?? null
)
const messengerBridges = ref<MessengerBridge[]>([])
const messengerBridgeOptions = computed(() =>
  messengerBridges.value.map(bridge => ({
    label: bridge.label,
    value: bridge.service,
  }))
)
const currentMessengerBridge = computed<MessengerBridge | null>(() =>
  messengerBridges.value.find(
    bridge => bridge.service === form.value.messenger_config.service
  ) ?? null
)

// =============================================================================
// Export
// =============================================================================

async function exportTool(tool: Tool) {
  try {
    const response = await api.get(`/tools/${tool.id}/export`, { responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([response.data], { type: 'text/plain' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${tool.code}.yaml`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    $q.notify({ type: 'negative', message: t('tools.exportError') })
  }
}

// =============================================================================
// Import
// =============================================================================

const importDialogOpen = ref(false)
const importYaml = ref('')
const importLoading = ref(false)
const importError = ref<string | null>(null)
const importConflict = ref<string | null>(null)
const importPreview = ref<{ code: string; label: string } | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

function openImport() {
  if (!canEdit.value) return
  resetImport()
  importDialogOpen.value = true
}

function resetImport() {
  importYaml.value = ''
  importError.value = null
  importConflict.value = null
  importPreview.value = null
  importLoading.value = false
}

function triggerFilePicker() {
  fileInput.value?.click()
}

function readFile(file: File) {
  const reader = new FileReader()
  reader.onload = (e) => {
    const content = String(e.target?.result ?? '')
    importYaml.value = content
    importError.value = null
    // Extract code and label from the preview with regular expressions.
    const codeMatch = content.match(/^code\s*:\s*(.+)$/m)
    const labelMatch = content.match(/^label\s*:\s*(.+)$/m)
    importPreview.value = (codeMatch && labelMatch)
      ? { code: codeMatch[1].trim(), label: labelMatch[1].trim() }
      : null
    if (!importPreview.value)
      importError.value = t('tools.detectError')
  }
  reader.readAsText(file)
}

function onFileSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) readFile(file)
  ;(event.target as HTMLInputElement).value = ''
}

function onFileDrop(event: DragEvent) {
  const file = event.dataTransfer?.files?.[0]
  if (file) readFile(file)
}

async function doImport(overwrite: boolean) {
  if (!canEdit.value) return
  if (!importYaml.value.trim()) return
  importLoading.value = true
  importError.value = null
  try {
    const { data } = await toolService.importTool(importYaml.value, overwrite)
    $q.notify({
      type: 'positive',
      message: data.created
        ? t('tools.savedCreated', { code: data.code })
        : t('tools.savedUpdated', { code: data.code })
    })
    await toolStore.fetchTools()
    importDialogOpen.value = false
    resetImport()
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: { detail?: string } } }
    if (err.response?.status === 409) {
      // The tool exists; switch to the overwrite confirmation step.
      const detail = err.response.data?.detail ?? ''
      const match = detail.match(/'([^']+)'/)
      importConflict.value = match ? match[1] : importPreview.value?.code ?? '?'
    } else {
      importError.value = err.response?.data?.detail ?? t('tools.importError')
    }
  } finally {
    importLoading.value = false
  }
}

// =============================================================================
// Create or edit form.
// =============================================================================

type ConnParamRow = { name: string; type: string; required: boolean; description: string; default: string }

const dialogOpen = ref(false)
const deleteDialogOpen = ref(false)
const saving = ref(false)
const editingTool = ref<Tool | null>(null)
const deletingTool = ref<Tool | null>(null)
const mcpTestDialogOpen = ref(false)
const testingMcp = ref(false)
const mcpTestParams = ref<Record<string, string>>({})
const mcpTestResult = ref<ToolMcpTestResponse | null>(null)
const mcpTestError = ref<string | null>(null)

const hasMcp = ref(false)
const hasFileShare = ref(false)
const hasMessenger = ref(false)
const hasListener = ref(false)
const activeTab = ref<string>('')
const mcpArgsRaw = ref('')
const mcpEnvRaw = ref('')

function firstEnabledTab(): string {
  if (hasMcp.value) return 'mcp'
  if (hasFileShare.value) return 'file_share'
  if (hasMessenger.value) return 'messenger'
  if (hasListener.value) return 'listener'
  return ''
}

// Focus a newly enabled section and fall back when the current tab is disabled.
watch([hasMcp, hasFileShare, hasMessenger, hasListener], ([m, f, g, l], [pm, pf, pg, pl]) => {
  if (m && !pm) activeTab.value = 'mcp'
  else if (f && !pf) activeTab.value = 'file_share'
  else if (g && !pg) activeTab.value = 'messenger'
  else if (l && !pl) activeTab.value = 'listener'
  const enabled = [
    m ? 'mcp' : '',
    f ? 'file_share' : '',
    g ? 'messenger' : '',
    l ? 'listener' : '',
  ].filter(Boolean)
  if (!enabled.includes(activeTab.value)) activeTab.value = enabled[0] ?? ''
})
const mcpHeadersRaw = ref('')
const connParams = ref<ConnParamRow[]>([])
const mcpTestConnectionParams = computed(() =>
  connParams.value.filter(param => param.name.trim() !== '')
)

// Connection parameter names used by authentication selects.
const connParamNames = computed(() =>
  connParams.value.map(p => p.name).filter(n => n.trim() !== '')
)

type McpFormConfig = Omit<McpConfig, 'auth'> & { auth: McpAuth }

const emptyMcpConfig = (): McpFormConfig => ({
  type: 'http', url: '', command: '', args: [], env: {}, headers: {},
  auth: { type: 'none', header_name: 'Authorization', login_param: 'login', password_param: 'password' },
  timeout: 120,
})

function mcpConfigForForm(config?: McpConfig | null): McpFormConfig {
  const defaults = emptyMcpConfig()
  if (!config) return defaults
  const cloned: McpConfig = JSON.parse(JSON.stringify(config))
  return {
    ...defaults,
    ...cloned,
    auth: {
      ...defaults.auth,
      ...(cloned.auth ?? {}),
    },
  }
}
const emptyFileShareConfig = (): FileShareConfig => ({ service: '', base_url: '', param_map: {} })
const emptyMessengerConfig = (): MessengerConfig => ({
  service: '',
  settings: {},
  param_map: {},
})

// Initialize param_map keys for the selected bridge.
function onFileShareServiceChange() {
  const bridge = currentFileShareBridge.value
  if (!bridge) return
  const previous = form.value.file_share_config.param_map
  form.value.file_share_config.param_map = Object.fromEntries(
    bridge.params.map(param => [param.key, previous[param.key] ?? '']),
  )
}

// Select the first available bridge when file sharing is enabled.
watch(hasFileShare, (on) => {
  if (on && !form.value.file_share_config.service && fileShareBridges.value.length) {
    form.value.file_share_config.service = fileShareBridges.value[0].service
    onFileShareServiceChange()
  }
})

function onMessengerServiceChange(reset = false) {
  const bridge = currentMessengerBridge.value
  if (!bridge) return
  const config = form.value.messenger_config
  if (reset) {
    config.settings = {}
    config.param_map = {}
  }
  const previousSettings = config.settings
  const previousParamMap = config.param_map
  config.settings = Object.fromEntries(
    bridge.settings.map(setting => [setting.key, previousSettings[setting.key] ?? setting.default ?? '']),
  )
  config.param_map = Object.fromEntries(
    bridge.params.map(param => [param.key, previousParamMap[param.key] ?? '']),
  )
}

watch(hasMessenger, (on) => {
  if (on && !form.value.messenger_config.service && messengerBridges.value.length) {
    form.value.messenger_config.service = messengerBridges.value[0].service
    onMessengerServiceChange()
  }
})

const emptyListenerConfig = (): ListenerConfig => ({ connection_key: '' })
const emptyTaskConfig = (): TaskConfig => ({ label: '', objective: '' })

interface FormData {
  code: string; label: string; description: string
  mcp_config: McpFormConfig
  file_share_config: FileShareConfig
  messenger_config: MessengerConfig
  listener_config: ListenerConfig
  task_config: TaskConfig
}

const form = ref<FormData>({
  code: '', label: '', description: '',
  mcp_config: emptyMcpConfig(),
  file_share_config: emptyFileShareConfig(),
  messenger_config: emptyMessengerConfig(),
  listener_config: emptyListenerConfig(),
  task_config: emptyTaskConfig(),
})

function resetForm() {
  form.value = {
    code: '',
    label: '',
    description: '',
    mcp_config: emptyMcpConfig(),
    file_share_config: emptyFileShareConfig(),
    messenger_config: emptyMessengerConfig(),
    listener_config: emptyListenerConfig(),
    task_config: emptyTaskConfig(),
  }
  hasMcp.value = false
  hasFileShare.value = false
  hasMessenger.value = false
  hasListener.value = false
  activeTab.value = ''
  mcpArgsRaw.value = ''; mcpEnvRaw.value = ''; mcpHeadersRaw.value = ''; connParams.value = []
  clearMcpTest()
}

function openCreate() { if (!canEdit.value) return; editingTool.value = null; resetForm(); dialogOpen.value = true }

function openEdit(tool: Tool) {
  if (!canEdit.value || tool.can_disable === false) return
  resetForm()
  editingTool.value = tool
  form.value.code = tool.code
  form.value.label = tool.label
  form.value.description = tool.description

  hasMcp.value = !!tool.mcp_config
  if (tool.mcp_config) {
    form.value.mcp_config = mcpConfigForForm(tool.mcp_config)
    mcpArgsRaw.value = (tool.mcp_config.args ?? []).join('\n')
    mcpEnvRaw.value = Object.keys(tool.mcp_config.env ?? {}).length ? JSON.stringify(tool.mcp_config.env, null, 2) : ''
    mcpHeadersRaw.value = Object.keys(tool.mcp_config.headers ?? {}).length ? JSON.stringify(tool.mcp_config.headers, null, 2) : ''
  } else {
    form.value.mcp_config = emptyMcpConfig(); mcpArgsRaw.value = ''; mcpEnvRaw.value = ''; mcpHeadersRaw.value = ''
  }

  hasFileShare.value = !!tool.file_share_config
  form.value.file_share_config = tool.file_share_config
    ? { ...emptyFileShareConfig(), ...JSON.parse(JSON.stringify(tool.file_share_config)) }
    : emptyFileShareConfig()
  onFileShareServiceChange()

  hasMessenger.value = !!tool.messenger_config
  form.value.messenger_config = tool.messenger_config
    ? { ...emptyMessengerConfig(), ...JSON.parse(JSON.stringify(tool.messenger_config)) }
    : emptyMessengerConfig()
  onMessengerServiceChange()

  hasListener.value = !!tool.listener_config || !!tool.task_config
  form.value.listener_config = tool.listener_config ? JSON.parse(JSON.stringify(tool.listener_config)) : emptyListenerConfig()

  form.value.task_config = tool.task_config ? JSON.parse(JSON.stringify(tool.task_config)) : emptyTaskConfig()

  connParams.value = sortedConnectionParamEntries(tool.connection_schema.params ?? {}).map(([name, def]) => ({
    name, type: def.type, required: def.required, description: def.description, default: def.default ?? '',
  }))
  activeTab.value = firstEnabledTab()
  dialogOpen.value = true
}

function addConnParam() { connParams.value.push({ name: '', type: 'string', required: true, description: '', default: '' }) }
function removeConnParam(index: number) { connParams.value.splice(index, 1) }

function clearLegacyStaticToken() {
  const auth = form.value.mcp_config.auth
  if (!auth) return
  auth.token_static = ''
  auth.token_static_configured = false
}

function clearLegacyListenerToken() {
  form.value.listener_config.token = ''
  form.value.listener_config.token_configured = false
}

function parseStringMap(raw: string, field: string): Record<string, string> {
  if (!raw.trim()) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    throw new Error(t('tools.invalidJsonMap', { field }))
  }
  if (
    !parsed
    || typeof parsed !== 'object'
    || Array.isArray(parsed)
    || Object.values(parsed).some(value => typeof value !== 'string')
  ) {
    throw new Error(t('tools.invalidJsonMap', { field }))
  }
  return parsed as Record<string, string>
}

function buildMcpConfig(): McpConfig {
  const auth = {
    ...emptyMcpConfig().auth,
    ...form.value.mcp_config.auth,
  }
  delete auth.token_static_configured
  return {
    ...form.value.mcp_config,
    auth,
    args: mcpArgsRaw.value ? mcpArgsRaw.value.split('\n').map(s => s.trim()).filter(Boolean) : [],
    env: parseStringMap(mcpEnvRaw.value, t('tools.envJson')),
    headers: parseStringMap(mcpHeadersRaw.value, t('tools.headersJson')),
  }
}

function buildPayload() {
  const mcp_config: McpConfig | null = hasMcp.value ? buildMcpConfig() : null
  const file_share_config: FileShareConfig | null = hasFileShare.value ? {
    service: form.value.file_share_config.service,
    base_url: form.value.file_share_config.base_url.trim(),
    param_map: Object.fromEntries(
      Object.entries(form.value.file_share_config.param_map)
        .map(([k, v]) => [k, (v ?? '').trim()])
        .filter(([, v]) => v !== ''),
    ),
  } : null
  const messenger_config: MessengerConfig | null = hasMessenger.value ? {
    service: form.value.messenger_config.service,
    settings: Object.fromEntries(
      Object.entries(form.value.messenger_config.settings)
        .map(([key, value]) => [key, (value ?? '').trim()])
    ),
    param_map: Object.fromEntries(
      Object.entries(form.value.messenger_config.param_map)
        .map(([key, value]) => [key, (value ?? '').trim()])
        .filter(([, value]) => value !== '')
    ),
  } : null
  const listener_config = hasListener.value ? { ...form.value.listener_config } : null
  if (listener_config) delete listener_config.token_configured
  const task_config = hasListener.value ? { ...form.value.task_config } : null
  const params: Record<string, ConnectionParamDef> = {}
  for (const [order, p] of connParams.value.entries()) {
    if (p.name.trim()) params[p.name.trim()] = { type: p.type, required: p.required, description: p.description, default: p.default, order }
  }
  return {
    mcp_config,
    file_share_config,
    messenger_config,
    listener_config,
    task_config,
    connection_schema: { params },
  }
}

function clearMcpTest() {
  mcpTestParams.value = {}
  mcpTestResult.value = null
  mcpTestError.value = null
}

function openMcpTest() {
  if (!canEdit.value) return
  clearMcpTest()
  mcpTestParams.value = Object.fromEntries(
    mcpTestConnectionParams.value.map(param => [
      param.name,
      param.type === 'password' ? '' : param.default,
    ])
  )
  mcpTestDialogOpen.value = true
}

function mcpTestErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (error instanceof Error && error.message) return error.message
  return t('tools.testMcpError')
}

function mcpDiagnosticIcon(status: ToolMcpTestDiagnosticStatus): string {
  if (status === 'success') return 'check_circle'
  if (status === 'error') return 'cancel'
  if (status === 'warning') return 'warning'
  if (status === 'skipped') return 'remove_circle_outline'
  return 'info'
}

function mcpDiagnosticColor(status: ToolMcpTestDiagnosticStatus): string {
  if (status === 'success') return 'positive'
  if (status === 'error') return 'negative'
  if (status === 'warning') return 'warning'
  if (status === 'skipped') return 'grey-6'
  return 'info'
}

async function testMcpConnection() {
  if (!canEdit.value) return
  testingMcp.value = true
  mcpTestResult.value = null
  mcpTestError.value = null
  try {
    const params = Object.fromEntries(
      Object.entries(mcpTestParams.value).map(([name, value]) => [
        name,
        value === '' ? null : value,
      ])
    )
    const payload: ToolMcpTestRequest = {
      code: form.value.code.trim(),
      mcp_config: buildMcpConfig(),
      params,
    }
    if (editingTool.value) payload.tool_id = editingTool.value.id
    const { data } = await toolService.testMcpConnection(payload)
    mcpTestResult.value = data
  } catch (error: unknown) {
    mcpTestError.value = mcpTestErrorMessage(error)
  } finally {
    testingMcp.value = false
  }
}

async function saveTool() {
  if (!canEdit.value) return
  if (!form.value.code.trim() || !form.value.label.trim()) {
    $q.notify({ type: 'warning', message: t('tools.saveRequired') }); return
  }
  saving.value = true
  try {
    const payload = buildPayload()
    if (editingTool.value) {
      await toolStore.updateTool(editingTool.value.id, { label: form.value.label, description: form.value.description, ...payload })
      $q.notify({ type: 'positive', message: t('tools.updated') })
    } else {
      await toolStore.createTool({ code: form.value.code, label: form.value.label, description: form.value.description, ...payload })
      $q.notify({ type: 'positive', message: t('tools.created') })
    }
    dialogOpen.value = false
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    const localMessage = e instanceof Error ? e.message : ''
    $q.notify({
      type: 'negative',
      message: err?.response?.data?.detail ?? (localMessage || t('tools.saveError')),
    })
  } finally {
    saving.value = false
  }
}

function confirmDelete(tool: Tool) { if (!canEdit.value || tool.can_disable === false) return; deletingTool.value = tool; deleteDialogOpen.value = true }

async function doDelete() {
  if (!canEdit.value) return
  if (!deletingTool.value) return
  saving.value = true
  try {
    await toolStore.deleteTool(deletingTool.value.id)
    $q.notify({ type: 'positive', message: t('tools.deleted') })
    deleteDialogOpen.value = false
  } catch {
    $q.notify({ type: 'negative', message: t('tools.deleteError') })
  } finally {
    saving.value = false
  }
}

async function fetchFileShareBridges() {
  try {
    const { data } = await toolService.getFileShareBridges()
    fileShareBridges.value = data
  } catch {
    fileShareBridges.value = []
  }
}

async function fetchMessengerBridges() {
  try {
    const { data } = await toolService.getMessengerBridges()
    messengerBridges.value = data
  } catch {
    messengerBridges.value = []
  }
}

onMounted(() => {
  toolStore.fetchTools()
  fetchFileShareBridges()
  fetchMessengerBridges()
})
</script>

<style scoped>
.tool-description-link { border: 0; padding: 0; background: none; color: var(--q-primary); cursor: pointer; font: inherit; text-align: left; text-decoration: underline; }
.tool-description-dialog { width: 700px; max-width: calc(100vw - 32px); max-height: 85vh; display: flex; flex-direction: column; }

.hidden { display: none; }

.tools-table :deep(.q-table__grid-content) {
  width: 100%;
  margin: 0;
}

.tools-table :deep(.q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
  padding: 8px 0;
}

.tool-mobile-card,
.tool-mobile-heading {
  min-width: 0;
}

.tool-mobile-capabilities {
  min-height: 24px;
}

.tool-mobile-capabilities :deep(.q-chip) {
  max-width: 100%;
}

.tool-mobile-capabilities :deep(.q-chip__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mcp-test-dialog {
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.mcp-test-dialog__body {
  min-height: 0;
  overflow-y: auto;
}

.tool-section {
  border: 1px solid #d8dde6;
  border-radius: 8px;
  padding: 16px;
  background: #ffffff;
}

.tool-section--active {
  border-width: 2px;
}

.tool-section__body {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

.connection-param-row {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 8px;
}

.connection-param-name,
.connection-param-type {
  flex: 0 0 calc(16.6667% - 8px);
  min-width: 0;
}

.connection-param-description {
  flex: 1 1 auto;
  min-width: 0;
}

.connection-param-required,
.connection-param-delete {
  flex: 0 0 auto;
  align-self: center;
}

.import-dropzone {
  border: 2px dashed #bdbdbd;
  border-radius: 8px;
  min-height: 160px;
  transition: border-color 0.2s, background 0.2s;
  user-select: none;
}

.import-dropzone:hover {
  border-color: #1976d2;
  background: #f5f9ff;
}

.import-dropzone--active {
  border-color: #4caf50;
  background: #f1faf1;
}

body.body--dark .tool-section {
  border-color: #3a3f47;
  background: #1d1d1d;
}

body.body--dark .connection-param-row {
  border-color: #3a3f47;
}

body.body--dark .import-dropzone {
  border-color: #555555;
}

body.body--dark .import-dropzone:hover {
  border-color: #1976d2;
  background: #1c2740;
}

body.body--dark .import-dropzone--active {
  border-color: #4caf50;
  background: #1e3320;
}

@media (max-width: 1023px) {
  .tools-actions > .q-btn {
    flex: 1 1 0;
    min-width: 0;
  }

  .tool-section {
    padding: 12px;
  }

  .tool-main-fields-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
    margin: 0;
  }

  .tool-main-fields-row > .tool-main-field {
    width: 100%;
    min-width: 0;
    margin: 0;
  }

  .tool-capability-toggles {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px 8px;
    margin: 8px 0 0;
  }

  .tool-capability-toggles > * {
    min-width: 0;
    margin: 0;
  }

  .connection-param-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(120px, 0.75fr);
    gap: 8px;
    padding: 10px;
    border: 1px solid #e1e5ec;
    border-radius: 6px;
  }

  .connection-param-name,
  .connection-param-type,
  .connection-param-description,
  .connection-param-required,
  .connection-param-delete {
    width: 100%;
    min-width: 0;
    margin: 0;
  }

  .connection-param-description {
    grid-column: 1 / -1;
  }

  .connection-param-required {
    justify-self: start;
  }

  .connection-param-delete {
    width: auto;
    justify-self: end;
  }

  .tool-section__body > .row {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
    margin: 0;
  }

  .tool-section__body > .row > * {
    width: 100%;
    min-width: 0 !important;
    max-width: none !important;
    margin: 0;
  }

  .tool-section__body > .q-field {
    width: 100%;
    max-width: none !important;
  }
}
</style>
