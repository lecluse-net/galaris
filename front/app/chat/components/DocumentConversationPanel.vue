<template>
  <section class="document-conversation" :class="{ 'document-conversation--dark': $q.dark.isActive }" :aria-label="t('chat.documentPanel.title')">
    <q-toolbar>
      <q-icon name="forum" color="primary" />
      <q-toolbar-title class="text-subtitle1">{{ t('chat.documentPanel.title') }}</q-toolbar-title>
      <q-btn v-if="canCreate" flat round dense icon="add" :aria-label="t('chat.newRoom')" :disable="openingCreate" @click="openCreate">
        <q-tooltip>{{ t('chat.newRoom') }}</q-tooltip>
      </q-btn>
      <q-btn flat round dense icon="close" :aria-label="t('chat.documentPanel.hide')" @click="emit('close')" />
    </q-toolbar>
    <q-banner v-if="error" dense role="alert">
      {{ error }}
      <q-btn outline :label="t('common.retry')" @click="retry" />
    </q-banner>
    <q-linear-progress v-if="initializing" indeterminate />
    <template v-if="store.enabled">
      <div class="q-pa-sm">
        <q-select :model-value="store.selectedRoom" :options="roomOptions" option-label="label" option-value="id"
          outlined dense use-input input-debounce="250" :label="t('chat.documentPanel.choose')"
          :loading="searching" @filter="filterRooms" @update:model-value="selectRoom">
          <template #prepend>
            <InternalAgentAvatar v-if="store.selectedRoom" :agent-id="store.selectedRoom.agent_id" :name="store.selectedRoom.agent_name" size="28px" />
          </template>
          <template #before-options>
            <ChatHomePagination class="document-conversation-pagination" :page="roomsPage" :page-size="roomsPageSize"
              :total="roomsTotal" :loading="searching" :label="t('chat.home.conversationPages')"
              @update:page="changePage" @update:page-size="changePageSize" />
          </template>
          <template #option="scope">
            <q-item v-bind="scope.itemProps">
              <q-item-section avatar><InternalAgentAvatar :agent-id="scope.opt.agent_id" :name="scope.opt.agent_name" size="32px" /></q-item-section>
              <q-item-section>
                <q-item-label>{{ scope.opt.label }}</q-item-label>
                <q-item-label caption>{{ scope.opt.agent_name }}</q-item-label>
              </q-item-section>
            </q-item>
          </template>
          <template #no-option><q-item><q-item-section>{{ t('chat.documentPanel.empty') }}</q-item-section></q-item></template>
        </q-select>
      </div>
      <template v-if="store.selectedRoom">
        <div v-if="documentId" class="q-px-sm q-pb-sm text-caption">{{ t('chat.documentPanel.context') }}</div>
        <q-scroll-area ref="scrollArea" class="document-conversation-messages" @scroll="onScroll">
          <MessageTimeline :room-id="store.selectedRoom.id" :messages="store.messages" :activity="store.activity"
            :live-round="store.liveRound" :pending-transcriptions="store.pendingVoiceTranscriptions"
            :agent-id="store.selectedRoom.agent_id" :agent-name="store.selectedRoom.agent_name"
            :loading="store.loadingSelectedRoom" :allow-reply="canSend" :can-read-documents="canReadDocuments"
            :can-edit-documents="false" @reply="replyingTo = $event" @controlled="refresh"
            @open-document="emit('open-document', $event.id)" @block-rendered="followBottom" @layout-changed="followBottom"
            @message-visible="markVisibleRead" />
        </q-scroll-area>
        <q-separator />
        <Composer v-if="canSend" :room-id="store.selectedRoom.id" :sending="store.sending" :commands="store.commands"
          :reply-to="replyingTo" :before-send="prepare" :max-attachment-bytes="store.status?.max_attachment_bytes ?? 0"
          @cancel-reply="replyingTo = null" @send="send" @error="reportError" />
        <div v-else class="q-pa-sm text-caption">{{ t('chat.readOnly') }}</div>
      </template>
      <div v-else class="q-pa-md text-caption">{{ t('chat.documentPanel.start') }}</div>
    </template>
    <div v-else-if="!initializing && !error" class="q-pa-md">{{ t('chat.disabled') }}</div>
    <RoomCreateDialog v-model="createOpen" :agents="recipients" :saving="creating" @create="createRoom" />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import type { QScrollArea } from 'quasar'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { websocket } from '@/core/websocket'
import type { DocumentFocus } from '@/core/util'
import { useChatState } from '../stores/chat'
import { chatService } from '../services/chatService'
import { useConversationVisibility } from '../useConversationVisibility'
import MessageTimeline from './MessageTimeline.vue'
import Composer from './Composer.vue'
import RoomCreateDialog from './RoomCreateDialog.vue'
import InternalAgentAvatar from './InternalAgentAvatar.vue'
import ChatHomePagination from './ChatHomePagination.vue'
import type { MessengerAgent, MessengerMessage, MessengerRoom, ReasoningEffort } from '../types'

