// Source text is always textContent. It cannot become HTML, scripts or authority.
import {PrivateReader} from './private-reader.js';
const byId = (id) => document.getElementById(id);
let nextCursor = null;
const reader = new PrivateReader({clear: (message) => {
  byId('inscription-list').replaceChildren();
  byId('inscription-detail').replaceChildren();
  nextCursor = null;
  if (byId('older')) byId('older').disabled = true;
  byId('status').textContent = message;
}});

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

const api = (path, body) => reader.read(path, body);

function download(value, name) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], {type: 'application/json'}));
  const link = element('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const selected = () => Array.from(byId('inscription-detail').querySelectorAll('input:checked')).map((input) => input.value);

export function renderDetail(detail) {
  const root = byId('inscription-detail');
  root.replaceChildren();
  const block = detail.record.extensions.earworm_representation;
  root.append(element('h2', block.outcome.status === 'no_response' ? 'An explicit non-response' : 'A retained written encounter'));
  root.append(element('p', detail.record.created_at + ' · ' + block.operation_ref, 'note'));
  const qualification = detail.record.extensions['oida.representation_execution']?.qualification;
  if (qualification === 'synthetic_fixture') root.append(element('p', 'Synthetic software fixture. No live model experience is established.', 'note'));
  root.append(element('p', 'Select artifacts for comparison, export, or a prepared return. Current permissions are checked for each action.'));
  const outputs = new Map(detail.outputs.map((output) => [output.representation_ref, output]));
  const accesses = new Map(block.accesses.map((access) => [access.representation_ref, access]));
  for (const item of detail.artifacts) {
    const rep = item.representation;
    const output = outputs.get(rep.representation_id);
    const access = accesses.get(rep.representation_id);
    const section = element('section', undefined, 'inscription-artifact');
    const heading = element('h3', (output ? 'Completed ' + output.kind : access?.role || 'Retained source or projection') + ' · ' + rep.form);
    const label = element('label');
    const checkbox = element('input');
    checkbox.type = 'checkbox'; checkbox.value = rep.representation_id; checkbox.disabled = !item.available;
    label.append(checkbox, document.createTextNode(' Select artifact'));
    section.append(heading, label);
    if (output) section.append(element('p', 'Authored by ' + output.authored_by.join(', '), 'note'));
    section.append(element('p', rep.origin.kind + ' · ' + rep.source_class + ' · ' + (rep.artifact.byte_count ?? 'unknown') + ' bytes', 'note'));
    if (item.text !== null && item.text !== undefined) {
      const text = element('pre', item.text, 'inscription-text');
      if (access?.role === 'instruction') {
        const context = element('details');
        context.append(element('summary', 'Read the adopted LISTENING.md context'), text);
        section.append(context);
      } else section.append(text);
    }
    else section.append(element('p', item.available ? 'Retained binary registry. A received textual projection is listed separately.' : 'Artifact access is withheld by current material terms.'));
    const metadata = element('details'); metadata.append(element('summary', 'Identity, access and convention'));
    metadata.append(element('pre', JSON.stringify({representation: rep, access: access || null}, null, 2), 'inscription-metadata'));
    section.append(metadata); root.append(section);
  }
  const tools = element('div', undefined, 'inscription-tools');
  const action = (label, handler) => {
    const button = element('button', label, 'btn'); button.type = 'button';
    button.addEventListener('click', async () => {button.disabled = true; try {await handler();} catch (error) {if (error.name !== 'AbortError') byId('status').textContent = error.message;} finally {button.disabled = false;}});
    tools.append(button);
  };
  const recordPath = 'api/representations/records/' + encodeURIComponent(detail.record.akousma_id);
  action('Compare two', async () => {
    const refs = selected(); if (refs.length !== 2) throw new Error('Select two artifacts to compare their exact bytes.');
    const result = await api('api/representations/compare?' + new URLSearchParams({left: refs[0], right: refs[1]}));
    byId('status').textContent = result.equal ? 'The selected artifacts have identical bytes.' : 'The selected artifacts have different bytes: ' + result.left_byte_count + ' and ' + result.right_byte_count + ' bytes.';
  });
  action('Export selected', async () => {
    const refs = selected(); if (!refs.length) throw new Error('Select the artifacts to export.');
    download(await api(recordPath + '/export', {representation_refs: refs, public: false}), 'akousmata-inscriptions.json');
    byId('status').textContent = 'The selected artifacts were exported under current owner permissions.';
  });
  action('Prepare independent return', async () => {
    const refs = selected(); if (refs.length !== 1) throw new Error('Select one original or completed work for this return.');
    download(await api(recordPath + '/revisit', {representation_ref: refs[0], context_basis: 'independent'}), 'akousmata-return-request.json');
    byId('status').textContent = 'Return request prepared. Choose a provider, model and scope before execution.';
  });
  root.append(tools);
  const links = element('details'); links.append(element('summary', 'Relations and return context'));
  links.append(element('pre', JSON.stringify({relations: detail.relations, return_basis: detail.return_basis, memory_parents: detail.memory_parents}, null, 2), 'inscription-metadata'));
  root.append(links);
}

export async function load(cursor = null) {
  reader.invalidate('Loading permitted records…');
  byId('status').textContent = 'Loading permitted records…';
  try {
    const outputKind = byId('output-kind').value;
    const query = byId('record-query')?.value || '';
    const form = byId('form')?.value || '';
    const result = await api('api/representations?' + new URLSearchParams({limit: '100', ...(outputKind ? {output_kind: outputKind} : {}), ...(query ? {query} : {}), ...(form ? {form} : {}), ...(cursor ? {cursor} : {})}));
    nextCursor = result.next_cursor;
    if (byId('older')) byId('older').disabled = !nextCursor;
    byId('inscription-list').replaceChildren();
    byId('inscription-detail').replaceChildren(element('p', 'Select a record to read its sources and outputs.'));
    for (const record of result.records) {
      const block = record.extensions.earworm_representation;
      const button = element('button', record.created_at + '\n' + (block.outputs.map((o) => o.kind).join(', ') || block.outcome.status), 'inscription-record');
      button.type = 'button';
      button.addEventListener('click', async () => {
        byId('inscription-detail').replaceChildren();
        try {renderDetail(await api('api/representations/records/' + encodeURIComponent(record.akousma_id))); byId('status').textContent = 'Current permitted record loaded.'; byId('inscription-detail').focus();}
        catch (error) {if (error.name !== 'AbortError') byId('status').textContent = error.message;}
      });
      byId('inscription-list').append(button);
    }
    byId('status').textContent = result.records.length ? result.records.length + ' permitted records on this page.' : nextCursor ? 'No permitted matches on this page. Continue to older records.' : 'No further permitted matches.';
  } catch (error) {if (error.name !== 'AbortError') byId('status').textContent = error.message;}
}

async function start() {
  byId('reload').addEventListener('click', () => void load());
  byId('output-kind').addEventListener('change', () => void load());
  byId('form').addEventListener('change', () => void load());
  byId('record-search').addEventListener('submit', (event) => {event.preventDefault(); void load();});
  byId('older').addEventListener('click', () => void load(nextCursor));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') reader.invalidate('Private view hidden and cleared.');
    else void load();
  });
  window.addEventListener('pagehide', () => reader.invalidate());
  await load();
}
if (!globalThis.AKOUSMATA_INSCRIPTION_FIXTURE) start();
