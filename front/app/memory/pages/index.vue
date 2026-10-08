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
      <q-tab name="list" icon="view_list" :label="t('memory.tabs.list')" />
      <q-tab name="graph" icon="hub" :label="t('memory.tabs.graph')" />
    </q-tabs>
    <q-separator />

    <q-card flat bordered class="memory-filter-block q-my-md">
      <q-form class="memory-filter-block__form" @submit="temporalFilter?.apply()">
        <div class="memory-filter-block__row memory-filter-block__row--primary">
          <div class="memory-filter-block__field">
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
        </div>

        <div
          class="memory-filter-block__row memory-filter-block__row--secondary"
          :class="{ 'memory-filter-block__row--list': activeTab === 'list' }"
        >
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
          <div v-if="activeTab === 'list'" class="memory-filter-block__temporal">
            <MemoryTemporalFilter ref="temporalFilter" v-model="store.temporal" :timezone="store.temporalTimezone" @update:model-value="() => searchSafely(true)" />
            <q-btn type="submit" color="primary" outline icon="refresh" :label="t('memory.temporalSearch.apply')" />
          </div>
        </div>
      </q-form>
    </q-card>

    <q-tab-panels v-model="activeTab" animated class="bg-transparent">
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

        <div v-if="store.recallTruncated" class="text-caption q-mb-md" role="status">
          {{ t('memory.recall.bounded') }}
        </div>
        <div v-if="store.degradationReason" class="text-caption q-mb-md" role="status">
          {{ t('memory.recall.degraded') }}
        </div>

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
              <div class="row items-start no-wrap q-gutter-sm">
                <MemoryItemThumbnail :key="props.row.item.id + ':' + props.row.item.node_kind" :item="props.row.item" :agent-id="store.selectedAgentId" />
                <div class="col memory-list-copy">
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
                  <div v-if="props.row.temporal_match_at" class="text-caption">
                    {{ t('memory.temporalSearch.match', { date: formatTemporalDate(props.row.temporal_match_at) }) }}
                  </div>
                </div>
              </div>
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
                  <div v-if="props.row.temporal_match_at" class="text-caption">
                    {{ t('memory.temporalSearch.match', { date: formatTemporalDate(props.row.temporal_match_at) }) }}
                  </div>
                  <div class="row items-start no-wrap q-gutter-sm">
                    <MemoryItemThumbnail :key="props.row.item.id + ':' + props.row.item.node_kind" :item="props.row.item" :agent-id="store.selectedAgentId" />
                    <div class="col memory-mobile-copy">
                      <div class="text-subtitle1 text-weight-medium memory-mobile-title">
                        <DocumentIcon v-if="props.row.item.node_kind === 'document'" :document-id="props.row.item.id" :title="props.row.item.title" class="q-mr-sm" />
                        {{ props.row.item.title }}
                      </div>
                    </div>
                    <MemoryAttachmentButton v-if="props.row.item.node_kind === 'attachment'"
                      :item-id="props.row.item.id" :agent-id="store.selectedAgentId" icon-only />
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
          ref="memoryGraph"
          v-if="activeTab === 'graph'"
          :agent-id="store.selectedAgentId"
          :query="store.query"
          :topic-item-id="store.selectedTopicItemId"
          :contact-item-id="store.selectedContactItemId"
          @open="openDetail"
        />
      </q-tab-panel>
    </q-tab-panels>

    <q-dialog v-model="detailDialog" allow-focus-outside :maximized="$q.screen.lt.md">
      <q-card class="memory-detail column no-wrap galaris-dialog-card">
        <q-toolbar class="galaris-dialog-title">
          <div class="memory-detail-heading">
            <q-toolbar-title>{{ t('memory.detailTitle', { kind: currentRoleLabel }) }}</q-toolbar-title>
            <div v-if="currentMetadata" class="memory-detail-badges">
              <q-badge outline color="white" :aria-label="t('memory.lastActivityBadge', { date: formatDate(currentMetadata.activity_at) })">
                <span>{{ formatDate(currentMetadata.activity_at) }}</span>
                <q-tooltip>{{ t('memory.graph.lastActivity') }}</q-tooltip>
              </q-badge>
              <q-badge outline color="white" :label="t('memory.accessCountBadge', { count: formatNumber(currentMetadata.access_count) })" />
              <q-badge v-if="store.currentItem" outline color="white"
                :label="t('documents.historyVersion', { revision: store.currentItem.revision })" />
              <q-badge v-if="store.currentItem?.source_managed && store.currentItem.managed_source_kind !== 'file_catalogue'"
                outline color="white" tabindex="0" :aria-label="t('memory.generatedHint')" :label="t('memory.generated')">
                <q-tooltip max-width="400px">{{ t('memory.generatedHint') }}</q-tooltip>
              </q-badge>
              <q-badge v-if="store.currentItem?.deletion_protected" class="memory-protection-badge"
                tabindex="0" :aria-label="t('memory.protectedHint')" :label="t('memory.protected')">
                <q-tooltip>{{ t('memory.protectedHint') }}</q-tooltip>
              </q-badge>
            </div>
          </div>
          <q-btn flat round dense icon="close" :aria-label="t('memory.close')" v-close-popup />
        </q-toolbar>
        <q-inner-loading :showing="store.detailLoading" />
        <q-tabs v-if="store.currentItem" v-model="detailTab" inline-label no-caps dense align="left" active-color="primary"
          indicator-color="primary" class="memory-detail-tabs">
          <q-tab name="memory" icon="edit_note" :label="t('memory.detailMemory')" />
          <q-tab name="links" icon="account_tree" :label="t('memory.detailLinks')" />
          <q-tab name="history" icon="history" :label="t('memory.detailHistory')" />
        </q-tabs>
        <q-separator />
        <q-tab-panels v-if="store.currentItem" :key="`${store.selectedAgentId}:${store.currentItem.id}`" v-model="detailTab" keep-alive :keep-alive-include="['memory', 'links']" class="col memory-detail-panels galaris-dialog-body">
          <q-tab-panel name="memory" class="q-pa-none">
            <MemoryContentPreviews :key="`${store.selectedAgentId}:${store.currentItem.id}:${dreamMediaRevision}`"
              :item="store.currentItem" :agent-id="store.selectedAgentId" />
            <div v-if="store.currentItem.old_at || store.findingsFor(store.currentItem.id).length" class="q-px-md q-pt-md">
              <div v-if="store.currentItem.old_at || store.findingsFor(store.currentItem.id).length" class="row items-center q-gutter-xs q-mb-sm">
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
            </div>
            <MemoryItemForm :draft="editor" :editing-id="store.currentItem.id" :lock-version="store.currentItem.lock_version"
              :summary-outdated="store.currentItem.summary_outdated"
              :resource-read-only="store.currentItem.read_only"
              :readonly="!canModifyCurrent || editorSaving || dreamBusy || dreamRefreshing" :text-available="currentContentIsText"
              :keyword-options="memoryKeywordOptions"
              :sharing-editable="canEdit || canAdminister" @update:draft="Object.assign(editor, $event)" @sharing-changed="onSharingChanged" />
          </q-tab-panel>
          <q-tab-panel name="links" class="memory-detail-links">
            <section :aria-label="t('memory.sources')" class="memory-links-section">
              <div class="memory-section-title"><q-icon name="source" />{{ t('memory.sources') }}</div>
              <q-list v-if="displayedSources.length" dense separator>
                <q-item v-for="source in displayedSources" :key="source.ref">
                  <q-item-section>
                    <RouterLink v-if="source.taskId !== null && canViewTasks" class="text-primary"
                      :to="{ path: '/task', query: { task_id: source.taskId } }">{{ source.ref }}</RouterLink>
                    <span v-else>{{ source.ref }}</span>
                  </q-item-section>
                </q-item>
              </q-list>
              <div v-else class="text-caption">{{ t('memory.noSources') }}</div>
            </section>
            <section v-if="graphContext?.node.id === store.currentItem.id && graphContext.relations.length" class="memory-links-section" :aria-label="t('memory.graph.neighbors')">
                <div class="memory-section-title"><q-icon name="hub" />{{ t('memory.graph.neighbors') }}</div>
                <MemoryGraphRelations :relations="graphContext.relations" @select="openGraphNeighbor" />
            </section>
            <section class="memory-links-section" :aria-label="t('memory.links')">
                <div class="row items-center justify-between q-mb-xs">
                  <div class="memory-section-title"><q-icon name="account_tree" />{{ t('memory.links') }}</div>
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
                <div v-else class="text-caption">{{ t('memory.noLinks') }}</div>
            </section>
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
        <q-card-actions class="galaris-dialog-actions memory-detail-actions" v-if="store.currentItem" v-show="detailTab !== 'history'" align="right">
          <q-btn
            v-if="canEdit && store.currentItem.node_kind !== 'document' && !store.currentItem.source_managed && !store.currentItem.deletion_protected && (store.currentItem.access.can_write || store.currentItem.owner_agent_id === store.selectedAgentId)"
            flat
            color="negative"
            icon="delete_forever"
            :label="t('memory.forget')"
            :disable="dreamBusy || dreamRefreshing"
            @click="confirmForget(store.currentItem)"
          />
          <MemoryDreamActions :key="`${store.selectedAgentId}:${store.currentItem.id}`"
            class="memory-detail-dream"
            :item-id="store.currentItem.id" :agent-id="store.selectedAgentId"
            :node-kind="store.currentItem.node_kind"
            :disabled="editorSaving || dreamDraftChanged || dreamRefreshing" @busy="dreamBusy = $event" @completed="onDreamCompleted" />
          <q-btn v-if="canModifyCurrent" class="memory-detail-save" color="primary" icon="save" :label="t('memory.save')" :loading="editorSaving"
            :disable="dreamBusy || dreamRefreshing" @click="saveEditor" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog allow-focus-outside v-model="editorDialog" :maximized="$q.screen.lt.md">
      <q-card class="memory-editor galaris-dialog-card">
        <q-toolbar class="galaris-dialog-title">
          <q-toolbar-title>{{ editingId ? t('memory.editTitle') : t('memory.createTitle') }}</q-toolbar-title>
          <q-btn flat round dense icon="close" :aria-label="t('memory.close')" v-close-popup />
        </q-toolbar>
        <div class="galaris-dialog-body">
          <MemoryItemForm :draft="editor" :editing-id="editingId" :lock-version="store.currentItem?.lock_version"
            :readonly="editorSaving"
            :keyword-options="memoryKeywordOptions"
            :sharing-editable="canEdit || canAdminister" @update:draft="Object.assign(editor, $event)" @sharing-changed="onSharingChanged" />
        </div>
        <q-card-actions class="galaris-dialog-actions" align="right">
          <q-btn
            v-if="canEdit"
            color="primary"
            icon="save"
            :label="t('memory.save')"
            :disable="store.selectedAgentId === null"
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
import MemoryItemThumbnail from '../components/MemoryItemThumbnail.vue'
import MemoryAttachmentButton from '../components/MemoryAttachmentButton.vue'
import MemoryContentPreviews from '../components/MemoryContentPreviews.vue'
import { showConfirmationDialog } from '@/core/util'
import { navigationIcon } from '@/core/navigation'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute } from 'vue-router'
import { useQuasar, type QTableProps } from 'quasar'
import { apiErrorDetail, isCancelledRequest } from '@/core/api'
import { isAxiosError } from 'axios'
import { websocket } from '@/core/websocket'
import { PageHeader } from '@/core/util'
import { privileges } from '@/core/authorize'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'
import { useAgentStore } from '@/app/agent/stores/agentStore'
import { AgentSelect } from '@/app/agent'
import MemoryGraph from '../components/MemoryGraph.vue'
import MemoryDreamActions from '../components/MemoryDreamActions.vue'
import MemoryGraphRelations from '../components/MemoryGraphRelations.vue'
import MemoryFindingDialog from '../components/MemoryFindingDialog.vue'
import MemoryLinkDialog from '../components/MemoryLinkDialog.vue'
import MemoryTemporalFilter from '../components/MemoryTemporalFilter.vue'
import MemoryItemHistory from '../components/MemoryItemHistory.vue'
import MemoryItemForm from '../components/MemoryItemForm.vue'
import { useMemoryStore } from '../stores/memoryStore'
import { memoryService } from '../services/memoryService'
import type {
  MemoryItem,
  MemoryItemDetail,
  MemoryGraphNode,
  MemoryGraphRelation,
  MemoryFinding,
  MemoryFindingKind,
  MemoryNodeKind,
  MemoryRelationType,
  MemorySortField,
  MemoryVisibility,
} from '../types'

