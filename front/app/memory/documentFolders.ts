import type { SolaireColor } from '@/core/util'
import type { DocumentFolderOption } from './types'

/** A shared folder contains at least one document accessible to multiple agents. */
export function folderAppearance(folder?: DocumentFolderOption): { tone: SolaireColor; label: string } {
  const kind = folder?.kind ?? 'custom'
  const shared = folder?.shared ?? false
  return {
    tone: kind === 'goal' ? 'green' : (shared ? 'red' : 'blue'),
    label: `documents.folderAppearance.${kind}${shared ? 'Shared' : 'Private'}`,
  }
}
