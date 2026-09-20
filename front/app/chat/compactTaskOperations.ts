const STREAMING_TAIL_CHARACTERS = 72

/** Render the moving end of streamed AI or thinking text in the Task chat panel. */
export function compactStreamingTail(content: string): string {
  const normalized = content.trim()
  if (!normalized) return ''
  return `...${normalized.slice(-STREAMING_TAIL_CHARACTERS).trimStart()}`
}
