/** Contact identity is independent of the document or file browser's Agent. */
export const CONTACT_CHANGED_EVENT = 'galaris:contact-changed'

export function notifyContactsChanged(...ids: string[]): void {
  window.dispatchEvent(new CustomEvent(CONTACT_CHANGED_EVENT, { detail: ids }))
}

export function contactResourceId(uri: string): string | null {
  return /^galaris:\/\/contact\/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(uri)?.[1] ?? null
}
