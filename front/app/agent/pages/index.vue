<template>
  <q-page class="agent-page q-pa-md">
    <PageHeader help-key="agents" :help-text="$t('contextHelpPages.agents')" :icon="navigationIcon('people')" :title="$t('nav.agent')" :description="$t('nav.agent_desc')" />

    <q-tabs v-model="activeTab" class="text-primary" active-color="primary" indicator-color="primary" align="left">
      <q-tab v-if="canViewAgents" name="agents" :label="$t('agent.tabAgents')" icon="people" />
      <q-tab v-if="canViewTeams" name="groups" :label="$t('team.title')" icon="groups" />
      <q-tab v-if="canViewAgents" name="titles" :label="$t('agent.tabTitles')" icon="badge" />
    </q-tabs>

    <q-separator />

    <q-tab-panels v-model="activeTab" animated>
      <!-- AGENTS TAB -->
      <q-tab-panel v-if="canViewAgents" name="agents">
        <q-banner
          v-if="harnessManagerUnavailable"
          class="bg-negative text-white q-mb-md"
          rounded
          role="alert"
        >
          <template #avatar>
            <q-icon name="error" color="white" />
          </template>
          {{ $t('agent.harness.managerUnavailable') }}
        </q-banner>

        <!-- One nested tab per group. -->
        <template v-if="groupTabs.length > 1">
          <q-tabs
            v-model="activeGroupTab"
            class="text-primary q-mb-sm"
            active-color="primary"
            indicator-color="primary"
            align="left"
            dense
            inline-label
          >
            <q-tab
              v-for="tab in groupTabs"
              :key="tab.name"
              :name="tab.name"
              :label="tab.label"
              :icon="tab.name === 'none' ? 'person_off' : 'groups'"
            />
          </q-tabs>
          <q-separator class="q-mb-md" />
        </template>

        <div class="agent-page-actions row justify-end q-mb-md q-gutter-sm">
          <q-btn
            v-if="canEdit && managedAgents.length"
            color="deep-purple"
            icon="restart_alt"
            :label="$t('agent.harness.restartAll')"
            :loading="fleetRestarting"
            @click="restartFleet"
          />
          <q-btn v-if="canEdit" color="primary" icon="add" :label="$t('agent.newAgent')" @click="openAgentDialog()" />
        </div>

        <!-- Agent Cards Grid -->
        <div v-if="displayedAgents.length > 0" class="agent-cards-grid">
          <div
            v-for="agent in displayedAgents"
            :key="agent.id"
            class="agent-card-wrapper"
          >
            <q-card class="agent-card" flat bordered>
              <q-card-section horizontal class="agent-card-horizontal">
                <!-- Avatar Section (Left) -->
                <q-card-section class="bg-grey-2 agent-avatar-section">
                  <div v-if="agent.has_avatar && avatarUrls[agent.id]" class="agent-image-container">
                    <img
                      :src="avatarUrls[agent.id]"
                      :alt="`${agent.first_name} ${agent.last_name}`"
                      class="agent-image"
                    />
                  </div>
                  <div v-else class="flex flex-center full-height">
                    <q-avatar size="112px" class="agent-fallback-avatar">
                      {{ agentInitials(agent) }}
                    </q-avatar>
                  </div>
                </q-card-section>

                <!-- Info Section (Right) -->
                <q-card-section class="agent-info-section q-pa-sm">
                  <div class="agent-identity-section">
                    <!-- Model profile -->
                    <div
                      class="profile-name text-caption text-grey-7 text-right ellipsis q-mb-xs"
                      :title="getAgentProfileLabel(agent)"
                    >
                      {{ getAgentProfileLabel(agent) }}
                    </div>

                    <!-- Name & Title -->
                    <div class="agent-name text-h6 text-weight-bold">
                      {{ agent.first_name }} {{ agent.last_name }}
                    </div>
                    <div class="agent-meta-row row items-baseline no-wrap">
                      <div
                        class="agent-job-title col ellipsis"
                        :class="agent.job_title
                          ? 'text-body1 text-weight-medium text-dark'
                          : 'text-body2 text-grey-6'"
                      >
                        {{ agent.job_title || $t('agent.noJobTitle') }}
                      </div>
                      <div
                        class="agent-manager text-caption text-grey-7 ellipsis"
                        :title="agent.user.display_name || agent.user.email"
                      >
                        {{ $t('agent.managerLabelShort') }} · {{ agent.user.display_name || agent.user.email }}
                      </div>
                    </div>

                    <q-separator class="q-mt-xs" />
                  </div>

                  <!-- Personality Summary -->
                  <div
                    class="agent-summary clickable-text-zone"
                    @click="openRichTextDialog(agent, 'personality')"
                  >
                    <div class="text-caption text-weight-medium text-primary q-mb-xs">
                      <q-icon name="psychology" size="xs" class="q-mr-xs" />
                      {{ $t('agent.personality') }}
                    </div>
                    <div
                      v-if="agent.personality"
                      class="text-body2 text-grey-8 ellipsis-2-lines"
                      style="min-height: 2.5em;"
                    >
                      {{ truncateText(richTextExcerpt(agent.personality ?? ''), 140) }}
                    </div>
                    <div v-else class="text-body2 text-grey-5" style="min-height: 2.5em;">
                      {{ $t('agent.notDefinedF') }}
                    </div>
                  </div>

                  <!-- Job Description Summary -->
                  <div
                    class="agent-summary clickable-text-zone"
                    @click="openRichTextDialog(agent, 'job_description')"
                  >
                    <div class="text-caption text-weight-medium text-primary q-mb-xs">
                      <q-icon name="work" size="xs" class="q-mr-xs" />
                      {{ $t('agent.jobDescription') }}
                    </div>
                    <div
                      v-if="agent.job_description"
                      class="text-body2 text-grey-8 ellipsis-2-lines"
                      style="min-height: 2.5em;"
                    >
                      {{ truncateText(richTextExcerpt(agent.job_description ?? ''), 140) }}
                    </div>
                    <div v-else class="text-body2 text-grey-5" style="min-height: 2.5em;">
                      {{ $t('agent.notDefinedF') }}
                    </div>
                  </div>
                </q-card-section>
              </q-card-section>

              <q-separator />

              <!-- Actions Section (Bottom) -->
              <q-card-actions class="agent-card-actions q-pa-sm">
                <q-chip
                  v-if="isManagedRuntime(agent)"
                  dense
                  square
                  :clickable="hasHarnessCapability(agent, 'logs')"
                  :color="harnessStatusColor(harnessState(agent).status)"
                  text-color="white"
                  :icon="harnessState(agent).status === 'loading' ? '' : harnessStatusIcon(harnessState(agent).status)"
                  size="sm"
                  @click="hasHarnessCapability(agent, 'logs') && openHarnessLogs(agent)"
                >
                  <q-spinner v-if="harnessState(agent).status === 'loading'" size="xs" class="q-mr-xs" />
                  {{ harnessStatusLabel(harnessState(agent).status) }}
                  <q-tooltip v-if="harnessState(agent).last_error || hasHarnessCapability(agent, 'logs')">
                    {{ harnessState(agent).last_error || $t('agent.harness.showLogs') }}
                  </q-tooltip>
                </q-chip>
                <div class="agent-action-buttons row items-center justify-end">
                  <template v-if="isManagedRuntime(agent) && canManageAgent(agent)">
                    <q-btn
                      v-if="hasHarnessAction(agent, 'start')"
                      class="agent-action-button"
                      flat color="warning" icon="play_arrow" :label="$t('agent.harness.start')" :aria-label="$t('agent.harness.start')" size="sm"
                      :loading="Boolean(harnessActionLoading[agent.id])"
                      :disable="harnessLifecycleBusy(agent)"
                      @click="runHarnessAction(agent, 'start')"
                    >
                      <q-tooltip>{{ $t('agent.harness.start') }}</q-tooltip>
                    </q-btn>
                    <q-btn
                      v-if="hasHarnessAction(agent, 'stop')"
                      class="agent-action-button"
                      flat color="warning" icon="stop" :label="$t('agent.harness.stop')" :aria-label="$t('agent.harness.stop')" size="sm"
                      :loading="Boolean(harnessActionLoading[agent.id])"
                      :disable="harnessLifecycleBusy(agent)"
                      @click="runHarnessAction(agent, 'stop')"
                    >
                      <q-tooltip>{{ $t('agent.harness.stop') }}</q-tooltip>
                    </q-btn>
                    <q-btn
                      v-if="hasHarnessAction(agent, 'restart')"
                      class="agent-action-button"
                      flat color="deep-purple" icon="restart_alt" :label="harnessRestartLabel(agent)" :aria-label="harnessRestartLabel(agent)" size="sm"
                      :loading="harnessActionLoading[agent.id] === 'restart'"
                      :disable="harnessLifecycleBusy(agent)"
                      @click="runHarnessAction(agent, 'restart')"
                    >
                      <q-tooltip>{{ harnessRestartLabel(agent) }}</q-tooltip>
                    </q-btn>
                  </template>
                  <q-btn
                    v-if="canManageAgent(agent)"
                    class="agent-action-button"
                    flat color="secondary" icon="edit" :label="$t('common.edit')" :aria-label="$t('agent.editTooltip')" size="sm"
                    @click="openAgentDialog(agent)"
                  >
                    <q-tooltip>{{ $t('agent.editTooltip') }}</q-tooltip>
                  </q-btn>
                  <q-btn
                    v-if="canManageAgent(agent)"
                    class="agent-action-button"
                    flat color="negative" icon="delete" :label="$t('common.delete')" :aria-label="$t('agent.deleteTooltip')" size="sm"
                    @click="confirmDeleteAgent(agent)"
                  >
                    <q-tooltip>{{ $t('agent.deleteTooltip') }}</q-tooltip>
                  </q-btn>
                </div>
              </q-card-actions>
            </q-card>
          </div>
        </div>

        <!-- No Data State -->
        <div v-else class="full-width row flex-center text-grey-8 q-gutter-sm q-pa-lg">
          <q-icon size="2em" name="people_outline" />
          <span>{{ agentStore.agents.length > 0 ? $t('agent.noAgentInGroup') : $t('agent.noAgent') }}</span>
        </div>
      </q-tab-panel>

      <!-- GROUPS TAB -->
      <q-tab-panel v-if="canViewTeams" name="groups"><TeamManager /></q-tab-panel>

      <!-- TITLES TAB -->
      <q-tab-panel v-if="canViewAgents" name="titles">
        <div class="row justify-end q-mb-md">
          <q-btn v-if="canEditGlobalCatalog" color="primary" icon="add" :label="$t('agent.newTitle')" @click="openTitleDialog()" />
        </div>

        <q-table
          :rows="agentStore.titles"
          :columns="titleColumns"
          row-key="id"
          :loading="agentStore.loading"
          :rows-per-page-options="[10, 20, 50, 100, 500]"
          :pagination="{ rowsPerPage: 50 }"
        >
          <template v-slot:body-cell-gender="props">
            <q-td :props="props">
              <q-chip
                :color="props.row.gender === 'M' ? 'blue' : 'pink'"
                text-color="white"
                size="sm"
              >
                {{ props.row.gender === 'M' ? $t('agent.genderM') : $t('agent.genderF') }}
              </q-chip>
            </q-td>
          </template>

          <template v-slot:body-cell-actions="props">
            <q-td :props="props" class="text-center">
              <q-btn v-if="canEditGlobalCatalog" flat round color="primary" icon="edit" size="sm" @click="openTitleDialog(props.row)">
                <q-tooltip>{{ $t('common.edit') }}</q-tooltip>
              </q-btn>
              <q-btn v-if="canEditGlobalCatalog" flat round color="negative" icon="delete" size="sm" @click="confirmDeleteTitle(props.row)">
                <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
              </q-btn>
            </q-td>
          </template>

          <template v-slot:no-data>
            <div class="full-width row flex-center text-grey-8 q-gutter-sm q-pa-lg">
              <q-icon size="2em" name="badge_outlined" />
              <span>{{ $t('agent.noTitleRegistered') }}</span>
            </div>
          </template>
        </q-table>
      </q-tab-panel>
    </q-tab-panels>

    <!-- AGENT DIALOG -->
    <q-dialog v-model="showAgentDialog">
      <q-card class="agent-dialog-card">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ isAgentEdit ? $t('agent.editAgent') : $t('agent.addAgent') }}</div>
          <q-space />
          <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup class="text-white" />
        </q-card-section>

        <q-tabs
          v-if="isAgentEdit"
          v-model="agentDialogTab"
          inline-label
          align="left"
          active-color="primary"
          indicator-color="primary"
          class="text-primary bg-grey-1"
        >
          <q-tab name="general" icon="person" :label="$t('agent.general')" />
          <q-tab v-if="canViewLlms" name="models" icon="model_training" :label="$t('agent.models.tab')" />
          <q-tab v-if="canManageMcp" name="mcp" icon="hub" :label="$t('agent.mcp.tab')" />
          <q-tab
            v-if="activeDriverTab"
            :name="activeDriverTab.name"
            :icon="activeDriverTab.icon"
            :label="$t(activeDriverTab.labelKey)"
          />
        </q-tabs>
        <q-separator v-if="isAgentEdit" />

        <q-card-section class="q-pt-md q-px-md">
          <q-form
            @submit="onAgentSubmit"
            @validation-error="onAgentValidationError"
            class="q-gutter-y-md"
          >

            <!-- Model configuration for every existing agent -->
            <template v-if="isAgentEdit && agentDialogTab === 'models'">
              <q-banner class="bg-blue-1 text-primary q-mb-md" dense rounded>
                <template #avatar><q-icon name="info" /></template>
                {{ $t('agent.models.intro') }}
              </q-banner>

              <q-card flat bordered>
                <q-card-section class="q-py-sm bg-grey-2">
                  <div class="text-subtitle2 text-primary">
                    <q-icon name="chat" class="q-mr-sm" />{{ $t('agent.models.llmTitle') }}
                  </div>
                </q-card-section>
                <q-card-section>
                  <q-select
                    v-model="agentForm.profile_id"
                    :options="profileOptions"
                    :label="$t('agent.models.profileLabel')"
                    filled emit-value map-options
                    :loading="llmProfileStore.loading"
                    :hint="$t('agent.models.profileHint')"
                  />
                </q-card-section>
              </q-card>

              <q-card flat bordered class="q-mt-md">
                <q-card-section class="q-py-sm bg-grey-2">
                  <div class="text-subtitle2 text-primary">
                    <q-icon name="record_voice_over" class="q-mr-sm" />{{ $t('agent.models.ttsTitle') }}
                  </div>
                </q-card-section>
                <q-card-section>
                  <q-select
                    v-model="agentForm.voice_selection"
                    :options="voiceOptions"
                    :label="$t('agent.models.ttsLabel')"
                    filled
                    emit-value
                    map-options
                    :loading="loadingNativeVoices"
                    :hint="voiceSelectionHint"
                  >
                    <template #option="{ itemProps, opt }">
                      <q-item v-if="opt.group" dense class="bg-grey-2">
                        <q-item-section>
                          <q-item-label header class="text-weight-bold text-primary">
                            {{ opt.label }}
                          </q-item-label>
                        </q-item-section>
                      </q-item>
                      <q-item v-else v-bind="itemProps">
                        <q-item-section avatar>
                          <q-icon :name="opt.icon" :color="opt.color" />
                        </q-item-section>
                        <q-item-section>
                          <q-item-label>{{ opt.label }}</q-item-label>
                          <q-item-label v-if="opt.caption" caption>{{ opt.caption }}</q-item-label>
                        </q-item-section>
                      </q-item>
                    </template>
                  </q-select>
                </q-card-section>
              </q-card>

              <div class="row justify-end q-mt-md q-gutter-sm">
                <q-btn :label="$t('common.cancel')" color="grey" flat v-close-popup />
                <q-btn v-if="canSaveAgent" :label="$t('common.save')" type="submit" color="primary" :loading="agentStore.loading || harnessChangePending" />
              </div>
            </template>

            <!-- General tab -->
            <template v-if="!isAgentEdit || agentDialogTab === 'general'">
            <!-- Avatar for existing agents -->
            <template v-if="isAgentEdit">
              <div class="row q-col-gutter-sm items-center q-mb-sm">
                <div class="col-4 flex flex-center">
                  <q-avatar size="80px" class="agent-fallback-avatar agent-dialog-avatar">
                    <img v-if="agentForm.id !== null && agentForm.has_avatar && avatarUrls[agentForm.id]" :src="avatarUrls[agentForm.id]" />
                    <template v-else>{{ agentInitials(agentForm) }}</template>
                  </q-avatar>
                </div>
                <div class="col-8 column q-gutter-y-sm">
                  <q-file
                    v-model="avatarFile"
                    class="agent-avatar-action"
                    :label="$t('agent.changeAvatar')"
                    filled
                    dense
                    accept="image/*"
                    @update:model-value="onAvatarSelected"
                    :loading="uploadingAvatar"
                    :disable="!canManageCurrentAgent"
                  >
                    <template v-slot:prepend>
                      <q-icon name="cloud_upload" />
                    </template>
                  </q-file>
                  <q-btn
                    v-if="canManageCurrentAgent && agentForm.has_avatar"
                    class="agent-avatar-action"
                    flat
                    color="negative"
                    icon="delete"
                    :label="$t('agent.deleteAvatar')"
                    @click="confirmDeleteAvatar"
                    :loading="uploadingAvatar"
                  />
                </div>
              </div>
              <q-separator class="q-my-md" />
            </template>

            <q-select
              v-model="agentForm.user_id"
              :options="managerOptions"
              :label="$t('agent.managerLabel')"
              filled
              emit-value
              map-options
              :loading="managersLoading"
              :rules="[val => val !== null || $t('agent.managerRequiredRule')]"
              :hint="$t('agent.managerHint')"
            />

            <!-- Row 1: title and code -->
            <div class="row q-col-gutter-md">
              <div class="col-12 col-sm-6">
                <q-select
                  v-model="agentForm.title_id"
                  :options="titleOptions"
                  :label="$t('agent.titleField')"
                  filled
                  emit-value
                  map-options
                  :rules="[val => val !== null || $t('agent.titleRequiredRule')]"
                />
              </div>
              <div class="col-12 col-sm-6">
                <q-input
                  v-model="agentForm.code"
                  :label="$t('agent.codeLabel')"
                  filled
                  :autofocus="!isAgentEdit"
                  :readonly="isAgentEdit"
                  :rules="codeRules"
                />
              </div>
            </div>

            <q-select
              v-if="isAgentEdit"
              v-model="selectedHarnessId"
              :options="harnessSelectionOptions"
              :label="$t('harnesses.selection')"
              :hint="$t('harnesses.selectionHint')"
              filled
              emit-value
              map-options
              :loading="harnessSelectionLoading"
              :disable="!canManageCurrentAgent || !harnessSelectionLoaded"
            />

            <!-- Row 2: first and last name -->
            <div class="row q-col-gutter-md">
              <div class="col-12 col-sm-6">
                <q-input
                  v-model="agentForm.first_name"
                  :label="$t('agent.firstName')"
                  filled
                  :rules="[val => !!val?.trim() || $t('agent.firstNameRule')]"
                />
              </div>
              <div class="col-12 col-sm-6">
                <q-input
                  v-model="agentForm.last_name"
                  :label="$t('agent.lastName')"
                  filled
                />
              </div>
            </div>

            <!-- Job title -->
            <div class="row q-col-gutter-md">
                <div class="col-12 col-sm-4">
                    <q-btn v-if="canViewTeams" flat icon="groups" :label="$t('team.title')" to="/team" />
                </div>
              <div class="col-12 col-sm-8">
                <q-input
              v-model="agentForm.job_title"
              :label="$t('agent.jobTitleLabel')"
              type="text"
              filled
              :hint="$t('agent.jobTitleHint')"
            />
              </div>
            </div>

            <!-- Personality and job description are edited after creation. -->
            <template v-if="isAgentEdit">
              <q-banner class="bg-info text-white q-mb-sm" dense rounded>
                <template v-slot:avatar>
                  <q-icon name="info" />
                </template>
                <div class="text-caption">
                  {{ $t('agent.editInfoBanner') }}
                </div>
              </q-banner>
            </template>

            <div class="row justify-end q-mt-md q-gutter-sm">
              <q-btn :label="$t('common.cancel')" color="grey" flat v-close-popup />
              <q-btn
                v-if="canSaveAgent"
                :label="isAgentEdit ? $t('common.edit') : $t('common.create')"
                type="submit"
                color="primary"
                :loading="agentStore.loading || harnessChangePending"
              />
            </div>
            </template>
          </q-form>

          <component
            v-if="isAgentEdit && activeDriverTab && agentDialogTab === activeDriverTab.name"
            :is="activeDriverTab.component"
            :agent-id="Number(agentForm.id)"
            @updated="showAgentDialog = false"
          />

          <!-- MCP tab for every existing agent driver -->
          <template v-if="isAgentEdit && agentDialogTab === 'mcp' && canManageMcp">
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
                  <q-btn flat round dense icon="content_copy" @click="copyText(mcpEndpointUrl)">
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
                  <q-btn flat round dense icon="content_copy" @click="copyText(mcpConfigSnippet)">
                    <q-tooltip>{{ $t('agent.mcp.copy') }}</q-tooltip>
                  </q-btn>
                </template>
              </q-input>

              <!-- Tokens -->
              <div class="row items-center q-mt-md">
                <div class="text-subtitle2 text-primary">{{ $t('agent.mcp.tokensTitle') }}</div>
                <q-space />
                <q-btn
                  v-if="canManageMcp"
                  color="primary"
                  icon="add"
                  :label="$t('agent.mcp.newToken')"
                  no-caps
                  :loading="mcpTokensLoading"
                  @click="openCreateMcpToken"
                />
              </div>
              <div class="text-caption text-grey-6">{{ $t('agent.mcp.tokensHint') }}</div>

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
                    <q-btn
                      v-if="canManageMcp"
                      flat round
                      :color="props.row.enabled ? 'grey' : 'positive'"
                      :icon="props.row.enabled ? 'block' : 'check_circle'"
                      @click="toggleMcpToken(props.row)"
                    >
                      <q-tooltip>{{ props.row.enabled ? $t('agent.mcp.disable') : $t('agent.mcp.enable') }}</q-tooltip>
                    </q-btn>
                    <q-btn v-if="canManageMcp" flat round color="negative" icon="delete" @click="deleteMcpToken(props.row)">
                      <q-tooltip>{{ $t('common.delete') }}</q-tooltip>
                    </q-btn>
                  </q-td>
                </template>
              </q-table>

              <div class="row justify-end q-mt-md">
                <q-btn :label="$t('common.close')" color="grey" flat v-close-popup />
              </div>
            </div>
          </template>
        </q-card-section>
      </q-card>
    </q-dialog>

    <q-dialog
      v-model="showHarnessChangeConfirm"
      @hide="settleHarnessChangeConfirmation(false)"
    >
      <q-card style="width: 560px; max-width: 92vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ $t('agent.harness.changeConfirmTitle') }}</div>
          <q-space />
          <q-btn
            icon="close"
            flat
            round
            dense
            :aria-label="$t('common.close')"
            @click="settleHarnessChangeConfirmation(false)"
          />
        </q-card-section>
        <q-card-section>
          <q-banner rounded class="bg-warning text-dark">
            <template v-slot:avatar><q-icon name="warning" /></template>
            {{ $t('agent.harness.changeConfirmMessage') }}
          </q-banner>
          <p class="q-mb-none q-mt-md">{{ $t('agent.harness.changeConfirmNextStep') }}</p>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn
            flat
            color="grey-7"
            :label="$t('common.cancel')"
            @click="settleHarnessChangeConfirmation(false)"
          />
          <q-btn
            color="negative"
            icon="delete_forever"
            :label="$t('agent.harness.changeConfirmAction')"
            @click="settleHarnessChangeConfirmation(true)"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog
      v-model="showPausedHarnessTasksConfirm"
      @hide="settlePausedHarnessTasksConfirmation(false)"
    >
      <q-card style="width: 620px; max-width: 92vw">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">{{ $t('agent.harness.blockingTasksTitle') }}</div>
          <q-space />
          <q-btn
            icon="close"
            flat
            round
            dense
            :aria-label="$t('common.close')"
            @click="settlePausedHarnessTasksConfirmation(false)"
          />
        </q-card-section>
        <q-card-section>
          <q-banner v-if="pausedHarnessTasks.length > 0" rounded class="bg-warning text-dark">
            <template v-slot:avatar><q-icon name="pause_circle" /></template>
            {{ $t('agent.harness.pausedTasksMessage', { count: pausedHarnessTasks.length }) }}
          </q-banner>
          <q-list v-if="pausedHarnessTasks.length > 0" bordered separator class="q-mt-md">
            <q-item v-for="task in pausedHarnessTaskPreview" :key="task.id">
              <q-item-section avatar><q-icon name="task_alt" color="warning" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ task.label }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-if="pausedHarnessTasksRemaining > 0">
              <q-item-section class="text-grey-7">
                {{ $t('agent.harness.pausedTasksMore', { count: pausedHarnessTasksRemaining }) }}
              </q-item-section>
            </q-item>
          </q-list>
          <p v-if="pausedHarnessTasks.length > 0 && activeHarnessTaskCount === 0" class="q-mb-none q-mt-md">
            {{ $t('agent.harness.pausedTasksConsequence') }}
          </p>
          <q-banner
            v-if="activeHarnessTaskCount > 0"
            rounded
            class="bg-orange-1 text-dark q-mt-md"
          >
            <template v-slot:avatar><q-icon name="schedule" color="warning" /></template>
            {{ $t('agent.harness.activeTasksMessage', { count: activeHarnessTaskCount }) }}
          </q-banner>
          <q-list v-if="activeHarnessTasks.length > 0" bordered separator class="q-mt-md">
            <q-item
              v-for="task in activeHarnessTasks"
              :key="task.id"
              :to="privilegeStore.hasPrivilege(privileges.TASK_ACCESS) ? { path: '/task', query: { task_id: task.id } } : undefined"
              target="_blank"
            >
              <q-item-section>
                <q-item-label>{{ task.label }}</q-item-label>
                <q-item-label caption>{{ `galaris://task/${task.id}` }}</q-item-label>
              </q-item-section>
              <q-item-section side><q-icon name="open_in_new" /></q-item-section>
            </q-item>
          </q-list>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn
            flat
            color="grey-7"
            :label="$t('common.cancel')"
            @click="settlePausedHarnessTasksConfirmation(false)"
          />
          <q-btn
            v-if="pausedHarnessTasks.length > 0 && activeHarnessTaskCount === 0"
            color="negative"
            icon="cancel_schedule_send"
            :label="$t('agent.harness.pausedTasksAction')"
            @click="settlePausedHarnessTasksConfirmation(true)"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <!-- RICH TEXT EDITOR DIALOG -->
    <q-dialog allow-focus-outside v-model="showRichTextDialog" style="max-width: 1400px">
      <q-card style="min-width: 1000px; max-width: 1400px; width: 90vw; max-height: 92vh">
        <q-card-section class="galaris-dialog-title row items-center">
          <div class="text-h6">
            <q-icon :name="richTextField === 'personality' ? 'psychology' : 'work'" class="q-mr-sm" />
            {{ richTextField === 'personality' ? $t('agent.editPersonality') : $t('agent.editJobDescription') }}
          </div>
          <q-space />
          <div class="text-caption q-mr-md">
            {{ richTextAgent?.first_name }} {{ richTextAgent?.last_name }}
          </div>
          <q-btn icon="close" :aria-label="$t('common.close')" flat round dense v-close-popup />
        </q-card-section>

        <q-card-section class="q-pa-md" style="max-height: 75vh; overflow: auto">
          <RichTextEditor
            v-model="richTextContent"
            min-height="500px"
            max-height="70vh"
          />
        </q-card-section>

        <q-card-actions align="right" class="q-pa-md bg-grey-2 galaris-dialog-actions">
          <q-btn :label="$t('common.cancel')" color="grey" flat v-close-popup />
          <q-btn
            v-if="richTextAgent && canManageAgent(richTextAgent)"
            :label="$t('common.save')"
            color="primary"
            @click="saveRichText"
            :loading="agentStore.loading"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <AgentAuxiliaryDialogs
      v-model:show-create-mcp-token="showCreateMcpTokenDialog"
      v-model:new-mcp-token-label="newMcpTokenLabel"
      v-model:show-new-mcp-token="showNewMcpTokenDialog"
      v-model:new-mcp-token-value="newMcpTokenValue"
      v-model:show-title="showTitleDialog"
      :title-form="titleForm"
      @update-title="Object.assign(titleForm, $event)"
      v-model:show-group="showGroupDialog"
      :group-form="groupForm"
      @update-group="Object.assign(groupForm, $event)"
      v-model:show-harness-logs="showHarnessLogsDialog"
      v-model:show-delete="showDeleteDialog"
      :can-edit="canEdit"
      :can-edit-catalog="canEditGlobalCatalog"
      :can-manage-mcp="canManageMcp"
      :loading="agentStore.loading || mcpTokensLoading"
      :is-title-edit="isTitleEdit"
      :is-group-edit="isGroupEdit"
      :gender-options="genderOptions"
      :harness-logs-agent-name="harnessLogsAgentName"
      :harness-logs="harnessLogs"
      :harness-logs-loading="harnessLogsLoading"
      :harness-log-color="harnessLogColor"
      :delete-message="deleteMessage"
      @create-mcp-token="confirmCreateMcpToken"
      @copy-token="copyText"
      @submit-title="onTitleSubmit"
      @submit-group="onGroupSubmit"
      @close-harness-logs="closeHarnessLogs"
      @refresh-harness-logs="fetchHarnessLogs"
      @confirm-delete="confirmDelete"
    />
  </q-page>
