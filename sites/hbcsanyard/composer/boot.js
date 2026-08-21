import { registry } from './registry.js';
import { registerBuiltins } from './formats.js';
import { createSession } from './session.js';
import { attachLayout, extractBody, collapseAll } from './layout.js';

registerBuiltins();

function ready() {
  if (window.MhwsComposer) return Promise.resolve(window.MhwsComposer);
  return new Promise((resolve) => {
    window.addEventListener('mhws-composer-ready', () => resolve(window.MhwsComposer), { once: true });
  });
}

const api = {
  registry,
  register: (ext) => registry.register(ext),
  mount: (opts) => createSession(opts),
  attachLayout,
  extractBody,
  collapseAll,
  ready,
};

window.MhwsComposer = api;
window.dispatchEvent(new CustomEvent('mhws-composer-ready', { detail: api }));
export { api as default };
