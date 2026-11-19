import { inject, type InjectionKey } from 'vue'
import { useRouter } from 'vue-router'
import { documentIdFromResourceUri, documentResourceHref, documentUriFromLink } from './documentResource'
import { documentFullscreenKey } from './documentFullscreen'

export const documentNavigationKey: InjectionKey<(id: string) => Promise<void>> = Symbol('documentNavigation')

/** The closest Documents page, Chat workspace or dialog owns document navigation. */
export function useDocumentNavigation(): (uri: string, fullscreen?: boolean) => boolean {
  const navigate = inject(documentNavigationKey, null)
  const fullscreen = inject(documentFullscreenKey, null)
  const router = useRouter()
  return (uri, fromFullscreen) => {
    const reference = documentUriFromLink(uri, window.location.origin)
    const id = reference && documentIdFromResourceUri(reference)
    if (!id) return false
    if (navigate) void navigate(id)
    else void router.push(documentResourceHref(id) + (fromFullscreen || fullscreen?.value ? '&fullscreen=1' : ''))
    return true
  }
}
