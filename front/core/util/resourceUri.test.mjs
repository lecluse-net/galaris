import assert from 'node:assert/strict'
import test from 'node:test'
import { canonicalResourceLink } from './resourceUri.ts'

test('canonical provider and native references are independent of installed Services', () => {
  const id = '11111111-1111-4111-8111-111111111111'
  for (const uri of [`chat://chat:direct:7:1:synthetic/${id}`, 'console://exports/report.pdf',
    'custom-provider://folder/report.txt', 'nextcloud://Shared/Report%20%C3%A9t%C3%A9.pdf',
    `file://${id}`, 'file://', 'console://', 'nextcloud://Shared/',
    `document://${id}/attachments/`, `data://${id}/attachments/${id}`,
    'galaris://skill/synthetic-guide/SKILL.md', `galaris://code/${id}`, `galaris://goal/${id}/cycles/`]) {
    assert.equal(canonicalResourceLink(uri), true, uri)
  }
})

test('resource links cannot become executable protocols, local file paths or noncanonical locators', () => {
  for (const uri of ['javascript:alert(1)', 'javascript://alert(1)', 'data:text/html,active', 'blob://id',
    'file:///etc/passwd', 'file://not-a-uuid', 'ssh://host/path', 'goal://123', '//host/path',
    'chat://room/../private', 'chat://room/%2e%2e/private', 'chat://room/%0aprivate',
    'chat://room/file?token=secret', 'chat://room/file#fragment', 'chat://room\\file',
    'chat://room//file', 'chat://room/raw space', 'chat://room/%ZZ', 'chat://room/%2Ffile']) {
    assert.equal(canonicalResourceLink(uri), false, uri)
  }
})