const { t, te, locale } = useI18n()
function formatTemporalDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: 'medium', timeStyle: 'short', timeZone: store.temporalTimezone ?? 'UTC',
  }).format(new Date(value))
}
const route = useRoute()
const $q = useQuasar()
const store = useMemoryStore()
const agentStore = useAgentStore()
const privilegeStore = usePrivilegeStore()
const canEdit = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_EDIT))
const canAdminister = computed(() => privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN))
const canViewTasks = computed(() => privilegeStore.hasPrivilege(privileges.TASK_ACCESS))
const activeTab = ref<'list' | 'graph'>('list')
const detailDialog = ref(false)
const memoryGraph = useTemplateRef<InstanceType<typeof MemoryGraph>>('memoryGraph')
const graphContext = ref<{ node: MemoryGraphNode; relations: MemoryGraphRelation[] } | null>(null)
const currentMetadata = computed(() => {
  const item = store.currentItem
  if (!item) return null
  const activityDates = [item.created_at, item.updated_at, item.last_accessed_at]
    .filter((value): value is string => value !== null)
    .sort((left, right) => Date.parse(right) - Date.parse(left))
  return {
    visibility: item.visibility,
    access_count: item.access_count,
    activity_at: graphContext.value?.node.id === item.id
      ? graphContext.value.node.activity_at : activityDates[0]!,
  }
})
const currentRoleLabel = computed(() => {
  const item = store.currentItem
  if (!item) return ''
  const role = graphContext.value?.node.id === item.id ? graphContext.value.node.entity_kind : item.node_kind
  return t(`memory.graph.roles.${role}`)
})
watch(detailDialog, open => {
  if (!open) {
    graphContext.value = null
    memoryGraph.value?.closeDetails()
  }
})
const detailTab = ref<'memory' | 'links' | 'history'>('memory')
const currentContentIsText = computed(() => store.currentItem?.content_type === 'text'
  && store.currentItem.payload.base64 == null)
