<template>
  <section v-if="canViewAgents" :class="{ 'agent-page--preview': previewAgentId !== undefined }">
    <q-banner v-if="previewAgentId !== undefined && catalogueRequests.fetchTitles?.error" role="alert" class="q-mb-md">
      {{ t('agent.tabTitles') }} · {{ apiErrorDetail(catalogueRequests.fetchTitles.error) ?? t('common.anError') }}
      <template #action><q-btn outline color="primary" :label="t('common.retry')" @click="agentStore.fetchTitles(true)" /></template>
    </q-banner>
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
    <template v-if="!previewAgentId && groupTabs.length > 1">
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

    <div v-if="!previewAgentId" class="agent-page-actions row justify-end q-mb-md q-gutter-sm">
      <q-btn
        v-if="canEdit && managedAgents.length"
        color="solaire-iris"
        icon="restart_alt"
        :label="$t('agent.harness.restartAll')"
        :loading="fleetRestarting"
        @click="restartFleet"
      />
      <q-btn v-if="canEditTeamMembers" outline color="primary" icon="group_add"
        :label="$t('team.addMembers')" :disable="currentTeamId === null" @click="showAddToTeamDialog = true" />
      <q-btn v-if="canEdit" color="primary" icon="add" :label="$t('agent.newAgent')" @click="openAgentDialog()" />
    </div>

    <!-- Agent Cards Grid -->
    <div v-if="displayedAgents.length > 0" class="agent-cards-grid">
      <div
        v-for="agent in displayedAgents"
        :key="agent.id"
        class="agent-card-wrapper"
      >
        <AgentCard :agent="agent" :avatar-url="avatarUrls[agent.id]" :initials="agentInitials(agent)"
          :profile-label="getAgentProfileLabel(agent)" :compact="previewAgentId !== undefined"
          @open-summary="field => openRichTextDialog(agent, field)">
          <q-card-actions class="agent-card-actions q-pa-sm">
            <q-chip
              v-if="agent.agent_driver === 'internal'"
              dense
              square
              color="positive"
              text-color="white"
              icon="check_circle"
              size="sm"
            >
              {{ $t('agent.harness.status.running') }}
            </q-chip>
            <q-chip
              v-else-if="isManagedRuntime(agent)"
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
                <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless agent card action. -->
                <q-btn flat
                  v-if="hasHarnessAction(agent, 'start')"
                  class="agent-action-button solaire-warning-action"
                  color="warning" icon="play_arrow" :label="$t('agent.harness.start')" :aria-label="$t('agent.harness.start')" size="sm"
                  :loading="Boolean(harnessActionLoading[agent.id])"
                  :disable="harnessLifecycleBusy(agent)"
                  @click="runHarnessAction(agent, 'start')"
                >
                  <q-tooltip>{{ $t('agent.harness.start') }}</q-tooltip>
                </q-btn>
                <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless agent card action. -->
                <q-btn flat
                  v-if="hasHarnessAction(agent, 'stop')"
                  class="agent-action-button"
                  style="color: #D1B306" icon="stop" :label="$t('agent.harness.stop')" :aria-label="$t('agent.harness.stop')" size="sm"
                  :loading="Boolean(harnessActionLoading[agent.id])"
                  :disable="harnessLifecycleBusy(agent)"
                  @click="runHarnessAction(agent, 'stop')"
                >
                  <q-tooltip>{{ $t('agent.harness.stop') }}</q-tooltip>
                </q-btn>
                <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless agent card action. -->
                <q-btn flat
                  v-if="hasHarnessAction(agent, 'restart')"
                  class="agent-action-button"
                  color="solaire-iris" icon="restart_alt" :label="harnessRestartLabel(agent)" :aria-label="harnessRestartLabel(agent)" size="sm"
                  :loading="harnessActionLoading[agent.id] === 'restart'"
                  :disable="harnessLifecycleBusy(agent)"
                  @click="runHarnessAction(agent, 'restart')"
                >
                  <q-tooltip>{{ harnessRestartLabel(agent) }}</q-tooltip>
                </q-btn>
              </template>
              <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless agent card action. -->
              <q-btn flat
                v-if="canManageAgent(agent)"
                class="agent-action-button"
                color="secondary" icon="edit" :label="$t('common.edit')" :aria-label="$t('agent.editServicetip')" size="sm"
                @click="openAgentDialog(agent)"
              >
                <q-tooltip>{{ $t('agent.editServicetip') }}</q-tooltip>
              </q-btn>
              <!-- eslint-disable-next-line galaris/ui-conventions -- Restore the borderless agent card action. -->
              <q-btn flat
                v-if="canManageAgent(agent)"
                class="agent-action-button"
                color="negative" icon="delete" :label="$t('common.delete')" :aria-label="$t('agent.deleteServicetip')" size="sm"
                @click="confirmDeleteAgent(agent)"
              >
                <q-tooltip>{{ $t('agent.deleteServicetip') }}</q-tooltip>
              </q-btn>
            </div>
          </q-card-actions>
        </AgentCard>
      </div>
    </div>

    <!-- No Data State -->
    <div v-else class="full-width row flex-center text-grey-8 q-gutter-sm q-pa-lg">
      <q-icon size="2em" name="people_outline" />
      <span>{{ agentStore.agents.length > 0 ? $t('agent.noAgentInGroup') : $t('agent.noAgent') }}</span>
    </div>
    <!-- AGENT DIALOG -->
    <TeamMembersDialog v-if="!previewAgentId" v-model="showAddToTeamDialog" :team-id="currentTeamId"
      @changed="agentStore.fetchAgents()" />

    <q-dialog v-model="showAgentDialog">
      <q-card class="agent-dialog-card galaris-dialog-card">
        <DialogHeader :title="isAgentEdit ? $t('agent.editAgent') : $t('agent.addAgent')" :close-label="$t('common.close')" />

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

        <q-card-section class="q-pt-md q-px-md galaris-dialog-body">
          <q-form
            v-if="showAgentForm"
            :id="agentFormId"
            @submit="onAgentSubmit"
            @validation-error="onAgentValidationError"
            class="q-gutter-y-md"
          >

            <!-- Model configuration for every existing agent -->
            <template v-if="isAgentEdit && agentDialogTab === 'models'">
              <q-banner class="bg-solaire-blue-light text-primary q-mb-md" dense rounded>
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
                  <q-select
                    v-model="agentForm.fallback_profile_id"
                    :options="fallbackProfileOptions"
                    :label="$t('agent.models.fallbackProfileLabel')"
                    filled emit-value map-options
                    class="q-mt-md"
                    :loading="llmProfileStore.loading"
                    :hint="$t('agent.models.fallbackProfileHint')"
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
            </template>

            <!-- General tab -->
            <div v-if="!isAgentEdit || agentDialogTab === 'general'" class="agent-general-form">
              <!-- Avatar for existing agents -->
              <template v-if="isAgentEdit">
                <div class="row q-col-gutter-x-sm items-center">
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
                      hide-bottom-space
                      accept="image/*"
                      @update:model-value="onAvatarSelected"
                      :loading="uploadingAvatar"
                      :disable="!canManageCurrentAgent || generatingCurrentAvatar"
                    >
                      <template v-slot:prepend>
                        <q-icon name="cloud_upload" />
                      </template>
                    </q-file>
                    <q-btn
                      v-if="canManageCurrentAgent && avatarGenerationAvailable"
                      class="agent-avatar-action"
                      outline
                      color="primary"
                      icon="auto_awesome"
                      :label="$t('agent.generateAvatar')"
                      :loading="generatingCurrentAvatar"
                      :disable="uploadingAvatar || avatarProfileUnsaved || generatingCurrentAvatar"
                      @click="openAvatarGenerationDialog"
                    >
                      <q-tooltip>{{ $t(avatarProfileUnsaved ? 'agent.avatarSaveFirst' : 'agent.generateAvatarHelp') }}</q-tooltip>
                    </q-btn>
                    <q-btn
                      v-if="canManageCurrentAgent && agentForm.has_avatar"
                      class="agent-avatar-action"

                      color="negative"
                      icon="delete"
                      :label="$t('agent.deleteAvatar')"
                      @click="confirmDeleteAvatar"
                      :loading="uploadingAvatar"
                      :disable="generatingCurrentAvatar"
                    />
                  </div>
                </div>
                <q-separator />
              </template>

              <q-select
                v-model="agentForm.user_id"
                :options="managerOptions"
                :label="$t('agent.managerLabel')"
                filled
                hide-bottom-space
                emit-value
                map-options
                :loading="managersLoading"
                :disable="managersLoading"
                :rules="[val => val !== null || $t('agent.managerRequiredRule')]"
                :hint="$t('agent.managerHint')"
              />

              <!-- Identity fields share one responsive grid. -->
              <div class="agent-identity-fields">
                <q-select
                  v-model="agentForm.title_id"
                  :options="titleOptions"
                  :label="$t('agent.titleField')"
                  filled
                  hide-bottom-space
                  emit-value
                  map-options
                  :rules="[val => val !== null || $t('agent.titleRequiredRule')]"
                />
                <q-input
                  v-model="agentForm.code"
                  :label="$t('agent.codeLabel')"
                  filled
                  hide-bottom-space
                  :autofocus="!isAgentEdit"
                  :readonly="isAgentEdit"
                  :rules="codeRules"
                />
                <q-input
                  v-model="agentForm.first_name"
                  :label="$t('agent.firstName')"
                  filled
                  hide-bottom-space
                  :rules="[val => !!val?.trim() || $t('agent.firstNameRule')]"
                />
                <q-input
                  v-model="agentForm.last_name"
                  :label="$t('agent.lastName')"
                  filled
                  hide-bottom-space
                />
              </div>

              <!-- Job title -->
              <q-input
                v-model="agentForm.job_title"
                :label="$t('agent.jobTitleLabel')"
                type="text"
                filled
                hide-bottom-space
                :hint="$t('agent.jobTitleHint')"
              />

              <!-- Runtime selection follows the agent's identity. -->
              <template v-if="isAgentEdit">
                <q-select
                  v-model="selectedHarnessId"
                  :options="harnessSelectionOptions"
                  :label="$t('harnesses.selection')"
                  :hint="$t('harnesses.selectionHint')"
                  filled emit-value map-options
                  hide-bottom-space
                  :loading="harnessSelectionLoading"
                  :disable="!canManageCurrentAgent || !harnessSelectionLoaded"
                />
              </template>

              <!-- Personality and job description are edited after creation. -->
              <template v-if="isAgentEdit">
                <q-banner class="bg-info text-white" dense rounded>
                  <template v-slot:avatar>
                    <q-icon name="info" />
                  </template>
                  <div class="text-caption">
                    {{ $t('agent.editInfoBanner') }}
                  </div>
                </q-banner>
              </template>
            </div>
          </q-form>

          <component
            v-if="isAgentEdit && activeDriverTab && agentDialogTab === activeDriverTab.name"
            :is="activeDriverTab.component"
            :agent-id="Number(agentForm.id)"
            @updated="showAgentDialog = false"
          />

          <!-- MCP tab for every existing agent driver -->
          <AgentMcpPanel v-if="isAgentEdit && agentDialogTab === 'mcp' && canManageMcp" :agent="agentForm" :can-manage="canManageMcp" />
        </q-card-section>
        <template v-if="showAgentForm">
          <q-separator />
          <q-card-actions align="right" class="galaris-dialog-actions q-pa-md">
            <q-btn v-close-popup outline color="primary" :label="$t('common.cancel')" />
            <q-btn
              v-if="canSaveAgent"
              :form="agentFormId"
              type="submit"
              color="primary"
              :label="$t(!isAgentEdit ? 'common.create' : agentDialogTab === 'models' ? 'common.save' : 'common.edit')"
              :loading="agentStore.loading || harnessChangePending"
            />
          </q-card-actions>
        </template>
      </q-card>
    </q-dialog>

    <AvatarGenerationDialog
      v-model="showAvatarGenerationDialog"
      :loading="generatingCurrentAvatar"
      :error="avatarGenerationError"
      @generate="generateAvatar"
    />

    <q-dialog data-confirmation
      v-model="showHarnessChangeConfirm"
      @hide="settleHarnessChangeConfirmation(false)"
    >
      <q-card class="galaris-dialog-card" style="width: 560px; max-width: 92vw">
        <DialogHeader :title="$t('agent.harness.changeConfirmTitle')" :close-label="$t('common.close')" :close-popup="false" @close="settleHarnessChangeConfirmation(false)" />
        <q-card-section class="galaris-dialog-body">
          <q-banner rounded class="bg-warning text-dark">
            <template v-slot:avatar><q-icon name="warning" /></template>
            {{ $t('agent.harness.changeConfirmMessage') }}
          </q-banner>
          <p class="q-mb-none q-mt-md">{{ $t('agent.harness.changeConfirmNextStep') }}</p>
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn outline

            color="grey-7"
            :label="$t('common.cancel')"
            @click="settleHarnessChangeConfirmation(false)"
          />
          <q-btn data-autofocus
            color="negative"
            icon="delete_forever"
            :label="$t('agent.harness.changeConfirmAction')"
            @click="settleHarnessChangeConfirmation(true)"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog data-confirmation
      v-model="showPausedHarnessTasksConfirm"
      @hide="settlePausedHarnessTasksConfirmation(false)"
    >
      <q-card class="galaris-dialog-card" style="width: 620px; max-width: 92vw">
        <DialogHeader :title="$t('agent.harness.blockingTasksTitle')" :close-label="$t('common.close')" :close-popup="false" @close="settlePausedHarnessTasksConfirmation(false)" />
        <q-card-section class="galaris-dialog-body">
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
            class="bg-solaire-orange-light text-dark q-mt-md"
          >
            <template v-slot:avatar><q-icon name="schedule" color="warning" /></template>
            {{ $t('agent.harness.activeTasksMessage', { count: activeHarnessTaskCount }) }}
          </q-banner>
          <q-list v-if="activeHarnessTasks.length > 0" bordered separator class="q-mt-md">
            <q-item
              v-for="task in activeHarnessTasks"
              :key="task.id"
              :clickable="canViewBlockingTasks"
              :role="canViewBlockingTasks ? 'button' : undefined"
              @click="canViewBlockingTasks && (blockingTaskId = task.id)"
            >
              <q-item-section>
                <q-item-label>{{ task.label }}</q-item-label>
                <q-item-label caption>{{ `galaris://task/${task.id}` }}</q-item-label>
              </q-item-section>
              <q-item-section v-if="canViewBlockingTasks" side><q-icon name="visibility" /></q-item-section>
            </q-item>
          </q-list>
          <ResourceDetailDialog v-if="blockingTaskTarget && canViewBlockingTasks" :target="blockingTaskTarget"
            @close="blockingTaskId = null" />
        </q-card-section>
        <q-separator />
        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn outline

            color="grey-7"
            :label="$t('common.cancel')"
            @click="settlePausedHarnessTasksConfirmation(false)"
          />
          <q-btn data-autofocus
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
      <q-card class="galaris-dialog-card" style="min-width: 1000px; max-width: 1400px; width: 90vw; max-height: 92vh">
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

        <q-card-section class="q-pa-md galaris-dialog-body" style="max-height: 75vh; overflow: auto">
          <RichTextEditor
            toolbar-mode="simple"
            v-model="richTextContent"
            min-height="500px"
            max-height="70vh"
          />
        </q-card-section>

        <q-card-actions align="right" class="q-pa-md galaris-dialog-actions">
          <q-btn outline :label="$t('common.cancel')" color="grey"  v-close-popup />
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
      v-model:show-harness-logs="showHarnessLogsDialog"
      v-model:show-delete="showDeleteDialog"
      :can-edit="canEdit"
      :harness-logs-agent-name="harnessLogsAgentName"
      :harness-logs="harnessLogs"
      :harness-logs-loading="harnessLogsLoading"
      :harness-log-color="harnessLogColor"
      :delete-message="deleteMessage"
      @close-harness-logs="closeHarnessLogs"
      @refresh-harness-logs="fetchHarnessLogs"
      @confirm-delete="confirmDelete"
    />
  </section>