const { documentId = null, beforeSend, captureDocumentFocus, visible = true } = defineProps<{
  documentId?: string | null; beforeSend: () => Promise<boolean>; captureDocumentFocus?: () => DocumentFocus | null; visible?: boolean
}>()
const emit = defineEmits<{ close: []; 'open-document': [id: string] }>()
const { t, locale } = useI18n()
const privilegeStore = usePrivilegeStore()
const store = reactive(useChatState())
const { markVisibleMessageRead: markVisibleRead } = useConversationVisibility({
  roomId: () => store.selectedRoom?.id ?? null,
  visible: () => visible,
  canRead: () => !store.loadingSelectedRoom && store.viewerAgentId === null,
  markRead: id => store.markSelectedRoomRead(id),
  setDisplayedRoom: id => store.setDisplayedRoom(id),
})
const scrollArea = useTemplateRef<QScrollArea>('scrollArea')
const initializing = ref(false), searching = ref(false), error = ref('')
const openingCreate = ref(false), creating = ref(false), createOpen = ref(false)
const recipients = ref<MessengerAgent[]>([])
const replyingTo = ref<MessengerMessage | null>(null)
const canCreate = computed(() => privilegeStore.hasPrivilege(privileges.CHAT_MANAGE) && store.status?.chat_enabled === true)
const canSend = computed(() => privilegeStore.hasPrivilege(privileges.CHAT_SEND) && store.selectedRoom?.writable === true && store.viewerAgentId === null)
const canReadDocuments = computed(() => [privileges.DOCUMENT_ACCESS, privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN].some(privilege => privilegeStore.hasPrivilege(privilege)))
const rooms = ref<MessengerRoom[]>([])
const roomsPage = ref(1), roomsPageSize = ref(50), roomsTotal = ref(0)
const roomOptions = computed(() => rooms.value.filter(room => room.conversation_type !== 'audio'))
let roomSearch = ''
let disposed = false, searchGeneration = 0
let following = true, preparedDocumentId: string | null = null
let preparedDocumentFocus: DocumentFocus | null = null
let retryAction: () => Promise<unknown> = initialize