const canModifyCurrent = computed(() => canEdit.value && Boolean(store.currentItem?.access.can_write)
  && (!store.currentItem?.source_managed || store.currentItem?.managed_source_kind === 'file_catalogue')
  && currentContentIsText.value)
const editorDialog = ref(false)
const editorSaving = ref(false)
const dreamBusy = ref(false)
const dreamRefreshing = ref(false)
const dreamMediaRevision = ref(0)
const memoryKeywordOptions = computed(() => [...new Set(store.hits.flatMap(hit => hit.item.keywords))])
const editingId = ref<string | null>(null)
const linkDialog = ref(false)
const linkedItemTitles = reactive<Record<string, string>>({})
const selectedFinding = ref<MemoryFinding | null>(null)
const temporalFilter = useTemplateRef<InstanceType<typeof MemoryTemporalFilter>>('temporalFilter')
const filterOptionsLoading = ref(false)
const topicFilterOptions = ref<{ value: string, label: string }[]>([])
const contactFilterOptions = ref<{ value: string, label: string }[]>([])
type TableRequest = Parameters<NonNullable<QTableProps['onRequest']>>[0]
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
  temporal: null as import('../types').MemoryTemporalAnchor | null,
  content: '',
  nodeKind: 'memory' as MemoryNodeKind,
  keywords: [] as string[],
  revision: null as number | null,
  lockVersion: null as number | null,
  mediaType: 'text/html', contentType: 'text',
})
const editorBase = ref<MemoryItemDetail | null>(null)
let documentRefreshRequest = 0

