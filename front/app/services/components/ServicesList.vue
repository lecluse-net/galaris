<template>
  <div>
    <q-tabs v-model="origin" dense align="left" class="q-mb-md tool-tabs" no-caps>
      <q-tab v-for="group in SERVICE_ORIGINS" :key="group" :name="group"
        :label="$t(group === 'custom' ? 'services.customServices' : 'services.internalServices')" />
    </q-tabs>
    <div class="row items-center q-gutter-sm q-mb-md tools-actions">
      <q-input
        v-model="search"
        :label="$t('services.searchServices')"
        outlined dense clearable
        class="col tools-search"
      >
        <template #prepend><q-icon name="search" /></template>
      </q-input>
      <q-btn v-if="canEdit" outline color="secondary" icon="upload" :label="$t('services.import')" @click="importDialogOpen = true" />
      <q-btn v-if="canEdit" color="primary" icon="add" :label="$t('services.newService')" @click="catalogOpen = true" />
    </div>

    <q-banner v-if="serviceRequests.fetchServices?.error" class="q-mb-md" role="alert">
      {{ $t('services.listLoadError') }}
      <template #action><q-btn outline color="primary" :label="$t('common.retry')" @click="loadServices" /></template>
    </q-banner>
    <q-table
      :rows="visibleTools" :filter="search" :filter-method="filterTools"
      :no-results-label="$t('services.noSearchResults')" :columns="columns"
      grid hide-header row-key="id" :loading="serviceStore.loading"
      :rows-per-page-options="[10, 20, 50, 100, 500]" :pagination="{ rowsPerPage: 50 }"
      class="services-grid"
    >
      <template #item="props">
        <div class="service-grid-item">
          <ServiceCard :service="props.row" :label="localizedToolLabel(props.row)"
            :description="toolDescription(props.row)" :definitions="capabilityDefinitions"
            :can-edit="canEdit"
            @describe="openDescription(props.row)" @export="exportTool(props.row)"
            @parameters="openGlobalParams(props.row)" @edit="openEdit(props.row)"
            @delete="confirmDelete(props.row)" @conversation="openConversationTools(props.row)" />
        </div>
      </template>
    </q-table>
    <q-dialog v-model="catalogOpen">
      <q-card class="service-catalog-dialog galaris-dialog-card">
        <DialogHeader :title="$t('services.newService')" :close-label="$t('common.close')" />
        <q-card-section class="scroll galaris-dialog-body">
          <div class="row justify-end q-mb-md">
            <q-btn outline color="primary" icon="add" :label="$t('services.createCustomService')" @click="openCreate" />
          </div>
          <ServiceCatalog :installed="serviceStore.services" @select="openPreset" />
        </q-card-section>
      </q-card>
    </q-dialog>
    <q-dialog v-model="descriptionOpen">
      <q-card class="tool-description-dialog galaris-dialog-card">
        <DialogHeader :title="descriptionTool ? localizedToolLabel(descriptionTool) : ''" :close-label="$t('common.close')" />
        <q-card-section class="scroll galaris-dialog-body">
          <p v-if="descriptionTool?.can_disable === false"><SystemServiceIcon /> {{ $t('services.systemServiceHint') }}</p>
          <Markdown :content="descriptionTool ? toolDescription(descriptionTool) : ''" />
        </q-card-section>
      </q-card>
    </q-dialog>

    <ServiceImportDialog v-model="importDialogOpen" :can-edit="canEdit" @imported="onServiceImported" />

    <ServiceGlobalParameters v-model="globalParamsDialogOpen" :tool="globalParamsTool" @saved="loadServices" />
    <ServiceConversationTools v-model="conversationToolsOpen" :tool="conversationToolsService"
      :label="conversationToolsService ? localizedToolLabel(conversationToolsService) : ''" :can-edit="canEdit" />

    <!-- ============================================================
         Create or edit dialog
    ============================================================ -->
    <q-dialog v-model="dialogOpen">
      <q-card class="tool-editor-dialog galaris-dialog-card">
        <DialogHeader :title="editingTool ? $t('services.editService') : $t('services.newService')" :close-label="$t('common.close')" />

        <q-card-section class="galaris-dialog-body">
          <q-form @submit.prevent="saveTool()" class="q-gutter-y-md">

            <section class="tool-section">
              <div class="text-subtitle2 text-grey-7 q-mb-sm">{{ $t('services.mainFields') }}</div>
              <div class="tool-editor-columns">
                <div class="tool-main-fields-row">
                  <q-input v-model="form.code" :label="$t('services.technicalName')" :readonly="!!editingTool" :disable="!!editingTool"
                    :hint="$t(hasFileShare || hasMessenger || hasMail ? 'services.resourceTechnicalNameHint' : 'services.technicalNameHint')" hide-bottom-space dense outlined class="tool-main-field" :rules="[v => !!v || $t('services.required')]" />
                  <q-input v-model="form.label" :label="$t('services.label')" hide-bottom-space dense outlined class="tool-main-field" :rules="[v => !!v || $t('services.required')]" />
                </div>
                <ServiceIconEditor :key="iconEditorKey" v-model="serviceIcon" />
                <q-input v-model="form.description" :label="$t('services.descriptionMarkdown')" type="textarea" :input-style="{ minHeight: '96px' }" dense outlined autogrow />
              </div>
            </section>

            <div class="tool-editor-columns">
              <section class="tool-section">
                <div class="row items-center q-mb-sm">
                  <div class="text-subtitle2 text-grey-7">{{ $t('services.protocols') }}</div>
                  <q-space />
                  <q-btn outline color="primary" icon="add" :label="$t('services.addCapability')">
                    <q-menu v-model="protocolMenuOpen" max-height="70vh" class="tool-protocol-menu"
                      role="menu" :aria-label="$t('services.addCapability')">
                      <div v-if="capabilityCatalogLoading" class="row justify-center q-pa-md" role="status">
                        <q-spinner color="primary" :aria-label="$t('common.loading')" />
                      </div>
                      <q-banner v-else-if="capabilityCatalogError" dense role="alert">
                        {{ $t('services.capabilitiesLoadError') }}
                        <template #action><q-btn outline color="primary" :label="$t('common.retry')" @click="fetchCapabilities" /></template>
                      </q-banner>
                      <q-list v-else>
                        <template v-for="option in capabilityOptions" :key="option.value">
                          <q-item-label v-if="option.header" header class="tool-protocol-group">{{ option.label }}</q-item-label>
                          <q-item v-else clickable role="menuitem" :disable="option.disable" class="tool-protocol-option"
                            @click="addCapability(option.value)">
                            <q-item-section>{{ option.label }}</q-item-section>
                          </q-item>
                        </template>
                      </q-list>
                    </q-menu>
                  </q-btn>
                </div>
                <q-tabs v-if="selectedCapabilities.length" v-model="activeTab" dense align="left" class="tool-tabs" narrow-indicator>
                  <q-tab v-for="value in selectedCapabilities" :key="value" :name="capabilityTab(value)"
                    :label="capabilityLabels(value, capabilityDefinitions, t).protocol" />
                </q-tabs>
                <q-linear-progress v-if="selectedCapabilities.length && capabilityCatalogLoading" indeterminate color="primary" />
                <q-banner v-if="selectedCapabilities.length && capabilityCatalogError" dense role="alert">
                  {{ $t('services.capabilitiesLoadError') }}
                  <template #action><q-btn outline color="primary" :label="$t('common.retry')" @click="fetchCapabilities" /></template>
                </q-banner>
                <template v-if="selectedCapabilities.length">
                  <q-separator class="q-mb-md" />
                  <q-tab-panels v-model="activeTab" animated>
                    <q-tab-panel v-for="value in customCapabilities" :key="value" :name="capabilityTab(value)" class="q-pa-none">
                      <code>{{ value }}</code>
                    </q-tab-panel>
                    <q-tab-panel v-for="protocol in parameterProtocols" :key="protocol.value" :name="capabilityTab(protocol.value)" class="q-pa-none">
                      <div v-for="section in protocolSections(protocol)" :key="section.label" class="tool-section__body">
                        <div v-if="section.label" class="text-subtitle2">{{ te(section.label) ? t(section.label) : section.label }}</div>
                        <div class="tool-parameter-grid">
                          <ConnectionParamInput v-for="[name, definition] in sortedConnectionParamEntries(section.settings)" :key="name"
                            v-model="protocolSettings[protocol.capability][name]" :name="name" :definition="definition" :tool-code="form.code" />
                        </div>
                        <div v-if="Object.keys(section.bindings).length" class="text-caption text-grey-6">{{ $t('services.messengerParamMap') }}</div>
                        <div v-for="(binding, role) in section.bindings" :key="role" class="row q-gutter-md items-center"
                          role="group" :aria-label="localizedParamLabel({ ...binding.definition, name: role, label: binding.label }, form.code)">
                          <div class="col-3 text-body2">{{ localizedParamLabel({ ...binding.definition, name: role, label: binding.label }, form.code) }}<span v-if="binding.definition.required" class="text-negative"> *</span></div>
                          <ConnectionParamSelect v-model="protocolParamMaps[protocol.capability][role]" outlined dense class="col"
                            :label="$t('services.mapToParam')" :options="connectionBindingOptions(binding.definition)"
                            :create-parameter="() => createConnParam(binding.parameter, binding.definition.type,
                              localizedParamLabel({ ...binding.definition, name: binding.parameter }, form.code), binding.definition.required, binding.definition.widget, binding.definition)" />
                        </div>
                      </div>
                    </q-tab-panel>
                    <q-tab-panel name="api" class="q-pa-none">
                      <RestConfigEditor v-model="form.rest_config" :params="connParams" :create-param="createConnParam" class="tool-section__body" />
                    </q-tab-panel>
                    <!-- Rubrique MCP -->
                    <q-tab-panel name="mcp" class="q-pa-none">
                      <div class="tool-section__body">
                        <div class="row q-gutter-md">
                          <q-input v-if="form.mcp_config.type !== 'stdio'" v-model="form.mcp_config.url" label="URL *"
                            dense outlined class="col" placeholder="https://..." />
                          <q-input v-else v-model="form.mcp_config.command" :label="$t('services.command')" dense outlined class="col" placeholder="npx" />
                        </div>
                        <q-input v-if="form.mcp_config.type === 'stdio'" v-model="mcpArgsRaw" :label="$t('services.argsPerLine')"
                          type="textarea" dense outlined autogrow />
                        <q-input v-if="form.mcp_config.type === 'stdio'" v-model="mcpEnvRaw" :label="$t('services.envJson')"
                          type="textarea" dense outlined autogrow :hint="$t('services.writeOnlyMappingHint')"
                          :placeholder="$t('services.envPlaceholder')" />
                        <q-input v-model="form.mcp_config.timeout" :label="$t('services.timeoutSeconds')" type="number" dense outlined style="max-width: 160px" />

                        <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ $t('services.auth') }}</div>
                        <div class="row q-gutter-md items-start">
                          <q-select :model-value="form.mcp_config.auth.type" :options="authTypeOptions" :label="$t('services.authType')"
                            @update:model-value="selectMcpAuth"
                            :hint="form.mcp_config.auth.type === 'oauth' ? $t('services.authOAuthHint') : undefined"
                            emit-value map-options dense outlined class="col-auto" style="min-width: 140px" />
                          <template v-if="form.mcp_config.auth.type === 'bearer'">
                            <ConnectionParamSelect v-model="form.mcp_config.auth.param" :options="connParamNames" :label="$t('services.tokenParam')"
                              :create-parameter="() => createConnParam('token', 'password', $t('services.tokenParam'))"
                              dense outlined class="col" clearable use-input input-debounce="0"
                              :hint="$t('services.tokenParamHint')" />
                          </template>
                          <template v-if="form.mcp_config.auth.type === 'header'">
                            <q-input v-model="form.mcp_config.auth.header_name" :label="$t('services.headerName')" dense outlined class="col"
                              placeholder="X-Redmine-API-Key" />
                            <ConnectionParamSelect v-model="form.mcp_config.auth.param" :options="connParamNames" :label="$t('services.valueParam')"
                              :create-parameter="() => createConnParam('token', 'password', $t('services.valueParam'))"
                              dense outlined class="col" clearable use-input input-debounce="0" />
                          </template>
                          <template v-if="form.mcp_config.auth.type === 'basic'">
                            <ConnectionParamSelect v-model="form.mcp_config.auth.login_param" :options="connParamNames" :label="$t('services.loginParam')"
                              :create-parameter="() => createConnParam('login', 'string', $t('services.loginParam'))"
                              dense outlined class="col" clearable use-input input-debounce="0" />
                            <ConnectionParamSelect v-model="form.mcp_config.auth.password_param" :options="connParamNames" :label="$t('services.passwordParam')"
                              :create-parameter="() => createConnParam('password', 'password', $t('services.passwordParam'))"
                              dense outlined class="col" clearable use-input input-debounce="0" />
                          </template>
                        </div>
                        <q-banner
                          v-if="form.mcp_config.auth.type !== 'oauth' && form.mcp_config.auth.token_static_configured"
                          dense rounded class="bg-solaire-orange-light text-solaire-orange q-mt-sm"
                        >
                          <template #avatar><q-icon name="key" color="solaire-orange" /></template>
                          {{ $t('services.legacyStaticTokenConfigured') }}
                          <template #action>
                            <q-btn
                              v-if="canEdit"
                               color="negative" :label="$t('services.removeLegacySecret')"
                              @click="clearLegacyStaticToken"
                            />
                          </template>
                        </q-banner>
                        <q-input v-if="['bearer', 'header'].includes(form.mcp_config.auth.type) && form.mcp_config.type !== 'stdio'"
                          v-model="form.mcp_config.auth.url_param" :label="$t('services.urlParam')"
                          dense outlined style="max-width: 280px" :hint="$t('services.urlParamHint')" />
                        <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ $t('services.staticHeaders') }}</div>
                        <q-input v-model="mcpHeadersRaw" :label="$t('services.headersJson')" type="textarea" dense outlined autogrow
                          :placeholder="$t('services.headersPlaceholder')" :hint="$t('services.writeOnlyMappingHint')" />
                        <div class="row justify-end q-mt-md">
                          <q-btn
                            v-if="canEdit && form.mcp_config.auth.type !== 'oauth'"
                            outline
                            color="secondary"
                            icon="lan"
                            :label="$t('services.testMcpConnection')"
                            :disable="!form.code.trim()"
                            @click="mcpTestDialogOpen = true"
                          />
                        </div>
                      </div>
                    </q-tab-panel>

                    <!-- File-sharing section. -->
                    <q-tab-panel name="file_share" class="q-pa-none">
                      <div class="tool-section__body">
                        <div class="row q-gutter-md">
                          <q-input v-model="form.file_share_config.base_url" :label="$t('services.fileShareBaseUrlLabel')" dense outlined class="col"
                            :hint="$t('services.fileShareBaseUrlHint')"
                            :placeholder="$t(form.file_share_config.service === 'samba' ? 'services.fileShareSambaUrlPlaceholder' : 'services.fileShareUrlPlaceholder')" />
                        </div>

                        <template v-if="currentFileShareBridge">
                          <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ $t('services.fileShareParamMap') }}</div>
                          <div v-for="p in currentFileShareBridge.params" :key="p.key" class="row q-gutter-md items-center">
                            <div class="col-3 text-body2">
                              {{ p.label }}<span v-if="p.required" class="text-negative"> *</span>
                            </div>
                            <ConnectionParamSelect
                              v-model="form.file_share_config.param_map[p.key]"
                              :options="connParamNames" use-input input-debounce="0" clearable
                              :create-parameter="() => createConnParam(p.key, p.type, p.label, p.required)"
                              :label="$t('services.mapToParam')"
                              dense outlined class="col"
                            />
                          </div>
                          <q-banner dense class="bg-grey-2 text-grey-8 q-mt-sm" rounded>
                            <template v-slot:avatar><q-icon name="info" color="solaire-iris" /></template>
                            {{ $t('services.fileShareCredsHint') }}
                          </q-banner>
                        </template>
                      </div>
                    </q-tab-panel>

                    <!-- Messaging section, independent from File sharing. -->
                    <q-tab-panel name="messenger" class="q-pa-none">
                      <div class="tool-section__body">
                        <template v-if="currentMessengerBridge">
                          <NetworkAccessNotice :kind="currentMessengerBridge.service" />
                          <div v-if="currentMessengerBridge.settings.length" class="q-gutter-y-sm">
                            <div class="text-caption text-grey-6">{{ $t('services.messengerServerSettings') }}</div>
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

                          <div class="text-caption text-grey-6 q-mt-sm q-mb-xs">{{ $t('services.messengerParamMap') }}</div>
                          <div v-for="p in currentMessengerBridge.params" :key="p.key" class="row q-gutter-md items-center">
                            <div class="col-3 text-body2">
                              {{ p.label }}<span v-if="p.required" class="text-negative"> *</span>
                            </div>
                            <ConnectionParamSelect
                              v-model="form.messenger_config.param_map[p.key]"
                              :options="connParamNames"
                              :create-parameter="() => createConnParam(p.key, p.type, p.label, p.required)"
                              use-input input-debounce="0" clearable
                              :label="$t('services.mapToParam')"
                              dense outlined class="col"
                            />
                          </div>
                          <q-banner dense class="bg-grey-2 text-grey-8 q-mt-sm" rounded>
                            <template #avatar><q-icon name="info" color="solaire-iris" /></template>
                            {{ $t('services.messengerCredsHint') }}
                          </q-banner>
                        </template>
                      </div>
                    </q-tab-panel>

                    <!-- Rubrique Listener webhook -->
                    <q-tab-panel name="listener" class="q-pa-none">
                      <div class="tool-section__body">
                        <div class="row q-gutter-md">
                          <q-input v-model="form.listener_config.connection_key" label="connection_key *" dense outlined class="col" />
                          <q-input v-model="form.listener_config.url" :label="$t('services.urlOptional')" dense outlined class="col" />
                        </div>
                        <q-banner
                          v-if="form.listener_config.token_configured"
                          dense rounded class="bg-solaire-orange-light text-solaire-orange q-mt-sm"
                        >
                          <template #avatar><q-icon name="key" color="solaire-orange" /></template>
                          {{ $t('services.legacyListenerTokenConfigured') }}
                          <template #action>
                            <q-btn
                              v-if="canEdit"
                               color="negative" :label="$t('services.removeLegacySecret')"
                              @click="clearLegacyListenerToken"
                            />
                          </template>
                        </q-banner>
                        <q-separator class="q-my-sm" />
                        <div class="text-subtitle2 text-grey-7 q-mb-xs">{{ $t('services.taskTemplate') }}</div>
                        <q-input v-model="form.task_config.label" :label="$t('services.labelVariables')" dense outlined />
                        <q-input v-model="form.task_config.objective" :label="$t('services.objectiveVariables')" type="textarea" dense outlined autogrow />
                      </div>
                    </q-tab-panel>
                  </q-tab-panels>
                  <ServiceSkillGeneration v-if="canGenerateSkill && editingTool?.rest_config"
                    :key="editingTool.id" :service-id="editingTool.id" :visible="activeTab === 'api'" />
                  <q-btn v-if="canEdit && activeCapability" color="negative" icon="delete" class="q-mt-md"
                    :label="$t('services.deleteProtocol')" @click="requestProtocolRemoval(activeCapability)" />
                </template>
              </section>

              <section class="tool-section">
                <div class="row items-center q-mb-sm">
                  <div class="text-subtitle2 text-grey-7">{{ $t('services.connectionParams') }}</div>
                  <q-space />
                  <q-btn v-if="canEdit" outline icon="add" :label="$t('services.addParam')" color="primary" @click="addConnParam" />
                </div>
                <div v-for="(param, key) in connParams" :key="key" class="connection-param-editor"
                  role="group" :aria-label="$t('services.parameterEditor', { name: param.name || param.label })">
                  <div class="connection-param-row">
                    <q-input v-model="param.name" :label="$t('services.paramName')" dense outlined class="connection-param-name" />
                    <q-input v-model="param.label" :label="$t('services.paramLabel')" dense outlined class="connection-param-description" />
                    <q-select v-model="param.type" :options="paramTypeOptions" :label="$t('services.type')" emit-value map-options dense outlined class="connection-param-type" />
                    <q-toggle v-model="param.required" :label="$t('services.required')" dense class="connection-param-required" />
                    <q-input v-model="param.default" :label="$t('services.paramDefault')" :disable="param.type === 'password'" dense outlined class="connection-param-default" />
                  </div>
                  <div class="row items-start q-gutter-sm q-mt-xs">
                    <q-input v-model="param.description" :label="$t('services.descriptionMarkdown')" dense outlined class="col" />
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
                  <div v-if="param.type === 'string' || param.type === 'integer'" class="q-mt-sm">
                    <q-btn outline dense icon="add" color="primary" :label="$t('services.addParamOption')" @click="param.options.push({ value: '', label: '' })" />
                    <div v-if="param.options.length" class="text-caption q-mb-sm">{{ $t('services.paramOptionsHint') }}</div>
                    <div v-for="(option, index) in param.options" :key="index" class="row q-col-gutter-sm q-mb-sm items-start">
                      <q-input v-model="option.value" :label="$t('services.paramOptionValue')" dense outlined class="col" />
                      <q-input v-model="option.label" :label="$t('services.paramOptionLabel')" dense outlined class="col" />
                      <q-btn flat round dense icon="delete" color="negative" :aria-label="$t('services.removeParamOption')" @click="param.options.splice(index, 1)" />
                    </div>
                  </div>
                </div>
              </section>
            </div>

          </q-form>
        </q-card-section>

        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn v-if="editingTool?.can_edit" outline color="primary" icon="download" :label="$t('services.exportYaml')" @click="exportTool(editingTool)" />
          <q-btn color="primary" outline :label="$t('common.cancel')" v-close-popup />
          <q-btn v-if="canEdit" color="primary" :label="editingTool ? $t('common.save') : $t('common.create')" :loading="saving" :disable="missingCreationCapability" @click="saveTool()" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog data-confirmation v-model="mcpAuthChangeOpen">
      <q-card class="galaris-dialog-card" style="width: min(560px, 95vw); max-width: 95vw">
        <DialogHeader :title="$t('services.changeMcpAuthTitle')" :close-label="$t('common.close')" />
        <q-card-section class="galaris-dialog-body">{{ $t('services.changeMcpAuthWarning') }}</q-card-section>
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn color="primary" outline :label="$t('common.cancel')" v-close-popup />
          <q-btn data-autofocus color="negative" :label="$t('services.changeMcpAuthConfirm')" @click="confirmMcpAuthChange" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog data-confirmation v-model="protocolDeleteOpen" @hide="pendingProtocolDelete = ''">
      <q-card class="galaris-dialog-card" style="width: min(560px, 95vw); max-width: 95vw">
        <DialogHeader :title="$t('services.deleteProtocol')" :close-label="$t('common.close')" />
        <q-card-section class="galaris-dialog-body">
          {{ $t('services.deleteProtocolConfirm', { name: capabilityLabels(pendingProtocolDelete, capabilityDefinitions, t).protocol }) }}
        </q-card-section>
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn color="primary" outline :label="$t('common.cancel')" v-close-popup />
          <q-btn data-autofocus color="negative" :label="$t('common.delete')" @click="confirmProtocolRemoval" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog data-confirmation v-model="paramDeleteOpen" @hide="pendingParamDelete = null">
      <q-card class="galaris-dialog-card" style="width: min(560px, 95vw); max-width: 95vw">
        <DialogHeader :title="$t('services.deleteParamTitle')" :close-label="$t('common.close')" />
        <q-card-section class="galaris-dialog-body">
          <p>{{ $t('services.deleteUsedParam', { name: pendingParamDelete?.name || pendingParamDelete?.label || '' }) }}</p>
          <ul>
            <li v-for="usage in pendingParamUsages" :key="usage">{{ usage }}</li>
          </ul>
          <p class="q-mb-none">{{ $t('services.deleteUsedParamHint') }}</p>
        </q-card-section>
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn color="primary" outline :label="$t('common.cancel')" v-close-popup />
          <q-btn data-autofocus color="negative" :label="$t('common.delete')" @click="confirmRemoveConnParam" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <ServiceMcpDiagnosticDialog v-model="mcpTestDialogOpen" :can-edit="canEdit && dialogOpen"
      :code="form.code" :transport="form.mcp_config.type" :service-id="editingTool?.id" :parameters="connParams"
      :build-mcp-config="buildMcpConfig" :build-candidate-definition="buildCandidateDefinition" />

    <!-- Deletion dialog. -->
    <q-dialog data-confirmation v-model="deleteDialogOpen">
      <q-card class="galaris-dialog-card" style="width: min(600px, 95vw); max-width: 95vw">
        <DialogHeader :title="$t('services.deleteService')" :close-label="$t('common.close')" />
        <q-card-section class="galaris-dialog-body">
          <p>{{ $t('services.deleteMessage', { name: deletingTool ? localizedToolLabel(deletingTool) : '' }) }}</p>
          <div v-if="deleteImpactLoading" role="status" class="row items-center q-gutter-sm">
            <q-spinner color="primary" /> <span>{{ $t('services.deletion.loading') }}</span>
          </div>
          <template v-else-if="deleteImpact">
            <p class="text-weight-medium">{{ $t('services.deletion.includes') }}</p>
            <ul v-if="deleteImpact.deleted.length">
              <li v-for="item in deleteImpact.deleted" :key="item.kind">{{ $t(`services.deletion.kinds.${item.kind}`) }} : {{ item.count }}</li>
            </ul>
            <p v-else>{{ $t('services.deletion.noDependencies') }}</p>
            <p v-if="deleteImpact.detached_count">{{ $t('services.deletion.detached', { count: deleteImpact.detached_count }) }}</p>
            <p class="q-mb-none">{{ $t('services.deletion.remoteData') }}</p>
          </template>
          <q-banner v-if="deleteImpactError" rounded class="q-mt-md bg-negative text-white" role="alert">
            {{ deleteImpactError }}
            <template v-if="!deleteImpact" #action>
              <q-btn outline color="white" :label="$t('common.retry')" @click="loadDeleteImpact" />
            </template>
          </q-banner>
        </q-card-section>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn color="primary" outline :label="$t('common.cancel')" v-close-popup />
          <q-btn data-autofocus v-if="canEdit" color="negative" :label="$t('common.delete')" :loading="deleting" :disable="deleteImpactLoading || !deleteImpact" @click="doDelete" />
        </q-card-actions>
      </q-card>
    </q-dialog>

  </div>