</template>

<script setup lang="ts">
import { DialogHeader, ResourceDetailDialog, useResourceDetail } from '@/core/util'
import { showConfirmationDialog } from '@/core/util'
import { ref, shallowRef, onUnmounted, reactive, computed, useId, watch, type Component } from 'vue'
import { useAgentStore, agentService } from '@/app/agent/facade'
import type { Agent, AgentManagerInfo } from '@/app/agent/contracts'
import { AgentCard, getAgentDriverTab, titleLabel } from '@/app/agent/interface'
import { harnessService } from '@/app/harnesses'
import type {
  HarnessCatalogEntry,
  HarnessTaskBlocker,
} from '@/app/harnesses'
import { useLLMProviderStore } from '@/app/llm/facade'
import { llmProviderService } from '@/app/llm/facade'
import type { LLMModelInfo } from '@/app/llm/contracts'
import { useParamsStore } from '@/core/params/facade'
import { useLLMProfileStore } from '@/app/llm/facade'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { apiErrorDetail, sessionGeneration } from '@/core/api'
import { RichTextEditor } from '@/core/util'
import { storeRequests } from '@/core/util/facade'
import { AgentAuxiliaryDialogs, AvatarGenerationDialog, AgentMcpPanel } from '@/app/agent'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { TeamMembersDialog } from '@/core/team'
import { useAgentHarnessRuntime } from '../composables/useAgentHarnessRuntime'

