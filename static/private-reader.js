// A private UI copy has a bounded access lease. Retained memory is not this cache.
export class PrivateReader {
  constructor({fetch = (...args) => globalThis.fetch(...args), clear, lease = 30000,
               schedule = (fn, ms) => setTimeout(fn, ms), cancel = (id) => clearTimeout(id)}) {
    Object.assign(this, {fetch, clear, lease, schedule, cancel});
    this.generation = 0;
    this.identity = null;
    this.controller = null;
    this.expiry = null;
  }
  invalidate(message = 'Private view cleared. Refresh to check current access.') {
    this.generation++;
    this.controller?.abort();
    this.controller = null;
    this.cancel(this.expiry);
    this.expiry = null;
    this.clear(message);
  }
  async read(path, body) {
    this.controller?.abort();
    const generation = ++this.generation;
    const controller = new AbortController();
    this.controller = controller;
    const timeout = this.schedule(() => {
      if (generation === this.generation) this.invalidate('Private read timed out. Refresh to check current access.');
    }, 10000);
    const check = () => {
      controller.signal.throwIfAborted();
      if (generation !== this.generation) throw new DOMException('Stale private response', 'AbortError');
    };
    const identify = async () => {
      const response = await this.fetch('owner/identity', {cache: 'no-store', signal: controller.signal});
      check();
      if (!response.ok) throw new Error('Owner identity is unavailable.');
      const value = await response.json();
      check();
      if (value.contract !== 'centaur/owner-identity/v1' || value.owner !== 'akousmata'
          || !['legacy', 'workspace'].includes(value.mode)
          || (value.mode === 'workspace' && (!value.workspace_id || !value.generation || !value.binding)))
        throw new Error('Owner identity cannot bind this reader.');
      const identity = JSON.stringify([value.mode, value.workspace_id, value.generation, value.binding, value.pid]);
      if (this.identity !== null && this.identity !== identity) {
        this.identity = identity;
        throw new Error('Workspace binding changed. Refresh to read the current workspace.');
      }
      this.identity = identity;
      return value.mode === 'workspace' ? {'X-Centaur-Workspace': value.workspace_id,
        'X-Centaur-Generation': value.generation, 'X-Centaur-Binding': value.binding} : {};
    };
    try {
      const headers = await identify();
      const response = await this.fetch(path, {cache: 'no-store', signal: controller.signal,
        headers: {...headers, ...(body ? {'Content-Type': 'application/json'} : {})},
        ...(body ? {method: 'POST', body: JSON.stringify(body)} : {})});
      check();
      if (!response.ok) throw new Error(response.status === 403
        ? 'Current material permissions withhold this action.'
        : 'This request is unavailable. Refresh to check current access.');
      const result = await response.json();
      check();
      await identify();
      check();
      // The first retained payload sets the deadline; another read cannot extend
      // the lease of previously displayed material without checking it again.
      if (this.expiry === null) this.expiry = this.schedule(() =>
        this.invalidate('Access lease expired. Refresh to check current permissions.'), this.lease);
      return result;
    } catch (error) {
      if (generation !== this.generation || controller.signal.aborted)
        throw new DOMException('Stale private response', 'AbortError');
      if (generation === this.generation && !controller.signal.aborted) this.invalidate(error.message);
      throw error;
    } finally {
      this.cancel(timeout);
    }
  }
}
