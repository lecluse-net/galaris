import test from 'node:test'
import assert from 'node:assert/strict'
import { TREE_PAGE_SIZE, treePages, treePageKey, treePageFromKey, virtualTreeNodes, treePageAncestors } from './treePages.ts'

test('large collections partition into contiguous ranges with at most 100 siblings', () => {
  for (const total of [101, 501, 10_000, 10_001, 1_000_000]) {
    const visit = within => {
      const pages = treePages('collection', total, within)
      assert.ok(pages.length <= TREE_PAGE_SIZE)
      assert.equal(pages[0].offset, within?.offset ?? 0)
      for (let index = 1; index < pages.length; index++) assert.equal(pages[index].offset, pages[index - 1].offset + pages[index - 1].size)
      const last = pages.at(-1)
      assert.equal(Math.min(total, last.offset + last.size), Math.min(total, within ? within.offset + within.size : total))
      for (const page of pages) {
        assert.deepEqual(treePageFromKey(treePageKey(page)), page)
        if (page.size > TREE_PAGE_SIZE) visit(page)
      }
    }
    visit()
  }
})

test('metadata ranges materialize only the opened page and can reveal an existing selection', () => {
  const nodes = Array.from({ length: 1_001 }, (_, index) => ({ id: String(index), label: `Synthetic ${index}` }))
  const closed = virtualTreeNodes(nodes, 'id', [])
  assert.equal(closed.length, 11)
  assert.equal(closed.flatMap(node => node.children).length, 11)
  const ancestors = treePageAncestors(nodes, 'id', '205')
  assert.equal(ancestors.length, 1)
  const opened = virtualTreeNodes(nodes, 'id', ancestors)
  const selectedPage = opened.find(node => node.id === ancestors[0])
  assert.equal(selectedPage.children.length, 100)
  assert.equal(selectedPage.children[5], nodes[205])
  assert.equal(treePageAncestors(nodes, 'id', 'missing'), null)
})

test('range keys stay stable across total changes and reject malformed values', () => {
  assert.equal(treePageKey(treePages('folder', 201)[0]), treePageKey(treePages('folder', 299)[0]))
  for (const value of ['folder', 'virtual-tree-page:[]', 'virtual-tree-page:["x",-1,100]', 'virtual-tree-page:["x",0,1]']) assert.equal(treePageFromKey(value), null)
})
