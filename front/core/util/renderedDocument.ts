/** Capture a live embedded rendering without re-executing its source. */
export type RenderedDocumentCapture = (signal: AbortSignal) => Promise<string>
export type RenderedDocumentResolver = (source: string, language: string, index: number, signal: AbortSignal) => Promise<string>
export type RegisterDocumentCapture = (capture: RenderedDocumentCapture | undefined) => void