</template>

<script setup lang="ts">
import { showConfirmationDialog } from '@/core/util'
import { useRoute } from 'vue-router'
import { navigationIcon } from '@/core/navigation'
import { ref, onUnmounted, reactive, computed, watch, type Component } from 'vue'
import { useAgentStore } from '../stores/agentStore'
import { agentService } from '../services/agentService'
import type { Agent, AgentManagerInfo, ExecutorDriverInfo, Title, AgentGroup } from '../services/agentService'
import { titleLabel } from '../titleLabels'
import { harnessService } from '@/app/harnesses'
import type {
  HarnessAction,
  HarnessCatalogEntry,
  HarnessCapability,
  HarnessRuntimeState,
  HarnessTaskBlocker,
} from '@/app/harnesses'
import { getAgentDriverTab } from '../driverTabs'
import { mcpTokenService, type AgentMcpToken } from '../services/mcpTokenService'
import { useLLMProviderStore } from '@/app/llm/stores/llmProviderStore'
import llmProviderService from '@/app/llm/services/llmProviderService'
import type { LLMModelInfo } from '@/app/llm/services/llmProviderService'
import { useParamsStore } from '@/core/params/stores/paramsStore'
import { useLLMProfileStore } from '@/app/llm/stores/llmProfileStore'
import { useQuasar, type QTableColumn } from 'quasar'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { apiErrorDetail } from '@/core/api'
import { RichTextEditor, richTextExcerpt, PageHeader, startVisiblePolling } from '@/core/util'
import { useHarnessLogs } from '../composables/useHarnessLogs'
import AgentAuxiliaryDialogs from '../components/AgentAuxiliaryDialogs.vue'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { TeamManager } from '@/core/team'

