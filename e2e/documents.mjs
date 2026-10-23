import { expect } from '@playwright/test'

// Exercise the canonical API when a journey needs a document with initial content.
export async function createDocument(request, { headers, data }) {
  const agent = data.owner_agent_id
  const created = await request.post('/api/documents', { headers, data: {
    owner_kind: 'agent', owner_id: agent, actor_agent_id: agent, title: data.title,
    document_type: data.document_type ?? 'html', folder: data.folder ?? '',
  } })
  if (!created.ok() || !data.payload) return created
  const document = await created.json()
  const response = await request.patch(`/api/documents/${document.id}?actor_agent_id=${agent}`, {
    headers, data: { expected_revision: document.revision, payload: data.payload,
      media_type: data.media_type ?? 'text/html', ...(data.keywords ? { keywords: data.keywords } : {}) },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response
}
