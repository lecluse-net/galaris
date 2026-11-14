import type { DocumentLibraryEntry } from './types'

export interface DocumentClassificationNode {
  id: string
  label: string
  topicId: string
  topic?: boolean
  keyword?: string | null
  special?: 'all' | 'none'
}

export interface DocumentClassificationContext {
  entry: DocumentLibraryEntry
  keyword: string | null
}
