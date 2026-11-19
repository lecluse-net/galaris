import type { NavigationBadge, NavigationTree } from '@/core/navigation'
import { privileges } from '@/core/authorize'
import { isChatNavigationVisible } from './availability'
import { useChatInboxStore } from './stores/inbox'

function badgeText(count: number): string {
  return count > 99 ? '99+' : String(count)
}

function chatBadges(): NavigationBadge[] {
  const { pendingQuestionCount, unreadCount } = useChatInboxStore()
  const badges: NavigationBadge[] = []
  if (pendingQuestionCount > 0) {
    badges.push({
      key: 'pending-question', text: badgeText(pendingQuestionCount), tone: 'warning',
      label: { key: pendingQuestionCount === 1 ? 'chat.onePendingQuestion' : 'chat.pendingQuestions', params: { count: pendingQuestionCount } },
    })
  }
  if (unreadCount > 0) {
    badges.push({
      key: 'unread', text: badgeText(unreadCount),
      label: { key: unreadCount === 1 ? 'chat.unreadMessage' : 'chat.unreadMessages', params: { count: unreadCount } },
    })
  }
  return badges
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
        badges: chatBadges,
      },
    },
  },
}

export default navigation
