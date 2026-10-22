const en = {
  title: 'Process Lab', description: 'Benchmark current business processes with synthetic inputs and real runs.',
  dataset: 'Synthetic input Dataset', cases: 'Synthetic cases (JSON array)', createDataset: 'Save synthetic cases', generate: 'Generate synthetic cases',
  instructions: 'Synthetic scenario instructions', count: 'Number of cases to generate', campaign: 'Campaign',
  start: 'Start real runs', notice: 'These benchmarks execute the real workflow, including its external effects.',
  open: 'Inspect a campaign', campaignId: 'Campaign identifier', check: 'Exact output check', evidence: 'Measured evidence',
}
const fr: typeof en = {
  title: 'Lab des processus', description: 'Évaluer les processus métier courants avec des entrées synthétiques et de vrais runs.',
  dataset: 'Jeu de données d’entrées synthétiques', cases: 'Cas synthétiques (tableau JSON)', createDataset: 'Enregistrer les cas synthétiques', generate: 'Générer des cas synthétiques',
  instructions: 'Consignes du scénario synthétique', count: 'Nombre de cas à générer', campaign: 'Campagne',
  start: 'Démarrer les runs réels', notice: 'Ces benchmarks exécutent le processus réel, y compris ses effets sur les applications externes.',
  open: 'Afficher une campagne', campaignId: 'Identifiant de campagne', check: 'Contrôle exact du résultat', evidence: 'Mesures observées',
}
const zh: typeof en = {
  ...en,
  dataset: '合成输入数据集',
}
export const processLabMessages = { en, fr, zh }