const $q = useQuasar()
const { t } = useI18n()
const agentStore = useAgentStore()
const llmProviderStore = useLLMProviderStore()
const paramsStore = useParamsStore()
const llmProfileStore = useLLMProfileStore()
const privilegeStore = usePrivilegeStore()
const canViewAgents = computed(() => privilegeStore.hasPrivilege('AGENT_ACCESS') || privilegeStore.hasPrivilege('AGENT_EDIT'))
const canViewTeams = computed(() => privilegeStore.hasPrivilege('TEAM_ACCESS'))
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.AGENT_EDIT))
const canManageAllAgents = computed(() => (
  privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL)
))
const canEditGlobalCatalog = computed(() => canEdit.value && canManageAllAgents.value)
const canManageAgent = (agent: Agent): boolean => (
  canEdit.value && (agent.is_owner || canManageAllAgents.value)
)
const canViewLlms = computed(() => (
  privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_ACCESS)
  || privilegeStore.hasPrivilege(privileges.LLM_PROVIDER_EDIT)
))
const canViewParams = computed(() => (
  privilegeStore.hasPrivilege(privileges.PARAMS_ACCESS)
  || privilegeStore.hasPrivilege(privileges.PARAMS_EDIT)
))

const activeTab = ref('agents')
watch([canViewAgents, canViewTeams], () => {
  const allowed = [...(canViewAgents.value ? ['agents', 'titles'] : []), ...(canViewTeams.value ? ['groups'] : [])]
  if (!allowed.includes(activeTab.value)) activeTab.value = allowed[0] ?? ''
}, { immediate: true })
const activeGroupTab = ref('')
const agentDialogTab = ref('general')
const showAgentDialog = ref(false)

