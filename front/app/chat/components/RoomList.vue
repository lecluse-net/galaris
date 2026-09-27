<template>
  <div class="column room-list-shell" :class="cards ? 'room-list-shell--cards' : 'full-height'">
    <div id="chat-room-filters" v-show="showFilters || cards" class="room-filters">
      <q-select
        ref="viewerSelect"
        v-if="canImpersonate && showFilters"
        :model-value="viewerAgentId"
        :options="viewerOptions"
        emit-value
        map-options
        dense
        outlined
        :clearable="false"
        menu-shrink
        class="q-px-sm q-pt-xs viewer-select"
        :aria-label="t('chat.viewAs')"
        :popup-content-style="viewerPopupStyle"
        @pointerdown="syncViewerPopupWidth"
        @keydown="syncViewerPopupWidth"
        @popup-show="syncViewerPopupWidth"
        @update:model-value="$emit('view-agent', $event ?? null)"
      >
        <template #prepend>
          <InternalAgentAvatar
            v-if="selectedViewer"
            :agent-id="selectedViewer.agent_id"
            :name="selectedViewer.display_name"
            size="26px"
          />
          <q-icon v-else name="visibility" />
        </template>
        <template #option="scope">
          <q-item v-bind="scope.itemProps">
            <q-item-section avatar>
              <InternalAgentAvatar
                v-if="scope.opt.value !== null"
                :agent-id="scope.opt.value"
                :name="scope.opt.label"
                size="30px"
              />
              <q-icon v-else name="person" />
            </q-item-section>
            <q-item-section><q-item-label>{{ scope.opt.label }}</q-item-label></q-item-section>
          </q-item>
        </template>
      </q-select>
      <div class="q-px-sm q-py-xs">
        <q-input v-model="search" dense outlined clearable debounce="250" :placeholder="t('chat.search')" :aria-label="t('chat.search')" @update:model-value="emit('search', search ?? '')" />
      </div>
      <div v-show="showFilters" class="room-filter-options q-px-sm q-pb-xs">
        <q-checkbox dense :model-value="includeExternal" :label="t('chat.showExternalRooms')" @update:model-value="emit('toggle-external', $event)" />
        <q-checkbox dense :model-value="includeArchived" :label="t('chat.showArchivedRooms')" @update:model-value="emit('toggle-archived', $event)" />
      </div>
    </div>
    <q-list class="conversation-list" :class="cards ? 'conversation-list--cards' : 'col scroll'" @scroll.passive="onScroll">
      <div v-if="cards && rooms.length === 0 && !loadingMore && !error" class="cards-empty">{{ t('chat.home.noConversations') }}</div>
      <div v-else-if="!cards && canCreate && rooms.length === 0 && !loadingMore" class="room-list-empty">
        <q-btn
          unelevated
          rounded
          no-caps
          color="primary"
          icon="add"
          size="lg"
          padding="16px 24px"
          :label="t('chat.newRoom')"
          @click="$emit('create')"
        />
      </div>
      <q-item
        v-for="room in rooms"
        :key="room.id"
        clickable
        :active="room.id === selectedId"
        active-class="room-item--active"
        :aria-current="room.id === selectedId ? 'true' : undefined"
        class="room-item"
        :class="{ 'room-item--unread': room.unread_count > 0, 'room-item--card': cards }"
        @click="$emit('select', room)"
      >
        <q-item-section avatar class="room-avatar"><InternalAgentAvatar :agent-id="room.agent_id" :name="room.agent_name" :size="cards ? '42px' : '54px'" /></q-item-section>
        <q-item-section>
          <q-item-label class="room-agent-name row items-center q-gutter-xs"><span :class="cards ? 'card-title' : 'ellipsis'">{{ room.label }}</span><q-icon v-if="room.archived" name="archive" size="15px" class="archived-room-icon"><q-tooltip>{{ t('chat.archivedRoom') }}</q-tooltip></q-icon><q-badge v-if="room.source" outline class="source-badge" :label="t(sourceTranslationKey(room.source))" /></q-item-label>
          <q-item-label v-if="cards" class="card-agent">{{ room.agent_name }}</q-item-label>
          <q-item-label v-if="room.show_last_message && (!cards || room.last_message)" class="room-message-preview" :lines="cards ? 2 : 1">{{ lastMessageText(room) || t('chat.emptyRoom') }}</q-item-label>
          <q-item-label v-if="cards" class="card-date">
            <time v-if="room.last_message?.created_at" :datetime="room.last_message.created_at" :title="t('chat.home.lastMessage')">{{ formatDate(room.last_message.created_at) }}</time>
            <span v-else>{{ t('chat.emptyRoom') }}</span>
          </q-item-label>
        </q-item-section>
        <q-item-section v-if="room.unread_count > 0" side>
          <q-badge
            rounded
            color="primary"
            text-color="white"
            class="room-unread-badge"
            :label="unreadBadgeLabel(room.unread_count)"
            :aria-label="unreadMessageLabel(room.unread_count)"
          >
            <q-tooltip>{{ unreadMessageLabel(room.unread_count) }}</q-tooltip>
          </q-badge>
        </q-item-section>
      </q-item>
      <div v-if="loadingMore" class="room-list-loader"><q-spinner color="primary" size="22px" /></div>
    </q-list>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { sourceTranslationKey } from '../sourcePresentation'
