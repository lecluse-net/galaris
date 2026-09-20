/** Only recognized video URLs produce the official privacy-enhanced YouTube player. */
export function youtubeEmbedUrl(value: string): string | null {
  try {
    const url = new URL(value)
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.port) return null
    const host = url.hostname.toLowerCase().replace(/^www\./, '')
    const parts = url.pathname.split('/').filter(Boolean)
    let id: string | null = null
    if (host === 'youtu.be' && parts.length === 1) id = parts[0] ?? null
    if (['youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtube-nocookie.com'].includes(host)) {
      if (url.pathname === '/watch') id = url.searchParams.get('v')
      else if (parts.length === 2 && ['embed', 'shorts', 'live'].includes(parts[0] ?? '')) id = parts[1] ?? null
    }
    return id && /^[\w-]{11}$/.test(id) ? `https://www.youtube-nocookie.com/embed/${id}` : null
  } catch { return null }
}

export function youtubePlayer(document: Document, src: string, title: string): HTMLIFrameElement {
  const frame = document.createElement('iframe')
  frame.src = src
  frame.title = title || 'YouTube'
  frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share'
  frame.allowFullscreen = true
  frame.referrerPolicy = 'strict-origin-when-cross-origin'
  frame.loading = 'lazy'
  return frame
}
