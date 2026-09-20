import { CodeBlock, Plugin, type ModelElement, type ModelWriter } from 'ckeditor5'
import { codeTokens } from './codeHighlight'
import { codeBlockText } from './ckeditorCodeTools'

interface BlockHighlight { source: string; language: string; numbered: boolean; markers: string[] }

/** Ephemeral editing markers: no formatting in saved HTML, clipboard data or undo history. */
export class GalarisCodeHighlight extends Plugin {
  static get pluginName() { return 'GalarisCodeHighlight' as const }
  static get requires() { return [CodeBlock] as const }

  private blocks = new Map<ModelElement, BlockHighlight>()
  private nextMarker = 0

  init(): void {
    this.editor.conversion.for('editingDowncast').markerToElement({
      model: 'codeLine',
      view: (data, { writer }) => writer.createUIElement('span', {
        class: 'galaris-code-line', 'data-code-line': data.markerName.split(':')[1], 'aria-hidden': 'true',
      }),
    })
    this.editor.conversion.for('editingDowncast').markerToHighlight({
      model: 'codeSyntax',
      view: data => ({ classes: data.markerName.split(':')[1] }),
    })
    this.listenTo(this.editor.model.document, 'change:data', () => {
      this.editor.model.enqueueChange({ isUndoable: false }, writer => this.refresh(writer))
    })
  }

  private refresh(writer: ModelWriter): void {
    const model = this.editor.model
    const remaining = new Set(this.blocks.keys())
    for (const root of model.document.roots) {
      if (root.rootName === '$graveyard' || !root.isAttached()) continue
      for (const item of model.createRangeIn(root).getItems()) {
        if (!item.is('element', 'codeBlock')) continue
        remaining.delete(item)
        const source = codeBlockText(item)
        const language = String(item.getAttribute('language') ?? '')
        const numbered = !!item.getAttribute('codeLineNumbers')
        const previous = this.blocks.get(item)
        if (previous?.source === source && previous.language === language && previous.numbered === numbered) continue
        previous?.markers.forEach(name => writer.removeMarker(name))
        const markers = codeTokens(source, language).map(token => {
          const name = `codeSyntax:${token.className}:${this.nextMarker++}`
          writer.addMarker(name, {
            range: writer.createRange(writer.createPositionAt(item, token.start), writer.createPositionAt(item, token.end)),
            usingOperation: false,
            affectsData: false,
          })
          return name
        })
        if (numbered) {
          let offset = 0
          source.split('\n').forEach((line, index) => {
            const name = `codeLine:${index + 1}:${this.nextMarker++}`
            writer.addMarker(name, { range: writer.createRange(writer.createPositionAt(item, offset)), usingOperation: false, affectsData: false })
            markers.push(name)
            offset += line.length + 1
          })
        }
        this.blocks.set(item, { source, language, numbered, markers })
      }
    }
    for (const block of remaining) {
      this.blocks.get(block)?.markers.forEach(name => writer.removeMarker(name))
      this.blocks.delete(block)
    }
  }

  override destroy(): void {
    this.blocks.clear()
    super.destroy()
  }
}
