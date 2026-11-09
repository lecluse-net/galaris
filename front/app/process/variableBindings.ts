import type { BpmnGraph, BpmnNode, NodeKind, ProcessVariable } from './services/nativeProcessService'

export type VariableDirection = 'inputs' | 'outputs'
export interface VariableConsumer { key: string; path: string[]; node: BpmnNode }

export function allowsVariableDirection(kind: NodeKind, direction: VariableDirection): boolean {
  return direction === 'inputs' ? kind !== 'end' : kind !== 'start' && kind !== 'if'
}

export function processInputs(graph: BpmnGraph): string[] {
  return graph.nodes.find(node => node.kind === 'start')?.inputs ?? []
}

export function processOutputs(graph: BpmnGraph): string[] {
  return [...new Set(graph.nodes.filter(node => node.kind === 'end').flatMap(node => node.outputs ?? []))]
}

export function variableConsumers(graph: BpmnGraph): VariableConsumer[] {
  const consumers: VariableConsumer[] = []
  function visit(body: BpmnGraph, path: string[]): void {
    for (const node of body.nodes) {
      const location = [...path, node.id]
      consumers.push({ key: JSON.stringify(location), path: location, node })
      if (node.body) visit(node.body, location)
    }
  }
  visit(graph, [])
  return consumers
}

export function variableUsage(graph: BpmnGraph, name: string, direction: VariableDirection): string[] {
  return variableConsumers(graph).filter(consumer => allowsVariableDirection(consumer.node.kind, direction)
    && (consumer.node[direction] ?? []).includes(name)).map(consumer => consumer.key)
}

export function setVariableUsage(graph: BpmnGraph, name: string, direction: VariableDirection, keys: string[]): BpmnGraph {
  if (!graph.variables?.some(variable => variable.name === name)) return graph
  function visit(body: BpmnGraph, path: string[]): BpmnGraph {
    const nodes = body.nodes.map(node => {
      const location = [...path, node.id], names = node[direction] ?? []
      const selected = allowsVariableDirection(node.kind, direction) && keys.includes(JSON.stringify(location))
      return { ...node, [direction]: selected ? names.includes(name) ? names : [...names, name] : names.filter(value => value !== name),
        body: node.body ? visit(node.body, location) : null }
    })
    return { ...body, nodes }
  }
  return visit(graph, [])
}

export function updateProcessVariables(graph: BpmnGraph, variables: ProcessVariable[]): BpmnGraph {
  const previous = graph.variables ?? []
  const renamed = previous.length === variables.length && previous.filter((variable, index) => variable.name !== variables[index]?.name).length === 1
    ? previous.findIndex((variable, index) => variable.name !== variables[index]?.name) : -1
  const names = new Set(variables.map(variable => variable.name))
  function references(values: string[] = []): string[] {
    return [...new Set(values.map(value => renamed >= 0 && value === previous[renamed]!.name ? variables[renamed]!.name : value).filter(value => names.has(value)))]
  }
  function visit(body: BpmnGraph): BpmnGraph {
    return { ...body, nodes: body.nodes.map(node => ({ ...node,
      inputs: references(node.inputs), outputs: references(node.outputs), body: node.body ? visit(node.body) : null })) }
  }
  return { ...visit(graph), variables }
}
