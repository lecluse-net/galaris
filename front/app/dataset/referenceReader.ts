import { datasetService } from './services/datasetService'
import { datasetResourceId } from './resource'

export async function search(query: string) {
  const page = await datasetService.list(1, 50, query)
  return page.items.map(item => ({ uri: item.uri, title: item.title, context: '' }))
}

export async function title(uri: string): Promise<string> {
  const id = datasetResourceId(uri)
  return id ? (await datasetService.read(id)).title : uri
}

export async function card(uri: string): Promise<string> {
  const id = datasetResourceId(uri)
  if (!id) throw new Error('Invalid Dataset reference')
  const dataset = await datasetService.read(id)
  const card = document.createElement('blockquote'), paragraph = document.createElement('p')
  const link = document.createElement('a'), title = document.createElement('strong')
  card.className = 'galaris-link-card'
  link.href = `data://${id}`; title.textContent = dataset.title
  link.append(title); paragraph.append(link); card.append(paragraph)
  const address = document.createElement('p'); address.textContent = `data://${id}`; card.append(address)
  return card.outerHTML
}
