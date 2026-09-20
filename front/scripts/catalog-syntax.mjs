import ts from 'typescript'

/** Reject overwritten literal keys before evaluating a catalog. */
export function validateCatalogSyntax(source, fileName) {
  const file = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true)
  function visit(node) {
    if (ts.isObjectLiteralExpression(node)) {
      const keys = new Set()
      for (const property of node.properties) {
        if (!ts.isPropertyAssignment(property) || ts.isComputedPropertyName(property.name)) continue
        const key = property.name.text
        if (keys.has(key)) {
          const { line } = file.getLineAndCharacterOfPosition(property.getStart(file))
          throw new Error(`${fileName}:${line + 1}: duplicate catalog key ${key}`)
        }
        keys.add(key)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(file)
}
