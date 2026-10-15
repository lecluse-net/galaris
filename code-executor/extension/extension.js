// Galaris repository navigation only. VS Code owns editing and save conflicts.
const vscode = require('vscode')
const fs = require('node:fs/promises')
const path = require('node:path')

exports.activate = function (context) {
  let applied = null
  let trustRequested = null
  let running = false
  const timer = setInterval(async () => {
    if (running) return
    running = true
    try {
      const request = JSON.parse(await fs.readFile('/profile/navigation.json', 'utf8'))
      if (request.sequence === applied) return
      const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      if (!root) return
      let candidate
      if (request.file) {
        const resolved = path.resolve(root, request.file)
        try { candidate = await fs.realpath(resolved) }
        catch (error) {
          if (error.code !== 'ENOENT' || request.view !== 'changes') throw error
          candidate = path.join(await fs.realpath(path.dirname(resolved)), path.basename(resolved))
        }
        const relative = path.relative(root, candidate)
        if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('File outside workspace')
      }
      await vscode.commands.executeCommand(request.view === 'files' ? 'workbench.view.explorer' : 'workbench.view.scm')
      if (request.view === 'files') {
        if (candidate) await vscode.window.showTextDocument(vscode.Uri.file(candidate), { preview: false })
      } else {
        if (!vscode.workspace.isTrusted) {
          if (trustRequested !== request.sequence) {
            trustRequested = request.sequence
            await vscode.commands.executeCommand('workbench.trust.manage')
          }
          return
        }
        const extension = vscode.extensions.getExtension('vscode.git')
        if (!extension) throw new Error('Git unavailable')
        const api = (await extension.activate()).getAPI(1)
        const rootUri = vscode.Uri.file(root)
        const repository = api.getRepository(rootUri) ?? await api.openRepository(rootUri)
        if (!repository) throw new Error('Git repository unavailable')
        await repository.status()
        if (candidate) {
          const changes = [...repository.state.indexChanges, ...repository.state.workingTreeChanges,
            ...repository.state.untrackedChanges, ...repository.state.mergeChanges]
          if (changes.some(change => change.uri.fsPath === candidate)) {
            await vscode.commands.executeCommand('git.openChange', vscode.Uri.file(candidate))
          } else {
            await vscode.window.showTextDocument(vscode.Uri.file(candidate), { preview: false })
          }
        } else {
          if (repository.state.indexChanges.length) await vscode.commands.executeCommand('git.viewStagedChanges', rootUri)
          if (repository.state.workingTreeChanges.length) await vscode.commands.executeCommand('git.viewChanges', rootUri)
          if (repository.state.untrackedChanges.length) await vscode.commands.executeCommand('git.viewUntrackedChanges', rootUri)
        }
      }
      applied = request.sequence
    } catch (error) {
      if (error.code !== 'ENOENT') console.error('Repository navigation unavailable')
    } finally { running = false }
  }, 500)
  context.subscriptions.push({ dispose: () => clearInterval(timer) })
}
