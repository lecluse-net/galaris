export type EditorMode = 'read' | 'edit'
export interface CodeWorkspace { id: string; uri: string; label: string; mode: EditorMode }
export interface CodeSession { id: string; workspace: CodeWorkspace; url: string; expires_at: string }
export interface CodeRecovery { workspace: CodeWorkspace; restart_required: boolean; url: string | null }