import { visibleMessageText } from '../messageDirectives'
import type { ChatViewerAgent, MessengerRoom } from '../types'
import InternalAgentAvatar from './InternalAgentAvatar.vue'

const props = defineProps<{ cards?: boolean; error?: boolean; searchValue?: string; showFilters?: boolean; rooms: MessengerRoom[]; selectedId?: string; canCreate: boolean; canImpersonate: boolean; viewerAgentId: number | null; viewerAgents: ChatViewerAgent[]; includeExternal: boolean; includeArchived: boolean; hasMore: boolean; loadingMore: boolean }>()
const emit = defineEmits<{ select: [room: MessengerRoom]; search: [value: string]; create: []; 'load-more': []; 'view-agent': [value: number | null]; 'toggle-external': [value: boolean]; 'toggle-archived': [value: boolean] }>()
const search = ref(props.searchValue ?? '')
watch(() => props.searchValue, value => { if (value !== undefined) search.value = value })
const { t, locale } = useI18n()
const dateFormatter = computed(() => new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }))
function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateFormatter.value.format(date)
}
const viewerSelect = useTemplateRef<{ $el: HTMLElement }>('viewerSelect')
const viewerPopupWidth = ref<number | null>(null)
const viewerOptions = computed(() => [
  { label: t('chat.myself'), value: null },
  ...props.viewerAgents.map(agent => ({ label: agent.display_name, value: agent.agent_id })),
])
const selectedViewer = computed(() => (
  props.viewerAgents.find(agent => agent.agent_id === props.viewerAgentId) ?? null
))
const viewerPopupStyle = computed(() => viewerPopupWidth.value === null
  ? undefined
  : { width: `${viewerPopupWidth.value}px`, maxWidth: 'calc(100vw - 16px)' })

function syncViewerPopupWidth(): void {
  const width = viewerSelect.value?.$el.getBoundingClientRect().width
  if (width) viewerPopupWidth.value = Math.round(width)
}

function lastMessageText(room: MessengerRoom): string {
  return visibleMessageText(room.last_message?.text ?? '')
}

function unreadBadgeLabel(count: number): string {
  return count > 99 ? '99+' : String(count)
}

function unreadMessageLabel(count: number): string {
  return count === 1
    ? t('chat.unreadMessage')
    : t('chat.unreadMessages', { count })
}