const props = defineProps<{ previewAgent?: Agent; requestedAgentId?: number }>()
const previewAgentId = computed(() => props.previewAgent?.id)
const emit = defineEmits<{ deleted: [] }>()
const $q = useQuasar()
const { t } = useI18n()
const agentStore = useAgentStore()
const catalogueRequests = storeRequests(agentStore)
const previewRecord = shallowRef(props.previewAgent)
const agents = computed(() => previewAgentId.value === undefined ? agentStore.agents : previewRecord.value ? [previewRecord.value] : [])

function applyPreviewAgent(updated: Agent): void {
  if (!pageDisposed && updated.id === previewAgentId.value) previewRecord.value = updated
}

async function refreshVisibleAgents(): Promise<void> {
  const id = previewAgentId.value
  if (id === undefined) {
    await agentStore.fetchAgents()
    return
  }
  const session = sessionGeneration()
  try {
    const { data } = await agentService.getAgent(id)
    if (session === sessionGeneration()) applyPreviewAgent(data)
  } catch (error) {
    if (!pageDisposed && session === sessionGeneration()) console.error('Failed to refresh agent details:', error)
  }
}

const llmProviderStore = useLLMProviderStore()
const paramsStore = useParamsStore()
const llmProfileStore = useLLMProfileStore()
const privilegeStore = usePrivilegeStore()
const canViewAgents = computed(() => privilegeStore.hasPrivilege('AGENT_ACCESS') || privilegeStore.hasPrivilege('AGENT_EDIT'))
const canViewTeams = computed(() => privilegeStore.hasPrivilege('TEAM_ACCESS'))
const canEditTeamMembers = computed(() => canViewTeams.value && privilegeStore.hasPrivilege('TEAM_MEMBERS_EDIT'))
const showAddToTeamDialog = ref(false)
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.AGENT_EDIT))
const canManageAllAgents = computed(() => (
  privilegeStore.hasPrivilege(privileges.AGENT_MANAGE_ALL)
))
const canManageAgent = (agent: Agent): boolean => (
  canEdit.value && (agent.is_owner || canManageAllAgents.value)
)
const {
  isManagedRuntime, managedAgents, harnessManagerUnavailable, harnessState, harnessStatusColor, harnessStatusIcon,
  harnessStatusLabel, hasHarnessCapability, hasHarnessAction, harnessRestartLabel, harnessLifecycleBusy,
  harnessActionLoading, runHarnessAction, restartFleet, fleetRestarting, markHarnessSelectionPending,
  fetchHarnessStatus, showHarnessLogsDialog, harnessLogs, harnessLogsLoading, harnessLogsAgentName,
  fetchHarnessLogs, openHarnessLogs, closeHarnessLogs, harnessLogColor,
} = useAgentHarnessRuntime({
  agents, previewAgentId, canViewAgents, canEdit, canManageAgent,
  loadCatalogue: () => previewAgentId.value === undefined
    ? Promise.all([agentStore.fetchAgents(), agentStore.fetchTitles(), agentStore.fetchGroups()])
    : agentStore.fetchTitles(),
})
const canViewLlms = computed(() => (
  privilegeStore.hasAnyPrivilege([privileges.LLM_MODEL_ACCESS, privileges.LLM_MODEL_EDIT, privileges.LLM_PROFILE_ACCESS, privileges.LLM_PROFILE_EDIT])
))
const canViewParams = computed(() => (
  privilegeStore.hasPrivilege(privileges.LLM_PROFILE_ACCESS)
  || privilegeStore.hasPrivilege(privileges.LLM_PROFILE_EDIT)
))

