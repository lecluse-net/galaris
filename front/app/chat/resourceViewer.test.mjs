import assert from 'node:assert/strict'
import test from 'node:test'

import {
  browserResourceKind,
  shouldOpenInline,
} from '../../core/util/resourceViewer.ts'
import { resourceTextLanguage } from '../../core/util/resourceText.ts'

test('HTML resources are detected from MIME type or filename', () => {
  assert.equal(browserResourceKind('text/html; charset=utf-8', 'report.bin'), 'html')
  assert.equal(browserResourceKind('application/octet-stream', 'dashboard.html'), 'html')
  assert.equal(browserResourceKind('application/pdf', 'report.bin'), 'pdf')
})

test('media cards detect legacy filenames while honoring audio and video MIME types', () => {
  assert.equal(browserResourceKind('', 'recording.MP4'), 'video')
  assert.equal(browserResourceKind('application/octet-stream', 'recording.wav'), 'audio')
  assert.equal(browserResourceKind('video/ogg', 'recording.ogg'), 'video')
  assert.equal(browserResourceKind('audio/webm', 'recording.webm'), 'audio')
})

test('Markdown attachments are previewable by MIME type or filename', () => {
  for (const [mime, name] of [
    ['text/markdown; charset=utf-8', 'notes.txt'],
    ['TEXT/X-MARKDOWN', 'notes'],
    ['application/octet-stream', 'NOTES.MD'],
    ['', 'notes.markdown'],
    ['text/plain', 'notes.mdown'],
    ['text/plain', 'notes.mkd'],
  ]) assert.equal(browserResourceKind(mime, name), 'markdown')
  assert.equal(browserResourceKind('text/plain', 'notes.txt'), 'text')
})

test('text and source attachments select their language without treating binary files as text', () => {
  for (const [mime, name, language] of [
    ['text/plain', 'notes.txt', 'text'],
    ['application/octet-stream', 'script.PY', 'python'],
    ['text/plain', 'main.rs', 'rust'],
    ['application/json; charset=utf-8', 'data', 'json'],
    ['application/problem+json', 'error', 'json'],
    ['text/plain', 'Dockerfile', 'dockerfile'],
    ['text/plain', 'Makefile', 'makefile'],
    ['text/javascript', 'source', 'javascript'],
    ['text/plain', 'component.vue', 'html'],
    ['text/csv', 'export', 'text'],
  ]) {
    assert.equal(browserResourceKind(mime, name), 'text')
    assert.equal(resourceTextLanguage(mime, name), language)
  }
  assert.equal(browserResourceKind('application/octet-stream', 'archive.zip'), null)
  assert.equal(browserResourceKind('text/html', 'index.html'), 'html')
  assert.equal(browserResourceKind('image/svg+xml', 'image.svg'), 'image')
})

test('only an unmodified primary click opens the inline viewer', () => {
  const click = {
    button: 0,
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    defaultPrevented: false,
  }
  assert.equal(shouldOpenInline(click), true)
  assert.equal(shouldOpenInline({ ...click, ctrlKey: true }), false)
  assert.equal(shouldOpenInline({ ...click, button: 1 }), false)
})