// MCP tab: access tokens for the agent's unified MCP server.
const mcpTokens = ref<AgentMcpToken[]>([])
const mcpTokensLoading = ref(false)
const showCreateMcpTokenDialog = ref(false)
const newMcpTokenLabel = ref('')
const showNewMcpTokenDialog = ref(false)
const newMcpTokenValue = ref('')

const mcpEndpointUrl = computed(
  () => `${window.location.origin}/api/mcp/${agentForm.code || ''}`
)
const mcpConfigSnippet = computed(() => JSON.stringify(
  {
    mcpServers: {
      [agentForm.code || 'agent']: {
        type: 'http',
        url: mcpEndpointUrl.value,
        headers: { Authorization: 'Bearer <TOKEN>' },
      },
    },
  },
  null,
  2,
))
const mcpTokenColumns = computed<QTableColumn[]>(() => [
  { name: 'label', label: t('agent.mcp.colLabel'), field: 'label', align: 'left' },
  { name: 'token', label: t('agent.mcp.colToken'), field: 'token', align: 'left' },
  { name: 'enabled', label: t('agent.mcp.colState'), field: 'enabled', align: 'center' },
  { name: 'created_at', label: t('agent.mcp.colCreatedAt'), field: 'created_at', align: 'left' },
  { name: 'actions', label: t('common.actions'), field: 'actions', align: 'right' },
])

function formatDateTime(dateStr: string) {
  return new Date(dateStr).toLocaleString()
}

function copyText(value: string) {
  navigator.clipboard.writeText(value).then(() => {
    $q.notify({ type: 'positive', message: t('agent.mcp.copied') })
  }).catch(() => {
    $q.notify({ type: 'negative', message: t('agent.mcp.copyFailed') })
  })
}

async function loadMcpTokens() {
  if (!canManageMcp.value || !isAgentEdit.value || !agentForm.id) return
  mcpTokensLoading.value = true
  try {
    const { data } = await mcpTokenService.listTokens(agentForm.id)
    mcpTokens.value = data
  } catch (error) {
    console.error('Error loading MCP tokens:', error)
    $q.notify({ type: 'negative', message: t('agent.mcp.loadError') })
  } finally {
    mcpTokensLoading.value = false
  }
}

function openCreateMcpToken() {
  if (!canManageMcp.value) return
  newMcpTokenLabel.value = ''
  showCreateMcpTokenDialog.value = true
}

async function confirmCreateMcpToken() {
  if (!canManageMcp.value || !agentForm.id) return
  mcpTokensLoading.value = true
  try {
    const { data } = await mcpTokenService.createToken(
      agentForm.id,
      newMcpTokenLabel.value ? { label: newMcpTokenLabel.value } : {},
    )
    // Reveal the clear-text token only in this copy dialog, then reload the masked list.
    newMcpTokenValue.value = data.token
    showCreateMcpTokenDialog.value = false
    showNewMcpTokenDialog.value = true
    await loadMcpTokens()
  } catch (error) {
    console.error('Error creating MCP token:', error)
    $q.notify({ type: 'negative', message: t('agent.mcp.createError') })
  } finally {
    mcpTokensLoading.value = false
  }
}

async function toggleMcpToken(token: AgentMcpToken) {
  if (!canManageMcp.value || !agentForm.id) return
  try {
    const { data } = await mcpTokenService.updateToken(agentForm.id, token.id, { enabled: !token.enabled })
    const idx = mcpTokens.value.findIndex(tk => tk.id === token.id)
    if (idx !== -1) mcpTokens.value[idx] = data
  } catch (error) {
    console.error('Error toggling MCP token:', error)
    $q.notify({ type: 'negative', message: t('agent.mcp.toggleError') })
  }
}

async function deleteMcpToken(token: AgentMcpToken) {
  if (!canManageMcp.value || !agentForm.id) return
  showConfirmationDialog({
    title: t('common.deleteConfirmTitle'),
    message: t('agent.mcp.deleteConfirm'),
    cancel: true,
  }).onOk(async () => {
    try {
      if (agentForm.id === null) return
      await mcpTokenService.deleteToken(agentForm.id, token.id)
      mcpTokens.value = mcpTokens.value.filter(tk => tk.id !== token.id)
      $q.notify({ type: 'positive', message: t('agent.mcp.deleted') })
    } catch (error) {
      console.error('Error deleting MCP token:', error)
      $q.notify({ type: 'negative', message: t('agent.mcp.deleteError') })
    }
  })
}
const showRichTextDialog = ref(false)
const showTitleDialog = ref(false)
const showGroupDialog = ref(false)
const showDeleteDialog = ref(false)
const isAgentEdit = ref(false)
const isTitleEdit = ref(false)
const isGroupEdit = ref(false)
const itemToDelete = ref<Agent | Title | AgentGroup | null>(null)
const deleteType = ref<'agent' | 'title' | 'group'>('agent') // 'agent', 'title' or 'group'

// Avatar state
const avatarFile = ref<File | null>(null)
const uploadingAvatar = ref(false)
const avatarUrls = reactive<Record<number, string>>({})

const agentInitials = (agent: Pick<Agent, 'first_name' | 'last_name' | 'code'>) => {
  const fullName = `${agent?.first_name || ''} ${agent?.last_name || ''}`.trim()
  const initials = fullName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]?.toUpperCase())
    .join('')

  return initials || String(agent?.code || '?').slice(0, 2).toUpperCase()
}

