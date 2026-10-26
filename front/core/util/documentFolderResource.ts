const uuid = '[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
const folder = new RegExp(`^document://folders/(${uuid})/?$`, 'i')

export function documentFolderId(uri: string): string | null {
  return folder.exec(uri)?.[1]?.toLowerCase() ?? null
}
export function documentFolderHref(id: string): string {
  return `/documents/folders/${encodeURIComponent(id)}`
}
export function canonicalFolderLink(value: string): string | null {
  const id = documentFolderId(value)
  if (id) return `document://folders/${id}/`
  try {
    const url = new URL(value, window.location.origin)
    if (url.origin !== window.location.origin) return null
    const match = new RegExp(`^/documents/folders/(${uuid})/?$`, 'i').exec(url.pathname)
    return match ? `document://folders/${match[1]!.toLowerCase()}/` : null
  } catch { return null }
}
