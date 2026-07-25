function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

function createPill(text, extra) {
  const pill = document.createElement('span');
  pill.className = 'status-pill' + (extra ? ` ${extra}` : '');
  pill.textContent = text;
  return pill;
}

window.addEventListener('DOMContentLoaded', () => {
  const slug = getQueryParam('project');
  const projectNameEl = document.getElementById('project-name');
  const subtitleEl = document.getElementById('project-subtitle');
  const logoEl = document.getElementById('project-logo');
  const tagsEl = document.getElementById('project-tags');
  const bodyEl = document.getElementById('project-body');

  VeerSite.loadProjects()
    .then(async (projects) => {
      const project = projects.find(item => item.slug === slug);
      if (!project) {
        document.title = 'Project not found — VeerLabs Solutions';
        bodyEl.innerHTML = '<p class="error-message">Project not found or unavailable. Return to the <a href="index.html">dashboard</a>.</p>';
        return;
      }

      if (project.requireAuth === true || project.requireAuth === 'true') {
        if (window.VeerEngage && typeof VeerEngage.ensureProjectAccess === 'function') {
          const ok = await VeerEngage.ensureProjectAccess(project.slug);
          if (!ok) {
            document.title = 'Access required — VeerLabs Solutions';
            bodyEl.innerHTML = '<p class="error-message">Access required to view this project. Return to the <a href="index.html">dashboard</a> and request temporary access.</p>';
            return;
          }
        }
      }

      document.title = `${project.name} — VeerLabs Solutions`;
      projectNameEl.textContent = project.name;
      subtitleEl.textContent = project.subtitle || '';
      VeerSite.applyProjectLogo(logoEl, project, 'detail');

      if (Array.isArray(project.status)) {
        project.status.forEach(tag => tagsEl.appendChild(createPill(tag, 'status-pill-accent')));
      }
      if (Array.isArray(project.tags)) {
        project.tags.forEach(tag => tagsEl.appendChild(createPill(tag)));
      }

      return VeerContent.renderProjectContent(bodyEl, project).then(() => {
        if (window.VeerEngage) {
          VeerEngage.mountContactButton();
          return VeerEngage.mountProjectEngagement(project.slug);
        }
        return null;
      });
    })
    .catch(() => {
      document.title = 'Error — VeerLabs Solutions';
      bodyEl.innerHTML = '<p class="error-message">Unable to load project content. Please try again later.</p>';
    });
});
