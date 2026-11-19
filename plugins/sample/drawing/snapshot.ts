import type { DocumentFormatContribution } from '@/app/document'

export const snapshot: DocumentFormatContribution['snapshot'] = async (_text, _title, signal, _images, _rendered, source) => {
  if (!source) throw new Error('Drawing source unavailable')
  const bytes = new Uint8Array(await (await source.load(signal)).arrayBuffer())
  signal.throwIfAborted()
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192))
  }
  return `<img alt="" src="data:image/png;base64,${btoa(binary)}" style="max-width:100%;height:auto">`
}