function mergeDocumentMemory(latest: MemoryItemDetail): void {
  const base = editorBase.value
  if (!base || base.id !== latest.id) return
  const previous = { content: base.payload.text ?? '', keywords: base.keywords, temporal: base.temporal ?? null }
  const remote = { content: latest.payload.text ?? '', keywords: latest.keywords, temporal: latest.temporal ?? null }
  const same = (left: unknown, right: unknown): boolean => JSON.stringify(left) === JSON.stringify(right)
  const fields = ['content', 'keywords', 'temporal'] as const
  // Keep the original lock on overlapping changes: saving must report a conflict,
  // never overwrite somebody else's keywords with a stale draft.
  if (fields.some(field => !same(editor[field], previous[field])
    && !same(remote[field], previous[field]) && !same(editor[field], remote[field]))) return
  if (same(editor.content, previous.content)) editor.content = remote.content
  if (same(editor.keywords, previous.keywords)) editor.keywords = [...remote.keywords]
  if (same(editor.temporal, previous.temporal)) editor.temporal = remote.temporal ? { ...remote.temporal } : null
  editor.revision = latest.revision
  editor.lockVersion = latest.lock_version
  editorBase.value = latest
}

async function onDocumentMemoryUpdate(response: { data: { id: string, node_kind: string } }): Promise<void> {
  const current = store.currentItem
  const agentId = store.selectedAgentId
  if (!detailDialog.value || editorSaving.value || store.saving || agentId === null
    || current?.node_kind !== 'document' || response.data.node_kind !== 'document'
    || response.data.id !== current.id) return
  const request = ++documentRefreshRequest
  const stillCurrent = (): boolean => request === documentRefreshRequest && detailDialog.value
    && store.selectedAgentId === agentId && store.currentItem?.id === current.id
    && !editorSaving.value && !store.saving
  try {
    const latest = await memoryService.getItem(current.id, agentId)
    if (!stillCurrent() || latest.lock_version < (store.currentItem?.lock_version ?? 0)) return
    mergeDocumentMemory(latest)
    store.currentItem = latest
  } catch (error) {
    if (!stillCurrent() || isCancelledRequest(error)) return
    if (isAxiosError(error) && [403, 404].includes(error.response?.status ?? 0)) {
      store.currentItem = null
      detailDialog.value = false
    }
    notifyError(error)
  }
}

