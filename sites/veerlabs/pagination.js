window.addEventListener('DOMContentLoaded', function () {
  const cardsPerPage = 4;
  const cardsContainer = document.querySelector('.cards');
  const paginationBar = document.querySelector('.pagination-bar');
  const template = document.getElementById('project-card-template');
  let allProjects = [];
  let currentPage = 1;

  function createCard(project) {
    const card = template.content.cloneNode(true);
    const cardEl = card.querySelector('.project-card');
    const logo = card.querySelector('.project-logo');
    const title = card.querySelector('.project-title');
    const subtitle = card.querySelector('.project-subtitle');
    const summary = card.querySelector('.project-summary');
    const tags = card.querySelector('.project-tags');
    const link = card.querySelector('.learn-more-icon');

    VeerSite.applyProjectLogo(logo, project, 'card');
    title.textContent = project.name;
    const cardSubtitle = VeerSite.getCardSubtitle(project);
    subtitle.textContent = cardSubtitle;
    subtitle.style.display = cardSubtitle ? '' : 'none';
    const summaryText = (globalThis.VeerContent && VeerContent.summaryPlainText)
      ? VeerContent.summaryPlainText(project.summary, { summaryFormat: project.summaryFormat })
      : project.summary;
    summary.textContent = summaryText;
    link.href = `project.html?project=${encodeURIComponent(project.slug)}`;

    if (Array.isArray(project.status)) {
      project.status.forEach(tag => {
        const pill = document.createElement('span');
        pill.className = 'status-pill status-pill-accent';
        pill.textContent = tag;
        tags.appendChild(pill);
      });
    }
    if (Array.isArray(project.tags)) {
      project.tags.slice(0, 4).forEach(tag => {
        const pill = document.createElement('span');
        pill.className = 'status-pill';
        pill.textContent = tag;
        tags.appendChild(pill);
      });
    }

    return cardEl;
  }

  function renderPagination(totalPages) {
    paginationBar.innerHTML = '';
    if (totalPages <= 1) return;
    for (let i = 1; i <= totalPages; i++) {
      const btn = document.createElement('button');
      btn.textContent = i;
      btn.className = 'pagination-btn' + (i === currentPage ? ' active' : '');
      btn.type = 'button';
      btn.setAttribute('aria-label', `Page ${i}`);
      btn.onclick = () => {
        currentPage = i;
        renderPage();
        cardsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
      };
      paginationBar.appendChild(btn);
    }
  }

  function renderPage() {
    cardsContainer.innerHTML = '';
    const totalPages = Math.max(1, Math.ceil(allProjects.length / cardsPerPage));
    const start = (currentPage - 1) * cardsPerPage;
    const pageItems = allProjects.slice(start, start + cardsPerPage);

    if (pageItems.length === 0) {
      cardsContainer.innerHTML = '<p class="error-message">No projects available.</p>';
      paginationBar.innerHTML = '';
      return;
    }

    pageItems.forEach(project => cardsContainer.appendChild(createCard(project)));
    renderPagination(totalPages);
  }

  VeerSite.loadProjects()
    .then(projects => {
      allProjects = projects;
      renderPage();
    })
    .catch(() => {
      cardsContainer.innerHTML = '<p class="error-message">Unable to load project tiles.</p>';
    });
});