</template>

<script setup lang="ts">
import { DialogHeader } from '@/core/util'
import { storeRequests } from '@/core/util/facade'
import { ref, computed, watch, onMounted, onActivated } from 'vue'
import ServiceCatalog from './ServiceCatalog.vue'
import ServiceCard from './ServiceCard.vue'
import ServiceConversationTools from './ServiceConversationTools.vue'
import ServiceIconEditor from './ServiceIconEditor.vue'
import type { ServiceCreate, ServiceIcon as Icon, ServiceCatalogMetadata } from '../services/serviceApi'
import { Markdown, NetworkAccessNotice } from '@/core/util'
import SystemServiceIcon from './SystemServiceIcon.vue'
import ConnectionParamInput from './ConnectionParamInput.vue'
import RestConfigEditor from './RestConfigEditor.vue'
import ConnectionParamSelect from './ConnectionParamSelect.vue'
import { useQuasar } from 'quasar'
import { useServiceStore } from '../stores/serviceStore'
import serviceApi from '../services/serviceApi'
import type {
  Service,
  McpAuth,
  McpConfig,
  RestConfig,
  FileShareConfig,
  FileShareBridge,
  MessengerConfig,
  MessengerBridge,
  ListenerConfig,
  ConnectionParamDef,
  ConnectionParamOption,
  TaskConfig,
} from '../services/serviceApi'
import api from '@/core/api'
import { isAxiosError } from 'axios'
import type { ServiceDeletionImpact } from '../services/serviceApi'
import { useI18n } from 'vue-i18n'
import { capabilityCode, capabilityLabels, toolCapabilitySelections } from '../capabilities'
import type { CapabilityDefinition, CapabilityProtocol } from '../services/serviceApi'
import { connectionParamLabel, SERVICE_ORIGINS, sortedConnectionParamEntries, toolMessageKey, toolOrigin, type ServiceOrigin } from '../presentation'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import ServiceGlobalParameters from './ServiceGlobalParameters.vue'
import ServiceImportDialog from './ServiceImportDialog.vue'
import ServiceMcpDiagnosticDialog from './ServiceMcpDiagnosticDialog.vue'
import ServiceSkillGeneration from './ServiceSkillGeneration.vue'

