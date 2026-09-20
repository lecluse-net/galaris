<template>
  <q-page class="q-pa-md">
    <PageHeader help-key="memory" :help-text="$t('contextHelpPages.memory')" :icon="navigationIcon('memory')" :title="t('nav.memory')" />

    <q-tabs
      v-model="activeTab"
      class="text-primary"
      active-color="primary"
      indicator-color="primary"
      align="left"
    >
      <q-tab name="search" icon="manage_search" :label="t('memory.tabs.search')" />
      <q-tab name="list" icon="view_list" :label="t('memory.tabs.list')" />
      <q-tab name="graph" icon="hub" :label="t('memory.tabs.graph')" />
    </q-tabs>
    <q-separator />

    <q-card v-if="activeTab !== 'search'" flat bordered class="memory-filter-block q-my-md">
      <q-card-section class="memory-filter-block__row memory-filter-block__row--primary row q-col-gutter-md items-center">
        <div class="col-12 col-md-6">
          <AgentSelect
            v-model="store.selectedAgentId"
            class="memory-agent-select"
            :options="agentOptions"
            behavior="menu"
            emit-value
            map-options
            outlined
            dense
            options-dense
            :label="t('memory.agent')"
            :loading="agentStore.loading"
          />
        </div>
        <div v-if="activeTab === 'graph'" class="col-12 col-md-6 memory-filter-block__timeline">
          <div class="memory-filter-block__slider">
            <q-slider
              v-model="graphTimeRangeDraftIndex"
              :min="0"
              :max="GRAPH_TIME_RANGE_OPTIONS.length - 1"
              :step="1"
              markers
              snap
              label
              label-always
              :label-value="graphTimeRangeLabel"
              :title="t('memory.graph.timeRange')"
              :aria-label="t('memory.graph.timeRange')"
              @change="applyGraphTimeRange"
            />
          </div>
        </div>
      </q-card-section>

      <q-card-section
        class="memory-filter-block__row memory-filter-block__row--secondary"
      >
        <div class="memory-filter-block__field">
          <q-input
            v-model="store.query"
            outlined
            dense
            clearable
            debounce="350"
            :placeholder="t('memory.search')"
            @update:model-value="scheduleSearch"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </div>
        <div class="memory-filter-block__field">
          <q-select
            v-model="store.selectedTypes"
            :options="typeOptions"
            behavior="menu"
            outlined
            dense
            multiple
            emit-value
            map-options
            options-dense
            :label="t('memory.type')"
            @update:model-value="() => searchSafely(true)"
          />
        </div>
        <div class="memory-filter-block__field">
          <q-select
            v-model="store.selectedTopicItemId"
            :options="topicFilterOptions"
            behavior="menu"
            outlined
            dense
            clearable
            emit-value
            map-options
            options-dense
            :loading="filterOptionsLoading"
            :label="t('memory.topicFilter')"
            @update:model-value="() => searchSafely(true)"
          />
        </div>
        <div class="memory-filter-block__field">
          <q-select
            v-model="store.selectedContactItemId"
            :options="contactFilterOptions"
            behavior="menu"
            outlined
            dense
            clearable
            emit-value
            map-options
            options-dense
            :loading="filterOptionsLoading"
            :label="t('memory.contactFilter')"
            @update:model-value="() => searchSafely(true)"
          />
        </div>
      </q-card-section>
    </q-card>

    <q-tab-panels v-model="activeTab" animated class="bg-transparent">
      <q-tab-panel name="search" class="q-pa-none">
        <MemorySearchTester
          ref="memorySearchTester"
          :agent-id="store.selectedAgentId"
          @open="openDetail"
        >
          <template #agent>
            <AgentSelect
              v-model="store.selectedAgentId"
              :options="agentOptions"
              behavior="menu"
              outlined
              dense
              options-dense
              :label="t('memory.agent')"
              :loading="agentStore.loading"
            />
          </template>
        </MemorySearchTester>
      </q-tab-panel>

      <q-tab-panel name="list" class="q-pa-none">
        <section>
        <div class="row justify-end items-center q-gutter-md q-mb-md">
          <div class="row q-gutter-sm">
            <q-btn
              v-if="canEdit"
              color="primary"
              icon="add"
              :label="t('memory.new')"
              :disable="store.selectedAgentId === null"
              @click="openCreate"
            />
          </div>
        </div>

        <q-banner v-if="store.error" rounded class="bg-red-1 text-negative q-mb-md">
          {{ t('memory.loadError') }}
          <template #action>
            <q-btn flat color="negative" :label="t('memory.retry')" @click="searchSafely()" />
          </template>
        </q-banner>

        <q-table
          flat
          bordered
          :row-key="row => row.item.id"
          :rows="store.hits"
          :columns="itemColumns"
          :loading="store.loading"
          :grid="$q.screen.lt.md"
          class="memory-list-table"
          :pagination="{
            page: store.page,
            rowsPerPage: store.rowsPerPage,
            rowsNumber: store.total,
            sortBy: store.sortBy,
            descending: store.sortDescending,
          }"
          :rows-per-page-options="store.rowsPerPageOptions"
          :no-data-label="store.selectedAgentId === null ? t('memory.selectAgent') : t('memory.empty')"
          @row-click="(_, hit) => hit.item.node_kind !== 'folder' && openDetail(hit.item.id)"
          @request="onTableRequest"
        >
          <template #body-cell-title="props">
            <q-td :props="props">
              <div class="row items-center q-gutter-xs">
                <DocumentIcon v-if="props.row.item.node_kind === 'document'" :document-id="props.row.item.id" :title="props.row.item.title" />
                <span class="text-weight-medium">{{ props.row.item.title }}</span>
                <q-chip
                  v-if="props.row.item.node_kind === 'document'"
                  dense
                  color="orange-1"
                  text-color="orange-10"
                  icon="description"
                >
                  {{ t('memory.kinds.document') }}
                </q-chip>
                <q-chip v-if="props.row.item.source_managed" dense color="blue-1" text-color="primary" icon="sync_lock">
                  {{ t('memory.generated') }}
                </q-chip>
                <q-chip v-else-if="props.row.item.deletion_protected" dense color="purple-1" text-color="purple-10" icon="lock">
                  {{ t('memory.protected') }}
                </q-chip>
                <q-chip v-if="props.row.item.old_at" dense color="grey-4" text-color="grey-9" icon="history">
                  {{ t('memory.findings.old') }}
                </q-chip>
                <q-chip
                  v-for="finding in store.findingsFor(props.row.item.id)"
                  :key="finding.id"
                  clickable
                  dense
                  :color="findingColor(finding.kind)"
                  text-color="white"
                  :icon="findingIcon(finding.kind)"
                  @click.stop="openFinding(finding)"
                >
                  {{ findingLabel(finding) }}
                </q-chip>
              </div>
              <div class="memory-excerpt text-caption text-grey-7 ellipsis-2-lines">
                {{ props.row.excerpt }}
              </div>
            </q-td>
          </template>
          <template #body-cell-memory_type="props">
            <q-td :props="props">
              <q-chip dense outline :color="typeColor(props.row.item.memory_type)">
                {{ t(`memory.types.${props.row.item.memory_type}`) }}
              </q-chip>
            </q-td>
          </template>
          <template #body-cell-visibility="props">
            <q-td :props="props">
              <q-icon :name="visibilityIcon(props.row.item.visibility)" class="q-mr-xs" />
              {{ t(`memory.visibilities.${props.row.item.visibility}`) }}
            </q-td>
          </template>
          <template #body-cell-owner="props">
            <q-td :props="props">{{ agentLabel(props.row.item.owner_agent_id) }}</q-td>
          </template>
          <template #body-cell-access_count="props">
            <q-td :props="props">
              {{ formatNumber(props.row.item.access_count) }}
            </q-td>
          </template>
          <template #body-cell-last_accessed_at="props">
            <q-td :props="props">
              {{ formatDate(props.row.item.last_accessed_at) }}
            </q-td>
          </template>
          <template #body-cell-updated_at="props">
            <q-td :props="props">{{ formatDate(props.row.item.updated_at || props.row.item.created_at) }}</q-td>
          </template>
          <template #body-cell-actions="props">
            <q-td :props="props" class="q-gutter-xs">
              <MemoryAttachmentButton v-if="props.row.item.node_kind === 'attachment'"
                :item-id="props.row.item.id" :agent-id="store.selectedAgentId" icon-only />
              <q-btn
                v-if="props.row.item.node_kind !== 'folder' && canEdit && props.row.item.access.can_write"
                flat
                round
                dense
                icon="edit"
                color="primary"
                :aria-label="t('memory.edit')"
                @click.stop="openEdit(props.row.item.id)"
              >
                <q-tooltip>{{ t('memory.edit') }}</q-tooltip>
              </q-btn>
            </q-td>
          </template>
          <template #item="props">
            <div class="q-table__grid-item col-12 memory-list-grid-item">
              <q-card
                flat
                bordered
                class="memory-mobile-card"
                :class="{ 'cursor-pointer': props.row.item.node_kind !== 'folder' }"
                :role="props.row.item.node_kind !== 'folder' ? 'button' : undefined"
                :tabindex="props.row.item.node_kind !== 'folder' ? 0 : undefined"
                @click="props.row.item.node_kind !== 'folder' && openDetail(props.row.item.id)"
                @keyup.enter.self="props.row.item.node_kind !== 'folder' && openDetail(props.row.item.id)"
              >
                <q-card-section class="q-gutter-md">
                  <div class="row items-start no-wrap q-gutter-sm">
                    <div class="col memory-mobile-copy">
                      <div class="text-subtitle1 text-weight-medium memory-mobile-title">
                        <DocumentIcon v-if="props.row.item.node_kind === 'document'" :document-id="props.row.item.id" :title="props.row.item.title" class="q-mr-sm" />
                        {{ props.row.item.title }}
                      </div>
                    </div>
                    <div v-if="props.row.item.node_kind !== 'folder'" class="row no-wrap">
                      <MemoryAttachmentButton v-if="props.row.item.node_kind === 'attachment'"
                        :item-id="props.row.item.id" :agent-id="store.selectedAgentId" icon-only />
                      <q-btn
                        v-if="canEdit && props.row.item.access.can_write"
                        flat
                        round
                        dense
                        icon="edit"
                        color="primary"
                        :aria-label="t('memory.edit')"
                        @click.stop="openEdit(props.row.item.id)"
                      />
                    </div>
                  </div>

                  <div class="row items-center q-gutter-xs memory-mobile-badges">
                    <q-chip
                      v-if="props.row.item.node_kind === 'document'"
                      dense
                      color="orange-1"
                      text-color="orange-10"
                      icon="description"
                    >
                      {{ t('memory.kinds.document') }}
                    </q-chip>
                    <q-chip
                      v-if="props.row.item.source_managed"
                      dense
                      color="blue-1"
                      text-color="primary"
                      icon="sync_lock"
                    >
                      {{ t('memory.generated') }}
                    </q-chip>
                    <q-chip
                      v-else-if="props.row.item.deletion_protected"
                      dense
                      color="purple-1"
                      text-color="purple-10"
                      icon="lock"
                    >
                      {{ t('memory.protected') }}
                    </q-chip>
                    <q-chip
                      v-if="props.row.item.old_at"
                      dense
                      color="grey-4"
                      text-color="grey-9"
                      icon="history"
                    >
                      {{ t('memory.findings.old') }}
                    </q-chip>
                    <q-chip
                      v-for="finding in store.findingsFor(props.row.item.id)"
                      :key="finding.id"
                      clickable
                      dense
                      :color="findingColor(finding.kind)"
                      text-color="white"
                      :icon="findingIcon(finding.kind)"
                      @click.stop="openFinding(finding)"
                    >
                      {{ findingLabel(finding) }}
                    </q-chip>
                  </div>

                  <div class="text-body2 text-grey-7 memory-mobile-excerpt">
                    {{ props.row.excerpt || '—' }}
                  </div>

                  <div class="memory-mobile-fields">
                    <div class="memory-mobile-field">
                      <div class="memory-mobile-label">{{ t('memory.type') }}</div>
                      <q-chip dense outline :color="typeColor(props.row.item.memory_type)" class="q-ma-none q-mt-xs">
                        {{ t(`memory.types.${props.row.item.memory_type}`) }}
                      </q-chip>
                    </div>
                    <div class="memory-mobile-field">
                      <div class="memory-mobile-label">{{ t('memory.visibility') }}</div>
                      <div class="q-mt-xs">
                        <q-icon :name="visibilityIcon(props.row.item.visibility)" class="q-mr-xs" />
                        {{ t(`memory.visibilities.${props.row.item.visibility}`) }}
                      </div>
                    </div>
                    <div class="memory-mobile-field memory-mobile-field--wide">
                      <div class="memory-mobile-label">{{ t('memory.owner') }}</div>
                      <div class="q-mt-xs memory-mobile-value">
                        {{ agentLabel(props.row.item.owner_agent_id) }}
                      </div>
                    </div>
                    <div class="memory-mobile-field">
                      <div class="memory-mobile-label">{{ t('memory.accessCount') }}</div>
                      <div class="q-mt-xs">{{ formatNumber(props.row.item.access_count) }}</div>
                    </div>
                    <div class="memory-mobile-field">
                      <div class="memory-mobile-label">{{ t('memory.lastAccessed') }}</div>
                      <div class="q-mt-xs memory-mobile-value">
                        {{ formatDate(props.row.item.last_accessed_at) }}
                      </div>
                    </div>
                    <div class="memory-mobile-field memory-mobile-field--wide">
                      <div class="memory-mobile-label">{{ t('memory.updated') }}</div>
                      <div class="q-mt-xs memory-mobile-value">
                        {{ formatDate(props.row.item.updated_at || props.row.item.created_at) }}
                      </div>
                    </div>
                  </div>
                </q-card-section>
              </q-card>
            </div>
          </template>
          </q-table>
        </section>
      </q-tab-panel>

      <q-tab-panel name="graph" class="q-pa-none">
        <MemoryGraph
          v-if="activeTab === 'graph'"
          :agent-id="store.selectedAgentId"
          :query="store.query"
          :memory-types="store.selectedTypes"
          :topic-item-id="store.selectedTopicItemId"
          :contact-item-id="store.selectedContactItemId"
          :time-range-milliseconds="graphTimeRangeMilliseconds"
          @open="openDetail"
        />
      </q-tab-panel>
    </q-tab-panels>

    <q-dialog v-model="detailDialog" allow-focus-outside :maximized="$q.screen.lt.md">
      <q-card class="memory-detail column no-wrap">
        <q-toolbar class="galaris-dialog-title">
          <DocumentIcon v-if="store.currentItem?.node_kind === 'document'" :document-id="store.currentItem.id" :title="store.currentItem.title" class="q-mr-sm" />
          <q-icon v-else
            name="neurology"
            size="sm"
            class="q-mr-sm"
          />
          <q-toolbar-title>{{ store.currentItem?.title }}</q-toolbar-title>
          <q-badge v-if="store.currentItem" outline color="white" class="q-mr-sm"
            :label="t('documents.historyVersion', { revision: store.currentItem.revision })" />
          <q-btn flat round dense icon="close" :aria-label="t('memory.close')" v-close-popup />
        </q-toolbar>
        <q-inner-loading :showing="store.detailLoading" />
        <q-tabs v-if="store.currentItem" v-model="detailTab" inline-label align="left" active-color="primary"
          indicator-color="primary" class="text-primary bg-grey-1">
          <q-tab name="memory" icon="edit_note" :label="t('memory.detailMemory')" />
          <q-tab name="history" icon="history" :label="t('memory.detailHistory')" />
        </q-tabs>
        <q-separator />
        <q-tab-panels v-if="store.currentItem" v-model="detailTab" class="col memory-detail-panels">
          <q-tab-panel name="memory" class="q-pa-none">
            <div v-if="store.currentItem.old_at || store.findingsFor(store.currentItem.id).length || store.currentItem.source_managed || store.currentItem.deletion_protected" class="q-px-sm q-pt-sm">
              <div v-if="store.currentItem.old_at || store.findingsFor(store.currentItem.id).length" class="row items-center q-gutter-xs q-mb-sm">
                <span class="memory-section-title">{{ t('memory.detailStatus') }}</span>
                <q-chip v-if="store.currentItem.old_at" dense color="grey-4" text-color="grey-9" icon="history">
                  {{ t('memory.findings.old') }}
                </q-chip>
                <q-chip
                  v-for="finding in store.findingsFor(store.currentItem.id)"
                  :key="finding.id"
                  clickable
                  dense
                  :color="findingColor(finding.kind)"
                  text-color="white"
                  :icon="findingIcon(finding.kind)"
                  @click="openFinding(finding)"
                >
                  {{ findingLabel(finding) }}
                </q-chip>
              </div>
              <q-banner
                v-if="store.currentItem.source_managed"
                dense
                rounded
                class="bg-blue-1 text-primary q-mb-sm"
              >
                <template #avatar><q-icon name="sync_lock" /></template>
                <div class="text-weight-medium">{{ t('memory.generated') }}</div>
                <div class="text-body2">{{ t('memory.generatedHint') }}</div>
              </q-banner>
              <q-banner
                v-else-if="store.currentItem.deletion_protected"
                dense
                rounded
                class="bg-purple-1 text-purple-10 q-mb-sm"
              >
                <template #avatar><q-icon name="lock" /></template>
                <div class="text-weight-medium">{{ t('memory.protected') }}</div>
                <div class="text-body2">{{ t('memory.protectedHint') }}</div>
              </q-banner>

            </div>
            <MemoryItemForm :draft="editor" :editing-id="store.currentItem.id" :lock-version="store.currentItem.lock_version"
              :readonly="!canModifyCurrent || editorSaving" :text-available="store.currentItem.payload.text != null"
              :owner-label="agentLabel(store.currentItem.owner_agent_id)" :sources="displayedSources" :can-view-tasks="canViewTasks"
              :keyword-options="memoryKeywordOptions"
              :sharing-editable="canEdit || canAdminister" @update:draft="Object.assign(editor, $event)" @sharing-changed="onSharingChanged" />
            <div v-if="store.currentItem.node_kind === 'attachment'" class="q-px-sm q-pb-sm">
              <MemoryAttachmentButton :item-id="store.currentItem.id" :agent-id="store.selectedAgentId" />
            </div>
            <q-card-section class="q-px-sm q-pt-none q-pb-sm">
              <div class="q-mt-sm">
                <div class="row items-center justify-between q-mb-xs">
                  <div class="memory-section-title">{{ t('memory.links') }}</div>
                  <q-btn
                    v-if="canEdit && !store.currentItem.source_managed && store.currentItem.access.can_write"
                    flat
                    color="primary"
                    icon="add_link"
                    :label="t('memory.addLink')"
                    @click="openLink"
                  />
                </div>
                <q-list v-if="store.links.length" bordered separator>
                  <q-item
                    v-for="link in store.links"
                    :key="link.id"
                    dense
                    clickable
                    @click="openLinkedItem(link.source_item_id === store.currentItem?.id ? link.target_item_id : link.source_item_id)"
                  >
                    <q-item-section avatar><q-icon name="account_tree" color="primary" /></q-item-section>
                    <q-item-section>
                      <q-item-label>{{ relationLabel(link.relation_type) }}</q-item-label>
                      <q-item-label caption>
                        {{ memoryTitle(link.source_item_id === store.currentItem?.id ? link.target_item_id : link.source_item_id) }}
                      </q-item-label>
                    </q-item-section>
                    <q-item-section side><q-icon name="chevron_right" /></q-item-section>
                  </q-item>
                </q-list>
                <div v-else class="text-caption text-grey-6">{{ t('memory.noLinks') }}</div>
              </div>

            </q-card-section>
          </q-tab-panel>
          <q-tab-panel name="history" class="q-pa-sm">
            <MemoryItemHistory v-if="detailDialog && store.selectedAgentId !== null" :key="store.currentItem.id"
              :item-id="store.currentItem.id" :agent-id="store.selectedAgentId" :current-revision="store.currentItem.revision"
              :revisions="store.revisions" :loading="store.revisionsLoading" :has-more="store.revisionsHaveMore"
              :page-size="store.revisionPageSize" :page-size-options="store.rowsPerPageOptions"
              @page-size="changeRevisionPageSize" @load-more="store.loadMoreRevisions().catch(notifyError)" />
          </q-tab-panel>
        </q-tab-panels>
        <q-separator />
        <q-card-actions class="galaris-dialog-actions" v-if="store.currentItem && detailTab === 'memory'" align="right">
          <q-btn
            v-if="canEdit && !store.currentItem.source_managed && !store.currentItem.deletion_protected && (store.currentItem.access.can_write || store.currentItem.owner_agent_id === store.selectedAgentId)"
            flat
            color="negative"
            icon="delete_forever"
            :label="t('memory.forget')"
            @click="confirmForget(store.currentItem)"
          />
          <q-space />
          <q-btn flat :label="t(canModifyCurrent ? 'memory.cancel' : 'memory.close')" @click="cancelEdit" />
          <q-btn v-if="canModifyCurrent" color="primary" icon="save" :label="t('memory.save')" :loading="editorSaving"
            :disable="!editor.title.trim() || !editor.content.trim()" @click="saveEditor" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog allow-focus-outside v-model="editorDialog" :maximized="$q.screen.lt.md">
      <q-card class="memory-editor">
        <q-toolbar class="galaris-dialog-title">
          <q-toolbar-title>{{ editingId ? t('memory.editTitle') : t('memory.createTitle') }}</q-toolbar-title>
          <q-btn flat round dense icon="close" :aria-label="t('memory.close')" v-close-popup />
        </q-toolbar>
        <MemoryItemForm :draft="editor" :editing-id="editingId" :lock-version="store.currentItem?.lock_version"
          :readonly="editorSaving"
          :owner-label="agentLabel(store.selectedAgentId)" :sources="[]"
          :keyword-options="memoryKeywordOptions"
          :sharing-editable="canEdit || canAdminister" @update:draft="Object.assign(editor, $event)" @sharing-changed="onSharingChanged" />
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn flat :label="t('memory.cancel')" v-close-popup />
          <q-btn
            v-if="canEdit"
            color="primary"
            icon="save"
            :label="t('memory.save')"
            :disable="!editor.title.trim() || !editor.content.trim() || store.selectedAgentId === null"
            :loading="editorSaving"
            @click="saveEditor"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <MemoryLinkDialog
      v-if="linkDialog && store.currentItem && store.selectedAgentId !== null"
      :source-item-id="store.currentItem.id"
      :agent-id="store.selectedAgentId"
      :saving="store.saving"
      @close="linkDialog = false"
      @save="saveLink"
    />

    <MemoryFindingDialog
      v-if="selectedFinding && store.selectedAgentId !== null"
      :finding="selectedFinding"
      :agent-id="store.selectedAgentId"
      :saving="store.saving"
      @close="selectedFinding = null"
      @resolved="resolveFinding"
    />
  </q-page>
