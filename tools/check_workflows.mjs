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

// Exercise the pure validator only; no n8n runtime, network, or credentials.
const intake = JSON.parse(readFileSync('n8n/workflows/telegram-tiktok-intake.json', 'utf8'));
const code = intake.nodes.find(n => n.name === 'Validate publish command').parameters.jsCode
  .replace('REPLACE_WITH_ALLOWED_TELEGRAM_CHAT_ID', '123')
  .replace('REPLACE_WITH_ALLOWED_TELEGRAM_USER_ID', '456');
const validate = (text, user = 456) => new Function('$input', code)({first: () => ({json: {
  message: {chat: {id: 123}, from: {id: user}, message_id: 789, text}
}})});
const url = 'https://www.tiktok.com/@creator/video/7281234567890123456';
const direct = validate(url);
if (direct.length !== 1 || direct[0].json.title !== '') throw new Error('Direct URL rejected');
if (validate('/publish ' + url)[0].json.request_key !== direct[0].json.request_key)
  throw new Error('Retry must retain the business-event key');
for (const input of ['hello', 'https://evil.example/video', url + ' ' + url]) {
  if (validate(input).length) throw new Error('Invalid input accepted');
}
if (validate(url, 999).length) throw new Error('Unauthorized sender accepted');
process.stdout.write('Validator fixtures passed: direct URL, command, invalid, unauthorized, stable retry key\n');
