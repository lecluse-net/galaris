<template>
  <q-page
    class="messenger-page"
    :class="{ 'messenger-page--dark': $q.dark.isActive, 'q-dark': $q.dark.isActive }"
    :style-fn="chatPageStyle"
  >
    <q-banner v-if="store.status && !store.enabled" class="bg-warning text-dark q-ma-md" rounded>{{ t('chat.disabled') }}</q-banner>
    <q-inner-loading :showing="store.loading" />
    <div ref="messengerGrid" v-if="store.enabled" class="messenger-grid" :class="{ 'messenger-grid--empty': !store.selectedRoom, 'messenger-grid--resizing': resizingColumns, 'messenger-grid--document': integratedDocument }" :style="messengerGridStyle">
      <section v-if="store.selectedRoom" class="chat-workspace" :class="{ 'mobile-hidden': $q.screen.lt.md && mobileView !== 'conversation' }">
        <div ref="documentWorkspace" class="chat-workspace-content" :class="{ 'chat-workspace-content--document': integratedDocument, 'chat-workspace-content--rows': effectiveDocumentLayout === 'rows', 'chat-workspace-content--resizing': resizingDocument }" :style="documentWorkspaceStyle">
      <main class="conversation-pane">
        <template v-if="store.selectedRoom">
          <q-toolbar class="conversation-toolbar"><template v-if="!integratedDocument"><q-btn v-if="$q.screen.lt.md" flat round dense icon="arrow_back" :aria-label="t('chat.details')" @click="mobileView = 'details'" /><q-btn v-if="canReadDocuments && store.viewerAgentId === null" flat round dense icon="search" :aria-label="t('chat.searchDocuments')" @click="documentSearchOpen = true"><q-tooltip>{{ t('chat.searchDocuments') }}</q-tooltip></q-btn></template><InternalAgentAvatar :agent-id="store.selectedRoom.agent_id" :name="store.selectedRoom.agent_name" size="36px" class="q-ml-xs" /><q-toolbar-title class="conversation-title">{{ store.selectedRoom.label }}</q-toolbar-title><q-btn flat round dense size="xs" icon="content_copy" class="room-id-copy" :aria-label="t('chat.copyRoomId')" :title="store.selectedRoom.id" @click="copyRoomId"><q-tooltip>{{ store.selectedRoom.id }}</q-tooltip></q-btn><q-badge v-if="store.selectedRoom.source" outline color="grey-7" :label="t(sourceTranslationKey(store.selectedRoom.source))" /><q-chip v-if="!canWriteSelectedRoom" dense outline color="grey-7" icon="lock" class="read-only-chip">{{ t('chat.readOnly') }}</q-chip><q-btn v-if="inboxStore.pushSupported && inboxStore.pushAvailable" flat round :loading="inboxStore.loading" :icon="inboxStore.subscribed ? 'notifications_active' : 'notifications_none'" :aria-label="t(inboxStore.subscribed ? 'chat.notifications.disableDevice' : 'chat.notifications.enableDevice')" @click="toggleDeviceNotifications" /><q-btn v-if="canCustomizeSelectedRoom" flat round icon="settings" :aria-label="t('chat.roomPreferences.open')" @click="preferencesDialog=true" /><q-btn v-if="canWriteSelectedRoom" flat round :icon="store.selectedRoom.muted ? 'notifications_off' : 'notifications'" :aria-label="t('chat.mute')" @click="toggleMute" /><VoiceCallPanel v-if="store.viewerAgentId === null && store.selectedRoom.agent_active && canCall && store.callAvailable" :room-id="store.selectedRoom.id" :language="locale" :active-call-id="store.activeCall?.call_id" :stopping-call-id="store.stoppingCallId" :ended-call-id="store.endedCallId" :mobile="$q.screen.lt.md" @error="reportError" @starting="store.prepareCallStart" @stopping="store.markCallStopping" @ended="refreshAfterCallEnded" /></q-toolbar>
          <div class="message-scroll-zone">
            <q-scroll-area ref="messageScrollArea" class="message-scroll" @scroll="onMessageScroll" @wheel.passive="beginConversationHistoryNavigation" @touchstart.passive="beginConversationHistoryNavigation"><div v-if="store.loadingOlderMessages" class="history-loader"><q-spinner color="primary" size="20px" /></div><MessageTimeline :room-id="store.selectedRoom.id" :messages="store.messages" :activity="store.activity" :live-round="store.liveRound" :pending-transcriptions="store.pendingVoiceTranscriptions" :agent-id="store.selectedRoom.agent_id" :agent-name="store.selectedRoom.agent_name" :loading="store.loadingSelectedRoom" :viewer-agent-id="store.viewerAgentId" :show-agent-avatars="!store.selectedRoom.source" :allow-reply="canWriteSelectedRoom" :can-read-documents="canReadDocuments" :can-edit-documents="canEditDocuments" @open-document="openConversationDocument" @reply="message => replyingTo = message" @topic-changed="refreshMessageTopics" @block-rendered="scrollRenderedConversationToBottom" @layout-changed="keepConversationAtBottom" @message-visible="markVisibleMessageRead" /></q-scroll-area>
            <transition name="scroll-to-bottom">
              <q-btn
                v-if="showScrollToBottom"
                class="scroll-to-bottom-button"
                flat
                round
                dense
                icon="keyboard_arrow_down"
                :aria-label="t('chat.scrollToBottom')"
                @click="scrollConversationToBottom"
              ><q-tooltip>{{ t('chat.scrollToBottom') }}</q-tooltip></q-btn>
            </transition>
          </div>
          <template v-if="canWriteSelectedRoom"><q-separator /><Composer :before-send="prepareMessage" :room-id="store.selectedRoom.id" :sending="store.sending" :commands="store.commands" :reply-to="replyingTo" :topic-id="selectedTopicId" :can-select-topic="canSelectTopic" :max-attachment-bytes="store.status?.max_attachment_bytes ?? 0" @send="sendMessage" @cancel-reply="replyingTo=null" @update:topic-id="selectedTopicId=$event" @error="reportError" /></template>
        </template>
      </main>
          <div v-if="integratedDocument" class="document-resizer" :class="{ 'document-resizer--rows': effectiveDocumentLayout === 'rows' }"
            role="separator" tabindex="0" :aria-label="t('chat.resizeDocument')"
            :aria-orientation="effectiveDocumentLayout === 'rows' ? 'horizontal' : 'vertical'"
            :aria-valuenow="documentChatRatio" :aria-valuemin="documentRatioLimits[0]" :aria-valuemax="documentRatioLimits[1]"
            @pointerdown="startDocumentResize" @pointermove="moveDocumentResize" @pointerup="finishDocumentResize"
            @pointercancel="finishDocumentResize" @lostpointercapture="finishDocumentResize" @keydown="resizeDocumentWithKeyboard"
          ><span class="column-resizer-handle"><q-icon name="drag_indicator" size="16px" /></span></div>
          <ChatDocumentPane v-if="integratedDocument" ref="documentPane" :document="integratedDocument" :agent-id="selectedDocumentAgentId" :editable="canEditDocuments" @available="displayedDocumentId = $event" @unavailable="displayedDocumentId = null" @close="selectedDocument = null">
            <template #actions>
              <q-btn v-if="canReadDocuments && store.viewerAgentId === null" flat round dense icon="search" :aria-label="t('chat.searchDocuments')" @click="documentSearchOpen = true"><q-tooltip>{{ t('chat.searchDocuments') }}</q-tooltip></q-btn>
              <q-btn flat round dense icon="view_column" :aria-label="t('chat.documentColumns')" :aria-pressed="effectiveDocumentLayout === 'columns'" :color="effectiveDocumentLayout === 'columns' ? 'primary' : undefined" @click="documentLayout = 'columns'"><q-tooltip>{{ t('chat.documentColumns') }}</q-tooltip></q-btn>
              <q-btn flat round dense icon="view_agenda" :aria-label="t('chat.documentRows')" :aria-pressed="effectiveDocumentLayout === 'rows'" :color="effectiveDocumentLayout === 'rows' ? 'primary' : undefined" @click="documentLayout = 'rows'"><q-tooltip>{{ t('chat.documentRows') }}</q-tooltip></q-btn>
            </template>
          </ChatDocumentPane>
        </div>
      </section>
      <div
        v-if="store.selectedRoom && sidebarVisible"
        class="column-resizer"
        role="separator"
        tabindex="0"
        aria-orientation="vertical"
        :aria-label="t('chat.resizeColumns')"
        :aria-valuenow="Math.round(conversationRatio)"
        @pointerdown="startColumnResize"
        @pointermove="moveColumnResize"
        @pointerup="finishColumnResize"
        @pointercancel="finishColumnResize"
        @lostpointercapture="finishColumnResize"
        @keydown="resizeColumnsWithKeyboard"
      ><span class="column-resizer-handle"><q-icon name="drag_indicator" size="16px" /></span></div>
      <aside id="chat-details" v-show="!$q.screen.lt.md || sidebarVisible || !store.selectedRoom" class="details-pane" :class="{ 'details-pane--empty': !store.selectedRoom }">
        <q-toolbar v-if="$q.screen.lt.md && store.selectedRoom" class="sidebar-mobile-toolbar"><q-btn flat round dense icon="arrow_back" :aria-label="t('chat.backToConversation')" @click="mobileView='conversation'" /><q-toolbar-title>{{ t('chat.details') }}</q-toolbar-title></q-toolbar>
        <ContextHelp help-key="chat" :text="t('contextHelpPages.chat')" />
        <q-list id="chat-sidebar-content" v-show="sidebarVisible || !store.selectedRoom" class="sidebar-accordion" :class="{ 'sidebar-accordion--empty': !store.selectedRoom }">
          <q-expansion-item v-if="store.selectedRoom" v-model="conversationsExpanded" dense-toggle expand-separator icon="forum" :label="t('chat.conversations')" class="sidebar-accordion-item" :class="{ 'sidebar-accordion-item--open': conversationsExpanded }" header-class="sidebar-accordion-header">
            <template #header>
              <q-item-section avatar><q-icon name="forum" /></q-item-section>
              <q-item-section>{{ t('chat.conversations') }}</q-item-section>
              <q-item-section side>
                <div class="row no-wrap">
                  <q-btn flat round dense icon="filter_list" class="room-list-options" :color="roomFiltersVisible ? 'primary' : undefined" :aria-label="t('chat.listOptions')" :aria-expanded="roomFiltersVisible" aria-controls="chat-room-filters" @click.stop="toggleRoomFilters" @keydown.stop><q-tooltip>{{ t('chat.listOptions') }}</q-tooltip></q-btn>
                  <q-btn v-if="canCreateRoom" flat round dense color="primary" icon="add" :aria-label="t('chat.newRoom')" @click.stop="openCreate" @keydown.stop><q-tooltip>{{ t('chat.newRoom') }}</q-tooltip></q-btn>
                </div>
              </q-item-section>
            </template>
            <div class="sidebar-section-content"><RoomList :show-filters="roomFiltersVisible" :rooms="store.rooms" :selected-id="store.selectedRoom?.id" :can-create="canCreateRoom" :can-impersonate="canImpersonate" :viewer-agent-id="store.viewerAgentId" :viewer-agents="viewerAgents" :include-external="store.includeExternalRooms" :include-archived="store.includeArchivedRooms" :has-more="store.hasMoreRooms" :loading-more="store.loadingMoreRooms" @select="selectRoom" @search="searchRooms" @toggle-external="toggleExternalRooms" @toggle-archived="toggleArchivedRooms" @load-more="loadMoreRooms" @view-agent="changeViewerAgent" @create="openCreate" /></div>
          </q-expansion-item>
          <section v-else class="sidebar-accordion-item sidebar-accordion-item--open conversations-section">
            <q-item dense class="sidebar-accordion-header">
              <q-item-section avatar><q-icon name="forum" /></q-item-section>
              <q-item-section><q-item-label>{{ t('chat.conversations') }}</q-item-label></q-item-section>
              <q-item-section side>
                <div class="row no-wrap">
                  <q-btn flat round dense icon="filter_list" class="room-list-options" :color="roomFiltersVisible ? 'primary' : undefined" :aria-label="t('chat.listOptions')" :aria-expanded="roomFiltersVisible" aria-controls="chat-room-filters" @click.stop="toggleRoomFilters" @keydown.stop><q-tooltip>{{ t('chat.listOptions') }}</q-tooltip></q-btn>
                  <q-btn v-if="canCreateRoom" flat round dense color="primary" icon="add" :aria-label="t('chat.newRoom')" @click.stop="openCreate" @keydown.stop><q-tooltip>{{ t('chat.newRoom') }}</q-tooltip></q-btn>
                </div>
              </q-item-section>
            </q-item>
            <div class="sidebar-section-content"><RoomList :show-filters="roomFiltersVisible" :rooms="store.rooms" :can-create="canCreateRoom" :can-impersonate="canImpersonate" :viewer-agent-id="store.viewerAgentId" :viewer-agents="viewerAgents" :include-external="store.includeExternalRooms" :include-archived="store.includeArchivedRooms" :has-more="store.hasMoreRooms" :loading-more="store.loadingMoreRooms" @select="selectRoom" @search="searchRooms" @toggle-external="toggleExternalRooms" @toggle-archived="toggleArchivedRooms" @load-more="loadMoreRooms" @view-agent="changeViewerAgent" @create="openCreate" /></div>
          </section>
          <q-expansion-item v-if="store.selectedRoom" v-model="documentsExpanded" dense-toggle expand-separator icon="description" :label="t('chat.workingDocuments')" class="sidebar-accordion-item" :class="{ 'sidebar-accordion-item--open': documentsExpanded }" header-class="sidebar-accordion-header">
            <template #header>
              <q-item-section avatar><q-icon name="description" /></q-item-section>
              <q-item-section>{{ t('chat.workingDocuments') }}</q-item-section>
              <q-item-section v-if="canReadDocuments && canEditDocuments" side>
                <q-btn flat round dense color="primary" icon="add" :aria-label="t('chat.createDocument')" @click.stop="conversationDocumentsPanel?.openCreateDocument()" @keydown.stop>
                  <q-tooltip>{{ t('chat.createDocument') }}</q-tooltip>
                </q-btn>
              </q-item-section>
            </template>
            <div class="sidebar-section-content"><ConversationDocumentsPanel embedded :displayed-document-id="selectedDocument?.id === displayedDocumentId ? displayedDocumentId : null" @has-items="documentsExpanded = $event" @open="openConversationDocument" ref="conversationDocumentsPanel" :room-id="store.selectedRoom.id" :from-message-id="visibleFromMessageId" :conversation-agent-id="store.selectedRoom.agent_id" :viewer-agent-id="store.viewerAgentId" :can-read="canReadDocuments" :can-edit="canEditDocuments" /></div>
          </q-expansion-item>
          <q-expansion-item v-if="store.selectedRoom" v-model="tasksExpanded" dense-toggle expand-separator icon="account_tree" :label="t('chat.tasks')" class="sidebar-accordion-item" :class="{ 'sidebar-accordion-item--open': tasksExpanded }" header-class="sidebar-accordion-header">
            <div class="sidebar-section-content"><AgentTasksPanel @has-items="tasksExpanded = $event" ref="agentTasksPanel" embedded :room-id="store.selectedRoom.id" :from-message-id="visibleFromMessageId" :conversation-agent-id="store.selectedRoom.agent_id" :viewer-agent-id="store.viewerAgentId" :can-read="canReadTasks" /></div>
          </q-expansion-item>
          <q-expansion-item v-if="store.selectedRoom" v-model="processesExpanded" dense-toggle expand-separator icon="schema" :label="t('chat.processes')" class="sidebar-accordion-item" :class="{ 'sidebar-accordion-item--open': processesExpanded }" header-class="sidebar-accordion-header">
            <div class="sidebar-section-content"><ConversationProcessesPanel @has-items="processesExpanded = $event" ref="conversationProcessesPanel" :room-id="store.selectedRoom.id" :from-message-id="visibleFromMessageId" :viewer-agent-id="store.viewerAgentId" :can-read="canReadProcesses" /></div>
          </q-expansion-item>
        </q-list>
      </aside>
    </div>

    <RoomCreateDialog v-model="createDialog" :agents="recipients.agents" :saving="creatingRoom" :can-edit-topic="canEditConversationTopic" @create="createRoom" />
    <RoomPreferencesDialog v-model="preferencesDialog" :room="store.selectedRoom" :saving="savingRoomPreferences" :archiving="archivingRoom" :can-edit-topic="canEditConversationTopic" @save="saveRoomPreferences" @archive="setRoomArchived" />
    <ConversationDocumentDialog ref="mobileDocument" v-model="mobileDocumentOpen" :document-id="selectedDocument?.id ?? null"
      :agent-id="selectedDocumentAgentId" :title="selectedDocument?.title ?? t('chat.workingDocument')" :editable="canEditDocuments" @changed="displayedDocumentId = $event.id" @unavailable="displayedDocumentId = null" />
    <ChatDocumentSearchDialog v-if="canReadDocuments && store.viewerAgentId === null" v-model="documentSearchOpen" @select="openLibraryDocument" />
  </q-page>