websocket.onEvent('memory', 'update', onDocumentMemoryUpdate)
onBeforeUnmount(() => {
  documentRefreshRequest++
  websocket.offEvent('memory', 'update', onDocumentMemoryUpdate)
})
watch([detailDialog, () => store.selectedAgentId, editingId], () => { documentRefreshRequest++ })

const dreamDraftChanged = computed(() => {
  const item = store.currentItem
  return Boolean(item && (editor.content !== (item.payload.text ?? '')
    || JSON.stringify(editor.keywords) !== JSON.stringify(item.keywords)
    || JSON.stringify(editor.temporal) !== JSON.stringify(item.temporal ?? null)))
})

async function onDreamCompleted(id: string): Promise<void> {
  if (!detailDialog.value || store.currentItem?.id !== id || dreamDraftChanged.value) return
  const agentId = store.selectedAgentId
  dreamRefreshing.value = true
  try {
    const item = await store.openItem(id)
    if (detailDialog.value && store.currentItem?.id === id && store.selectedAgentId === agentId) {
      prepareEditor(item)
      dreamMediaRevision.value++
    }
    if (agentId !== null) {
      const findings = await memoryService.listFindings(agentId)
      if (store.selectedAgentId === agentId) store.findings = findings
    }
  } catch (error) { notifyError(error) }
  finally { dreamRefreshing.value = false }
}

function relationLabel(relation: string): string {
  const key = `memory.relationTypes.${relation}`
  return te(key) ? t(key) : t('memory.otherRelation')
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
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

async function openDetail(id: string, node?: MemoryGraphNode, relations: MemoryGraphRelation[] = []): Promise<void> {
  if (store.hits.some(hit => hit.item.id === id && hit.item.node_kind === 'folder')) return
  editingId.value = null
  graphContext.value = node ? { node, relations } : null
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

async function openGraphNeighbor(id: string): Promise<void> {
  detailDialog.value = false
  await nextTick()
  memoryGraph.value?.selectNode(id)
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
    temporal: null,
    content: '',
    nodeKind: 'memory',
    keywords: [], revision: null, lockVersion: null,
    mediaType: 'text/html', contentType: 'text',
  })
  editorBase.value = null
}

function openCreate(): void {
  editingId.value = null
  resetEditor()
  editorDialog.value = true
}

function prepareEditor(item: MemoryItemDetail): void {
  editingId.value = item.id
  Object.assign(editor, {
    temporal: item.temporal ? { ...item.temporal } : null,
    content: item.payload.text ?? '',
    nodeKind: item.node_kind,
    keywords: [...item.keywords],
    revision: item.revision,
    lockVersion: item.lock_version,
    mediaType: item.media_type, contentType: item.content_type,
  })
  editorBase.value = item
}

