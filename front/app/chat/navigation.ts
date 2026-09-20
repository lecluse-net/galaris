import type { NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { isChatNavigationVisible } from './availability'
import { useChatInboxStore } from './stores/inbox'

function unreadBadge(): string {
  const count = useChatInboxStore().unreadCount
  return count > 99 ? '99+' : count > 0 ? String(count) : ''
}

const navigation: NavigationTree = {
  act: {
    children: {
      chat: {
        label: 'nav.chat',
        description: 'nav.chat_desc',
        icon: 'forum',
        to: '/chat',
        order: 10,
        privileges: [privileges.CHAT_ACCESS],
        visible: isChatNavigationVisible,
        badge: unreadBadge,
      },
    },
  },
}

export default navigation