// Load avatars for agents
const loadAvatars = async () => {
  for (const agent of agentStore.agents) {
    if (agent.has_avatar && !avatarUrls[agent.id]) {
      try {
        const url = await agentService.getAvatarBlobUrl(agent.id)
        avatarUrls[agent.id] = url
      } catch (error) {
        console.error(`Failed to load avatar for agent ${agent.id}:`, error)
      }
    }
  }
}

// Rich text editor state
const richTextAgent = ref<Agent | null>(null)
const richTextField = ref<'personality' | 'job_description'>('personality') // 'personality' or 'job_description'
const richTextContent = ref('')

const genderOptions = computed(() => [
  { label: t('agent.genderM'), value: 'M' },
  { label: t('agent.genderF'), value: 'F' }
])

const titleOptions = computed(() => {
  return agentStore.titles.map(title => ({
    label: `${titleLabel(title.label, t)} (${title.gender === 'M' ? 'M' : 'F'})`,
    value: title.id
  }))
})

// Executor drivers come from the backend registry. The internal harness is
// unconditional; external drivers are offered only when fully available.
const drivers = ref<ExecutorDriverInfo[]>([])
const managers = ref<AgentManagerInfo[]>([])
const managersLoading = ref(false)
const harnessStates = reactive<Record<number, HarnessRuntimeState>>({})
const unavailableHarnessManagerAgentIds = reactive(new Set<number>())
const harnessActionLoading = reactive<Record<number, HarnessAction | undefined>>({})
const harnessCatalog = ref<HarnessCatalogEntry[]>([])
const selectedHarnessId = ref<string | null>(null)
const initialHarnessId = ref<string | null>(null)
const harnessSelectionLoading = ref(false)
const harnessSelectionLoaded = ref(false)
const fleetRestarting = ref(false)
const showHarnessChangeConfirm = ref(false)
let harnessChangeConfirmation: ((confirmed: boolean) => void) | null = null
const harnessChangePending = ref(false)
const showPausedHarnessTasksConfirm = ref(false)
const pausedHarnessTasks = ref<HarnessTaskBlocker[]>([])
const activeHarnessTasks = ref<HarnessTaskBlocker[]>([])
const activeHarnessTaskCount = ref(0)
let pausedHarnessTasksConfirmation: ((confirmed: boolean) => void) | null = null
let stopHarnessPolling: (() => void) | undefined
let pageDisposed = false

const fetchDrivers = async () => {
  try {
    const { data } = await agentService.getDrivers()
    drivers.value = data
  } catch {
    drivers.value = []
  }
}

const isManagedRuntime = (agent: Agent): boolean => (
  harnessStates[agent.id]?.managed
  ?? drivers.value.some(driver => driver.name === agent.agent_driver && driver.manages_runtime)
)

const managedAgents = computed(() => agentStore.agents.filter(agent => (
  isManagedRuntime(agent) && canManageAgent(agent)
)))

const managedRuntimeAgents = computed(() => agentStore.agents.filter(isManagedRuntime))

const harnessManagerUnavailable = computed(() => managedRuntimeAgents.value.some(
  agent => unavailableHarnessManagerAgentIds.has(agent.id),
))

const managerOptions = computed(() => managers.value.map(manager => ({
  label: manager.display_name
    ? `${manager.display_name} — ${manager.email}`
    : manager.email,
  value: manager.id,
})))

const harnessSelectionOptions = computed(() => [
  { label: t('harnesses.internal'), value: null },
  ...harnessCatalog.value.map(harness => ({
    label: harness.provider_code === 'openai_messages'
      ? `${harness.name} · API`
      : harness.name,
    value: harness.id,
  })),
])

async function loadHarnessSelection(agent: Agent): Promise<void> {
  harnessSelectionLoading.value = true
  harnessSelectionLoaded.value = false
  try {
    const [catalogResponse, selectionResponse] = await Promise.all([
      harnessService.catalog(true),
      harnessService.selection(agent.id),
    ])
    harnessCatalog.value = catalogResponse.data
    selectedHarnessId.value = selectionResponse.data.harness_id
    initialHarnessId.value = selectionResponse.data.harness_id
    harnessSelectionLoaded.value = true
  } catch {
    harnessCatalog.value = []
    selectedHarnessId.value = null
    initialHarnessId.value = null
    $q.notify({ type: 'negative', message: t('harnesses.catalog.loadError') })
  } finally {
    harnessSelectionLoading.value = false
  }
}

const fetchManagers = async (): Promise<void> => {
  if (!canEdit.value) return
  managersLoading.value = true
  try {
    const { data } = await agentService.getManagers()
    managers.value = data
  } finally {
    managersLoading.value = false
  }
}

const harnessState = (agent: Agent): HarnessRuntimeState => (
  harnessStates[agent.id] ?? {
    status: 'loading',
    lifecycle_status: 'internal',
    managed: false,
    capabilities: [],
    last_error: null,
  }
)

const hasHarnessCapability = (agent: Agent, capability: HarnessCapability): boolean => (
  harnessState(agent).capabilities.includes(capability)
)

const harnessStatusLabel = (status: string): string => {
  if (['absent', 'provisioning', 'deprovisioning', 'error'].includes(status)) {
    return t(`agent.harness.lifecycle.${status}`)
  }
  return t(`agent.harness.status.${status || 'unknown'}`)
}

const harnessStatusColor = (status: string): string => {
  if (status === 'running') return 'positive'
  if (status === 'error') return 'negative'
  if (status === 'stopped') return 'grey-7'
  if (status === 'absent' || status === 'disabled') return 'grey-5'
  return 'warning'
}

const harnessStatusIcon = (status: string): string => {
  if (status === 'running') return 'check_circle'
  if (status === 'stopped') return 'stop_circle'
  if (status === 'absent' || status === 'disabled') return 'radio_button_unchecked'
  if (status === 'loading') return 'hourglass_top'
  return 'help_outline'
}

const hasHarnessAction = (agent: Agent, action: HarnessAction): boolean => (
  harnessState(agent).available_actions?.includes(action) ?? false
)

const harnessRestartLabel = (agent: Agent): string => (
  t(harnessState(agent).status === 'absent' ? 'agent.harness.createRuntime' : 'agent.harness.restart')
)

const harnessLifecycleBusy = (agent: Agent): boolean => (
  ['provisioning', 'deprovisioning'].includes(harnessState(agent).lifecycle_status)
)

async function fetchHarnessStatus(agent: Agent, silent = false): Promise<void> {
  if (!silent) {
    harnessStates[agent.id] = {
      status: 'loading',
      lifecycle_status: harnessStates[agent.id]?.lifecycle_status ?? 'internal',
      managed: harnessStates[agent.id]?.managed ?? false,
      capabilities: harnessStates[agent.id]?.capabilities ?? [],
      last_error: harnessStates[agent.id]?.last_error ?? null,
    }
  }
  try {
    harnessStates[agent.id] = (await harnessService.status(agent.id)).data
    unavailableHarnessManagerAgentIds.delete(agent.id)
  } catch (error: unknown) {
    const serviceUnavailable = isAxiosError(error) && error.response?.status === 503
    let managed = isManagedRuntime(agent)
    if (serviceUnavailable && !managed) {
      try {
        managed = (await harnessService.selection(agent.id)).data.containerized
      } catch {
        // Keep the last known runtime kind when the persisted selection cannot be read.
      }
    }
    if (managed && serviceUnavailable) {
      unavailableHarnessManagerAgentIds.add(agent.id)
    } else {
      unavailableHarnessManagerAgentIds.delete(agent.id)
    }
    harnessStates[agent.id] = {
      status: 'unknown',
      lifecycle_status: harnessStates[agent.id]?.lifecycle_status ?? 'internal',
      managed,
      capabilities: harnessStates[agent.id]?.capabilities ?? [],
      last_error: harnessStates[agent.id]?.last_error ?? null,
    }
  }
}

async function runHarnessAction(agent: Agent, action: HarnessAction): Promise<void> {
  if (!canManageAgent(agent) || harnessActionLoading[agent.id] || !hasHarnessAction(agent, action)) return
  harnessActionLoading[agent.id] = action
  try {
    await harnessService.action(agent.id, action)
    harnessStates[agent.id] = {
      ...harnessState(agent),
      available_actions: [],
      status: action === 'stop' ? harnessState(agent).status : 'provisioning',
      lifecycle_status: action === 'stop' ? harnessState(agent).lifecycle_status : 'provisioning',
      last_error: null,
    }
    $q.notify({ type: 'positive', message: t(`agent.harness.action.${action}Queued`) })
  } catch {
    await fetchHarnessStatus(agent, true)
    $q.notify({ type: 'negative', message: t(`agent.harness.action.${action}Error`) })
  } finally {
    delete harnessActionLoading[agent.id]
  }
}

function confirmHarnessReplacement(): Promise<boolean> {
  showHarnessChangeConfirm.value = true
  return new Promise(resolve => {
    harnessChangeConfirmation = resolve
  })
}

function settleHarnessChangeConfirmation(confirmed: boolean): void {
  const resolve = harnessChangeConfirmation
  harnessChangeConfirmation = null
  showHarnessChangeConfirm.value = false
  resolve?.(confirmed)
}

const pausedHarnessTaskPreview = computed(() => pausedHarnessTasks.value.slice(0, 5))
const pausedHarnessTasksRemaining = computed(() => Math.max(
  0,
  pausedHarnessTasks.value.length - pausedHarnessTaskPreview.value.length,
))

function confirmPausedHarnessTasksTermination(): Promise<boolean> {
  showPausedHarnessTasksConfirm.value = true
  return new Promise(resolve => {
    pausedHarnessTasksConfirmation = resolve
  })
}