</template>

<script setup lang="ts">
import { ContextHelp } from '@/core/util'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { apiErrorDetail } from '@/core/api'
import { websocket } from '@/core/websocket'
import { privileges } from '@/core/authorize'
import { usePrivilegeStore } from '@/core/authorize/stores/privilegeStore'
import RoomList from '../components/RoomList.vue'; import MessageTimeline from '../components/MessageTimeline.vue'; import Composer from '../components/Composer.vue'; import AgentTasksPanel from '../components/AgentTasksPanel.vue'; import VoiceCallPanel from '../components/VoiceCallPanel.vue'; import InternalAgentAvatar from '../components/InternalAgentAvatar.vue'
import RoomPreferencesDialog from '../components/RoomPreferencesDialog.vue'
import RoomCreateDialog from '../components/RoomCreateDialog.vue'
import ConversationDocumentsPanel from '../components/ConversationDocumentsPanel.vue'
import ConversationDocumentDialog from '../components/ConversationDocumentDialog.vue'
import ConversationProcessesPanel from '../components/ConversationProcessesPanel.vue'
import ChatDocumentPane from '../components/ChatDocumentPane.vue'
import ChatDocumentSearchDialog from '../components/ChatDocumentSearchDialog.vue'
import type { WorkingDocumentReference } from '@/core/util'
import type { ConversationDocumentReference } from '../types'
import { useChatInboxStore } from '../stores/inbox'
import { sourceTranslationKey } from '../sourcePresentation'
import { useChatStore } from '../stores/chat'; import { chatService as service } from '../services/chatService'; import type { ChatViewerAgent, MessageTopicChange, MessengerMessage, MessengerRoom, ReasoningEffort, RecipientCatalog } from '../types'

