<template>
  <div class="column full-height room-list-shell">
    <q-select
      ref="viewerSelect"
      v-if="canImpersonate"
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
    <div class="row q-px-sm q-py-xs q-gutter-x-sm room-search">
      <q-btn
        round
        :flat="!includeExternal && !includeArchived"
        :unelevated="includeExternal || includeArchived"
        :color="includeExternal || includeArchived ? 'primary' : 'grey-7'"
        icon="filter_list"
        class="room-list-options"
        :aria-label="t('chat.listOptions')"
      >
        <q-tooltip>{{ t('chat.listOptions') }}</q-tooltip>
        <q-menu>
          <q-list class="room-list-options-menu">
            <q-item tag="label">
              <q-item-section avatar>
                <q-checkbox
                  :model-value="includeExternal"
                  @update:model-value="$emit('toggle-external', $event)"
                />
              </q-item-section>
              <q-item-section>{{ t('chat.showExternalRooms') }}</q-item-section>
            </q-item>
            <q-item tag="label">
              <q-item-section avatar>
                <q-checkbox
                  :model-value="includeArchived"
                  @update:model-value="$emit('toggle-archived', $event)"
                />
              </q-item-section>
              <q-item-section>{{ t('chat.showArchivedRooms') }}</q-item-section>
            </q-item>
          </q-list>
        </q-menu>
      </q-btn>
      <q-input v-model="search" dense outlined clearable debounce="250" class="col" :placeholder="t('chat.search')" @update:model-value="$emit('search', search)" />
      <q-btn v-if="canCreate && (rooms.length > 0 || loadingMore)" round flat icon="add" :aria-label="t('chat.newRoom')" @click="$emit('create')" />
    </div>
    <q-list class="col scroll conversation-list" @scroll.passive="onScroll">
      <div v-if="canCreate && rooms.length === 0 && !loadingMore" class="room-list-empty">
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
        class="room-item"
        :class="{ 'room-item--unread': room.unread_count > 0 }"
        @click="$emit('select', room)"
      >
        <q-item-section avatar><InternalAgentAvatar :agent-id="room.agent_id" :name="room.agent_name" size="38px" /></q-item-section>
        <q-item-section><q-item-label class="room-agent-name row items-center q-gutter-xs"><span class="ellipsis">{{ room.label }}</span><q-icon v-if="room.archived" name="archive" size="15px" class="archived-room-icon"><q-tooltip>{{ t('chat.archivedRoom') }}</q-tooltip></q-icon><q-badge v-if="room.source" outline color="grey-7" class="source-badge" :label="t(sourceTranslationKey(room.source))" /></q-item-label><q-item-label v-if="room.show_last_message" class="room-message-preview" lines="1">{{ lastMessageText(room) || t('chat.emptyRoom') }}</q-item-label></q-item-section>
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
import { computed, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { sourceTranslationKey } from '../sourcePresentation'
import { visibleMessageText } from '../messageDirectives'
import type { ChatViewerAgent, MessengerRoom } from '../types'
import InternalAgentAvatar from './InternalAgentAvatar.vue'

const props = defineProps<{ rooms: MessengerRoom[]; selectedId?: string; canCreate: boolean; canImpersonate: boolean; viewerAgentId: number | null; viewerAgents: ChatViewerAgent[]; includeExternal: boolean; includeArchived: boolean; hasMore: boolean; loadingMore: boolean }>()
const emit = defineEmits<{ select: [room: MessengerRoom]; search: [value: string]; create: []; 'load-more': []; 'view-agent': [value: number | null]; 'toggle-external': [value: boolean]; 'toggle-archived': [value: boolean] }>()
const search = ref('')
const { t } = useI18n()
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
.room-search { min-width: 0; flex-wrap: nowrap; border-bottom: 1px solid var(--chat-border, rgba(35, 46, 66, .08)); }
.room-list-options { flex: 0 0 auto; }
:global(.room-list-options-menu) { min-width: 280px; }
.viewer-select { max-width: 100%; }
.conversation-list { min-width: 0; max-width: 100%; padding: 5px; }
.room-list-empty { display: flex; align-items: center; justify-content: center; min-height: 200px; height: 100%; padding: 24px 12px; }
.room-list-empty .q-btn { max-width: 100%; }
.room-list-loader { display: flex; justify-content: center; padding: 10px; }
.room-item { min-height: 62px; margin: 2px 0; border-radius: 10px; transition: background-color .16s ease, transform .16s ease; }
.room-item:hover { background: var(--chat-surface-hover, #f4f6fa); }
.room-item--active { background: var(--chat-surface-selected, #e9efff) !important; }
.room-item--unread:not(.room-item--active) { background: color-mix(in srgb, var(--q-primary) 7%, var(--chat-surface, #fff)); }
.room-item--unread .room-agent-name { color: var(--chat-text, #252b36); font-weight: 700; }
.room-item--unread .room-message-preview { font-weight: 600; }
.room-agent-name { color: var(--chat-text-secondary, #596274); font-size: .82rem; font-weight: 550; }
.archived-room-icon { flex: 0 0 auto; color: var(--chat-text-muted, #7c8798); }
.source-badge { flex: 0 0 auto; font-size: .58rem; font-weight: 500; }
.room-message-preview { margin-top: 3px; color: var(--chat-text, #252b36); font-size: .88rem; }
.room-unread-badge { min-width: 23px; min-height: 20px; justify-content: center; padding: 3px 6px; font-weight: 700; }
:global(.q-dark) .room-item--unread:not(.room-item--active) { background: color-mix(in srgb, var(--q-primary) 15%, var(--chat-surface, #1f232b)); }
</style>