function settlePausedHarnessTasksConfirmation(confirmed: boolean): void {
  const resolve = pausedHarnessTasksConfirmation
  pausedHarnessTasksConfirmation = null
  showPausedHarnessTasksConfirm.value = false
  resolve?.(confirmed)
}

async function loadPausedHarnessTasks(agentId: number): Promise<void> {
  const blockers = (await harnessService.taskBlockers(agentId)).data
  pausedHarnessTasks.value = blockers.paused_tasks
  activeHarnessTasks.value = blockers.active_tasks ?? []
  activeHarnessTaskCount.value = blockers.active_count
}

async function terminatePausedHarnessTasks(agentId: number): Promise<void> {
  const blockers = (await harnessService.terminatePausedTasks(agentId)).data
  pausedHarnessTasks.value = blockers.paused_tasks
  activeHarnessTasks.value = blockers.active_tasks ?? []
  activeHarnessTaskCount.value = blockers.active_count
}

async function restartFleet(): Promise<void> {
  if (!canEdit.value || fleetRestarting.value) return
  fleetRestarting.value = true
  try {
    await Promise.all(
      managedAgents.value
        .filter(agent => hasHarnessAction(agent, 'restart'))
        .map(agent => runHarnessAction(agent, 'restart')),
    )
  } finally {
    fleetRestarting.value = false
  }
}

const { showHarnessLogsDialog, harnessLogs, harnessLogsLoading, harnessLogsAgentName,
  fetchHarnessLogs, openHarnessLogs, closeHarnessLogs } = useHarnessLogs(
    async agentId => (await harnessService.logs(agentId)).data.lines,
    (agent, failed) => harnessState(agent).last_error || (failed
      ? t('agent.harness.logsError') : harnessStatusLabel(harnessState(agent).lifecycle_status)),
  )

function harnessLogColor(line: string): string {
  if (/error|exception|traceback|critical/i.test(line)) return '#f28b82'
  if (/warning|warn/i.test(line)) return '#fdd663'
  if (/info/i.test(line)) return '#a8d8a8'
  return '#d4d4d4'
}

const codeRules = [
  (val: string) => !!String(val || '').trim() || t('agent.codeRequiredRule'),
  (val: string) => String(val || '').trim().length <= 50 || t('agent.codeMaxLengthRule'),
  (val: string) => /^[a-zA-Z0-9_-]+$/.test(String(val || '').trim()) || t('agent.codeFormatRule'),
]

// One tab per group, plus an ungrouped tab when needed.
const groupTabs = computed(() => {
  const tabs = agentStore.sortedGroups.map(g => ({ name: String(g.id), label: g.name }))
  const hasUngrouped = agentStore.agents.some(agent => !agent.team_ids?.length)
  if (hasUngrouped) tabs.push({ name: 'none', label: t('agent.noGroup') })
  return tabs
})

const displayedAgents = computed(() => {
  const list = agentStore.sortedAgents
  if (activeGroupTab.value === 'none') {
    return list.filter(agent => !agent.team_ids?.length)
  }
  const gid = Number(activeGroupTab.value)
  return list.filter(agent => agent.team_ids?.includes(gid))
})

// Model configuration lives in shared profiles: the agent model tab exposes a
// single profile picker plus the dedicated voice selection below.
const profileOptions = computed(() =>
  [{
    label: t('agent.models.useCurrentProfile', {
      profile: llmProfileStore.currentProfile?.label || t('agent.models.profileNotConfigured'),
    }),
    value: null,
  }, ...llmProfileStore.profiles.map(profile => ({ label: profile.label, value: profile.id }))]
)

type VoiceOption = {
  label: string
  value: string
  caption?: string
  icon?: string
  color?: string
  disable?: boolean
  group?: boolean
}

const NO_VOICE = 'none'
const TTS_VOICE_PREFIX = 'tts:'
const REALTIME_VOICE_PREFIX = 'realtime:'
const nativeVoiceResources = ref<Record<number, LLMModelInfo[]>>({})
const loadingNativeVoices = ref(false)

function stsVoiceValue(modelId: number, voiceCode: string): string {
  return `${REALTIME_VOICE_PREFIX}${modelId}:${encodeURIComponent(voiceCode)}`
}

function voiceSelectionForAgent(agent: Agent): string {
  return agent.voice || NO_VOICE
}

async function loadNativeVoiceResources(): Promise<void> {
  const providerIds = [...new Set(
    llmProviderStore.llms
      .filter(llm => llm.service_capabilities.includes('realtime_conversation'))
      .map(llm => llm.llm_provider_id),
  )]
  if (providerIds.length === 0) {
    nativeVoiceResources.value = {}
    return
  }

  loadingNativeVoices.value = true
  try {
    const entries = await Promise.all(providerIds.map(async providerId => {
      try {
        const response = await llmProviderService.getProviderResources(
          providerId,
          'speech',
        )
        return [
          providerId,
          response.data.models.filter(resource => resource.resource_type === 'voice'),
        ] as const
      } catch {
        return [providerId, []] as const
      }
    }))
    nativeVoiceResources.value = Object.fromEntries(entries)
  } finally {
    loadingNativeVoices.value = false
  }
}

const titleColumns = computed<QTableColumn[]>(() => [
  { name: 'label', label: t('agent.colLabel'), field: (row: Title) => titleLabel(row.label, t), sortable: true, align: 'left' },
  { name: 'gender', label: t('agent.colGender'), field: 'gender', sortable: true, align: 'center' },
  { name: 'actions', label: t('common.actions'), field: 'actions', align: 'center', style: 'width: 100px' }
])

const agentForm = reactive<{
  id: number | null; user_id: number | null; title_id: number | null; group_id: number | null;
  code: string; first_name: string; last_name: string; job_title: string; agent_driver: string;
  has_avatar: boolean; profile_id: number | null; voice_selection: string;
}>({
  id: null,
  user_id: null,
  title_id: null,
  group_id: null,
  code: '',
  first_name: '',
  last_name: '',
  job_title: '',
  agent_driver: 'internal',
  has_avatar: false,
  profile_id: null,
  voice_selection: NO_VOICE,
})

const editedAgent = computed(() => (
  agentForm.id === null
    ? null
    : agentStore.agents.find(agent => agent.id === agentForm.id) ?? null
))
const canManageCurrentAgent = computed(() => (
  isAgentEdit.value
  && editedAgent.value !== null
  && canManageAgent(editedAgent.value)
))
const canSaveAgent = computed(() => (
  isAgentEdit.value ? canManageCurrentAgent.value : canEdit.value
))
const canManageMcp = computed(() => (
  canManageCurrentAgent.value && privilegeStore.hasPrivilege(privileges.MCP_API_ACCESS)
))

const activeDriverTab = computed(() => getAgentDriverTab(agentForm.agent_driver))

const pipelineVoiceOptions = computed<VoiceOption[]>(() => [
  {
    label: t('agent.models.ttsNone'),
    value: NO_VOICE,
    icon: 'volume_off',
    color: 'grey-7',
  },
  ...llmProviderStore.llms
    .filter(llm => llm.service_capabilities.includes('speech'))
    .map(llm => ({
      label: llm.label,
      value: `${TTS_VOICE_PREFIX}${llm.id}`,
      caption: llm.provider_name,
      icon: 'record_voice_over',
      color: 'purple',
    })),
])

const stsVoiceOptions = computed<VoiceOption[]>(() => {
  const options = llmProviderStore.llms
    .filter(llm => llm.service_capabilities.includes('realtime_conversation'))
    .flatMap(model => (
      nativeVoiceResources.value[model.llm_provider_id] || []
    ).map(voice => ({
      label: voice.name || voice.id.replace(/^voice:/, ''),
      value: stsVoiceValue(model.id, voice.id),
      caption: `${model.provider_name} · ${model.label}`,
      icon: 'spatial_audio',
      color: 'teal',
    })))

  return options
})

const voiceOptions = computed<VoiceOption[]>(() => [
  {
    label: t('agent.models.pipelineVoiceGroup'),
    value: 'group:pipeline',
    disable: true,
    group: true,
  },
  ...pipelineVoiceOptions.value,
  {
    label: t('agent.models.stsVoiceGroup'),
    value: 'group:sts',
    disable: true,
    group: true,
  },
  ...(stsVoiceOptions.value.length
    ? stsVoiceOptions.value
    : [{
        label: t('agent.models.noStsVoice'),
        value: 'sts:unavailable',
        disable: true,
        icon: 'info',
        color: 'grey-7',
      }]),
])

const voiceSelectionHint = computed(() => {
  if (agentForm.voice_selection.startsWith(REALTIME_VOICE_PREFIX)) {
    return t('agent.models.stsHint')
  }
  return t('agent.models.ttsHint')
})

const titleForm = reactive<{ id: number | null; label: string; gender: 'M' | 'F' | null }>({
  id: null,
  label: '',
  gender: null
})

const groupForm = reactive<{ id: number | null; name: string; order: number }>({
  id: null,
  name: '',
  order: 0
})

const deleteMessage = computed(() => {
  if (itemToDelete.value && 'first_name' in itemToDelete.value) {
    return t('agent.confirmDeleteAgent', { name: `${itemToDelete.value?.first_name || ''} ${itemToDelete.value?.last_name || ''}`.trim() })
  }
  if (itemToDelete.value && 'name' in itemToDelete.value) {
    return t('agent.confirmDeleteGroup', { name: itemToDelete.value?.name || '' })
  }
  return t('agent.confirmDeleteTitle', { name: titleLabel(itemToDelete.value && 'label' in itemToDelete.value ? itemToDelete.value.label : '', t) })
})

