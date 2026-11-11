import { readFileSync } from 'node:fs';

for (const path of [
  'n8n/workflows/telegram-tiktok-intake.json',
  'n8n/workflows/telegram-notify-results.json'
]) {
  const workflow = JSON.parse(readFileSync(path, 'utf8'));
  const names = new Set(workflow.nodes.map(n => n.name));
  if (names.size !== workflow.nodes.length) throw new Error('Duplicate node names: ' + path);
  if (workflow.active) throw new Error('Template workflow must not activate before credential setup');
  for (const node of workflow.nodes) {
    if (node.type === 'n8n-nodes-base.code') {
      new Function(node.parameters.jsCode); // Validate syntax without running imported code.
    }
    if (node.type === 'n8n-nodes-base.httpRequest') {
      if (!node.parameters.url.includes('publisher:8000')) {
        throw new Error('HTTP requests must remain on the private Publisher network');
      }
      if (node.parameters.genericAuthType !== 'httpHeaderAuth') {
        throw new Error('HTTP requests must use service credential authentication');
      }
    }
  }
  for (const [source, outputs] of Object.entries(workflow.connections)) {
    if (!names.has(source)) throw new Error('Unknown source ' + source);
    for (const edges of outputs.main ?? []) {
      for (const edge of edges) {
        if (!names.has(edge.node)) throw new Error('Unknown target ' + edge.node);
      }
    }
  }
  process.stdout.write('Validated n8n JSON and Code syntax: ' + path + '\n');
}