const activeGroupTab = ref('')
const currentTeamId = computed(() => agentStore.groups.find(group => String(group.id) === activeGroupTab.value)?.id ?? null)
const agentDialogTab = ref('general')
const agentFormId = useId()
const showAgentDialog = ref(false)
let agentDialogGeneration = 0
let modelOptionsGeneration = -1
const isCurrentAgentDialog = (generation: number): boolean => (
  !pageDisposed && showAgentDialog.value && generation === agentDialogGeneration
)

const showRichTextDialog = ref(false)
const showDeleteDialog = ref(false)
const isAgentEdit = ref(false)
const showAgentForm = computed(() => !isAgentEdit.value || ['general', 'models'].includes(agentDialogTab.value))
const itemToDelete = ref<Agent | null>(null)

// Avatar state
const avatarFile = ref<File | null>(null)
const uploadingAvatar = ref(false)
const avatarGenerationAvailable = ref(false)
const showAvatarGenerationDialog = ref(false)
const avatarGenerationError = ref('')
const generatingAvatarIds = reactive(new Set<number>())
const generatingCurrentAvatar = computed(() => agentForm.id !== null && generatingAvatarIds.has(agentForm.id))
const avatarProfileUnsaved = computed(() => {
  const saved = agents.value.find(agent => agent.id === agentForm.id)
  return !saved || saved.title_id !== agentForm.title_id
    || saved.first_name !== agentForm.first_name || saved.last_name !== agentForm.last_name
    || (saved.job_title ?? '') !== agentForm.job_title
})
const avatarUrls = reactive<Record<number, string>>({})
const avatarVersions: Record<number, string> = {}
let avatarLoad: AbortController | undefined

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
  avatarLoad?.abort()
  const { signal } = avatarLoad = new AbortController()
  const portraits = agents.value.filter(agent => agent.has_avatar)
  const ids = new Set(portraits.map(agent => agent.id))
  for (const [id, url] of Object.entries(avatarUrls)) {
    if (ids.has(Number(id))) continue
    URL.revokeObjectURL(url)
    delete avatarUrls[Number(id)]
    delete avatarVersions[Number(id)]
  }
  await Promise.all(portraits.map(async agent => {
    const updatedAt = agent.updated_at ?? ''
    if (avatarUrls[agent.id] && avatarVersions[agent.id] === updatedAt) return
    if (avatarUrls[agent.id]) {
      URL.revokeObjectURL(avatarUrls[agent.id])
      delete avatarUrls[agent.id]
    }
    try {
      const url = await agentService.getAvatarBlobUrl(agent.id, signal, updatedAt)
      const current = agents.value.find(item => item.id === agent.id)
      if (signal.aborted || !current?.has_avatar || (current.updated_at ?? '') !== updatedAt) {
        URL.revokeObjectURL(url)
        return
      }
      if (avatarUrls[agent.id]) URL.revokeObjectURL(avatarUrls[agent.id])
      avatarUrls[agent.id] = url
      avatarVersions[agent.id] = updatedAt
    } catch (error) {
      if (!signal.aborted) console.error(`Failed to load avatar for agent ${agent.id}:`, error)
    }
  }))
}

