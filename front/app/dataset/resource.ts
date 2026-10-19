const uuid = '[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
const reference = new RegExp(`^data://(${uuid})$`, 'i')
const route = new RegExp(`^/dataset/(${uuid})/?$`, 'i')

/** Accept native references and links copied from this installation. */
export function datasetResourceId(uri: string): string | null {
  const native = reference.exec(uri)
  if (native) return native[1]!.toLowerCase()
  try {
    const url = new URL(uri, window.location.origin)
    return url.origin === window.location.origin ? route.exec(url.pathname)?.[1]?.toLowerCase() ?? null : null
  } catch { return null }
}