</template>

<script setup lang="ts">
import DocumentIcon from '../components/DocumentIcon.vue'
import MemoryAttachmentButton from '../components/MemoryAttachmentButton.vue'
import { showConfirmationDialog } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useQuasar, type QTableProps } from 'quasar'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { PageHeader } from '@/core/util'
import { privileges } from '@/core/authorize'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { AgentSelect } from '@/app/agent'
import MemoryGraph from '../components/MemoryGraph.vue'
import MemoryFindingDialog from '../components/MemoryFindingDialog.vue'
import MemoryLinkDialog from '../components/MemoryLinkDialog.vue'
import MemorySearchTester from '../components/MemorySearchTester.vue'
import MemoryItemHistory from '../components/MemoryItemHistory.vue'
import MemoryItemForm from '../components/MemoryItemForm.vue'
import { useMemoryStore } from '../stores/memoryStore'
import { memoryService } from '../services/memoryService'
import type {
  MemoryItem,
  MemoryItemDetail,
  MemoryFinding,
  MemoryFindingKind,
  MemoryNodeKind,
  MemoryRelationType,
  MemorySortField,
  MemoryType,
  MemoryVisibility,
} from '../types'

const { t, te, locale } = useI18n()
const route = useRoute()
const $q = useQuasar()
const store = useMemoryStore()
const agentStore = useAgentStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_EDIT))
const canAdminister = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN))
const canViewTasks = computed(() => privilegeStore.hasPrivilege(privileges.TASK_ACCESS))
const activeTab = ref<'search' | 'list' | 'graph'>('list')
const detailDialog = ref(false)
const detailTab = ref<'memory' | 'history'>('memory')
const canModifyCurrent = computed(() => canEdit.value && Boolean(store.currentItem?.access.can_write)
  && !store.currentItem?.source_managed && store.currentItem?.payload.text != null)