// Rich text editor state
const richTextAgent = ref<Agent | null>(null)
const richTextField = ref<'personality' | 'job_description'>('personality') // 'personality' or 'job_description'
const richTextContent = ref('')

const titleOptions = computed(() => {
  return agentStore.titles.map(title => ({
    label: `${titleLabel(title.label, t)} (${title.gender === 'M' ? 'M' : 'F'})`,
    value: title.id
  }))
})

const managers = ref<AgentManagerInfo[]>([])
const managersLoading = ref(false)
const harnessCatalog = ref<HarnessCatalogEntry[]>([])
const selectedHarnessId = ref<string | null>(null)
const initialHarnessId = ref<string | null>(null)
const harnessSelectionLoading = ref(false)
const harnessSelectionLoaded = ref(false)
const showHarnessChangeConfirm = ref(false)
let harnessChangeConfirmation: ((confirmed: boolean) => void) | null = null
const harnessChangePending = ref(false)
const showPausedHarnessTasksConfirm = ref(false)
const { id: blockingTaskId, target: blockingTaskTarget } = useResourceDetail('task')
const canViewBlockingTasks = computed(() => privilegeStore.hasPrivilege(privileges.TASK_ACCESS))
const pausedHarnessTasks = ref<HarnessTaskBlocker[]>([])
const activeHarnessTasks = ref<HarnessTaskBlocker[]>([])
const activeHarnessTaskCount = ref(0)
let pausedHarnessTasksConfirmation: ((confirmed: boolean) => void) | null = null
let pageDisposed = false

