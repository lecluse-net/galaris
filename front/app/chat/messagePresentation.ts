import type { MessengerMessage } from './types'
import { visibleMessageText } from './messageDirectives'

export function displayMessageText(
  message: MessengerMessage,
  translate: (key: string, values: Record<string, string>) => string,
): string {
  const answer = message.interaction_answer
  return visibleMessageText(answer
    ? translate('chatInteraction.answer', { ...answer })
    : message.text)
}