const editorDialog = ref(false)
const editorSaving = ref(false)
const memoryKeywordOptions = computed(() => [...new Set(store.hits.flatMap(hit => hit.item.keywords))])
const editingId = ref<string | null>(null)
const linkDialog = ref(false)
const linkedItemTitles = reactive<Record<string, string>>({})
const selectedFinding = ref<MemoryFinding | null>(null)
const memorySearchTester = useTemplateRef<InstanceType<typeof MemorySearchTester>>('memorySearchTester')
const filterOptionsLoading = ref(false)
const topicFilterOptions = ref<{ value: string, label: string }[]>([])
const contactFilterOptions = ref<{ value: string, label: string }[]>([])
const HOUR = 60 * 60 * 1000
const DAY = 24 * HOUR
const YEAR = 365 * DAY
interface GraphTimeRangeOption {
  amount: number | null
  milliseconds: number | null
  unit: 'hours' | 'days' | 'years' | null
}

const GRAPH_TIME_RANGE_OPTIONS: readonly GraphTimeRangeOption[] = [
  { amount: 1, milliseconds: HOUR, unit: 'hours' },
  { amount: 3, milliseconds: 3 * HOUR, unit: 'hours' },
  { amount: 6, milliseconds: 6 * HOUR, unit: 'hours' },
  { amount: 12, milliseconds: 12 * HOUR, unit: 'hours' },
  { amount: 1, milliseconds: DAY, unit: 'days' },
  { amount: 2, milliseconds: 2 * DAY, unit: 'days' },
  { amount: 3, milliseconds: 3 * DAY, unit: 'days' },
  { amount: 7, milliseconds: 7 * DAY, unit: 'days' },
  { amount: 14, milliseconds: 14 * DAY, unit: 'days' },
  { amount: 30, milliseconds: 30 * DAY, unit: 'days' },
  { amount: 60, milliseconds: 60 * DAY, unit: 'days' },
  { amount: 90, milliseconds: 90 * DAY, unit: 'days' },
  { amount: 180, milliseconds: 180 * DAY, unit: 'days' },
  { amount: 1, milliseconds: YEAR, unit: 'years' },
  { amount: 2, milliseconds: 2 * YEAR, unit: 'years' },
  { amount: 3, milliseconds: 3 * YEAR, unit: 'years' },
  { amount: 5, milliseconds: 5 * YEAR, unit: 'years' },
  { amount: 10, milliseconds: 10 * YEAR, unit: 'years' },
  { amount: 20, milliseconds: 20 * YEAR, unit: 'years' },
  { amount: null, milliseconds: null, unit: null },
]
const DEFAULT_GRAPH_TIME_RANGE_INDEX = GRAPH_TIME_RANGE_OPTIONS.length - 1
const graphTimeRangeDraftIndex = ref(DEFAULT_GRAPH_TIME_RANGE_INDEX)
const graphTimeRangeIndex = ref(DEFAULT_GRAPH_TIME_RANGE_INDEX)
const graphTimeRangeDraft = computed<GraphTimeRangeOption>(() => (
  GRAPH_TIME_RANGE_OPTIONS[graphTimeRangeDraftIndex.value]
  ?? GRAPH_TIME_RANGE_OPTIONS[DEFAULT_GRAPH_TIME_RANGE_INDEX]!
))
const graphTimeRangeMilliseconds = computed<number | null>(() => (
  GRAPH_TIME_RANGE_OPTIONS[graphTimeRangeIndex.value]?.milliseconds ?? null
))
const graphTimeRangeLabel = computed(() => {
  const option = graphTimeRangeDraft.value
  if (option.amount === null || option.unit === null) return t('memory.graph.allHistory')
  const unit = option.unit === 'years' && option.amount === 1 ? 'year' : option.unit
  return t(`memory.graph.rangeUnits.${unit}`, { count: option.amount })
})