const managerOptions = computed(() => {
  const options = [...managers.value]
  const currentManager = editedAgent.value?.user
  if (currentManager && !options.some(manager => manager.id === currentManager.id)) {
    options.push(currentManager)
  }
  return options.map(manager => ({
    label: manager.display_name
      ? `${manager.display_name} — ${manager.email}`
      : manager.email,
    value: manager.id,
  }))
})

const harnessSelectionOptions = computed(() => [
  { label: t('harnesses.internal'), value: null },
  ...harnessCatalog.value.map(harness => ({
    label: harness.provider_code === 'openai_messages'
      ? `${harness.name} · API`
      : harness.name,
    value: harness.id,
  })),
])

async function loadHarnessSelection(agent: Agent, generation: number): Promise<void> {
  harnessSelectionLoading.value = true
  harnessSelectionLoaded.value = false
  try {
    const [catalogResponse, selectionResponse] = await Promise.all([
      harnessService.catalog(true),
      harnessService.selection(agent.id),
    ])
    if (!isCurrentAgentDialog(generation)) return
    harnessCatalog.value = catalogResponse.data
    selectedHarnessId.value = selectionResponse.data.harness_id
    initialHarnessId.value = selectionResponse.data.harness_id
    harnessSelectionLoaded.value = true
  } catch {
    if (!isCurrentAgentDialog(generation)) return
    harnessCatalog.value = []
    selectedHarnessId.value = null
    initialHarnessId.value = null
    $q.notify({ type: 'negative', message: t('harnesses.catalog.loadError') })
  } finally {
    if (isCurrentAgentDialog(generation)) harnessSelectionLoading.value = false
  }
}

const fetchManagers = async (generation: number): Promise<void> => {
  if (!canEdit.value) return
  managersLoading.value = true
  try {
    const { data } = await agentService.getManagers()
    if (!isCurrentAgentDialog(generation)) return
    managers.value = data
    if (!isAgentEdit.value && agentForm.user_id === null) {
      agentForm.user_id = data.find(manager => manager.is_current_user)?.id ?? null
    }
  } catch {
    if (isCurrentAgentDialog(generation)) {
      $q.notify({ type: 'negative', message: t('common.anError') })
    }
  } finally {
    if (isCurrentAgentDialog(generation)) managersLoading.value = false
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
  blockingTaskId.value = null
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
  if (previewAgentId.value !== undefined) return agents.value
  const list = agentStore.sortedAgents
  if (activeGroupTab.value === 'none') {
    return list.filter(agent => !agent.team_ids?.length)
  }
  const gid = Number(activeGroupTab.value)
  return list.filter(agent => agent.team_ids?.includes(gid))
})

// Model configuration lives in shared profiles: the agent model tab exposes a
// primary and optional fallback profile pickers, plus the dedicated voice selection.
const profileOptions = computed(() =>
  [{
    label: t('agent.models.useCurrentProfile', {
      profile: llmProfileStore.currentProfile?.label || t('agent.models.profileNotConfigured'),
    }),
    value: null,
  }, ...llmProfileStore.profiles.map(profile => ({ label: profile.label, value: profile.id }))]
)
const fallbackProfileOptions = computed(() => [
  {
    label: llmProfileStore.defaultFallbackProfileId == null
      ? t('agent.models.noFallbackProfile')
      : t('agent.models.useDefaultFallbackProfile', {
          profile: llmProfileStore.getProfileById(llmProfileStore.defaultFallbackProfileId)?.label,
        }),
    value: null,
  },
  ...llmProfileStore.profiles.map(profile => ({ label: profile.label, value: profile.id })),
])

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

async function loadNativeVoiceResources(generation: number): Promise<void> {
  if (!privilegeStore.hasAnyPrivilege([privileges.LLM_PROVIDER_ACCESS, privileges.LLM_PROVIDER_EDIT])) return
  const providerIds = [...new Set(
    llmProviderStore.llms
      .filter(llm => llm.service_capabilities.includes('realtime_conversation'))
      .map(llm => llm.llm_provider_id),
  )]
  if (providerIds.length === 0) {
    if (isCurrentAgentDialog(generation)) nativeVoiceResources.value = {}
    return
  }

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
  if (isCurrentAgentDialog(generation)) nativeVoiceResources.value = Object.fromEntries(entries)
}

async function loadModelOptions(generation: number): Promise<void> {
  if (!canViewLlms.value || modelOptionsGeneration === generation) return
  modelOptionsGeneration = generation
  loadingNativeVoices.value = true
  const results = await Promise.allSettled([
    llmProviderStore.fetchLLMs().then(() => {
      if (isCurrentAgentDialog(generation)) return loadNativeVoiceResources(generation)
    }),
    ...(canViewParams.value ? [llmProfileStore.fetchProfiles()] : []),
  ])
  if (!isCurrentAgentDialog(generation)) return
  loadingNativeVoices.value = false
  if (results.some(result => result.status === 'rejected')) {
    modelOptionsGeneration = -1
    $q.notify({ type: 'negative', message: t('common.anError') })
  }
}