const $q = useQuasar()
const { t, te } = useI18n()
const serviceStore = useServiceStore()
const emit = defineEmits<{ deleted: [id: number] }>()
const serviceRequests = storeRequests(serviceStore)
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.SERVICE_EDIT))
const canGenerateSkill = computed(() => canEdit.value
  && privilegeStore.hasPrivilege(privileges.TASK_EDIT)
  && privilegeStore.hasPrivilege(privileges.SKILL_EDIT)
  && privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL))
const search = ref<string | null>('')
const origin = ref<ServiceOrigin>(SERVICE_ORIGINS[0])
const catalogOpen = ref(false)
const serviceIcon = ref<Icon | null>(null)
const catalogInfo = ref<ServiceCatalogMetadata | null>(null)
const iconEditorKey = ref(0)
const visibleTools = computed(() => serviceStore.services.filter(tool => toolOrigin(tool) === origin.value))
const conversationToolsOpen = ref(false)
const conversationToolsService = ref<Service | null>(null)

function openConversationTools(tool: Service): void {
  conversationToolsService.value = tool
  conversationToolsOpen.value = true
}
function localizedParamLabel(param: { name: string } & Partial<ConnectionParamDef>, toolCode?: string): string {
  return connectionParamLabel(toolCode, param.name, param, t, te)
}