const resetAgentForm = () => {
  agentForm.id = null
  agentForm.user_id = managers.value.find(manager => manager.is_current_user)?.id ?? null
  agentForm.title_id = null
  agentForm.group_id = null
  agentForm.code = ''
  agentForm.first_name = ''
  agentForm.last_name = ''
  agentForm.job_title = ''
  agentForm.agent_driver = 'internal'
  agentForm.profile_id = null
  agentForm.voice_selection = NO_VOICE
  harnessCatalog.value = []
  selectedHarnessId.value = null
  initialHarnessId.value = null
  harnessSelectionLoaded.value = false
  pausedHarnessTasks.value = []
  activeHarnessTasks.value = []
  activeHarnessTaskCount.value = 0
}

const resetTitleForm = () => {
  titleForm.id = null
  titleForm.label = ''
  titleForm.gender = null
}

const openAgentDialog = async (agent: Agent | null = null) => {
  await fetchManagers()
  // Refresh the catalog so a voice or STS resource configured in another tab
  // is immediately available in the agent's single voice picker.
  if (canViewLlms.value) {
    await llmProviderStore.fetchLLMs()
    await loadNativeVoiceResources()
  }

  // Refresh model profiles so the picker lists every profile configured on
  // the "Modèles utilisés" page. A failure keeps the last known list.
  if (canViewParams.value) {
    try {
      await llmProfileStore.fetchProfiles()
    } catch {
      // Keep the stale list; the agent keeps its current profile.
    }
  }

  if (agent) {
    isAgentEdit.value = true
    agentDialogTab.value = 'general'
    mcpTokens.value = []
    Object.assign(agentForm, {
      id: agent.id,
      user_id: agent.user_id,
      title_id: agent.title_id,
      group_id: agent.group_id ?? null,
      code: agent.code || '',
      first_name: agent.first_name,
      last_name: agent.last_name,
      job_title: agent.job_title || '',
      agent_driver: agent.agent_driver || 'internal',
      has_avatar: agent.has_avatar,
      profile_id: agent.profile_id ?? null,
      voice_selection: voiceSelectionForAgent(agent),
    })
    await loadHarnessSelection(agent)
    // Load avatar if agent has one and it's not already loaded
    if (agent.has_avatar && !avatarUrls[agent.id]) {
      try {
        const url = await agentService.getAvatarBlobUrl(agent.id)
        avatarUrls[agent.id] = url
      } catch (error) {
        console.error(`Failed to load avatar for agent ${agent.id}:`, error)
      }
    }
  } else {
    isAgentEdit.value = false
    resetAgentForm()
  }
  avatarFile.value = null
  showAgentDialog.value = true
}

const openRichTextDialog = (agent: Agent, field: 'personality' | 'job_description') => {
  richTextAgent.value = agent
  richTextField.value = field
  richTextContent.value = agent[field] || ''
  showRichTextDialog.value = true
}

const saveRichText = async () => {
  if (!richTextAgent.value || !canManageAgent(richTextAgent.value)) return
  if (!richTextField.value) return

  try {
    const data = {
      [richTextField.value]: richTextContent.value || null
    }

    await agentStore.updateAgent(richTextAgent.value.id, data)
    $q.notify({
      type: 'positive',
      message: richTextField.value === 'personality'
        ? t('agent.notify.personalityUpdated')
        : t('agent.notify.jobDescriptionUpdated')
    })
    showRichTextDialog.value = false
  } catch (error) {
    $q.notify({ type: 'negative', message: t('agent.notify.saveError') })
  }
}

const openTitleDialog = (title: Title | null = null) => {
  if (title) {
    isTitleEdit.value = true
    Object.assign(titleForm, title)
  } else {
    isTitleEdit.value = false
    resetTitleForm()
  }
  showTitleDialog.value = true
}

const onGroupSubmit = async () => {
  if (!canEdit.value) return
  try {
    const data = {
      name: groupForm.name,
      order: Number(groupForm.order) || 0
    }

    if (isGroupEdit.value && groupForm.id !== null) {
      await agentStore.updateGroup(groupForm.id, data)
      $q.notify({ type: 'positive', message: t('agent.notify.groupUpdated') })
    } else {
      await agentStore.createGroup(data)
      $q.notify({ type: 'positive', message: t('agent.notify.groupCreated') })
    }
    showGroupDialog.value = false
  } catch (error) {
    $q.notify({ type: 'negative', message: t('common.anError') })
  }
}

const confirmDeleteAgent = (agent: Agent) => {
  itemToDelete.value = agent
  deleteType.value = 'agent'
  showDeleteDialog.value = true
}

const confirmDeleteTitle = (title: Title) => {
  itemToDelete.value = title
  deleteType.value = 'title'
  showDeleteDialog.value = true
}

const confirmDelete = async () => {
  if (!itemToDelete.value) return

  try {
    if (deleteType.value === 'agent') {
      await agentStore.deleteAgent(itemToDelete.value.id)
      $q.notify({ type: 'positive', message: t('agent.notify.agentDeleted') })
    } else if (deleteType.value === 'group') {
      await agentStore.deleteGroup(itemToDelete.value.id)
      $q.notify({ type: 'positive', message: t('agent.notify.groupDeleted') })
    } else {
      await agentStore.deleteTitle(itemToDelete.value.id)
      $q.notify({ type: 'positive', message: t('agent.notify.titleDeleted') })
    }
  } catch (error) {
    const messages = {
      agent: t('agent.notify.cannotDeleteAgent'),
      group: t('agent.notify.cannotDeleteGroup'),
      title: t('agent.notify.cannotDeleteTitle')
    }
    $q.notify({ type: 'negative', message: messages[deleteType.value] || t('agent.notify.cannotDelete') })
  }
}

const onAgentSubmit = async () => {
  if (!canSaveAgent.value || harnessChangePending.value || agentForm.title_id === null) return
  const harnessChanged = isAgentEdit.value
    && harnessSelectionLoaded.value
    && selectedHarnessId.value !== initialHarnessId.value
  if (harnessChanged && initialHarnessId.value !== null) {
    const confirmed = await confirmHarnessReplacement()
    if (!confirmed) return
  }
  if (harnessChanged && agentForm.id !== null && privilegeStore.hasPrivilege(privileges.TASK_EDIT)) {
    harnessChangePending.value = true
    try {
      await loadPausedHarnessTasks(agentForm.id)
    } catch {
      $q.notify({
        type: 'negative',
        message: t('agent.harness.pausedTasksCheckError'),
      })
      harnessChangePending.value = false
      return
    }
    if (pausedHarnessTasks.value.length > 0 || activeHarnessTaskCount.value > 0) {
      harnessChangePending.value = false
      const confirmed = await confirmPausedHarnessTasksTermination()
      if (!confirmed || activeHarnessTaskCount.value > 0) return
      harnessChangePending.value = true
      try {
        await terminatePausedHarnessTasks(agentForm.id)
      } catch {
        $q.notify({
          type: 'negative',
          message: t('agent.harness.pausedTasksTerminateError'),
        })
        harnessChangePending.value = false
        return
      }
      if (pausedHarnessTasks.value.length > 0 || activeHarnessTaskCount.value > 0) {
        $q.notify({
          type: 'warning',
          message: t('agent.harness.activeTasksStillBlock'),
          multiLine: true,
        })
        harnessChangePending.value = false
        return
      }
    }
  }
  try {
    const data = {
      user_id: agentForm.user_id,
      title_id: agentForm.title_id,
      first_name: agentForm.first_name,
      last_name: agentForm.last_name,
      job_title: agentForm.job_title === '' ? null : agentForm.job_title,
      profile_id: agentForm.profile_id,
      voice: agentForm.voice_selection === NO_VOICE ? null : agentForm.voice_selection,
    }

    if (isAgentEdit.value && agentForm.id !== null) {
      await agentStore.updateAgent(agentForm.id, data)
      if (harnessChanged) {
        selectedHarnessId.value === null
          ? await harnessService.selectInternal(agentForm.id)
          : await harnessService.install(agentForm.id, selectedHarnessId.value)
        // The status endpoint owns lifecycle/action projection; do not reconstruct it
        // from the selection response (which has no runtime observation).
        harnessStates[agentForm.id] = { ...harnessState({ id: agentForm.id } as Agent), status: 'loading', available_actions: [] }
        await agentStore.fetchAgents()
        const savedAgent = agentStore.agents.find(agent => agent.id === agentForm.id)
        if (savedAgent) await fetchHarnessStatus(savedAgent, true)
        initialHarnessId.value = selectedHarnessId.value
      }
      $q.notify({
        type: 'positive',
        message: harnessChanged
          ? t('agent.harness.preferenceSaved')
          : t('agent.notify.agentUpdated'),
      })
    } else {
      await agentStore.createAgent({
        ...data,
        code: agentForm.code.trim(),
      })
      $q.notify({ type: 'positive', message: t('agent.notify.agentCreated') })
    }
    showAgentDialog.value = false
  } catch (error) {
    const message = apiErrorDetail(error)

    console.error(
      `[AgentForm] Agent ${isAgentEdit.value ? 'update' : 'creation'} failed`,
      {
        status: isAxiosError(error) ? error.response?.status : undefined,
        error,
      },
    )
    $q.notify({
      type: 'negative',
      message: message || t('agent.notify.saveError'),
      multiLine: true,
    })
  } finally {
    harnessChangePending.value = false
  }
}

const onAgentValidationError = (component: Component) => {
  const field = component as { $el?: HTMLElement; focus?: () => void }
  const label = field?.$el?.querySelector?.('.q-field__label')?.textContent?.trim()
  console.warn('[AgentForm] Submission blocked by validation', {
    field: label || 'champ inconnu',
  })
  field?.focus?.()
  $q.notify({
    type: 'warning',
    message: label
      ? t('agent.notify.formInvalidField', { field: label })
      : t('agent.notify.formInvalid'),
  })
}

