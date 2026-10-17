export interface ResourceAttachment {
  id: string
  uri?: string
  name: string
  media_type: string
  size_bytes: number
}

export interface AttachmentSource<T extends ResourceAttachment = ResourceAttachment> {
  content: (attachment: T, preview: boolean, signal?: AbortSignal) => Promise<Blob>
  thumbnail?: (attachment: T, signal?: AbortSignal) => Promise<Blob>
  add?: (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<T>
  remove?: (attachment: T) => Promise<void>
  info?: (id: string) => Promise<T>
}