const globalParamsDialogOpen = ref(false)
const globalParamsTool = ref<Service | null>(null)
function openGlobalParams(tool: Service): void {
  if (!canEdit.value || tool.can_disable === false) return
  globalParamsTool.value = tool
  globalParamsDialogOpen.value = true
}

const descriptionOpen = ref(false)
const descriptionTool = ref<Service | null>(null)
function toolDescription(tool: Service): string {
  if (!tool.description?.trim()) return ''
  const key = toolMessageKey(tool.code, 'description')
  return key && (!tool.can_edit || tool.description === t(key, {}, { locale: 'en' })) ? t(key) : tool.description
}
function openDescription(tool: Service): void {
  if (!toolDescription(tool)) return
  descriptionTool.value = tool
  descriptionOpen.value = true
}

function localizedToolLabel(tool: Service): string {
  const key = toolMessageKey(tool.code, 'label')
  return key && (!tool.can_edit || tool.label === t(key, {}, { locale: 'en' })) ? t(key) : tool.label
}

// =============================================================================
// Table
// =============================================================================

function filterTools(rows: readonly Service[], terms: string): Service[] {
  const normalize = (text: string) => text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim()
  const query = normalize(terms)
  return rows.filter(tool => [tool.code, localizedToolLabel(tool), toolDescription(tool)]
    .some(text => normalize(text).includes(query)))
}