type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]

const memoryTypes: MemoryType[] = ['core', 'working', 'episodic', 'semantic', 'procedural', 'social']
const typeOptions = computed(() => memoryTypes.map(value => ({ value, label: t(`memory.types.${value}`) })))
const agentOptions = computed(() => agentStore.agents.map(agent => ({
  value: agent.id,
  label: `${agent.first_name} ${agent.last_name}`.trim() || agent.code,
})))
const taskSourcePattern = /^task:([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})$/i
const displayedSources = computed(() => (
  store.currentItem?.source_refs.map(ref => ({
    ref,
    taskId: taskSourcePattern.exec(ref)?.[1] ?? null,
  })) ?? []
))

const itemColumns = computed<QTableProps['columns']>(() => [
  {
    name: 'title',
    label: t('memory.title'),
    field: (row: { item: MemoryItem }) => row.item.title,
    align: 'left',
    sortable: true,
  },
  {
    name: 'memory_type',
    label: t('memory.type'),
    field: (row: { item: MemoryItem }) => row.item.memory_type,
    align: 'left',
    sortable: true,
  },
  {
    name: 'visibility',
    label: t('memory.visibility'),
    field: (row: { item: MemoryItem }) => row.item.visibility,
    align: 'left',
    sortable: true,
  },
  {
    name: 'owner',
    label: t('memory.owner'),
    field: (row: { item: MemoryItem }) => agentLabel(row.item.owner_agent_id),
    align: 'left',
    sortable: true,
  },
  {
    name: 'access_count',
    label: t('memory.accessCount'),
    field: (row: { item: MemoryItem }) => row.item.access_count,
    align: 'right',
    sortable: true,
    sortOrder: 'da',
  },
  {
    name: 'last_accessed_at',
    label: t('memory.lastAccessed'),
    field: (row: { item: MemoryItem }) => row.item.last_accessed_at,
    align: 'left',
    sortable: true,
    sortOrder: 'da',
  },
  {
    name: 'updated_at',
    label: t('memory.updated'),
    field: (row: { item: MemoryItem }) => row.item.updated_at || row.item.created_at,
    align: 'left',
    sortable: true,
    sortOrder: 'da',
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
])

const editor = reactive({
  title: '',
  content: '',
  memoryType: 'semantic' as MemoryType,
  nodeKind: 'memory' as MemoryNodeKind,
  keywords: [] as string[],
  readOnly: false,
  revision: null as number | null,
  mediaType: 'text/html', contentType: 'text',
})

function relationLabel(relation: string): string {
  const key = `memory.relationTypes.${relation}`
  return te(key) ? t(key) : t('memory.otherRelation')
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function applyGraphTimeRange(): void {
  graphTimeRangeIndex.value = graphTimeRangeDraftIndex.value
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale.value).format(value)
}

function agentLabel(agentId: number | null): string {
  if (agentId === null) return t('memory.publicOwner')
  return agentOptions.value.find(option => option.value === agentId)?.label ?? `#${agentId}`
}

function memoryTitle(memoryId: string): string {
  return linkedItemTitles[memoryId]
    ?? store.hits.find(hit => hit.item.id === memoryId)?.item.title
    ?? memoryId
}

function typeColor(type: MemoryType): string {
  return ({ core: 'deep-purple', working: 'orange', episodic: 'blue', semantic: 'teal', procedural: 'indigo', social: 'pink' })[type]
}

function visibilityIcon(visibility: MemoryVisibility): string {
  return ({ private: 'lock', shared: 'group', public: 'public' })[visibility]
}

function findingIcon(kind: MemoryFindingKind): string {
  return ({ duplicate: 'content_copy', contradiction: 'compare_arrows', aging: 'history' })[kind]
}

function findingColor(kind: MemoryFindingKind): string {
  return ({ duplicate: 'orange-8', contradiction: 'red-7', aging: 'blue-grey-7' })[kind]
}

function findingLabel(finding: MemoryFinding): string {
  const label = t(`memory.findings.kinds.${finding.kind}`)
  if (finding.score === null) return label
  const score = new Intl.NumberFormat(locale.value, {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(finding.score)
  return `${label} · ${score}`
}

function openFinding(finding: MemoryFinding): void {
  selectedFinding.value = finding
}

async function resolveFinding(
  action: 'apply' | 'dismiss',
  canonicalItemId?: string,
): Promise<void> {
  if (selectedFinding.value === null) return
  try {
    await store.resolveFinding(selectedFinding.value, action, canonicalItemId)
    selectedFinding.value = null
    $q.notify({ type: 'positive', message: t(`memory.findings.${action}Done`) })
  } catch (error) {
    notifyError(error)
  }
}

function notifyError(error?: unknown): void {
  const detail = apiErrorDetail(error)
  $q.notify({
    type: 'negative',
    message: detail
      ? t('memory.operationErrorWithDetail', { detail })
      : t('memory.operationError'),
    multiLine: true,
    timeout: detail ? 10_000 : 5_000,
  })
}

async function searchSafely(resetPage = false): Promise<void> {
  try {
    await store.search({ resetPage })
  } catch (error) {
    notifyError(error)
  }
}

function scheduleSearch(): void {
  void searchSafely(true)
}

let filterOptionsVersion = 0
onBeforeUnmount(() => { filterOptionsVersion += 1 })
async function loadFilterOptions(agentId: number | null): Promise<void> {
  const version = ++filterOptionsVersion
  if (agentId === null) {
    filterOptionsLoading.value = false
    topicFilterOptions.value = []
    contactFilterOptions.value = []
    return
  }
  filterOptionsLoading.value = true
  try {
    const options = await memoryService.listFilterOptions(agentId)
    if (version !== filterOptionsVersion) return
    topicFilterOptions.value = options.topics.map(option => ({
      value: option.id,
      label: option.label,
    }))
    contactFilterOptions.value = options.contacts.map(option => ({
      value: option.id,
      label: option.label,
    }))
  } catch (error) {
    if (version === filterOptionsVersion && !isCancelledRequest(error)) notifyError(error)
  } finally {
    if (version === filterOptionsVersion) filterOptionsLoading.value = false
  }
}

function isMemorySortField(value: string | null): value is MemorySortField {
  return value === 'title'
    || value === 'memory_type'
    || value === 'visibility'
    || value === 'owner'
    || value === 'access_count'
    || value === 'last_accessed_at'
    || value === 'updated_at'
}

async function onTableRequest(request: TableRequest): Promise<void> {
  const requestedSortBy = request.pagination.sortBy
  const sortBy = isMemorySortField(requestedSortBy) ? requestedSortBy : null

  try {
    await store.search({
      page: request.pagination.page,
      rowsPerPage: request.pagination.rowsPerPage,
      sortBy,
      sortDescending: request.pagination.descending,
    })
  } catch (error) {
    notifyError(error)
  }
}

async function openDetail(id: string): Promise<void> {
  if (store.hits.some(hit => hit.item.id === id && hit.item.node_kind === 'folder')) return
  editingId.value = null
  detailTab.value = 'memory'
  detailDialog.value = true
  try {
    const item = await store.openItem(id)
    if (item.node_kind === 'folder') { detailDialog.value = false; return }
    if (detailDialog.value && store.currentItem?.id === item.id) prepareEditor(item)
  } catch (error) {
    detailDialog.value = false
    notifyError(error)
  }
}

async function changeRevisionPageSize(size: number): Promise<void> {
  store.revisionPageSize = size
  await store.loadMoreRevisions(true).catch(notifyError)
}

async function openLinkedItem(id: string): Promise<void> {
  await openDetail(id)
}

function openLink(): void {
  linkDialog.value = true
}

async function saveLink(
  targetItemId: string,
  relationType: MemoryRelationType,
  targetTitle: string,
): Promise<void> {
  try {
    await store.createLink(targetItemId, relationType)
    linkedItemTitles[targetItemId] = targetTitle
    linkDialog.value = false
    $q.notify({ type: 'positive', message: t('memory.linkSaved') })
  } catch (error) {
    notifyError(error)
  }
}

function resetEditor(): void {
  Object.assign(editor, {
    title: '', content: '', memoryType: 'semantic',
    nodeKind: 'memory',
    keywords: [], readOnly: false, revision: null,
    mediaType: 'text/html', contentType: 'text',
  })
}

function openCreate(): void {
  editingId.value = null
  resetEditor()
  editorDialog.value = true
}

async function openEdit(id: string): Promise<void> {
  await openDetail(id)
}

function prepareEditor(item: MemoryItemDetail): void {
  editingId.value = item.id
  Object.assign(editor, {
    title: item.title,
    content: item.payload.text ?? '',
    memoryType: item.memory_type,
    nodeKind: item.node_kind,
    keywords: [...item.keywords],
    readOnly: item.read_only,
    revision: item.revision,
    mediaType: item.media_type, contentType: item.content_type,
  })
}

function cancelEdit(): void {
  detailDialog.value = false
  editingId.value = null
  resetEditor()
}

async function saveEditor(): Promise<void> {
  if (editorSaving.value) return
  if (!editor.title.trim() || !editor.content.trim() || store.selectedAgentId === null) return
  if (detailDialog.value && !canModifyCurrent.value) return
  const keywords = [...new Set(editor.keywords.map(value => value.trim()).filter(Boolean))]
  const wasEditing = editingId.value !== null
  editorSaving.value = true
  try {
    if (editingId.value) {
      await store.updateItem(editingId.value, {
        expected_revision: editor.revision ?? undefined,
        title: editor.title.trim(),
        payload: { text: editor.content },
        media_type: editor.mediaType,
        memory_type: editor.memoryType,
        keywords,
        read_only: editor.readOnly,
      })
    } else {
      const created = await store.createItem({
        owner_agent_id: store.selectedAgentId,
        title: editor.title.trim(),
        payload: { text: editor.content },
        media_type: editor.mediaType,
        memory_type: editor.nodeKind === 'document' ? 'working' : editor.memoryType,
        node_kind: editor.nodeKind,
        visibility: 'private',
        keywords,
        read_only: editor.readOnly,
      })
      await openDetail(created.id)
    }
    editorDialog.value = false
    $q.notify({ type: 'positive', message: t(wasEditing ? 'memory.updatedDone' : 'memory.createdDone') })
    detailTab.value = 'memory'
    if (store.currentItem) prepareEditor(store.currentItem)
  } catch (error) {
    notifyError(error)
  } finally {
    editorSaving.value = false
  }
}

function confirmForget(item: MemoryItem): void {
  showConfirmationDialog({
    title: t('memory.forget'),
    message: t('memory.forgetConfirm', { title: item.title }),
    cancel: true,
    color: 'negative',
    ok: { label: t('memory.forget'), color: 'negative' },
  }).onOk(async () => {
    try {
      await store.forgetItem(item.id)
      memorySearchTester.value?.removeResult(item.id)
      detailDialog.value = false
      $q.notify({ type: 'positive', message: t('memory.forgottenDone') })
    } catch (error) {
      notifyError(error)
    }
  })
}

async function onSharingChanged(): Promise<void> {
  const id = editingId.value && editorDialog.value ? editingId.value : store.currentItem?.id
  if (!id) return
  try {
    await store.openItem(id)
    await store.search()
  } catch (error) {
    notifyError(error)
  }
}

watch(() => store.selectedAgentId, (agentId, previousAgentId) => {
  if (agentId !== previousAgentId) {
    store.selectedTopicItemId = null
    store.selectedContactItemId = null
    topicFilterOptions.value = []
    contactFilterOptions.value = []
  }
  void Promise.all([
    loadFilterOptions(agentId),
    searchSafely(true),
  ]).catch(notifyError)
})
watch(() => editor.nodeKind, (nodeKind) => {
  if (editingId.value === null && nodeKind === 'document') {
    editor.memoryType = 'working'
  }
})

onMounted(async () => {
  try {
    await agentStore.fetchAgents()
    const rawAgentId = Array.isArray(route.query.agent) ? route.query.agent[0] : route.query.agent
    const requestedAgentId = rawAgentId ? Number(rawAgentId) : null
    const routeAgentId = requestedAgentId !== null
      && Number.isInteger(requestedAgentId)
      && agentStore.agents.some(agent => agent.id === requestedAgentId)
      ? requestedAgentId
      : null
    const nextAgentId = routeAgentId
      ?? store.selectedAgentId
      ?? agentStore.agents[0]?.id
      ?? null
    if (store.selectedAgentId !== nextAgentId) {
      store.selectedAgentId = nextAgentId
      await nextTick()
    }
    const rawContactId = Array.isArray(route.query.contact)
      ? route.query.contact[0]
      : route.query.contact
    if (typeof rawContactId === 'string' && rawContactId) {
      activeTab.value = 'list'
      store.selectedContactItemId = rawContactId
    }
    await Promise.all([
      loadFilterOptions(store.selectedAgentId),
      searchSafely(true),
    ])
  } catch (error) {
    notifyError(error)
  }
})

watch(() => [route.query.item_id, agentStore.agents.length] as const, async ([value]) => {
  if (typeof value !== 'string' || !/^[0-9a-f-]{36}$/.test(value)) return
  for (const agent of agentStore.agents) {
    try { await memoryService.getItem(value, agent.id); store.selectedAgentId = agent.id; await openDetail(value); return } catch { /* Try another managed agent without exposing inaccessible metadata. */ }
  }
  if (agentStore.agents.length) $q.notify({ type: 'negative', message: t('richEditor.unavailable') })
}, { immediate: true })
</script>

<style scoped>
.memory-filter-block__row {
  padding: 10px 12px;
}

.memory-filter-block__row--primary {
  padding-bottom: 8px;
}

.memory-agent-select :deep(.q-field__native > .row) {
  min-width: 0;
  max-width: 100%;
}

.memory-filter-block__row--secondary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding-top: 0;
}

.memory-filter-block__field {
  min-width: 0;
}

.memory-filter-block__timeline {
  min-width: 0;
}

.memory-filter-block__slider {
  padding: 20px 0 0;
}

.memory-list-table {
  min-width: 0;
  max-width: 100%;
}

.memory-list-table :deep(.q-table) {
  table-layout: fixed;
  width: 100%;
}

.memory-list-table :deep(th),
.memory-list-table :deep(td) {
  padding: 8px;
  white-space: normal;
  overflow-wrap: anywhere;
}

.memory-list-table :deep(th:first-child) {
  width: 30%;
}

.memory-list-table :deep(th:last-child) {
  width: 64px;
}

.memory-list-table :deep(.q-chip) {
  max-width: 100%;
  height: auto;
  min-height: 24px;
  white-space: normal;
}

.memory-list-table :deep(.q-chip__content) {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

.memory-list-table :deep(.q-table__bottom),
.memory-list-table :deep(.q-table__control) {
  flex-wrap: wrap;
  gap: 8px;
}

.memory-list-table :deep(.q-table__bottom) {
  padding: 8px;
}

.memory-excerpt {
  max-width: 100%;
  overflow-wrap: anywhere;
}
.memory-mobile-card,
.memory-mobile-copy,
.memory-mobile-field {
  min-width: 0;
}

:deep(.memory-list-table .q-table__grid-content) {
  width: 100%;
  margin: 0;
}

:deep(.memory-list-table .q-table__grid-item) {
  min-width: 0;
  max-width: 100%;
}

.memory-list-grid-item {
  padding: 8px 0;
}

.memory-mobile-title,
.memory-mobile-excerpt,
.memory-mobile-value {
  overflow-wrap: anywhere;
}

.memory-mobile-badges {
  row-gap: 4px;
}

.memory-mobile-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.memory-mobile-field--wide {
  grid-column: 1 / -1;
}

.memory-mobile-label {
  color: #757575;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}

.memory-detail { width: 980px; max-width: 96vw; height: min(760px, 88vh); }
.memory-detail-panels { min-height: 0; }
.memory-section-title { font-size: 0.75rem; font-weight: 600; color: inherit; }
.memory-editor { width: 980px; max-width: 96vw; max-height: 92vh; overflow: auto; }
.memory-detail :deep(.q-toolbar__title),
.memory-editor :deep(.q-toolbar__title) { font-size: 1rem; }
.member-editor { width: min(620px, 94vw); }

@media (max-width: 1023px) {
  .memory-filter-block__row--secondary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 599px) {
  .memory-filter-block__row {
    padding: 8px;
  }

  .memory-filter-block__row--secondary {
    grid-template-columns: minmax(0, 1fr);
    padding-top: 0;
  }
}
</style>