function reportError(): void { if (!disposed) error.value = t('chat.error') }
async function run(action: () => Promise<unknown>): Promise<void> {
  error.value = ''
  retryAction = action
  try { await action() } catch { reportError() }
}
function retry(): void { void run(retryAction) }
async function initialize(): Promise<void> {
  const generation = searchGeneration
  initializing.value = true
  try {
    await store.setViewerAgent(null)
    if (!disposed) {
      await store.initialize()
      if (!disposed && generation === searchGeneration) {
        rooms.value = store.rooms
        roomsTotal.value = store.roomsTotal
        roomsPage.value = 1
        roomsPageSize.value = 50
        roomSearch = ''
      }
    }
    if (disposed) store.releaseSelectedRoom()
  } finally { initializing.value = false }
}
async function selectRoom(room: MessengerRoom): Promise<void> {
  following = true
  await run(() => store.selectRoom(room))
  followBottom()
}
function filterRooms(value: string, update: (callback: () => void) => void): void {
  const generation = searchGeneration + 1
  void loadRooms(value, 1).then(() => { if (!disposed && generation === searchGeneration) update(() => undefined) })
}
async function loadRooms(search = roomSearch, page = roomsPage.value, pageSize = roomsPageSize.value): Promise<void> {
  const generation = ++searchGeneration
  searching.value = true
  error.value = ''
  retryAction = () => loadRooms(search, page, pageSize)
  try {
    const result = await chatService.rooms(page, pageSize, search)
    if (disposed || generation !== searchGeneration) return
    rooms.value = result.items
    roomsTotal.value = result.total
    roomsPage.value = page
    roomsPageSize.value = pageSize
    roomSearch = search
  } catch (failure) {
    if (!disposed && generation === searchGeneration) {
      if (isAxiosError(failure) && [403, 404].includes(failure.response?.status ?? 0)) {
        rooms.value = []
        roomsTotal.value = 0
        store.disconnect()
        store.purge()
      }
      reportError()
    }
  } finally {
    if (!disposed && generation === searchGeneration) searching.value = false
  }
}
function changePage(page: number): void { void loadRooms(roomSearch, page) }
function changePageSize(size: number): void { void loadRooms(roomSearch, 1, size) }
function refresh(): void { void run(() => store.refreshSelected()) }
async function openCreate(): Promise<void> {
  if (!canCreate.value || openingCreate.value) return
  openingCreate.value = true
  await run(async () => {
    const result = await chatService.recipients()
    if (!disposed && canCreate.value) { recipients.value = result.agents; createOpen.value = true }
  })
  openingCreate.value = false
}
async function createRoom(agentId: number, label: string, topicId: string | null, showLastMessage: boolean): Promise<void> {
  if (creating.value || !canCreate.value) return
  creating.value = true
  error.value = ''
  retryAction = initialize
  try {
    const room = await chatService.createRoom(agentId, label, topicId, showLastMessage)
    if (disposed) return
    createOpen.value = false
    await store.selectRoom(room)
    await loadRooms('', 1)
  } catch { reportError() }
  finally { creating.value = false }
}
async function prepare(): Promise<boolean> {
  const room = store.selectedRoom?.id, id = documentId
  preparedDocumentId = null
  preparedDocumentFocus = null
  if (!await beforeSend() || disposed || room !== store.selectedRoom?.id || id !== documentId) return false
  preparedDocumentId = id
  preparedDocumentFocus = id ? captureDocumentFocus?.() ?? null : null
  return true
}
async function send(text: string, files: File[] | undefined, effort: ReasoningEffort | undefined, taskRequested: boolean, acknowledge: (accepted: boolean) => void): Promise<void> {
  let accepted = false
  const roomId = store.selectedRoom?.id
  error.value = ''
  try {
    accepted = await store.send(text, files, replyingTo.value?.id ?? null, null, effort ?? null, taskRequested,
      documentId === preparedDocumentId ? preparedDocumentId : null, locale.value,
      documentId === preparedDocumentId ? preparedDocumentFocus : null)
    if (accepted && store.selectedRoom?.id === roomId) { replyingTo.value = null; following = true; followBottom() }
  } catch { reportError() }
  finally { acknowledge(accepted) }
}
function followBottom(): void {
  if (!following || !visible) return
  void nextTick(() => { if (!disposed && following) scrollArea.value?.setScrollPosition('vertical', scrollArea.value.getScroll().verticalSize, 0) })
}
async function onScroll(info: ReturnType<QScrollArea['getScroll']>): Promise<void> {
  following = info.verticalSize - info.verticalContainerSize - info.verticalPosition < 48
  if (info.verticalPosition > 100 || !store.hasOlderMessages || store.loadingOlderMessages) return
  const room = store.selectedRoom?.id, size = info.verticalSize, position = info.verticalPosition
  await run(() => store.loadOlderMessages())
  await nextTick()
  if (!disposed && store.selectedRoom?.id === room) scrollArea.value?.setScrollPosition('vertical', position + scrollArea.value.getScroll().verticalSize - size, 0)
}
function showDocument(event: { data?: { room_id?: string; document_id?: string } }): void {
  if (visible && canReadDocuments.value && !store.selectedRoom?.source && event.data?.room_id === store.selectedRoom?.id && event.data?.document_id) emit('open-document', event.data.document_id)
}
watch(() => store.selectedRoom?.id, () => { replyingTo.value = null; following = true })
watch(() => store.enabled, enabled => {
  if (!enabled) {
    searchGeneration++
    rooms.value = []
    roomsTotal.value = 0
    searching.value = false
  }
})
watch(() => [store.messages.length, store.liveRound, visible], followBottom)
onMounted(() => { websocket.onEvent('chat', 'document_show', showDocument); void run(initialize) })
onBeforeUnmount(() => { disposed = true; searchGeneration++; websocket.offEvent('chat', 'document_show', showDocument); store.releaseSelectedRoom() })
</script>

<style scoped>
.document-conversation {
  --chat-page-bg: transparent; --chat-surface: transparent;
  --chat-surface-raised: var(--solaire-gray-light); --chat-surface-soft: var(--solaire-gray-light);
  --chat-surface-sent: var(--solaire-blue-light); --chat-surface-selected: var(--solaire-blue-light);
  --chat-text: currentColor; --chat-text-secondary: currentColor;
  --chat-border: color-mix(in srgb, currentColor 20%, transparent); --chat-border-strong: var(--chat-border); --chat-received-border: var(--chat-border);
  --chat-thinking-bg: var(--solaire-yellow-light); --chat-thinking-text: currentColor;
  display: flex; flex-direction: column; height: 100%; min-width: 0; min-height: 0; overflow: hidden;
}
.document-conversation--dark {
  --chat-surface-raised: var(--solaire-gray-dark); --chat-surface-soft: var(--solaire-gray-dark);
  --chat-surface-sent: var(--solaire-blue-dark); --chat-surface-selected: var(--solaire-blue-dark);
  --chat-thinking-bg: var(--solaire-yellow-dark);
}
.document-conversation-messages { flex: 1; min-height: 150px; }
.document-conversation :deep(.composer-shell) { max-height: 45%; overflow: auto; }
.document-conversation-pagination { position: sticky; top: 0; z-index: 1; margin-top: 0; padding: 8px; background: white; }
:global(body.body--dark) .document-conversation-pagination { background: var(--solaire-gray-dark); }
</style>