const columns = computed(() => [
  { name: 'code',        label: t('agent.colName'),     field: 'code',     align: 'left'   as const, sortable: true },
  { name: 'label', label: t('services.labelColumn'), field: 'label', align: 'left' as const, sortable: true },
  { name: 'capabilities', label: t('services.capabilities'), field: 'capabilities', align: 'left' as const },
  { name: 'actions',     label: '',        field: 'actions',  align: 'right'  as const },
])

const authTypeOptions = computed(() => [
  { label: t('services.authNone'), value: 'none' },
  ...(form.value.mcp_config.type === 'stdio' ? [] : [{ label: t('services.authOAuth'), value: 'oauth' }]),
  { label: t('services.authBearer'), value: 'bearer' },
  { label: t('services.authHeader'), value: 'header' },
  { label: t('services.authBasic'), value: 'basic' },
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
const currentFileShareBridge = computed<FileShareBridge | null>(() =>
  fileShareBridges.value.find(b => b.service === form.value.file_share_config.service) ?? null
)
const messengerBridges = ref<MessengerBridge[]>([])
const currentMessengerBridge = computed<MessengerBridge | null>(() =>
  messengerBridges.value.find(
    bridge => bridge.service === form.value.messenger_config.service
  ) ?? null
)

// =============================================================================
// Export
// =============================================================================

async function exportTool(tool: Service) {
  try {
    const response = await api.get(`/services/${tool.id}/export`, { responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([response.data], { type: 'text/plain' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${tool.code}.yaml`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    $q.notify({ type: 'negative', message: t('services.exportError') })
  }
}

const importDialogOpen = ref(false)

async function onServiceImported(code: string, reveal: boolean): Promise<void> {
  await loadServices()
  if (!reveal || importDialogOpen.value) return
  const imported = serviceStore.services.find(tool => tool.code === code)
  origin.value = imported ? toolOrigin(imported) : 'custom'
  search.value = ''
}

// =============================================================================
// Create or edit form.
// =============================================================================

type ConnParamRow = ConnectionParamDef & { name: string; label: string; options: ConnectionParamOption[] }

const dialogOpen = ref(false)
const deleteDialogOpen = ref(false)
const saving = ref(false)
const editingTool = ref<Service | null>(null)
const deletingTool = ref<Service | null>(null)
const mcpTestDialogOpen = ref(false)
const mcpAuthChangeOpen = ref(false)

const hasMcp = ref(false)
const hasApi = ref(false)
const hasFileShare = ref(false)
const hasMessenger = ref(false)
const hasListener = ref(false)
const hasMail = ref(false)
const hasCalendar = ref(false)
const selectedCapabilities = ref<string[]>([])
const protocolMenuOpen = ref(false)
const capabilityDefinitions = ref<CapabilityDefinition[]>([])
const capabilityCatalogLoading = ref(false), capabilityCatalogError = ref(false)
const protocolSettings = ref<Record<string, Record<string, string | null>>>({})
const protocolParamMaps = ref<Record<string, Record<string, string>>>({})
function protocolSections(protocol: CapabilityProtocol) {
  const settings = protocol.parameters ?? {}, bindings = protocol.connection_parameters ?? {}
  const labels = new Set([...Object.values(settings), ...Object.values(bindings)].map(field => field.section ?? ''))
  return [...labels].map(label => ({ label,
    settings: Object.fromEntries(Object.entries(settings).filter(([, field]) => (field.section ?? '') === label)),
    bindings: Object.fromEntries(Object.entries(bindings).filter(([, field]) => (field.section ?? '') === label)),
  }))
}
const parameterProtocols = computed(() => selectedCapabilities.value.flatMap(value =>
  capabilityDefinitions.value.flatMap(definition => definition.protocols.filter(protocol => protocol.value === value
    && (Object.keys(protocol.parameters ?? {}).length || Object.keys(protocol.connection_parameters ?? {}).length)))))
watch(parameterProtocols, protocols => {
  for (const protocol of protocols) {
    const settings = protocolSettings.value[protocol.capability] ??= {}
    for (const [name, definition] of Object.entries(protocol.parameters ?? {})) {
      settings[name] ??= editingTool.value?.global_params?.[name]?.value ?? definition.default ?? ''
    }
    const bindings = protocolParamMaps.value[protocol.capability] ??= {}
    for (const role of Object.keys(bindings)) {
      if (!(role in (protocol.connection_parameters ?? {}))) delete bindings[role]
    }
    const existing = editingTool.value
    const config = protocol.capability === 'mail' ? existing?.mail_config : existing?.calendar_config
    const legacy = config && !Object.keys(config.settings ?? {}).length && !Object.keys(config.param_map ?? {}).length
    for (const [role, binding] of Object.entries(protocol.connection_parameters ?? {})) {
      const name = binding.legacy_parameter ?? binding.parameter
      const definition = legacy ? existing?.connection_schema.params?.[name] : undefined
      if (definition && !connParams.value.some(param => param.name === name)) {
        connParams.value.push({ ...definition, builtin: false, name, label: definition.label ?? '',
          options: definition.options ?? [], default: definition.default ?? '' })
      }
      if (!bindings[role]) bindings[role] = definition ? name : ''
    }
  }
})
function connectionBindingOptions(definition: ConnectionParamDef): string[] {
  return connParams.value.filter(param => param.type === definition.type && (param.widget || '') === (definition.widget || '')).map(param => param.name)
}
const missingCreationCapability = computed(() => !editingTool.value && !selectedCapabilities.value.length)
const activeTab = ref<string>('')
const mcpArgsRaw = ref('')
const mcpEnvRaw = ref('')

function firstEnabledTab(): string { return selectedCapabilities.value[0] ? capabilityTab(selectedCapabilities.value[0]) : '' }

function capabilityTab(value: string): string {
  const code = capabilityCode(value)
  const enabled: Record<string, boolean> = { mcp: hasMcp.value, api: hasApi.value, file_share: hasFileShare.value,
    messenger: hasMessenger.value, listener: hasListener.value, mail: hasMail.value, calendar: hasCalendar.value }
  return enabled[code] ? code : 'custom:' + value
}
const customCapabilities = computed(() => selectedCapabilities.value.filter(value => capabilityTab(value).startsWith('custom:')
  && !parameterProtocols.value.some(protocol => protocol.value === value)))
const activeCapability = computed(() => selectedCapabilities.value.find(value => capabilityTab(value) === activeTab.value))
const capabilityOptions = computed(() => capabilityDefinitions.value.flatMap(definition => [
  { label: definition.builtin ? t(definition.label) : definition.label, value: definition.code, header: true, disable: true },
  ...definition.protocols.map(protocol => ({ value: protocol.value, header: false,
    label: capabilityLabels(protocol.value, capabilityDefinitions.value, t).protocol,
    disable: selectedCapabilities.value.some(value => capabilityCode(value) === definition.code),
  })),
]))
function addCapability(value: string) {
  if (capabilityCatalogLoading.value || capabilityCatalogError.value
    || selectedCapabilities.value.some(item => capabilityCode(item) === capabilityCode(value))) return
  const code = capabilityCode(value), protocol = value.slice(0, -(code.length + 1))
  const recognized = capabilityDefinitions.value.some(definition => definition.protocols.some(item => item.value === value))
  if (!recognized) return
  if (recognized) {
    if (code === 'mcp' && ['http', 'sse', 'stdio'].includes(protocol)) {
      form.value.mcp_config.type = protocol as McpConfig['type']
      if (protocol === 'stdio' && form.value.mcp_config.auth.type === 'oauth') form.value.mcp_config.auth.type = 'none'
      hasMcp.value = true
    } else if (code === 'api') hasApi.value = true
    else if (code === 'file_share') { form.value.file_share_config.service = protocol; hasFileShare.value = true; onFileShareServiceChange() }
    else if (code === 'messenger') { form.value.messenger_config.service = protocol; hasMessenger.value = true; onMessengerServiceChange(true) }
    else if (code === 'listener') hasListener.value = true
    else if (code === 'mail') hasMail.value = true
    else if (code === 'calendar') hasCalendar.value = true
  }
  selectedCapabilities.value.push(value)
  activeTab.value = capabilityTab(value)
  protocolMenuOpen.value = false
}
const pendingProtocolDelete = ref('')
const protocolDeleteOpen = ref(false)
function requestProtocolRemoval(value: string) {
  pendingProtocolDelete.value = value
  protocolDeleteOpen.value = true
}
function confirmProtocolRemoval() {
  const value = pendingProtocolDelete.value
  if (canEdit.value && selectedCapabilities.value.includes(value)) removeCapability(value)
  protocolDeleteOpen.value = false
}
function removeCapability(value: string) {
  const code = capabilityCode(value)
  selectedCapabilities.value = selectedCapabilities.value.filter(item => item !== value)
  if (code === 'mcp') hasMcp.value = false
  else if (code === 'api') hasApi.value = false
  else if (code === 'file_share') hasFileShare.value = false
  else if (code === 'messenger') hasMessenger.value = false
  else if (code === 'listener') hasListener.value = false
  else if (code === 'mail') hasMail.value = false
  else if (code === 'calendar') hasCalendar.value = false
  if (!selectedCapabilities.value.some(item => capabilityTab(item) === activeTab.value)) activeTab.value = firstEnabledTab()
}
async function fetchCapabilities() {
  capabilityCatalogLoading.value = true; capabilityCatalogError.value = false
  try { capabilityDefinitions.value = (await serviceApi.getCapabilities()).data }
  catch { capabilityCatalogError.value = true }
  finally { capabilityCatalogLoading.value = false }
}

const mcpHeadersRaw = ref('')
const connParams = ref<ConnParamRow[]>([])
const pendingParamDelete = ref<ConnParamRow | null>(null)
const paramDeleteOpen = ref(false)
const pendingParamUsages = computed(() =>
  pendingParamDelete.value ? connParamUsages(pendingParamDelete.value.name) : []
)
watch(dialogOpen, open => {
  if (!open) {
    mcpAuthChangeOpen.value = false
    protocolMenuOpen.value = false
    protocolDeleteOpen.value = false
    pendingProtocolDelete.value = ''
    paramDeleteOpen.value = false
    pendingParamDelete.value = null
  }
})

// Connection parameter names used by authentication selects.
const connParamNames = computed(() =>
  connParams.value.map(param => param.name).filter(name => name.trim() !== '')
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
  delete cloned.auth?.token_static
  return {
    ...defaults,
    ...cloned,
    auth: {
      ...defaults.auth,
      ...(cloned.auth ?? {}),
    },
  }
}

function selectMcpAuth(type: McpAuth['type']) {
  if (type === form.value.mcp_config.auth.type) return
  const saved = editingTool.value?.mcp_config
  form.value.mcp_config.auth = saved && (saved.auth?.type ?? 'none') === type
    ? mcpConfigForForm(saved).auth
    : { ...emptyMcpConfig().auth, type }
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
const emptyRestConfig = (): RestConfig => ({
  base_url: '',
  auth: { type: 'none', param: '', header_name: 'X-API-Key', query_name: 'api_key', login_param: '', password_param: '' },
  header_params: {}, timeout: 60, max_response_bytes: 2097152,
})
const emptyTaskConfig = (): TaskConfig => ({ label: '', objective: '' })

interface FormData {
  code: string; label: string; description: string
  mcp_config: McpFormConfig
  rest_config: RestConfig
  file_share_config: FileShareConfig
  messenger_config: MessengerConfig
  listener_config: ListenerConfig
  task_config: TaskConfig
}

const form = ref<FormData>({
  code: '', label: '', description: '',
  mcp_config: emptyMcpConfig(),
  rest_config: emptyRestConfig(),
  file_share_config: emptyFileShareConfig(),
  messenger_config: emptyMessengerConfig(),
  listener_config: emptyListenerConfig(),
  task_config: emptyTaskConfig(),
})

function resetForm() {
  serviceIcon.value = null; catalogInfo.value = null; iconEditorKey.value++
  paramDeleteOpen.value = false
  pendingParamDelete.value = null
  form.value = {
    code: '',
    label: '',
    description: '',
    mcp_config: emptyMcpConfig(),
    rest_config: emptyRestConfig(),
    file_share_config: emptyFileShareConfig(),
    messenger_config: emptyMessengerConfig(),
    listener_config: emptyListenerConfig(),
    task_config: emptyTaskConfig(),
  }
  hasMcp.value = false
  hasApi.value = false
  hasFileShare.value = false
  hasMessenger.value = false
  hasListener.value = false
  hasMail.value = false
  hasCalendar.value = false
  selectedCapabilities.value = []
  protocolSettings.value = {}
  protocolParamMaps.value = {}
  activeTab.value = ''
  mcpArgsRaw.value = ''; mcpEnvRaw.value = ''; mcpHeadersRaw.value = ''; connParams.value = []
  mcpTestDialogOpen.value = false
}

function openCreate() { if (!canEdit.value) return; catalogOpen.value = false; editingTool.value = null; resetForm(); dialogOpen.value = true }

function openEdit(tool: Service) {
  if (!canEdit.value || tool.can_disable === false) return
  editingTool.value = tool
  openDefinition(tool)
}

function openPreset(definition: ServiceCreate) {
  if (!canEdit.value) return
  catalogOpen.value = false
  editingTool.value = null
  openDefinition(definition)
}

function openDefinition(tool: ServiceCreate) {
  resetForm()
  serviceIcon.value = tool.icon ? JSON.parse(JSON.stringify(tool.icon)) : null
  catalogInfo.value = tool.catalog ? JSON.parse(JSON.stringify(tool.catalog)) : null
  protocolSettings.value = { mail: { ...tool.mail_config?.settings }, calendar: { ...tool.calendar_config?.settings } }
  protocolParamMaps.value = { mail: { ...tool.mail_config?.param_map }, calendar: { ...tool.calendar_config?.param_map } }
  form.value.code = tool.code
  form.value.label = tool.label
  form.value.description = tool.description ?? ''
  hasMail.value = !!tool.mail_config
  hasCalendar.value = !!tool.calendar_config
  hasApi.value = !!tool.rest_config
  form.value.rest_config = tool.rest_config ? JSON.parse(JSON.stringify(tool.rest_config)) : emptyRestConfig()

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

  connParams.value = sortedConnectionParamEntries(tool.connection_schema?.params ?? {}).filter(([, def]) => !def.builtin).map(([name, def]) => ({
    ...def, name, label: def.label ?? '', options: (def.options ?? []).map(option => ({ ...option })), default: def.default ?? '',
  }))
  selectedCapabilities.value = toolCapabilitySelections(tool)
  activeTab.value = firstEnabledTab()
  dialogOpen.value = true
}

function addConnParam() { connParams.value.push({ name: '', label: '', options: [], type: 'string', required: true, description: '', default: '' }) }
function createConnParam(baseName: string, type: string, label: string, required = true, widget = '', definition?: Partial<ConnectionParamDef>): string {
  const stem = baseName.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '') || 'param'
  const names = new Set(connParams.value.map(param => param.name.trim()))
  let name = stem
  for (let suffix = 2; names.has(name); suffix++) name = `${stem}_${suffix}`
  connParams.value.push({ name, label,
    options: (definition?.options ?? []).map(option => {
      const key = option.label ?? ''
      return { ...option, label: te(key) ? t(key) : option.label ?? option.value }
    }),
    type, required, widget, description: definition?.description && te(definition.description) ? t(definition.description) : '', default: definition?.default ?? '' })
  return name
}
function connParamUsages(rawName: string): string[] {
  const name = rawName.trim()
  if (!name) return []
  const matches = (value: string | null | undefined) => value?.trim() === name
  const reference = '${connection:' + name + '}'
  const usages: string[] = []
  const mcp = form.value.mcp_config
  const mcpAuth = mcp.auth
  const mcpAuthUsed = mcpAuth.type === 'basic'
    ? matches(mcpAuth.login_param) || matches(mcpAuth.password_param)
    : ['bearer', 'header'].includes(mcpAuth.type) && matches(mcpAuth.param)
  if (hasMcp.value && (mcpAuthUsed || [mcp.url || '', mcpArgsRaw.value, mcpHeadersRaw.value, mcpEnvRaw.value].some(value => value.includes(reference)))) {
    usages.push(t('services.mcpCapability'))
  }
  const rest = form.value.rest_config
  const restAuthUsed = rest.auth.type === 'basic'
    ? matches(rest.auth.login_param) || matches(rest.auth.password_param)
    : rest.auth.type !== 'none' && matches(rest.auth.param)
  if (hasApi.value && (restAuthUsed || Object.values(rest.header_params).some(matches) || rest.base_url.includes(reference))) {
    usages.push(t('services.restApi'))
  }
  if (hasFileShare.value && Object.values(form.value.file_share_config.param_map).some(matches)) usages.push(t('services.fileShare'))
  if (hasMessenger.value && Object.values(form.value.messenger_config.param_map).some(matches)) usages.push(t('services.messenger'))
  for (const protocol of parameterProtocols.value) {
    if (Object.values(protocolParamMaps.value[protocol.capability] ?? {}).some(matches)) usages.push(capabilityLabels(protocol.value, capabilityDefinitions.value, t).protocol)
  }
  if (hasListener.value && matches(form.value.listener_config.connection_key)) usages.push(t('services.listener'))
  if (editingTool.value?.global_params?.[name]?.configured) usages.push(t('services.globalParams'))
  return usages
}

function removeConnParam(index: number) {
  if (!canEdit.value) return
  const param = connParams.value[index]
  if (!param) return
  if (connParamUsages(param.name).length) {
    pendingParamDelete.value = param
    paramDeleteOpen.value = true
  } else {
    connParams.value.splice(index, 1)
  }
}

function confirmRemoveConnParam() {
  const param = pendingParamDelete.value
  if (canEdit.value && dialogOpen.value && param) {
    const index = connParams.value.indexOf(param)
    if (index >= 0) connParams.value.splice(index, 1)
  }
  paramDeleteOpen.value = false
  pendingParamDelete.value = null
}

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
    throw new Error(t('services.invalidJsonMap', { field }))
  }
  if (
    !parsed
    || typeof parsed !== 'object'
    || Array.isArray(parsed)
    || Object.values(parsed).some(value => typeof value !== 'string')
  ) {
    throw new Error(t('services.invalidJsonMap', { field }))
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
    env: parseStringMap(mcpEnvRaw.value, t('services.envJson')),
    headers: parseStringMap(mcpHeadersRaw.value, t('services.headersJson')),
  }
}

function buildPayload() {
  const rest_config = hasApi.value ? { ...form.value.rest_config, auth: { ...form.value.rest_config.auth }, header_params: { ...form.value.rest_config.header_params } } : null
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
    if (p.name.trim() && ['string', 'integer'].includes(p.type) && p.options.length) {
      const values = p.options.map(option => option.value)
      if (values.some(value => !value.trim() || (p.type === 'integer' && !/^[+-]?\d+$/.test(value)))
        || new Set(values).size !== values.length || (p.default && !values.includes(p.default))) {
        throw new Error(t('services.invalidParamOptions', { name: p.label || p.name }))
      }
    }
    if (p.name.trim()) params[p.name.trim()] = {
      type: p.type, required: p.required, description: p.description,
      default: p.type === 'password' ? '' : p.default, order, label: p.label.trim(),
      options: ['string', 'integer'].includes(p.type) ? p.options : [],
      widget: p.widget,
    }
  }
  return {
    capabilities: [...selectedCapabilities.value],
    mcp_config,
    mail_config: hasMail.value ? { settings: Object.fromEntries(Object.entries(protocolSettings.value.mail ?? {}).map(([name, value]) => [name, value ?? ''])), param_map: protocolParamMaps.value.mail ?? {} } : null,
    calendar_config: hasCalendar.value ? { settings: Object.fromEntries(Object.entries(protocolSettings.value.calendar ?? {}).map(([name, value]) => [name, value ?? ''])), param_map: protocolParamMaps.value.calendar ?? {} } : null,
    rest_config,
    file_share_config,
    messenger_config,
    listener_config,
    task_config,
    connection_schema: { params },
  }
}

function buildCandidateDefinition(): ServiceCreate {
  return {
    code: form.value.code.trim(),
    label: form.value.label.trim(),
    description: form.value.description,
    ...buildPayload(),
  }
}

function confirmMcpAuthChange() {
  mcpAuthChangeOpen.value = false
  void saveTool(true)
}

async function saveTool(confirmedMcpAuth = false) {
  if (!canEdit.value) return
  if (missingCreationCapability.value) {
    $q.notify({ type: 'warning', message: t('services.capabilityRequired') }); return
  }
  if (!form.value.code.trim() || !form.value.label.trim()) {
    $q.notify({ type: 'warning', message: t('services.saveRequired') }); return
  }
  try {
    const payload = buildPayload()
    const savedMcp = editingTool.value?.mcp_config
    const previousAuth = savedMcp?.auth?.type ?? 'none'
    const newAuth = payload.mcp_config?.auth?.type ?? 'none'
    const changingMcpAuth = !!savedMcp && previousAuth !== newAuth
    if (changingMcpAuth && !confirmedMcpAuth) {
      mcpAuthChangeOpen.value = true
      return
    }
    saving.value = true
    if (editingTool.value) {
      await serviceStore.updateService(editingTool.value.id, { label: form.value.label, description: form.value.description, icon: serviceIcon.value, catalog: catalogInfo.value, ...payload,
        expected_mcp_auth_type: changingMcpAuth ? previousAuth : undefined })
      $q.notify({ type: 'positive', message: t('services.updated') })
    } else {
      await serviceStore.createService({ code: form.value.code, label: form.value.label, description: form.value.description, icon: serviceIcon.value, catalog: catalogInfo.value, ...payload })
      origin.value = 'custom'
      search.value = ''
      $q.notify({ type: 'positive', message: t('services.created') })
    }
    dialogOpen.value = false
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    const localMessage = e instanceof Error ? e.message : ''
    $q.notify({
      type: 'negative',
      message: err?.response?.data?.detail ?? (localMessage || t('services.saveError')),
    })
  } finally {
    saving.value = false
  }
}

const deleteImpact = ref<ServiceDeletionImpact | null>(null)
const deleteImpactLoading = ref(false)
const deleteImpactError = ref('')
const deleting = ref(false)
let deleteImpactRequest = 0

function confirmDelete(tool: Service) {
  if (!canEdit.value || !tool.can_edit || tool.can_disable === false) return
  deletingTool.value = tool
  deleteDialogOpen.value = true
  void loadDeleteImpact()
}

watch(deleteDialogOpen, open => {
  if (!open) {
    deleteImpactRequest++
    deleteImpact.value = null
  }
})

async function loadDeleteImpact() {
  const target = deletingTool.value
  if (!target || !deleteDialogOpen.value) return
  const request = ++deleteImpactRequest
  deleteImpact.value = null
  deleteImpactLoading.value = true
  deleteImpactError.value = ''
  try {
    const { data } = await serviceApi.getDeletionImpact(target.id)
    if (request === deleteImpactRequest) deleteImpact.value = data
  } catch {
    if (request === deleteImpactRequest) deleteImpactError.value = t('services.deletion.loadError')
  } finally {
    if (request === deleteImpactRequest) deleteImpactLoading.value = false
  }
}

async function doDelete() {
  if (!canEdit.value) return
  const target = deletingTool.value
  const impact = deleteImpact.value
  if (!target || !impact || deleteImpactLoading.value || deleting.value) return
  deleting.value = true
  try {
    await serviceStore.deleteService(target.id, impact.version)
    emit('deleted', target.id)
    $q.notify({ type: 'positive', message: t('services.deleted') })
    if (deletingTool.value?.id === target.id) deleteDialogOpen.value = false
  } catch (error) {
    if (!deleteDialogOpen.value || deletingTool.value?.id !== target.id) return
    if (isAxiosError(error) && error.response?.status === 409) {
      await loadDeleteImpact()
      if (deleteDialogOpen.value && deletingTool.value?.id === target.id) deleteImpactError.value = t('services.deletion.changed')
    } else {
      deleteImpactError.value = t('services.deleteError')
    }
  } finally {
    deleting.value = false
  }
}

async function fetchFileShareBridges() {
  try {
    const { data } = await serviceApi.getFileShareBridges()
    fileShareBridges.value = data
  } catch {
    fileShareBridges.value = []
  }
}

async function fetchMessengerBridges() {
  try {
    const { data } = await serviceApi.getMessengerBridges()
    messengerBridges.value = data
  } catch {
    messengerBridges.value = []
  }
}

async function loadServices(): Promise<void> {
  try { await serviceStore.fetchServices() } catch { /* The store exposes the error for retry. */ }
}

onActivated(() => {
  if (!serviceStore.loading) void loadServices()
})

onMounted(() => {
  void loadServices()
  void fetchFileShareBridges()
  void fetchMessengerBridges()
  void fetchCapabilities()
})
</script>

<style scoped>
.tool-protocol-menu { min-width: 260px; max-width: calc(100vw - 24px); }
.tool-protocol-group {
  margin-top: 8px;
  padding: 8px 12px;
  border-left: 3px solid var(--solaire-blue-accent);
  background: var(--solaire-blue-light);
  color: inherit;
  font-weight: 700;
}

.tool-protocol-group:first-child { margin-top: 0; }
.body--dark .tool-protocol-group { background: var(--solaire-blue-dark); }
.tool-protocol-option { padding-left: 28px; }

.tool-tabs {
  color: var(--solaire-blue-accent);
}

.tool-tabs :deep(.q-tab__indicator) {
  background-color: var(--solaire-blue-accent);
}

.tool-description-link { border: 0; padding: 0; background: none; color: var(--q-primary); cursor: pointer; font: inherit; text-align: left; text-decoration: underline; }
.tool-description-dialog { width: 700px; max-width: calc(100vw - 32px); max-height: 85vh; display: flex; flex-direction: column; }

.hidden { display: none; }

.services-grid :deep(.q-table__grid-content) {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 510px), 1fr));
  gap: 16px;
  width: 100%;
  margin: 0;
}
.service-grid-item { min-width: 0; }
.service-catalog-dialog {
  width: min(1200px, 96vw);
  max-width: 96vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}
.service-catalog-dialog .galaris-dialog-body { min-height: 0; }

.tool-editor-dialog {
  width: min(1480px, 96vw);
  max-width: 96vw;
  max-height: 95vh;
}

.tool-editor-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  align-items: start;
}

.tool-editor-columns > * {
  min-width: 0;
}

.tool-main-fields-row {
  display: grid;
  gap: 16px;
}

.tool-capability-toggles {
  row-gap: 8px;
}

.tool-section,
.connection-param-editor {
  border: 1px solid rgba(0, 0, 0, .24);
  border-radius: 4px;
}

.tool-section {
  padding: 16px;
  background: #ffffff;
}

.tool-section__body {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

.tool-parameter-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
@media (max-width: 1023px) { .tool-parameter-grid { grid-template-columns: minmax(0, 1fr); } }

.connection-param-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: start;
  gap: 12px;
  margin-bottom: 8px;
}

.connection-param-editor {
  padding: 16px;
  margin-bottom: 12px;
}

.connection-param-name,
.connection-param-description {
  grid-column: span 3;
  min-width: 0;
}

.connection-param-type,
.connection-param-default {
  min-width: 0;
}

.connection-param-required,
.connection-param-delete {
  flex: 0 0 auto;
  align-self: center;
}

body.body--dark .tool-section {
  background: #1d1d1d;
}

body.body--dark .tool-section,
body.body--dark .connection-param-editor {
  border-color: rgba(255, 255, 255, .6);
}

@media (max-width: 1023px) {
  .tools-search {
    flex: 1 1 100%;
  }

  .tools-actions > .q-btn {
    flex: 1 1 0;
    min-width: 0;
  }

  .tool-section {
    padding: 12px;
  }

  .tool-editor-columns {
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }

  .tool-main-fields-row {
    gap: 12px;
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
    margin: 0 0 16px;
  }

  .tool-capability-toggles > * {
    min-width: 0;
    margin: 0;
  }

  .connection-param-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(120px, 0.75fr);
    gap: 8px;
  }

  .connection-param-name,
  .connection-param-type,
  .connection-param-description,
  .connection-param-default,
  .connection-param-required,
  .connection-param-delete {
    width: 100%;
    min-width: 0;
    margin: 0;
  }

  .connection-param-name,
  .connection-param-description,
  .connection-param-default {
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
