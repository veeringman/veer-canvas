/**
 * Extension + starter registry. New document types and toolbar actions
 * register here; the session and toolbar never hard-code a closed list.
 */
export function createRegistry() {
  const extensions = [];
  const starters = [];
  const byId = new Map();

  function register(ext) {
    if (!ext || !ext.id) throw new Error('Extension needs an id');
    const existing = byId.get(ext.id);
    if (existing) {
      const i = extensions.indexOf(existing);
      if (i >= 0) extensions.splice(i, 1);
    }
    extensions.push(ext);
    byId.set(ext.id, ext);
    return ext;
  }

  function setStarters(list) {
    starters.splice(0, starters.length, ...(Array.isArray(list) ? list : []));
  }

  function starter(id) {
    const key = String(id || '').trim();
    return starters.find((s) => s.id === key) || null;
  }

  return {
    register,
    setStarters,
    starter,
    get extensions() {
      return extensions.slice();
    },
    get starters() {
      return starters.slice();
    },
    groups() {
      const order = [];
      const seen = new Set();
      for (const ext of extensions) {
        const g = ext.group || 'more';
        if (!seen.has(g)) {
          seen.add(g);
          order.push(g);
        }
      }
      return order;
    },
  };
}

export const registry = createRegistry();
