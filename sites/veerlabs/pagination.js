window.addEventListener('DOMContentLoaded', function () {
  const cardsPerPage = 4;
  const cardsContainer = document.querySelector('.cards');
  const paginationBar = document.querySelector('.pagination-bar');
  const template = document.getElementById('project-card-template');
  let allProjects = [];
  let currentPage = 1;

  function showStatus(message, isError) {
    if (!cardsContainer) return;
    cardsContainer.innerHTML = `<p class="error-message${isError ? '' : ' is-loading'}">${message}</p>`;
    if (paginationBar) paginationBar.innerHTML = '';
  }

  function createCard(project) {
    if (!template) throw new Error('Project card template missing');
    const fragment = template.content.cloneNode(true);
    const cardEl = fragment.querySelector('.project-card');
    if (!cardEl) throw new Error('Project card root missing');

    const logo = cardEl.querySelector('.project-logo');
    const title = cardEl.querySelector('.project-title');
    const subtitle = cardEl.querySelector('.project-subtitle');
    const summary = cardEl.querySelector('.project-summary');
    const tags = cardEl.querySelector('.project-tags');
    // Support both current and previously cached markup/selectors.
    const link = cardEl.querySelector('.learn-more-btn, .learn-more-icon, a[href]');

    if (logo && window.VeerSite) {
      VeerSite.applyProjectLogo(logo, project, 'card');
    }
    if (title) title.textContent = project.name || project.slug || 'Untitled';

    if (subtitle) {
      const cardSubtitle = window.VeerSite ? VeerSite.getCardSubtitle(project) : (project.subtitle || '');
      subtitle.textContent = cardSubtitle || '';
      subtitle.classList.toggle('is-empty', !cardSubtitle);
    }

    if (summary) {
      let summaryText = project.summary || '';
      try {
        if (window.VeerContent && typeof VeerContent.summaryPlainText === 'function') {
          summaryText = VeerContent.summaryPlainText(project.summary, {
            summaryFormat: project.summaryFormat,
          });
        }
      } catch (_error) {
        summaryText = typeof project.summary === 'string' ? project.summary : '';
      }
      summary.textContent = summaryText || '';
    }

    if (link) {
      link.href = `project.html?project=${encodeURIComponent(project.slug || '')}`;
      if (project.requireAuth === true || project.requireAuth === 'true') {
        link.dataset.requireAuth = '1';
        link.classList.add('is-gated');
        link.title = 'Learn more (sign-in required)';
      }
    }
    if (cardEl) {
      cardEl.dataset.slug = project.slug || '';
      if (project.requireAuth === true || project.requireAuth === 'true') {
        cardEl.dataset.requireAuth = '1';
      }
    }

    if (tags) {
      tags.innerHTML = '';
      if (Array.isArray(project.status)) {
        project.status.forEach((tag) => {
          const pill = document.createElement('span');
          pill.className = 'status-pill status-pill-accent';
          pill.textContent = tag;
          tags.appendChild(pill);
        });
      }
      if (Array.isArray(project.tags)) {
        project.tags.slice(0, 4).forEach((tag) => {
          const pill = document.createElement('span');
          pill.className = 'status-pill';
          pill.textContent = tag;
          tags.appendChild(pill);
        });
      }
    }

    return cardEl;
  }

  function renderPagination(totalPages) {
    if (!paginationBar) return;
    paginationBar.innerHTML = '';
    if (totalPages <= 1) return;
    for (let i = 1; i <= totalPages; i += 1) {
      const btn = document.createElement('button');
      btn.textContent = String(i);
      btn.className = 'pagination-btn' + (i === currentPage ? ' active' : '');
      btn.type = 'button';
      btn.setAttribute('aria-label', `Page ${i}`);
      btn.onclick = () => {
        currentPage = i;
        renderPage();
        if (cardsContainer) {
          cardsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      };
      paginationBar.appendChild(btn);
    }
  }

  function renderPage() {
    if (!cardsContainer) return;
    cardsContainer.innerHTML = '';
    const totalPages = Math.max(1, Math.ceil(allProjects.length / cardsPerPage));
    const start = (currentPage - 1) * cardsPerPage;
    const pageItems = allProjects.slice(start, start + cardsPerPage);

    if (pageItems.length === 0) {
      showStatus('No projects available.', true);
      return;
    }

    let rendered = 0;
    pageItems.forEach((project) => {
      try {
        cardsContainer.appendChild(createCard(project));
        rendered += 1;
      } catch (error) {
        console.error('Failed to render project card', project && project.slug, error);
      }
    });

    if (!rendered) {
      showStatus('Unable to render project tiles. Please hard-refresh the page.', true);
      return;
    }
    renderPagination(totalPages);
    if (window.VeerEngage && typeof VeerEngage.hydrateTiles === 'function') {
      VeerEngage.hydrateTiles(cardsContainer);
    }
    if (window.VeerEngage && typeof VeerEngage.bindLearnMoreGates === 'function') {
      VeerEngage.bindLearnMoreGates(cardsContainer);
    }
  }

  if (!cardsContainer) return;
  showStatus('Loading projects…', false);

  if (!window.VeerSite || typeof VeerSite.loadProjects !== 'function') {
    showStatus('Site scripts failed to load. Please hard-refresh (Cmd/Ctrl+Shift+R).', true);
    return;
  }

  VeerSite.loadProjects()
    .then((projects) => {
      allProjects = Array.isArray(projects) ? projects : [];
      currentPage = 1;
      renderPage();
    })
    .catch((error) => {
      console.error('Failed to load projects', error);
      showStatus('Unable to load project tiles. Please hard-refresh the page.', true);
    });
});