function onScroll(event: Event): void {
  const target = event.currentTarget as HTMLElement
  if (
    props.hasMore
    && !props.loadingMore
    && target.scrollHeight - target.scrollTop - target.clientHeight <= 80
  ) emit('load-more')
}
</script>

<style scoped>
.room-list-shell { width: 100%; min-width: 0; overflow: hidden; color: var(--chat-text, #252b36); background: var(--chat-surface, #fff); }
.room-filters { flex: 0 0 auto; min-width: 0; border-bottom: 1px solid var(--chat-border); }
.room-filter-options { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start; gap: 8px; font-size: .75rem; }
.viewer-select { max-width: 100%; }
.conversation-list { min-width: 0; max-width: 100%; padding: 0; }
.room-list-empty { display: flex; align-items: center; justify-content: center; min-height: 200px; height: 100%; padding: 24px 12px; }
.room-list-empty .q-btn { max-width: 100%; }
.room-list-loader { display: flex; justify-content: center; padding: 10px; }
.room-item { min-height: 62px; padding: 1px 16px 1px 4px; margin: 2px 0; border-radius: 0; transition: background-color .16s ease, transform .16s ease; }
.room-avatar { padding-right: 12px; }
.room-item.room-item--active { color: inherit; background: var(--solaire-blue-light); border-radius: 0; box-shadow: inset 3px 0 var(--solaire-blue-accent); }
.body--dark .room-item.room-item--active { background: var(--solaire-blue-dark); }
.room-item--unread:not(.room-item--active) { background: color-mix(in srgb, var(--q-primary) 7%, var(--chat-surface, #fff)); }
.room-item--unread .room-agent-name { color: var(--chat-text, #252b36); font-weight: 700; }
.room-item--unread .room-message-preview { font-weight: 600; }
.room-agent-name { color: var(--chat-text-secondary, #596274); font-size: .82rem; font-weight: 550; }
.archived-room-icon { flex: 0 0 auto; color: var(--chat-text-muted, #7c8798); }
.source-badge { flex: 0 0 auto; font-size: .58rem; font-weight: 500; }
.room-message-preview { margin-top: 3px; color: var(--chat-text, #252b36); font-size: .88rem; }
.room-unread-badge { min-width: 23px; min-height: 20px; justify-content: center; padding: 3px 6px; font-weight: 700; }
.room-list-shell--cards { overflow: visible; background: transparent; }
.room-list-shell--cards .room-filters { margin-bottom: 20px; border: 0; }
.room-list-shell--cards .room-filters > div { padding-left: 0; padding-right: 0; }
.room-list-shell--cards .viewer-select { padding-left: 0; padding-right: 0; padding-bottom: 8px; }
.conversation-list--cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); gap: 16px; }
.room-item--card { align-items: flex-start; margin: 0; padding: 20px; border: 1px solid var(--chat-border-strong); border-radius: 16px; background: var(--chat-surface); }
.room-item--card:hover, .room-item--card:focus-visible { border-color: var(--solaire-blue-accent); }
.room-item--card.room-item--unread { background: var(--solaire-blue-light); }
.room-item--card .room-agent-name { font-size: 1rem; font-weight: 650; color: var(--chat-text); }
.card-title { overflow-wrap: anywhere; }
.card-agent, .card-date { color: var(--chat-text-secondary); font-size: .78rem; line-height: 1.5; }
.room-item--card .room-message-preview { margin-top: 14px; min-height: 2.8em; line-height: 1.4 !important; overflow-wrap: anywhere; font-weight: 400; }
.room-item--card .card-date { margin-top: 16px; }
.cards-empty { grid-column: 1 / -1; padding: 32px 16px; text-align: center; color: var(--chat-text-secondary); }
body.body--dark .room-item--card.room-item--unread { background: var(--solaire-blue-dark); }
:global(.q-dark) .room-item--unread:not(.room-item--active):not(.room-item--card) { background: color-mix(in srgb, var(--q-primary) 15%, var(--chat-surface, #1f232b)); }
</style>