const $q=useQuasar(); const {t,locale}=useI18n(); const route=useRoute(); const store=useChatStore(); const inboxStore=useChatInboxStore(); const privilegeStore=usePrivilegeStore(); const mobileView=ref<'conversation'|'details'>('details'); const createDialog=ref(false); const creatingRoom=ref(false); const preferencesDialog=ref(false); const savingRoomPreferences=ref(false); const archivingRoom=ref(false); const conversationsExpanded=ref(false); const tasksExpanded=ref(false); const documentsExpanded=ref(false); const processesExpanded=ref(false); const recipients=ref<RecipientCatalog>({agents:[]}); const viewerAgents=ref<ChatViewerAgent[]>([]); const roomSearch=ref(''); const replyingTo=ref<MessengerMessage|null>(null); const selectedTopicId=ref<string|null>(null)
const roomFiltersVisible = ref(false)
function toggleRoomFilters(): void {
  roomFiltersVisible.value = !roomFiltersVisible.value
  if (roomFiltersVisible.value) conversationsExpanded.value = true
  else if (!store.rooms.length) conversationsExpanded.value = false
}
const chatPageVisible=ref(document.visibilityState==='visible')
const selectedDocument = ref<WorkingDocumentReference | null>(null)
const selectedDocumentAgentId = ref<number | null>(null)
const displayedDocumentId = ref<string | null>(null)
const documentPane = ref<InstanceType<typeof ChatDocumentPane> | null>(null)
const mobileDocument = ref<InstanceType<typeof ConversationDocumentDialog> | null>(null)
watch([() => selectedDocument.value?.id, selectedDocumentAgentId], () => { displayedDocumentId.value = null }, { flush: 'sync' })
const documentSearchOpen = ref(false)
const documentLayout = ref<'columns' | 'rows'>('columns')
const integratedDocument = computed(() => !$q.screen.lt.md && canReadDocuments.value ? selectedDocument.value : null)
const mobileDocumentOpen = computed({
  get: () => $q.screen.lt.md && canReadDocuments.value && selectedDocument.value !== null,
  set: (open: boolean) => { if (!open && $q.screen.lt.md) selectedDocument.value = null },
})
const documentWorkspace = ref<HTMLElement | null>(null)
const documentWorkspaceWidth = ref(0)
const minimumDocumentWidth = 560
const minimumChatWidth = 320
const effectiveDocumentLayout = computed(() => documentLayout.value === 'columns'
  && documentWorkspaceWidth.value < minimumChatWidth + 8 + minimumDocumentWidth ? 'rows' : documentLayout.value)