const onTitleSubmit = async () => {
  if (!canEdit.value || titleForm.gender === null) return
  try {
    const data = {
      label: titleForm.label,
      gender: titleForm.gender
    }

    if (isTitleEdit.value && titleForm.id !== null) {
      await agentStore.updateTitle(titleForm.id, data)
      $q.notify({ type: 'positive', message: t('agent.notify.titleUpdated') })
    } else {
      await agentStore.createTitle(data)
      $q.notify({ type: 'positive', message: t('agent.notify.titleCreated') })
    }
    showTitleDialog.value = false
  } catch (error) {
    $q.notify({ type: 'negative', message: t('common.anError') })
  }
}

const getAgentProfileLabel = (agent: Agent): string => (
  agent.profile?.label
  ?? llmProfileStore.currentProfile?.label
  ?? t('agent.models.profileNotConfigured')
)

const truncateText = (text: string | null, maxLength: number) => {
  if (!text) return ''
  return text.length > maxLength ? text.substring(0, maxLength) + '...' : text
}

// Avatar functions
const onAvatarSelected = async (file: File | null) => {
  if (!canManageCurrentAgent.value || !file || !agentForm.id) return

  uploadingAvatar.value = true
  try {
    await agentService.uploadAvatar(agentForm.id, file)
    agentForm.has_avatar = true
    // Load the new avatar
    const url = await agentService.getAvatarBlobUrl(agentForm.id)
    avatarUrls[agentForm.id] = url
    $q.notify({ type: 'positive', message: t('agent.notify.avatarUploaded') })
    // Refresh the agent list to update has_avatar status
    await agentStore.fetchAgents()
  } catch (error) {
    $q.notify({ type: 'negative', message: t('agent.notify.avatarUploadError') })
  } finally {
    uploadingAvatar.value = false
    avatarFile.value = null
  }
}

const confirmDeleteAvatar = async () => {
  if (!canManageCurrentAgent.value) return
  if (!agentForm.id) return

  showConfirmationDialog({
    title: t('common.confirm'),
    message: t('agent.confirmDeleteAvatar'),
    cancel: true
  }).onOk(async () => {
    uploadingAvatar.value = true
    try {
      if (agentForm.id === null) return
      await agentService.deleteAvatar(agentForm.id)
      agentForm.has_avatar = false
      $q.notify({ type: 'positive', message: t('agent.notify.avatarDeleted') })
      // Refresh the agent list to update has_avatar status
      await agentStore.fetchAgents()
    } catch (error) {
      $q.notify({ type: 'negative', message: t('agent.notify.avatarDeleteError') })
    } finally {
      uploadingAvatar.value = false
    }
  })
}

// Watch for agents to be loaded and then load avatars.
watch(() => agentStore.agents, async (newAgents) => {
  if (newAgents && newAgents.length > 0) {
    await loadAvatars()
  }
}, { immediate: true })

// Keep the active group tab valid and select the first available tab when necessary.
watch(groupTabs, (tabs) => {
  if (tabs.length === 0) {
    activeGroupTab.value = ''
    return
  }
  if (!tabs.some(t => t.name === activeGroupTab.value)) {
    activeGroupTab.value = tabs[0].name
  }
}, { immediate: true })

watch(canViewLlms, allowed => {
  if (allowed) {
    void llmProviderStore.fetchLLMs()
    // The agent profile label reads the current profile; a failure must not
    // break the page (the label falls back on the generic default).
    void llmProfileStore.fetchProfiles().catch(() => {})
  }
}, { immediate: true })

watch(canViewParams, allowed => {
  if (allowed) void paramsStore.fetchParams()
}, { immediate: true })

// Load MCP tokens lazily when the tab opens.
watch(agentDialogTab, (tab) => {
  if (tab === 'mcp') loadMcpTokens()
})

watch(() => agentForm.agent_driver, () => {
  const genericTabs = ['general', 'models', 'mcp']
  if (!genericTabs.includes(agentDialogTab.value)
    && agentDialogTab.value !== activeDriverTab.value?.name) {
    agentDialogTab.value = 'general'
  }
})

const richRoute = useRoute()
watch(() => richRoute.query.agent_id, async value => {
  if (typeof value !== 'string' || !/^[1-9][0-9]*$/.test(value)) return
  try { await agentStore.fetchAgents(); const agent = agentStore.agents.find(valueAgent => valueAgent.id === Number(value)); if (agent) await openAgentDialog(agent); else $q.notify({ type: 'negative', message: t('richEditor.unavailable') }) } catch { $q.notify({ type: 'negative', message: t('richEditor.unavailable') }) }
}, { immediate: true })
watch(canViewAgents, async allowed => {
  stopHarnessPolling?.()
  if (!allowed) return
  await Promise.all([
    agentStore.fetchAgents(),
    agentStore.fetchTitles(),
    agentStore.fetchGroups(),
  ])
  await fetchDrivers()
  await Promise.all(agentStore.agents.map(agent => fetchHarnessStatus(agent)))
  if (pageDisposed) return
  stopHarnessPolling = startVisiblePolling(async () => {
    const refreshes: Promise<void>[] = []
    for (const agent of managedRuntimeAgents.value) {
      if (!harnessActionLoading[agent.id]) refreshes.push(fetchHarnessStatus(agent, true))
    }
    await Promise.all(refreshes)
  }, 5000)
}, { immediate: true })

watch(activeTab, async (tab, previous) => {
  if (tab === 'agents' && previous === 'groups' && canViewAgents.value) {
    await Promise.all([agentStore.fetchAgents(), agentStore.fetchGroups()])
  }
})

onUnmounted(() => {
  pageDisposed = true
  stopHarnessPolling?.()
})
</script>

<style scoped>
.agent-dialog-card {
  width: 800px;
  max-width: 90vw;
}

.ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Clickable text zones for personality and job description */
.clickable-text-zone {
  cursor: pointer;
  border-radius: 4px;
  padding: 4px;
  margin: -4px;
  transition: background-color 0.2s ease;
}

.clickable-text-zone:hover {
  background-color: rgba(0, 0, 0, 0.05);
}

/* Agent Card Styles */
.agent-card {
  transition: box-shadow 0.3s ease;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.agent-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.agent-card-wrapper {
  width: 100%;
}

.agent-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, 700px);
  gap: 16px;
  justify-content: center;
}

@media (max-width: 750px) {
  .agent-cards-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.agent-card-horizontal {
  display: grid;
  grid-template-columns: minmax(140px, 180px) minmax(0, 1fr);
  min-height: 207px;
}

.agent-avatar-section {
  padding: 0;
  overflow: hidden;
  position: relative;
  height: 100%;
  min-width: 0;
}

.agent-info-section {
  min-width: 0;
}

.agent-identity-section {
  min-width: 0;
}

.agent-summary {
  margin-bottom: 8px;
}

.agent-image-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.agent-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
}

body.body--dark .agent-fallback-avatar {
  color: #9ab2f0;
  background: linear-gradient(145deg, #24304d, #1e2740);
}

.agent-fallback-avatar {
  color: #3f69d8;
  background: linear-gradient(145deg, #e7edff, #f3f6ff);
  box-shadow: 0 8px 22px rgba(63, 105, 216, 0.16);
  font-size: clamp(72px, 28vw, 112px) !important;
  font-weight: 750;
  letter-spacing: 0.04em;
}

.agent-dialog-avatar {
  font-size: 1.35rem;
}

.agent-avatar-action {
  width: 100%;
  max-width: 250px;
}

.agent-fallback-avatar :deep(img) {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.ellipsis-2-lines {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.profile-name {
  min-width: 0;
  line-height: 1.2;
}

.agent-name {
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.agent-manager {
  max-width: 42%;
  margin-left: 8px;
  line-height: 1.2;
  text-align: right;
}

.agent-card-actions {
  flex-wrap: nowrap;
  gap: 4px;
}

.agent-card-actions .q-chip {
  flex: 0 0 auto;
  margin: 0;
}

.agent-action-buttons {
  min-width: 0;
  margin-left: auto;
}

@media (max-width: 1023.98px) {
  .agent-card-horizontal {
    grid-template-columns: 84px minmax(0, 1fr);
    min-height: 0;
  }

  .agent-avatar-section {
    grid-column: 1;
    grid-row: 1;
    width: 84px;
    height: auto;
    min-height: 0;
    aspect-ratio: 1;
  }

  .agent-avatar-section > .agent-image-container,
  .agent-avatar-section > .flex {
    position: absolute;
    inset: 0;
  }

  .agent-avatar-section .agent-fallback-avatar {
    width: 54px !important;
    height: 54px !important;
  }

  .agent-info-section {
    display: contents;
  }

  .agent-identity-section {
    grid-column: 2;
    grid-row: 1;
    padding: 8px;
  }

  .agent-name {
    font-size: 1rem;
    line-height: 1.2;
  }

  .agent-job-title {
    font-size: 0.875rem;
    line-height: 1.25;
  }

  .agent-meta-row {
    display: block;
  }

  .agent-job-title,
  .agent-manager {
    width: 100%;
    max-width: 100%;
  }

  .agent-manager {
    margin-top: 2px;
    margin-left: 0;
    text-align: right;
  }

  .agent-summary {
    grid-column: 1 / -1;
    margin: 0;
    padding: 4px 12px;
  }

  .agent-summary + .agent-summary {
    padding-top: 0;
  }

  .agent-summary .text-body2 {
    min-height: 0 !important;
  }
}

@media (max-width: 599.98px) {
  .agent-page {
    padding: 8px;
  }

  .agent-page-actions {
    display: grid;
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .agent-page-actions .q-btn {
    width: 100%;
    margin: 0;
  }

  :deep(.agent-action-button .q-btn__content .block) {
    display: none;
  }

  .agent-action-button {
    min-width: 32px;
    padding-right: 4px;
    padding-left: 4px;
  }
}

</style>
