import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PrivateReader} from '../static/private-reader.js';

const identity = (generation = 'fixture') => ({contract: 'centaur/owner-identity/v1',
  owner: 'akousmata', mode: 'workspace', workspace_id: 'fixture:workspace', generation,
  binding: 'fixture:binding', pid: 1});
const response = (value, status = 200) => ({ok: status === 200, status, json: async () => value});
const tick = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};

test('the default transport preserves the browser fetch receiver', async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = function(path) {
    assert.equal(this, globalThis);
    return Promise.resolve(response(path === 'owner/identity' ? identity() : {records: []}));
  };
  const reader = new PrivateReader({clear: () => {}});
  try {assert.deepEqual(await reader.read('list'), {records: []});}
  finally {reader.invalidate(); globalThis.fetch = previous;}
});
function harness() {
  const requests = [], timers = new Map(), cleared = [];
  let owner = identity(), timer = 0;
  const reader = new PrivateReader({
    fetch: async (path, options) => {
      assert.equal(options.cache, 'no-store');
      if (path === 'owner/identity') return response(owner);
      return new Promise(resolve => requests.push({path, options, resolve}));
    },
    clear: message => cleared.push(message),
    schedule: (run, ms) => {const id = ++timer; timers.set(id, {run, ms}); return id;},
    cancel: id => timers.delete(id),
  });
  return {reader, requests, timers, cleared, rebind: () => {owner = identity('changed');}};
}

test('late detail cannot replace a newer selection or clear its payload', async () => {
  const {reader, requests, cleared} = harness();
  const first = reader.read('old').catch(error => error.name);
  await tick();
  const next = reader.read('new');
  await tick();
  assert.equal(requests[0].options.signal.aborted, true);
  requests[1].resolve(response({text: 'NEW_PRIVATE'}));
  assert.deepEqual(await next, {text: 'NEW_PRIVATE'});
  requests[0].resolve(response({text: 'OLD_PRIVATE'}));
  assert.equal(await first, 'AbortError');
  assert.deepEqual(cleared, []);
  reader.invalidate();
});

test('failed refresh clears retained payload and aborts pending work', async () => {
  const {reader, requests, cleared} = harness();
  const first = reader.read('detail'); await tick();
  requests[0].resolve(response({text: 'PRIVATE'})); await first;
  const next = reader.read('refresh'); await tick();
  requests[1].resolve(response({}, 403));
  await assert.rejects(next, /permissions/);
  assert.match(cleared.at(-1), /permissions/);
  assert.equal(requests[1].options.signal.aborted, true);
});

test('expiry clears all copies independently of a stalled request', async () => {
  const {reader, requests, timers, cleared} = harness();
  const first = reader.read('list'); await tick();
  requests[0].resolve(response({records: ['PRIVATE']})); await first;
  const pending = reader.read('detail').catch(error => error.name); await tick();
  [...timers.values()].find(timer => timer.ms === 30000).run();
  assert.match(cleared.at(-1), /expired/);
  requests[1].resolve(response({text: 'LATE_PRIVATE'}));
  assert.equal(await pending, 'AbortError');
});

test('owner binding is checked both before and after a payload', async () => {
  const {reader, requests, cleared, rebind} = harness();
  const result = reader.read('detail'); await tick();
  assert.equal(requests[0].options.headers['X-Centaur-Generation'], 'fixture');
  rebind(); requests[0].resolve(response({text: 'OLD_BINDING_PRIVATE'}));
  await assert.rejects(result, /binding changed/);
  assert.match(cleared.at(-1), /binding changed/);
  const fresh = reader.read('list'); await tick();
  requests[1].resolve(response({records: []}));
  assert.deepEqual(await fresh, {records: []});
  reader.invalidate();
});

test('visibility invalidation and a bounded request cancel late responses', async () => {
  const {reader, requests, timers, cleared} = harness();
  const first = reader.read('pending').catch(error => error.name); await tick();
  [...timers.values()].find(timer => timer.ms === 10000).run();
  assert.match(cleared.at(-1), /timed out/);
  requests[0].resolve(response({text: 'LATE'})); assert.equal(await first, 'AbortError');
  const next = reader.read('pending').catch(error => error.name); await tick();
  reader.invalidate('Private view hidden and cleared.');
  requests[1].resolve(response({text: 'HIDDEN'})); assert.equal(await next, 'AbortError');
});