watch(documentWorkspace, (element, _previous, onCleanup) => {
  if (!element) return
  const measure = () => { documentWorkspaceWidth.value = element.getBoundingClientRect().width }
  const observer = new ResizeObserver(measure)
  observer.observe(element)
  measure()
  onCleanup(() => observer.disconnect())
}, { flush: 'post' })
const documentRatios = ref({ columns: 50, rows: 50 })
const documentRatioLimits = computed<[number, number]>(() => {
  if (effectiveDocumentLayout.value === 'rows') return [20, 80]
  const available = Math.max(1, documentWorkspaceWidth.value - 8)
  const maximum = Math.max(0, Math.min(80, (available - minimumDocumentWidth) / available * 100))
  return [Math.min(maximum, Math.max(20, minimumChatWidth / available * 100)), maximum]
})
const documentChatRatio = computed(() => {
  const [minimum, maximum] = documentRatioLimits.value
  return Math.min(maximum, Math.max(minimum, documentRatios.value[effectiveDocumentLayout.value]))
})
const documentWorkspaceStyle = computed(() => ({
  '--chat-share': `${documentChatRatio.value}fr`,
  '--document-share': `${100 - documentChatRatio.value}fr`,
  '--document-min-width': `${minimumDocumentWidth}px`,
}))
const resizingDocument = ref(false)
let documentResize: { pointerId: number; coordinate: number; ratio: number } | null = null
watch(effectiveDocumentLayout, () => { documentResize = null; resizingDocument.value = false })
function setDocumentChatRatio(value: number): void {
  const [minimum, maximum] = documentRatioLimits.value
  documentRatios.value[effectiveDocumentLayout.value] = Math.min(maximum, Math.max(minimum, value))
}
function startDocumentResize(event: PointerEvent): void {
  if (event.button !== 0 || !event.isPrimary) return
  documentResize = { pointerId: event.pointerId, coordinate: effectiveDocumentLayout.value === 'rows' ? event.clientY : event.clientX, ratio: documentChatRatio.value }
  resizingDocument.value = true
  const target = event.currentTarget as HTMLElement
  target.focus({ preventScroll: true })
  target.setPointerCapture(event.pointerId)
  event.preventDefault()
}
function moveDocumentResize(event: PointerEvent): void {
  const bounds = documentWorkspace.value?.getBoundingClientRect()
  if (!documentResize || documentResize.pointerId !== event.pointerId || !bounds) return
  const rows = effectiveDocumentLayout.value === 'rows'
  const distance = (rows ? event.clientY : event.clientX) - documentResize.coordinate
  setDocumentChatRatio(documentResize.ratio + distance / Math.max(1, (rows ? bounds.height : bounds.width) - 8) * 100)
}
function finishDocumentResize(event: PointerEvent): void {
  if (documentResize?.pointerId !== event.pointerId) return
  documentResize = null
  resizingDocument.value = false
  const target = event.currentTarget as HTMLElement
  if (target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId)
}
function resizeDocumentWithKeyboard(event: KeyboardEvent): void {
  const [decrease, increase] = effectiveDocumentLayout.value === 'rows' ? ['ArrowUp', 'ArrowDown'] : ['ArrowLeft', 'ArrowRight']
  if (![decrease, increase, 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  setDocumentChatRatio(event.key === 'Home' ? 20 : event.key === 'End' ? 80 : documentChatRatio.value + (event.key === decrease ? -2 : 2))
}
const sidebarVisible = computed(() => !$q.screen.lt.md || mobileView.value === 'details')
async function openLibraryDocument(document: WorkingDocumentReference): Promise<void> {
  const roomId = store.selectedRoom?.id
  if (documentPane.value && !await documentPane.value.flush()) return
  if (store.selectedRoom?.id !== roomId) return
  selectedDocumentAgentId.value = null
  selectedDocument.value = document
  mobileView.value = 'conversation'
}
async function openConversationDocument(document: Pick<ConversationDocumentReference, 'id' | 'label'>): Promise<void> {
  const roomId = store.selectedRoom?.id
  if (documentPane.value && !await documentPane.value.flush()) return
  if (store.selectedRoom?.id !== roomId) return
  selectedDocumentAgentId.value = store.viewerAgentId ?? store.selectedRoom?.agent_id ?? null
  selectedDocument.value = { id: document.id, title: document.label }
  mobileView.value = 'conversation'
}
let documentDisplayRequest = 0
watch(() => store.selectedRoom?.id, () => { documentDisplayRequest += 1 }, { flush: 'sync' })
watch(selectedDocument, () => { documentDisplayRequest += 1 }, { flush: 'sync' })
async function onDocumentShow(event: { data?: { room_id?: string; document_id?: string } }): Promise<void> {
  const room = store.selectedRoom
  const id = event.data?.document_id
  if (!room || room.source || event.data?.room_id !== room.id || !id || !canReadDocuments.value) return
  const request = ++documentDisplayRequest
  try {
    if (documentPane.value && !await documentPane.value.flush()) return
    if (mobileDocumentOpen.value && !await mobileDocument.value?.flush()) return
    if (request !== documentDisplayRequest || store.selectedRoom?.id !== room.id) return
    // Load through the existing viewer-authorized editor; the event grants no access.
    selectedDocumentAgentId.value = store.viewerAgentId ?? room.agent_id
    selectedDocument.value = { id, title: t('chat.workingDocument') }
    mobileView.value = 'conversation'
  } catch (error) {
    reportError(error)
  }
}
onMounted(() => websocket.onEvent('chat', 'document_show', onDocumentShow))
onBeforeUnmount(() => {
  documentDisplayRequest += 1
  websocket.offEvent('chat', 'document_show', onDocumentShow)
})
const chatPageFocused=ref(document.hasFocus())
const latestIntersectingMessageId=ref<string|null>(null)
const conversationSurfaceVisible=computed(() => !$q.screen.lt.md || mobileView.value === 'conversation' || integratedDocument.value !== null)
const displayedConversationRoomId=computed(() => chatPageVisible.value && conversationSurfaceVisible.value ? store.selectedRoom?.id ?? null : null)
type MessageScrollArea = { getScroll: () => { verticalSize: number }; setScrollPosition: (axis: 'vertical', offset: number, duration?: number) => void; setScrollPercentage: (axis: 'vertical', offset: number, duration?: number) => void }
type MessageScrollInfo = { verticalPosition: number; verticalSize: number; verticalContainerSize: number }
type BottomScrollablePanelHandle = { scrollToBottom: () => void }
const messageScrollArea=ref<MessageScrollArea|null>(null)
const agentTasksPanel=ref<BottomScrollablePanelHandle|null>(null)
const conversationProcessesPanel=ref<BottomScrollablePanelHandle|null>(null)
const conversationDocumentsPanel=ref<(BottomScrollablePanelHandle & { openCreateDocument: () => void })|null>(null)
const messengerGrid=ref<HTMLElement|null>(null)
const conversationRatio=ref(68)
const resizingColumns=ref(false)
const showScrollToBottom=ref(false)
let resizingPointerId:number|null=null
let historyScrollEnabled=false
let restoringHistoryPosition=false
let followingConversationBottom=false
let historyNavigationRequested=false
let conversationScrollRevision=0
const conversationBottomThreshold=24
function chatPageStyle(offset:number,height:number):{height:string;minHeight:string}{const availableHeight=Math.max(0,height-offset);return{height:`${availableHeight}px`,minHeight:`${availableHeight}px`}}
const messengerGridStyle=computed(()=>store.selectedRoom ? {'--conversation-width':`clamp(420px, calc(${conversationRatio.value}% - ${8*conversationRatio.value/100}px), calc(100% - 328px))`} : undefined)
const visibleFromMessageId=computed(()=>store.messages[0]?.id ?? null)
function columnRatioLimits():[number,number]{const width=Math.max(1,(messengerGrid.value?.getBoundingClientRect().width??0)-8);const minimumConversation=Math.min(420,width*.6);const minimumDetails=Math.min(320,width*.4);return[minimumConversation/width*100,(width-minimumDetails)/width*100]}
function setConversationRatio(value:number){const[min,max]=columnRatioLimits();conversationRatio.value=Math.min(max,Math.max(min,value))}
function resizeColumnsAt(clientX:number){const bounds=messengerGrid.value?.getBoundingClientRect();if(!bounds)return;const available=Math.max(1,bounds.width-8);setConversationRatio((clientX-bounds.left)/available*100)}
function startColumnResize(event:PointerEvent){if($q.screen.lt.md)return;resizingPointerId=event.pointerId;resizingColumns.value=true;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);resizeColumnsAt(event.clientX);event.preventDefault()}
function moveColumnResize(event:PointerEvent){if(resizingPointerId!==event.pointerId)return;resizeColumnsAt(event.clientX)}
function finishColumnResize(event:PointerEvent){if(resizingPointerId!==event.pointerId)return;const target=event.currentTarget as HTMLElement;if(target.hasPointerCapture(event.pointerId))target.releasePointerCapture(event.pointerId);resizingPointerId=null;resizingColumns.value=false}
function resizeColumnsWithKeyboard(event:KeyboardEvent){if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;event.preventDefault();setConversationRatio(conversationRatio.value+(event.key==='ArrowLeft'?-2:2))}
const canManagePrivilege=computed(()=>privilegeStore.hasPrivilege(privileges.CHAT_MANAGE)); const canSend=computed(()=>privilegeStore.hasPrivilege(privileges.CHAT_SEND)); const canCall=computed(()=>privilegeStore.hasPrivilege(privileges.CHAT_CALL)); const canImpersonate=computed(()=>privilegeStore.hasPrivilege(privileges.CHAT_IMPERSONATE)); const canCreateRoom=computed(()=>canManagePrivilege.value&&store.viewerAgentId===null&&store.status?.chat_enabled===true); const canCustomizeSelectedRoom=computed(()=>store.viewerAgentId===null&&store.selectedRoom!==null); const canWriteSelectedRoom=computed(()=>canSend.value&&store.viewerAgentId===null&&store.selectedRoom?.writable===true); const canReadTasks=computed(()=>privilegeStore.hasPrivilege(privileges.TASK_ACCESS)||privilegeStore.hasPrivilege(privileges.TASK_EDIT)); const canReadDocuments=computed(()=>privilegeStore.hasPrivilege(privileges.MEMORY_ACCESS)||privilegeStore.hasPrivilege(privileges.MEMORY_EDIT)||privilegeStore.hasPrivilege(privileges.MEMORY_ADMIN)); const canEditDocuments=computed(()=>privilegeStore.hasPrivilege(privileges.MEMORY_EDIT)&&store.viewerAgentId===null); const canReadProcesses=computed(()=>privilegeStore.hasPrivilege(privileges.PROCESS_READ)||privilegeStore.hasPrivilege(privileges.PROCESS_LAUNCH)||privilegeStore.hasPrivilege(privileges.PROCESS_ADMIN)); const canSelectTopic=computed(()=>privilegeStore.hasPrivilege(privileges.TOPIC_ACCESS)||privilegeStore.hasPrivilege(privileges.TOPIC_EDIT))
const canEditConversationTopic=computed(()=>privilegeStore.hasPrivilege(privileges.TOPIC_EDIT)&&store.viewerAgentId===null)
watch([() => store.selectedRoom?.id, () => store.viewerAgentId, canReadDocuments], () => {
  selectedDocument.value = null
  documentSearchOpen.value = false
})
async function report(action:()=>Promise<void>){try{await action()}catch(error){$q.notify({type:'negative',message:apiErrorDetail(error) ?? t('chat.error')})}}
function reportError(error:unknown){$q.notify({type:'negative',message:apiErrorDetail(error) ?? t('chat.error')})}
async function copyRoomId():Promise<void>{const roomId=store.selectedRoom?.id;if(!roomId)return;try{await copyToClipboard(roomId);$q.notify({type:'positive',icon:'content_copy',message:t('chat.roomIdCopied'),timeout:1600})}catch{$q.notify({type:'negative',message:t('chat.copyRoomIdError')})}}
function refreshAfterCallEnded(){void store.refreshSelected().catch(()=>undefined)}
function refreshMessageTopics(change:MessageTopicChange){store.applyMessageTopicChange(change);void report(()=>store.refreshSelected())}
function nextAnimationFrame():Promise<void>{return new Promise<void>(resolve=>window.requestAnimationFrame(()=>resolve()))}
async function scrollInitialConversationToBottom():Promise<void>{await nextTick();for(let attempt=0;attempt<3;attempt+=1){await nextAnimationFrame();const scroll=messageScrollArea.value;if(!scroll)return;scroll.setScrollPosition('vertical',scroll.getScroll().verticalSize,0)}}
function scrollConversationToBottom():void{conversationScrollRevision+=1;followingConversationBottom=true;historyNavigationRequested=false;showScrollToBottom.value=false;const scroll=messageScrollArea.value;if(scroll)scroll.setScrollPosition('vertical',scroll.getScroll().verticalSize,0)}
function beginConversationHistoryNavigation():void{conversationScrollRevision+=1;followingConversationBottom=false;historyScrollEnabled=true;historyNavigationRequested=true}
function keepConversationAtBottom():void{if(!followingConversationBottom)return;window.requestAnimationFrame(()=>{if(followingConversationBottom)messageScrollArea.value?.setScrollPercentage('vertical',1,0)})}
async function scrollRenderedConversationToBottom():Promise<void>{const revision=++conversationScrollRevision;followingConversationBottom=true;historyScrollEnabled=false;historyNavigationRequested=false;showScrollToBottom.value=false;await scrollInitialConversationToBottom();await nextAnimationFrame();if(revision!==conversationScrollRevision)return;historyScrollEnabled=true}
async function scrollInitialChatZonesToBottom():Promise<void>{await scrollRenderedConversationToBottom();agentTasksPanel.value?.scrollToBottom();conversationProcessesPanel.value?.scrollToBottom();conversationDocumentsPanel.value?.scrollToBottom()}
async function searchRooms(value:string){roomSearch.value=value;await report(()=>store.loadRooms(value))}
async function toggleExternalRooms(value:boolean){await report(()=>store.loadRooms(roomSearch.value,value))}
async function toggleArchivedRooms(value:boolean){await report(()=>store.loadRooms(roomSearch.value,store.includeExternalRooms,value))}
function loadMoreRooms(){void report(()=>store.loadMoreRooms())}
async function changeViewerAgent(value:number|null){replyingTo.value=null;selectedTopicId.value=null;await report(()=>store.setViewerAgent(value));mobileView.value='details'}
async function selectRoom(room:MessengerRoom){followingConversationBottom=true;historyScrollEnabled=false;showScrollToBottom.value=false;replyingTo.value=null;selectedTopicId.value=null;mobileView.value='conversation';await report(()=>store.selectRoom(room));if(store.selectedRoom?.id===room.id)await scrollInitialChatZonesToBottom()}
async function selectRequestedRoom():Promise<boolean>{const value=route.query.room;const roomId=typeof value==='string'&&value.length>0?value:null;if(!roomId)return false;const room=store.rooms.find(item=>item.id===roomId)??await service.room(roomId);await selectRoom(room);return true}
async function prepareMessage(): Promise<boolean> {
  const roomId = store.selectedRoom?.id
  if (documentPane.value && !await documentPane.value.flush()) {
    $q.notify({type:'negative', message:t('documents.autosaveError')})
    return false
  }
  return store.selectedRoom?.id === roomId
}
async function sendMessage(text:string,files?:File[],reasoningEffortOverride?:ReasoningEffort,taskRequested=false){
  try {
    const documentId = integratedDocument.value?.id === displayedDocumentId.value
      ? displayedDocumentId.value : null
    await store.send(text,files,replyingTo.value?.id ?? null,selectedTopicId.value,reasoningEffortOverride ?? null,taskRequested,documentId,locale.value,documentId ? documentPane.value?.captureFocus() ?? null : null)
    replyingTo.value=null;selectedTopicId.value=null
  } catch(error) { reportError(error) }
}
async function onMessageScroll(info:MessageScrollInfo){const atBottom=info.verticalSize-info.verticalContainerSize-info.verticalPosition<=conversationBottomThreshold;showScrollToBottom.value=historyScrollEnabled&&!atBottom;if(!historyScrollEnabled||restoringHistoryPosition)return;if(atBottom&&(info.verticalPosition>120||!store.hasOlderMessages))void store.loadRecentMessages().catch(()=>undefined);if(!historyNavigationRequested||info.verticalPosition>120||store.loadingOlderMessages||!store.hasOlderMessages)return;restoringHistoryPosition=true;const roomId=store.selectedRoom?.id;const previousSize=info.verticalSize;const previousPosition=info.verticalPosition;try{await store.loadOlderMessages();await nextTick();if(store.selectedRoom?.id!==roomId)return;const currentSize=messageScrollArea.value?.getScroll().verticalSize ?? previousSize;messageScrollArea.value?.setScrollPosition('vertical',previousPosition+currentSize-previousSize);await nextAnimationFrame();await nextAnimationFrame()}finally{restoringHistoryPosition=false}}
async function openCreate(){await report(async()=>{recipients.value=await service.recipients();createDialog.value=true})}
async function createRoom(agentId:number,label:string,topicId:string|null,showLastMessage:boolean){creatingRoom.value=true;try{await report(async()=>{const room=await service.createRoom(agentId,label,topicId,showLastMessage);createDialog.value=false;await store.loadRooms();await selectRoom(room)})}finally{creatingRoom.value=false}}
async function saveRoomPreferences(label:string,showLastMessage:boolean,topicId:string|null){savingRoomPreferences.value=true;try{await store.updateRoomPreferences(label,showLastMessage);if(canEditConversationTopic.value&&topicId!==store.selectedRoom?.topic_id)await store.updateRoomTopic(topicId);preferencesDialog.value=false}catch(error){reportError(error)}finally{savingRoomPreferences.value=false}}
async function setRoomArchived(archived:boolean){archivingRoom.value=true;try{await store.setRoomArchived(archived);preferencesDialog.value=false;$q.notify({type:'positive',message:t(archived?'chat.roomPreferences.archived':'chat.roomPreferences.unarchived')})}catch(error){reportError(error)}finally{archivingRoom.value=false}}
async function toggleMute(){if(!store.selectedRoom)return;await report(async()=>{await service.setMuted(store.selectedRoom!.id,!store.selectedRoom!.muted);await store.refreshSelected()})}
async function toggleDeviceNotifications():Promise<void>{try{if(inboxStore.subscribed){await inboxStore.disablePush();$q.notify({type:'positive',message:t('chat.notifications.disabled')});return}const enabled=await inboxStore.enablePush();if(enabled)$q.notify({type:'positive',message:t('chat.notifications.enabled')});else if(inboxStore.permission==='denied')$q.notify({type:'warning',message:t('chat.notifications.denied')})}catch(error){reportError(error)}}
function retryVisibleRead(){const messageId=latestIntersectingMessageId.value;if(messageId)void markVisibleMessageRead(messageId)}
function updateChatPageVisibility(){chatPageVisible.value=document.visibilityState==='visible';if(chatPageVisible.value)retryVisibleRead()}
function updateChatPageFocus(){chatPageFocused.value=document.hasFocus();if(chatPageFocused.value)retryVisibleRead()}
async function markVisibleMessageRead(messageId:string):Promise<void>{latestIntersectingMessageId.value=messageId;if(!chatPageVisible.value||!chatPageFocused.value||!conversationSurfaceVisible.value||store.loadingSelectedRoom||store.viewerAgentId!==null||!store.messages.some(message=>message.id===messageId))return;await store.markSelectedRoomRead(messageId).catch(()=>undefined);await inboxStore.refreshSummary().catch(()=>undefined)}
watch(() => store.rooms.length > 0, value => { conversationsExpanded.value = value || roomFiltersVisible.value }, { immediate: true })
watch(() => store.selectedRoom?.id ?? null, () => { selectedTopicId.value=null;latestIntersectingMessageId.value=null })
watch(conversationSurfaceVisible, visible => {if(visible)retryVisibleRead()})
watch(displayedConversationRoomId, roomId => {inboxStore.setDisplayedRoom(roomId);store.setDisplayedRoom(roomId)}, {immediate:true})
watch(
  () => route.query.room,
  value => {if(typeof value==='string'&&value&&store.enabled&&store.selectedRoom?.id!==value)void report(()=>selectRequestedRoom().then(()=>undefined))},
)
onMounted(()=>{document.addEventListener('visibilitychange',updateChatPageVisibility);window.addEventListener('focus',updateChatPageFocus);window.addEventListener('blur',updateChatPageFocus);void report(async()=>{await store.initialize();if(canImpersonate.value)viewerAgents.value=await service.viewerAgents();const requestedRoomSelected=await selectRequestedRoom();if(!requestedRoomSelected&&store.selectedRoom){mobileView.value='conversation';await scrollInitialChatZonesToBottom()}})}); onBeforeUnmount(()=>{document.removeEventListener('visibilitychange',updateChatPageVisibility);window.removeEventListener('focus',updateChatPageFocus);window.removeEventListener('blur',updateChatPageFocus);inboxStore.setDisplayedRoom(null);store.setDisplayedRoom(null);store.releaseSelectedRoom()})
</script>

<style scoped>
.messenger-page {
  --chat-page-bg: #eceff3;
  --chat-surface: #fff;
  --chat-surface-raised: #fbfcfe;
  --chat-surface-soft: #f5f7fa;
  --chat-surface-hover: #f4f6fa;
  --chat-surface-selected: #e9efff;
  --chat-surface-sent: #e6efff;
  --chat-parameters-bg: #fff;
  --chat-border: rgba(35, 46, 66, .08);
  --chat-received-border: rgba(86, 105, 137, .2);
  --chat-border-strong: rgba(35, 46, 66, .14);
  --chat-text: #252b36;
  --chat-text-secondary: #596274;
  --chat-text-muted: #7c8798;
  --chat-text-subtle: #98a2b3;
  --chat-task-text-muted: #596274;
  --chat-task-text-subtle: #667085;
  --chat-shadow: rgba(35, 46, 66, .12);
  --chat-danger-soft: rgba(193, 0, 21, .05);
  --chat-thinking-bg: #fff2ce;
  --chat-thinking-text: #8c6417;
  overflow: hidden;
  color: var(--chat-text);
  background: var(--chat-page-bg);
  color-scheme: light;
}

.messenger-page--dark {
  --chat-page-bg: #0e1014;
  --chat-surface: #1b1e23;
  --chat-surface-raised: #24282f;
  --chat-surface-soft: #22262c;
  --chat-surface-hover: #292d34;
  --chat-surface-selected: #253452;
  --chat-surface-sent: #1f365c;
  --chat-parameters-bg: #171a1f;
  --chat-border: rgba(255, 255, 255, .09);
  --chat-received-border: rgba(176, 191, 218, .22);
  --chat-border-strong: rgba(255, 255, 255, .15);
  --chat-text: #e7ebf2;
  --chat-text-secondary: #c3ccda;
  --chat-text-muted: #a2adbd;
  --chat-text-subtle: #8490a2;
  --chat-task-text-muted: #cbd3df;
  --chat-task-text-subtle: #b4bfce;
  --chat-shadow: rgba(0, 0, 0, .38);
  --chat-danger-soft: rgba(255, 82, 82, .08);
  --chat-thinking-bg: #40371f;
  --chat-thinking-text: #f0cf84;
  color-scheme: dark;
}

.messenger-grid {
  display: grid;
  grid-template-columns: var(--conversation-width, clamp(420px, calc(68% - 5.44px), calc(100% - 328px))) 8px minmax(320px, 1fr);
  height: 100%;
}
.messenger-grid--empty { display: flex; width: 100%; min-width: 0; align-items: center; justify-content: center; padding: 24px; }
.messenger-grid--resizing { cursor: col-resize; user-select: none; }
.messenger-grid--document { grid-template-columns: minmax(0, var(--conversation-width)) 8px minmax(240px, 1fr); }
.chat-workspace { display: flex; min-width: 0; min-height: 0; height: 100%; flex-direction: column; overflow: hidden; }
.chat-workspace-content { display: grid; flex: 1; min-height: 0; min-width: 0; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr); }
.chat-workspace-content--document { grid-template-columns: minmax(0, var(--chat-share)) 8px minmax(var(--document-min-width), var(--document-share)); }
.chat-workspace-content--document.chat-workspace-content--rows { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, var(--chat-share)) 8px minmax(0, var(--document-share)); }
.chat-workspace-content--resizing { user-select: none; cursor: col-resize; }
.chat-workspace-content--resizing.chat-workspace-content--rows { cursor: row-resize; }
.chat-workspace-content .conversation-pane { min-height: 0; }
.chat-workspace-content--document .conversation-toolbar { overflow-x: auto; }
.chat-workspace-content--document :deep(.composer-shell) { flex: 0 1 auto; min-height: 0; max-height: 45%; overflow: auto; }
.conversation-pane,
.details-pane { position: relative; display: flex; min-width: 0; height: 100%; flex-direction: column; overflow: hidden; }
.conversation-pane { background: var(--chat-page-bg); }
.column-resizer, .document-resizer { position: relative; z-index: 2; height: 100%; cursor: col-resize; touch-action: none; outline: none; background: color-mix(in srgb, var(--chat-border) 44%, transparent); }
.column-resizer::before, .document-resizer::before { position: absolute; inset: 0 auto 0 3px; width: 2px; background: var(--chat-border-strong); content: ""; transition: background-color .15s ease; }
.column-resizer:hover::before,
.column-resizer:focus-visible::before,
.messenger-grid--resizing .column-resizer::before,
.document-resizer:hover::before,
.document-resizer:focus-visible::before,
.chat-workspace-content--resizing .document-resizer::before { background: var(--q-primary); }
.column-resizer-handle { position: absolute; top: 50%; left: 50%; z-index: 1; display: flex; width: 20px; height: 42px; align-items: center; justify-content: center; transform: translate(-50%, -50%); border: 1px solid var(--chat-border-strong); border-radius: 10px; color: var(--chat-text-muted); background: var(--chat-surface-raised); box-shadow: 0 2px 8px var(--chat-shadow); }
.document-resizer--rows { cursor: row-resize; }
.document-resizer--rows::before { inset: 3px 0 auto; width: auto; height: 2px; }
.document-resizer--rows .column-resizer-handle { transform: translate(-50%, -50%) rotate(90deg); }
.details-pane { color: var(--chat-text); background: var(--chat-surface); }
.details-pane--empty { width: min(620px, 100%); max-width: 100%; height: min(720px, 100%); border: 1px solid var(--chat-border); border-radius: 14px; box-shadow: 0 10px 32px var(--chat-shadow); }
.details-pane--empty .sidebar-accordion { min-width: 0; max-width: 100%; border-radius: inherit; }
.conversation-toolbar { flex: 0 0 auto; min-height: 54px; color: var(--chat-text); background: var(--chat-surface); border-bottom: 1px solid var(--chat-border); }
.conversation-title { color: var(--chat-text-secondary); font-size: .9rem; font-weight: 550; }
.room-id-copy { min-width: 22px; min-height: 22px; color: var(--chat-text-subtle); }
.room-id-copy :deep(.q-icon) { font-size: 13px; }
.room-id-copy:hover,
.room-id-copy:focus-visible { color: var(--q-primary); }
.message-scroll-zone { position: relative; flex: 1 1 auto; min-width: 0; min-height: 0; }
.message-scroll { width: 100%; height: 100%; min-width: 0; min-height: 0; }
.message-scroll :deep(.q-scrollarea__container) { overflow-x: hidden; overflow-anchor: none; }
.message-scroll :deep(.q-scrollarea__content) { width: 100%; min-width: 0 !important; max-width: 100%; }
.message-scroll :deep(.q-scrollarea__bar--h),
.message-scroll :deep(.q-scrollarea__thumb--h) { display: none; }
.scroll-to-bottom-button { position: absolute; right: 14px; bottom: 12px; z-index: 2; color: var(--chat-text-muted); background: color-mix(in srgb, var(--chat-surface-raised) 88%, transparent); border: 1px solid var(--chat-border-strong); box-shadow: 0 2px 8px color-mix(in srgb, var(--chat-shadow) 70%, transparent); opacity: .78; backdrop-filter: blur(5px); transition: color .15s ease, opacity .15s ease, background-color .15s ease; }
.scroll-to-bottom-button:hover,
.scroll-to-bottom-button:focus-visible { color: var(--q-primary); background: var(--chat-surface-raised); opacity: 1; }
.scroll-to-bottom-enter-active,
.scroll-to-bottom-leave-active { transition: opacity .15s ease, transform .15s ease; }
.scroll-to-bottom-enter-from,
.scroll-to-bottom-leave-to { opacity: 0; transform: translateY(6px); }
.history-loader { display: flex; justify-content: center; padding: 7px; background: var(--chat-page-bg); }
.sidebar-mobile-toolbar { flex: 0 0 auto; min-height: 48px; background: var(--chat-surface); border-bottom: 1px solid var(--chat-border); }
.sidebar-mobile-toolbar .q-toolbar__title { font-size: .9rem; font-weight: 600; }
.sidebar-accordion { display: flex; flex: 1 1 auto; min-height: 0; margin-top: 80px; flex-direction: column; overflow: hidden; background: var(--chat-surface); }
.sidebar-accordion--empty { width: 100%; margin-top: 0; }
.sidebar-accordion-item { flex: 0 0 auto; min-height: 0; color: var(--chat-text); background: var(--chat-surface); }
.sidebar-accordion-item--open { flex: 1 1 0; overflow: hidden; }
.conversations-section { display: flex; flex-direction: column; }
.sidebar-accordion-item--open:deep(.q-expansion-item__container) { display: flex; height: 100%; min-height: 0; flex-direction: column; }
.sidebar-accordion-item--open:deep(.q-expansion-item__content) { flex: 1 1 auto; min-height: 0; overflow: hidden; }
.sidebar-accordion:deep(.sidebar-accordion-header) { min-height: 44px; padding: 0 12px; color: var(--chat-text-secondary); background: var(--chat-page-bg); font-size: .78rem; font-weight: 600; }
.sidebar-accordion:deep(.q-item__section--avatar) { min-width: 34px; color: var(--q-primary); }
.sidebar-section-content { display: flex; width: 100%; max-width: 100%; height: 100%; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; border-top: 1px solid var(--chat-border); }
.sidebar-empty { display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 8px; padding: 20px; color: var(--chat-text-subtle); text-align: center; font-size: .75rem; }
.read-only-chip { flex: 0 0 auto; font-size: .67rem; }
.mobile-hidden { display: none; }

@media (max-width: 1023.98px) {
  .conversation-toolbar { min-height: 48px; }
  .messenger-grid { display: block; }
  .messenger-grid--document { display: grid; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) minmax(120px, 30%); }
  .messenger-grid--empty { display: flex; padding: 16px; }
  .column-resizer { display: none; }
  .conversation-pane,
  .details-pane { width: 100%; border: 0; }
  .details-pane--empty { height: 100%; border-radius: 12px; }
  .sidebar-accordion { margin-top: 0; }
}
</style>