async function saveEditor(): Promise<void> {
  if (editorSaving.value || dreamBusy.value || dreamRefreshing.value) return
  if (store.selectedAgentId === null) return
  if (detailDialog.value && !canModifyCurrent.value) return
  const keywords = [...new Set(editor.keywords.map(value => value.trim()).filter(Boolean))]
  const wasEditing = editingId.value !== null
  editorSaving.value = true
  try {
    if (editingId.value) {
      await store.updateItem(editingId.value, {
        expected_revision: editor.revision ?? undefined,
        expected_lock_version: editor.lockVersion ?? undefined,
        temporal: editor.temporal,
        payload: { text: editor.content },
        media_type: editor.mediaType,
        keywords,
      })
    } else {
      const created = await store.createItem({
        owner_agent_id: store.selectedAgentId,
        temporal: editor.temporal,
        payload: { text: editor.content },
        media_type: editor.mediaType,
        node_kind: editor.nodeKind,
        keywords,
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

let initializingAgent = true
let pageDisposed = false
onBeforeUnmount(() => { pageDisposed = true })
watch(() => store.selectedAgentId, (agentId, previousAgentId) => {
  if (agentId !== previousAgentId) {
    detailDialog.value = false
    graphContext.value = null
    store.selectedTopicItemId = null
    store.selectedContactItemId = null
    topicFilterOptions.value = []
    contactFilterOptions.value = []
  }
  if (initializingAgent) return
  void Promise.all([
    loadFilterOptions(agentId),
    searchSafely(true),
  ]).catch(notifyError)
})

onMounted(async () => {
  try {
    await agentStore.fetchAgents()
    if (pageDisposed) return
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
    initializingAgent = false
    await Promise.all([
      loadFilterOptions(store.selectedAgentId),
      searchSafely(true),
    ])
  } catch (error) {
    notifyError(error)
  } finally {
    initializingAgent = false
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
.memory-filter-block__form {
  display: grid;
  gap: 12px;
  padding: 16px;
}

.memory-filter-block__row {
  display: grid;
  gap: 12px;
  align-items: start;
}

.memory-filter-block__row--primary {
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
}

.memory-filter-block :deep(.q-field__control),
.memory-filter-block :deep(.q-field__marginal) {
  min-height: 44px;
}

.memory-filter-block__temporal {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.memory-filter-block__temporal > .q-field {
  flex: 1;
  min-width: 0;
}

.memory-filter-block__temporal > .q-btn {
  min-height: 44px;
  flex: 0 0 auto;
}

.memory-agent-select :deep(.q-field__native > .row) {
  min-width: 0;
  max-width: 100%;
}

.memory-filter-block__row--secondary {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.memory-filter-block__row--list {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(300px, 1.4fr);
}

.memory-filter-block__field {
  min-width: 0;
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
.memory-list-copy,
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
.memory-detail-tabs { background: var(--solaire-gray-light); }
.memory-detail-links { display: grid; align-content: start; gap: 20px; padding: 16px; }
.memory-links-section { min-width: 0; overflow-wrap: anywhere; }
.memory-section-title { display: flex; align-items: center; gap: 8px; font-size: 0.875rem; font-weight: 600; margin-bottom: 8px; }
.memory-section-title > .q-icon { color: var(--solaire-blue-accent); font-size: 18px; }
.memory-detail-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px; }
.memory-detail-actions :deep(.q-btn) { margin: 0; flex: 0 0 auto; width: auto; max-width: none; white-space: nowrap; }
.memory-detail-actions :deep(.q-btn__content) { flex-wrap: nowrap; white-space: nowrap; }
.memory-detail-dream { display: contents; }
.memory-detail-dream :deep(.row.q-gutter-sm) { display: contents; }
.memory-detail-dream :deep(.text-caption) { flex-basis: 100%; text-align: right; margin: 0; }
.memory-detail-save { flex-shrink: 0; }
.memory-detail-heading { display: flex; align-items: center; flex-wrap: wrap; flex: 1; min-width: 0; gap: 8px; }
.memory-detail-heading .q-toolbar__title { padding: 0; }
.memory-detail-badges { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.memory-protection-badge { background: var(--solaire-orange-accent); color: #101010; }
body.body--dark .memory-detail-tabs { background: var(--solaire-gray-dark); }
@media (max-width: 599px) {
  .memory-detail-heading .q-toolbar__title { flex-basis: 100%; }
}
.memory-editor { width: 980px; max-width: 96vw; max-height: 92vh; overflow: auto; }
.memory-detail :deep(.q-toolbar__title),
.memory-editor :deep(.q-toolbar__title) { font-size: 1rem; }
.member-editor { width: min(620px, 94vw); }

@media (max-width: 1023px) {
  .memory-filter-block__row--primary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .memory-filter-block__row--secondary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .memory-filter-block__temporal {
    grid-column: 1 / -1;
  }
}

@media (max-width: 599px) {
  .memory-filter-block__form {
    padding: 12px;
  }

  .memory-filter-block__row--primary,
  .memory-filter-block__row--secondary {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