const agentForm = reactive<{
  id: number | null; user_id: number | null; title_id: number | null;
  code: string; first_name: string; last_name: string; job_title: string; agent_driver: string;
  has_avatar: boolean; profile_id: number | null; fallback_profile_id: number | null; voice_selection: string;
}>({
  id: null,
  user_id: null,
  title_id: null,
  code: '',
  first_name: '',
  last_name: '',
  job_title: '',
  agent_driver: 'internal',
  has_avatar: false,
  profile_id: null,
  fallback_profile_id: null,
  voice_selection: NO_VOICE,
})

const editedAgent = computed(() => (
  agentForm.id === null
    ? null
    : agents.value.find(agent => agent.id === agentForm.id) ?? null
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

const deleteMessage = computed(() => t('agent.confirmDeleteAgent', {
  name: `${itemToDelete.value?.first_name ?? ''} ${itemToDelete.value?.last_name ?? ''}`.trim(),
}))

const resetAgentForm = () => {
  agentForm.id = null
  agentForm.user_id = managers.value.find(manager => manager.is_current_user)?.id ?? null
  agentForm.title_id = null
  agentForm.code = ''
  agentForm.first_name = ''
  agentForm.last_name = ''
  agentForm.job_title = ''
  agentForm.agent_driver = 'internal'
  agentForm.has_avatar = false
  agentForm.profile_id = null
  agentForm.fallback_profile_id = null
  agentForm.voice_selection = NO_VOICE
  harnessCatalog.value = []
  selectedHarnessId.value = null
  initialHarnessId.value = null
  harnessSelectionLoaded.value = false
  pausedHarnessTasks.value = []
  activeHarnessTasks.value = []
  activeHarnessTaskCount.value = 0
}

const openAgentDialog = (agent: Agent | null = null) => {
  const generation = ++agentDialogGeneration
  resetAgentForm()
  agentDialogTab.value = 'general'
  if (agent) {
    isAgentEdit.value = true
    Object.assign(agentForm, {
      id: agent.id,
      user_id: agent.user_id,
      title_id: agent.title_id,
      code: agent.code || '',
      first_name: agent.first_name,
      last_name: agent.last_name,
      job_title: agent.job_title || '',
      agent_driver: agent.agent_driver || 'internal',
      has_avatar: agent.has_avatar,
      profile_id: agent.profile_id ?? null,
      fallback_profile_id: agent.fallback_profile_id ?? null,
      voice_selection: voiceSelectionForAgent(agent),
    })
  } else {
    isAgentEdit.value = false
  }
  avatarFile.value = null
  avatarGenerationAvailable.value = false
  showAgentDialog.value = true
  // Existing portraits already load with the catalogue; no request blocks opening.
  void fetchManagers(generation)
  if (agent) void loadHarnessSelection(agent, generation)
  if (agent && canManageAgent(agent)) void loadAvatarGenerationAvailability(generation)
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

    const updated = await agentStore.updateAgent(richTextAgent.value.id, data)
    applyPreviewAgent(updated)
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

const confirmDeleteAgent = (agent: Agent) => {
  itemToDelete.value = agent
  showDeleteDialog.value = true
}

const confirmDelete = async () => {
  const agent = itemToDelete.value
  if (!agent || !canManageAgent(agent)) return
  try {
    await agentStore.deleteAgent(agent.id)
    if (agent.id === previewAgentId.value) emit('deleted')
    $q.notify({ type: 'positive', message: t('agent.notify.agentDeleted') })
  } catch {
    $q.notify({ type: 'negative', message: t('agent.notify.cannotDeleteAgent') })
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
      fallback_profile_id: agentForm.fallback_profile_id,
      voice: agentForm.voice_selection === NO_VOICE ? null : agentForm.voice_selection,
    }

    if (isAgentEdit.value && agentForm.id !== null) {
      const updated = await agentStore.updateAgent(agentForm.id, data)
      applyPreviewAgent(updated)
      if (harnessChanged) {
        selectedHarnessId.value === null
          ? await harnessService.selectInternal(agentForm.id)
          : await harnessService.install(agentForm.id, selectedHarnessId.value)
        // The status endpoint owns lifecycle/action projection; do not reconstruct it
        // from the selection response (which has no runtime observation).
        markHarnessSelectionPending(agentForm.id)
        await refreshVisibleAgents()
        const savedAgent = agents.value.find(agent => agent.id === agentForm.id)
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
    const validationDetail = isAxiosError<{ detail?: unknown }>(error) && error.response?.status === 400
      ? error.response.data?.detail
      : null
    const message = typeof validationDetail === 'string'
      ? validationDetail.trim().slice(0, 2000)
      : apiErrorDetail(error)

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

const getAgentProfileLabel = (agent: Agent): string => (
  agent.profile?.label
  ?? llmProfileStore.currentProfile?.label
  ?? t('agent.models.profileNotConfigured')
)

// Avatar functions
const loadAvatarGenerationAvailability = async (generation: number) => {
  try {
    const response = await agentService.getAvatarGenerationAvailability()
    if (!pageDisposed && generation === agentDialogGeneration) {
      avatarGenerationAvailable.value = response.data.available
    }
  } catch {
    if (!pageDisposed && generation === agentDialogGeneration) avatarGenerationAvailable.value = false
  }
}

const openAvatarGenerationDialog = () => {
  avatarGenerationError.value = ''
  showAvatarGenerationDialog.value = true
}

const generateAvatar = async (instructions: string) => {
  const id = agentForm.id
  if (id === null || !canManageCurrentAgent.value || !avatarGenerationAvailable.value
    || generatingAvatarIds.has(id) || uploadingAvatar.value || avatarProfileUnsaved.value) return
  const generation = agentDialogGeneration
  avatarGenerationError.value = ''
  generatingAvatarIds.add(id)
  try {
    await agentService.generateAvatar(id, instructions)
    if (pageDisposed) return
    if (showAgentDialog.value && agentForm.id === id) agentForm.has_avatar = true
    if (generation === agentDialogGeneration) showAvatarGenerationDialog.value = false
    await refreshVisibleAgents()
    $q.notify({ type: 'positive', message: t('agent.notify.avatarGenerated') })
  } catch (error) {
    if (pageDisposed) return
    const message = apiErrorDetail(error) || t('agent.notify.avatarGenerationError')
    if (generation === agentDialogGeneration && showAvatarGenerationDialog.value) avatarGenerationError.value = message
    else $q.notify({ type: 'negative', message })
    if (generation === agentDialogGeneration) void loadAvatarGenerationAvailability(generation)
  } finally {
    generatingAvatarIds.delete(id)
  }
}

const onAvatarSelected = async (file: File | null) => {
  if (!canManageCurrentAgent.value || !file || !agentForm.id || generatingCurrentAvatar.value) return

  uploadingAvatar.value = true
  try {
    await agentService.uploadAvatar(agentForm.id, file)
    agentForm.has_avatar = true
    // Load the new avatar
    const url = await agentService.getAvatarBlobUrl(agentForm.id)
    if (pageDisposed) URL.revokeObjectURL(url)
    else {
      if (avatarUrls[agentForm.id]) URL.revokeObjectURL(avatarUrls[agentForm.id])
      avatarUrls[agentForm.id] = url
    }
    $q.notify({ type: 'positive', message: t('agent.notify.avatarUploaded') })
    // Refresh the agent list to update has_avatar status
    await refreshVisibleAgents()
  } catch (error) {
    $q.notify({ type: 'negative', message: t('agent.notify.avatarUploadError') })
  } finally {
    uploadingAvatar.value = false
    avatarFile.value = null
  }
}

const confirmDeleteAvatar = async () => {
  if (!canManageCurrentAgent.value || generatingCurrentAvatar.value) return
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
      await refreshVisibleAgents()
    } catch (error) {
      $q.notify({ type: 'negative', message: t('agent.notify.avatarDeleteError') })
    } finally {
      uploadingAvatar.value = false
    }
  })
}

watch(agents, loadAvatars, { immediate: true })

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

// Refresh tab-specific options only when their tab opens.
watch(agentDialogTab, (tab) => {
  if (tab === 'models' && showAgentDialog.value) void loadModelOptions(agentDialogGeneration)
})

watch(showAgentDialog, open => {
  if (!open) {
    showAvatarGenerationDialog.value = false
    agentDialogGeneration++
    managersLoading.value = false
    harnessSelectionLoading.value = false
    loadingNativeVoices.value = false
  }
}, { flush: 'sync' })

watch(() => agentForm.agent_driver, () => {
  const genericTabs = ['general', 'models', 'mcp']
  if (!genericTabs.includes(agentDialogTab.value)
    && agentDialogTab.value !== activeDriverTab.value?.name) {
    agentDialogTab.value = 'general'
  }
})

watch(() => props.requestedAgentId, async id => {
  if (previewAgentId.value || id === undefined) return
  await agentStore.fetchAgents()
  if (pageDisposed || id !== props.requestedAgentId) return
  const agent = agentStore.agents.find(item => item.id === id)
  if (agent) openAgentDialog(agent)
  else $q.notify({ type: 'negative', message: t('richEditor.unavailable') })
}, { immediate: true })
onUnmounted(() => {
  pageDisposed = true
  avatarLoad?.abort()
  for (const url of Object.values(avatarUrls)) URL.revokeObjectURL(url)
})
</script>

<style scoped>
.agent-page--preview .agent-cards-grid { display: block; }

.agent-dialog-card {
  width: 800px;
  max-width: 90vw;
}

.agent-general-form,
.agent-identity-fields {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.agent-identity-fields {
  grid-template-columns: repeat(2, minmax(0, 1fr));
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
  .agent-identity-fields {
    grid-template-columns: minmax(0, 1fr);
  }

}

@media (max-width: 599.98px) {
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
