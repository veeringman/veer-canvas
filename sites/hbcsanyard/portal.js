(() => {
  const state = {
    session: null,
    pendingHouse: '',
    pendingContact: false,
    missingEmail: false,
    missingPhone: false,
  };

  const el = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    const token = state.session?.token;
    if (token) headers['X-RWA-Token'] = token;
    const res = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText || `HTTP ${res.status}`);
    return data;
  }

  function inr(n) {
    const num = Number(n) || 0;
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(num);
  }

  function showError(msg) {
    const box = el('loginError');
    if (!box) return;
    box.hidden = !msg;
    box.textContent = msg || '';
  }

  function isSuperAdmin(r = state.session?.resident) {
    return Boolean(r?.superAdmin);
  }

  function isEcAdmin(r = state.session?.resident) {
    return r?.role === 'admin';
  }

  function setAuthed(session) {
    state.session = session;
    const isAuthed = Boolean(session?.resident);
    document.body.classList.toggle('is-authed', isAuthed);
    const gate = el('gateView');
    const app = el('appView');
    if (gate) gate.hidden = isAuthed;
    if (app) app.hidden = !isAuthed;
    if (!isAuthed) return;

    const r = session.resident;
    const chip = el('userChip');
    if (chip) {
      const tag = r.superAdmin ? ' · Super admin' : (r.role === 'admin' ? ' · EC' : '');
      const label = r.superAdmin ? 'admin' : r.houseId;
      const titleBit = r.officialTitle ? ` (${r.officialTitle})` : '';
      chip.textContent = `${label} · ${r.name}${titleBit}${tag}`;
    }

    document.querySelectorAll('.admin-only').forEach((node) => {
      node.hidden = !isEcAdmin(r);
    });
    document.querySelectorAll('.superadmin-only').forEach((node) => {
      node.hidden = !isSuperAdmin(r);
    });

    const officialWrap = el('profileOfficialTitleWrap');
    if (officialWrap) officialWrap.hidden = !(isEcAdmin(r) && !r.superAdmin);

    if (el('profileHouse')) el('profileHouse').value = r.houseId || '';
    if (el('profileTitle')) el('profileTitle').value = r.title || '';
    if (el('profileName')) el('profileName').value = r.name || '';
    if (el('profileProfession')) el('profileProfession').value = r.profession || '';
    if (el('profileEmployment')) el('profileEmployment').value = r.employmentStatus || 'unknown';
    if (el('profileOfficialTitle')) el('profileOfficialTitle').value = r.officialTitle || '';
    if (el('profileEmail')) el('profileEmail').value = r.email || '';
    if (el('profilePhone')) el('profilePhone').value = r.phone || '';
  }

  async function refreshSession() {
    const data = await api('/api/rwa/session');
    if (data.authenticated) {
      setAuthed(data);
      await loadHome();
    } else {
      setAuthed(null);
    }
  }

  function formatNoticeBody(text) {
    const raw = String(text || '').trim();
    if (!raw) return '';
    const paragraphs = raw.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
    const blocks = paragraphs.length ? paragraphs : [raw];
    return blocks.map((block) => {
      const lines = block.split('\n').map((line) => {
        const escaped = escapeHtml(line);
        return escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      });
      // A lone **Heading** line becomes a notice subhead
      if (lines.length === 1 && /^\*\*.+\*\*$/.test(block.trim())) {
        return `<p class="notice-subhead">${lines[0]}</p>`;
      }
      if (lines.length >= 2 && /^\*\*.+\*\*$/.test(block.split('\n')[0].trim())) {
        return `<p class="notice-subhead">${lines[0]}</p><p>${lines.slice(1).join('<br>')}</p>`;
      }
      return `<p>${lines.join('<br>')}</p>`;
    }).join('');
  }

  function renderNoticeCard(n, { canMoveUp = false, canMoveDown = false } = {}) {
    const date = (n.publishedAt || '').slice(0, 10);
    const moveActions = (isEcAdmin() && n.pinned) ? `
        <button type="button" class="btn ghost compact notice-move-up" data-id="${escapeHtml(n.id)}" ${canMoveUp ? '' : 'disabled'} title="Move up">↑ Up</button>
        <button type="button" class="btn ghost compact notice-move-down" data-id="${escapeHtml(n.id)}" ${canMoveDown ? '' : 'disabled'} title="Move down">↓ Down</button>` : '';
    const actions = isEcAdmin() ? `
      <div class="notice-actions">
        ${moveActions}
        <button type="button" class="btn ghost compact notice-edit" data-id="${escapeHtml(n.id)}">Edit</button>
        <button type="button" class="btn ghost compact notice-pin" data-id="${escapeHtml(n.id)}" data-pinned="${n.pinned ? '1' : '0'}">${n.pinned ? 'Unpin' : 'Pin'}</button>
        <button type="button" class="btn ghost compact notice-delete" data-id="${escapeHtml(n.id)}">Delete</button>
      </div>` : '';
    return `
      <article class="notice ${n.pinned ? 'is-pinned' : ''}" data-id="${escapeHtml(n.id)}">
        <div class="notice-head">
          <h3 class="notice-title">${escapeHtml(n.title)}</h3>
          ${n.pinned ? '<span class="notice-pin-badge">Pinned</span>' : ''}
        </div>
        <div class="meta">${escapeHtml(n.category || 'general')}${date ? ` · ${escapeHtml(date)}` : ''}</div>
        <div class="notice-body">${formatNoticeBody(n.body)}</div>
        ${actions}
      </article>`;
  }

  let noticesCache = [];

  async function loadHome() {
    const notices = await api('/api/rwa/notices');
    const list = el('noticeList');
    if (!list) return;
    noticesCache = notices.notices || [];
    const pinnedIds = noticesCache.filter((n) => n.pinned).map((n) => n.id);
    list.innerHTML = noticesCache.length
      ? noticesCache.map((n) => {
          const pIdx = n.pinned ? pinnedIds.indexOf(n.id) : -1;
          return renderNoticeCard(n, {
            canMoveUp: pIdx > 0,
            canMoveDown: pIdx >= 0 && pIdx < pinnedIds.length - 1,
          });
        }).join('')
      : '<p class="muted">No notices yet.</p>';
  }

  function resetNoticeForm() {
    const form = el('noticeForm');
    if (!form) return;
    form.reset();
    if (el('noticeEditId')) el('noticeEditId').value = '';
    if (el('noticeFormTitle')) el('noticeFormTitle').textContent = 'Publish notice';
    if (el('noticeSubmitBtn')) el('noticeSubmitBtn').textContent = 'Publish notice';
    if (el('noticeCancelEditBtn')) el('noticeCancelEditBtn').hidden = true;
    if (el('noticeFormStatus')) el('noticeFormStatus').textContent = '';
  }

  function startNoticeEdit(notice) {
    if (!notice) return;
    switchPanel('admin');
    if (el('noticeEditId')) el('noticeEditId').value = notice.id || '';
    if (el('noticeTitleInput')) el('noticeTitleInput').value = notice.title || '';
    if (el('noticeBodyInput')) el('noticeBodyInput').value = notice.body || '';
    if (el('noticeCategoryInput')) el('noticeCategoryInput').value = notice.category || 'general';
    if (el('noticePinnedInput')) el('noticePinnedInput').checked = Boolean(notice.pinned);
    if (el('noticeFormTitle')) el('noticeFormTitle').textContent = 'Update notice';
    if (el('noticeSubmitBtn')) el('noticeSubmitBtn').textContent = 'Save changes';
    if (el('noticeCancelEditBtn')) el('noticeCancelEditBtn').hidden = false;
    if (el('noticeFormStatus')) el('noticeFormStatus').textContent = `Editing ${notice.id}`;
    el('noticeForm')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function loadDues() {
    const data = await api('/api/rwa/payments/me');
    const card = el('duesCard');
    const p = data.payment;
    if (card) {
      if (!p) {
        card.innerHTML = '<p class="muted">No ledger row for this plot yet.</p>';
      } else {
        card.innerHTML = `
          <div class="stat-grid">
            <div class="stat"><span>Previous total</span><strong>${inr(p.previousTotal ?? p.balancePrev)}</strong></div>
            <div class="stat"><span>Previous paid</span><strong>${inr(p.previousPaid ?? 0)}</strong></div>
            <div class="stat"><span>Previous pending / dues</span><strong>${inr(p.previousPending ?? p.balancePrev)}</strong></div>
            <div class="stat"><span>Current year total</span><strong>${inr(p.currentYearTotal ?? p.feeAmount)}</strong></div>
            <div class="stat"><span>Pending / dues</span><strong>${inr(p.pendingDues ?? p.balanceOutstanding)}</strong></div>
          </div>`;
      }
    }
    const bank = el('bankCard');
    if (bank) {
      renderPayCard(bank, data.summary?.bank, { showEdit: isEcAdmin() });
    }

    if (isEcAdmin()) {
      await loadLedger();
      el('adminDues').hidden = false;
    }
  }

  function qrImgUrl(bank) {
    if (!bank?.hasQr && !bank?.qrUrl) return '';
    const base = bank.qrUrl || '/api/rwa/bank/qr';
    return `${base}?t=${encodeURIComponent(bank.qrFilename || bank.updatedAt || Date.now())}`;
  }

  function renderPayCard(target, bank, { showEdit = false } = {}) {
    if (!target) return;
    const b = bank || {};
    const name = b.bankName || b.bank_name || 'Bank of Baroda — Mandi';
    const account = b.accountNo || b.account_no || '09640100004511';
    const ifsc = b.ifsc || 'BARB0MANDIX';
    const upiId = b.upiId || '';
    const upiName = b.upiName || '';
    const qr = qrImgUrl(b);
    const label = b.label || 'RWA collection';
    target.innerHTML = `
      <div class="pay-card-body">
        <div>
          <h3>${escapeHtml(label)}</h3>
          <p class="pay-meta">
            <span><strong>${escapeHtml(name)}</strong></span>
            <span>A/C ${escapeHtml(account)}</span>
            <span>IFSC ${escapeHtml(ifsc)}</span>
            ${upiId ? `<span>UPI ${escapeHtml(upiId)}${upiName ? ` · ${escapeHtml(upiName)}` : ''}</span>` : '<span class="muted">No UPI ID set yet</span>'}
          </p>
          ${showEdit ? '<div class="btn-row"><button type="button" class="btn secondary compact js-edit-bank">Edit bank &amp; UPI</button></div>' : ''}
        </div>
        ${qr ? `<img class="pay-qr" src="${escapeHtml(qr)}" alt="UPI QR code" width="168" height="168">` : '<p class="muted">UPI QR not uploaded yet.</p>'}
      </div>`;
  }

  function renderEcBankPreview(bank) {
    const box = el('ecBankPreview');
    if (!box) return;
    renderPayCard(box, bank, { showEdit: false });
  }

  function setBankEditError(msg) {
    const box = el('bankEditError');
    if (!box) return;
    box.hidden = !msg;
    box.textContent = msg || '';
  }

  function fillBankEditForm(bank) {
    const b = bank || {};
    if (el('bankEditLabel')) el('bankEditLabel').value = b.label || 'RWA collection';
    if (el('bankEditBankName')) el('bankEditBankName').value = b.bankName || b.bank_name || '';
    if (el('bankEditAccountNo')) el('bankEditAccountNo').value = b.accountNo || b.account_no || '';
    if (el('bankEditIfsc')) el('bankEditIfsc').value = b.ifsc || '';
    if (el('bankEditUpiId')) el('bankEditUpiId').value = b.upiId || '';
    if (el('bankEditUpiName')) el('bankEditUpiName').value = b.upiName || '';
    if (el('bankEditQrFile')) el('bankEditQrFile').value = '';
    const preview = el('bankEditQrPreview');
    const qr = qrImgUrl(b);
    if (preview) {
      if (qr) {
        preview.hidden = false;
        preview.innerHTML = `<img src="${escapeHtml(qr)}" alt="Current UPI QR" width="120" height="120"><span class="muted">Current QR on file</span>`;
      } else {
        preview.hidden = true;
        preview.innerHTML = '';
      }
    }
  }

  async function loadBankDetails() {
    const data = await api('/api/rwa/bank');
    renderEcBankPreview(data.bank);
    return data.bank;
  }

  function showDialog(dialog) {
    if (!dialog) return false;
    try {
      if (typeof dialog.showModal === 'function') {
        if (!dialog.open) dialog.showModal();
        return true;
      }
    } catch (err) {
      console.warn('showModal failed', err);
    }
    dialog.setAttribute('open', '');
    return true;
  }

  async function openBankEdit(bank) {
    const dialog = el('bankEditDialog');
    if (!dialog) {
      alert('Bank editor is missing from the page. Try Refresh app.');
      return;
    }
    setBankEditError('');
    if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Loading…';
    let current = bank || null;
    try {
      current = await loadBankDetails();
    } catch (err) {
      if (!current) {
        setBankEditError(err.message || 'Could not load bank details');
        if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
        showDialog(dialog);
        return;
      }
    }
    fillBankEditForm(current || {});
    if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    showDialog(dialog);
  }

  function closeBankEdit() {
    const dialog = el('bankEditDialog');
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  async function saveBankDetails(event) {
    event.preventDefault();
    setBankEditError('');
    const btn = el('bankEditSaveBtn');
    if (btn) btn.disabled = true;
    if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Saving…';
    try {
      const payload = {
        label: el('bankEditLabel')?.value.trim() || 'RWA collection',
        bankName: el('bankEditBankName')?.value.trim() || '',
        accountNo: el('bankEditAccountNo')?.value.trim() || '',
        ifsc: el('bankEditIfsc')?.value.trim() || '',
        upiId: el('bankEditUpiId')?.value.trim() || '',
        upiName: el('bankEditUpiName')?.value.trim() || '',
      };
      const data = await api('/api/rwa/bank', { method: 'PATCH', body: JSON.stringify(payload) });
      const file = el('bankEditQrFile')?.files?.[0];
      let bank = data.bank;
      if (file) bank = await uploadBankQr(file);
      renderEcBankPreview(bank);
      if (el('bankCard')) renderPayCard(el('bankCard'), bank, { showEdit: isEcAdmin() });
      fillBankEditForm(bank);
      if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Saved.';
    } catch (err) {
      setBankEditError(err.message || 'Save failed');
      if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function uploadBankQr(file) {
    const body = new FormData();
    body.append('qr', file);
    const headers = {};
    const token = state.session?.token;
    if (token) headers['X-RWA-Token'] = token;
    const res = await fetch('/api/rwa/bank/qr', {
      method: 'POST',
      credentials: 'same-origin',
      headers,
      body,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText || `HTTP ${res.status}`);
    return data.bank;
  }

  async function uploadBankQrOnly() {
    const file = el('bankEditQrFile')?.files?.[0];
    if (!file) {
      setBankEditError('Choose a QR image first');
      return;
    }
    setBankEditError('');
    if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Uploading QR…';
    try {
      const bank = await uploadBankQr(file);
      renderEcBankPreview(bank);
      if (el('bankCard')) renderPayCard(el('bankCard'), bank, { showEdit: isEcAdmin() });
      fillBankEditForm(bank);
      if (el('bankEditStatus')) el('bankEditStatus').textContent = 'QR uploaded.';
    } catch (err) {
      setBankEditError(err.message || 'QR upload failed');
      if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    }
  }

  async function clearBankQr() {
    setBankEditError('');
    if (el('bankEditStatus')) el('bankEditStatus').textContent = 'Removing QR…';
    try {
      const data = await api('/api/rwa/bank/qr', { method: 'DELETE', body: '{}' });
      renderEcBankPreview(data.bank);
      if (el('bankCard')) renderPayCard(el('bankCard'), data.bank, { showEdit: isEcAdmin() });
      fillBankEditForm(data.bank);
      if (el('bankEditStatus')) el('bankEditStatus').textContent = 'QR removed.';
    } catch (err) {
      setBankEditError(err.message || 'Could not remove QR');
      if (el('bankEditStatus')) el('bankEditStatus').textContent = '';
    }
  }

  let ledgerCache = [];
  let ledgerAutoRecalc = true;

  function renderLedgerSummary(sum) {
    if (!el('ledgerSummary') || !sum) return;
    el('ledgerSummary').textContent =
      `${sum.households || 0} households · due ${inr(sum.totalDue)} · received ${inr(sum.totalReceived)} · outstanding ${inr(sum.totalOutstanding)}`;
  }

  function renderLedgerRows() {
    const tbody = el('ledgerRows');
    if (!tbody) return;
    const q = (el('ledgerSearch')?.value || '').trim().toLowerCase();
    const rows = ledgerCache.filter((r) => {
      if (!q) return true;
      return `${r.houseId} ${r.plotNo || ''} ${r.name || ''} ${r.section || ''} ${r.remarks || ''}`.toLowerCase().includes(q);
    });
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="muted">No matching ledger rows.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr data-house="${escapeHtml(r.houseId)}">
        <td><code>${escapeHtml(r.houseId)}</code></td>
        <td>${escapeHtml(r.name || '')}</td>
        <td>${inr(r.previousTotal ?? r.balancePrev)}</td>
        <td>${inr(r.previousPaid ?? 0)}</td>
        <td>${inr(r.previousPending ?? r.balancePrev)}</td>
        <td>${inr(r.currentYearTotal ?? r.feeAmount)}</td>
        <td>${inr(r.pendingDues ?? r.balanceOutstanding)}</td>
        <td><button type="button" class="btn secondary compact ledger-edit" data-house="${escapeHtml(r.houseId)}">Edit</button></td>
      </tr>`).join('');
  }

  async function loadLedger() {
    const all = await api('/api/rwa/payments');
    ledgerCache = all.rows || [];
    renderLedgerSummary(all.summary || {});
    renderLedgerRows();
  }

  function setLedgerEditError(msg) {
    const box = el('ledgerEditError');
    if (!box) return;
    box.hidden = !msg;
    box.textContent = msg || '';
  }

  function syncLedgerDerivedPreview() {
    const prev = Number(el('ledgerEditPrevTotal')?.value || 0);
    const year = Number(el('ledgerEditYearTotal')?.value || 0);
    const received = Number(el('ledgerEditReceived')?.value || 0);
    const totalDue = Number(el('ledgerEditTotalDue')?.value || (prev + year));
    const pending = Number(el('ledgerEditPending')?.value || (totalDue - received));
    const prevPaid = Math.min(Math.max(received, 0), Math.max(prev, 0));
    const prevPending = Math.max(0, prev - prevPaid);
    if (el('ledgerEditDerived')) {
      el('ledgerEditDerived').textContent =
        `Preview · previous paid ${inr(prevPaid)} · previous pending ${inr(prevPending)} · pending/dues ${inr(pending)}`;
    }
  }

  function recalcLedgerTotalsFromInputs() {
    if (!ledgerAutoRecalc) return;
    const prev = Number(el('ledgerEditPrevTotal')?.value || 0);
    const year = Number(el('ledgerEditYearTotal')?.value || 0);
    const received = Number(el('ledgerEditReceived')?.value || 0);
    if (el('ledgerEditTotalDue')) el('ledgerEditTotalDue').value = String(prev + year);
    if (el('ledgerEditPending')) el('ledgerEditPending').value = String(prev + year - received);
    syncLedgerDerivedPreview();
  }

  function openLedgerEdit(houseId) {
    const row = ledgerCache.find((r) => r.houseId === houseId);
    const dialog = el('ledgerEditDialog');
    if (!row || !dialog) return;
    ledgerAutoRecalc = true;
    setLedgerEditError('');
    el('ledgerEditHouseId').value = row.houseId;
    el('ledgerEditTitle').textContent = `Edit · plot ${row.houseId}`;
    el('ledgerEditSubtitle').textContent = `${row.name || 'Resident'}${row.section ? ` · ${row.section}` : ''}`;
    el('ledgerEditPrevTotal').value = String(row.previousTotal ?? row.balancePrev ?? 0);
    el('ledgerEditFeeYear').value = String(row.feeYear || 2026);
    el('ledgerEditYearTotal').value = String(row.currentYearTotal ?? row.feeAmount ?? 0);
    el('ledgerEditReceived').value = String(row.amountReceived ?? 0);
    el('ledgerEditTotalDue').value = String(row.totalDue ?? 0);
    el('ledgerEditPending').value = String(row.pendingDues ?? row.balanceOutstanding ?? 0);
    el('ledgerEditRemarks').value = row.remarks || '';
    syncLedgerDerivedPreview();
    showDialog(dialog);
  }

  function closeLedgerEdit() {
    const dialog = el('ledgerEditDialog');
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  async function saveLedgerEdit(event) {
    event.preventDefault();
    const houseId = el('ledgerEditHouseId')?.value?.trim();
    if (!houseId) return;
    const payload = {
      previousTotal: Number(el('ledgerEditPrevTotal').value),
      feeYear: Number(el('ledgerEditFeeYear').value),
      currentYearTotal: Number(el('ledgerEditYearTotal').value),
      amountReceived: Number(el('ledgerEditReceived').value),
      totalDue: Number(el('ledgerEditTotalDue').value),
      pendingDues: Number(el('ledgerEditPending').value),
      remarks: el('ledgerEditRemarks').value.trim(),
    };
    setLedgerEditError('');
    const btn = el('ledgerEditSaveBtn');
    if (btn) btn.disabled = true;
    if (el('ledgerEditStatus')) el('ledgerEditStatus').textContent = `Saving ${houseId}…`;
    try {
      const data = await api(`/api/rwa/payments/${encodeURIComponent(houseId)}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      const updated = data.payment || {};
      const idx = ledgerCache.findIndex((r) => r.houseId === houseId);
      if (idx >= 0) ledgerCache[idx] = { ...ledgerCache[idx], ...updated };
      renderLedgerSummary(data.summary || {});
      renderLedgerRows();
      closeLedgerEdit();
      if (el('ledgerEditStatus')) el('ledgerEditStatus').textContent = `Saved plot ${houseId}`;
      // Refresh personal dues card if EC is viewing own plot or just keep summary fresh
      loadDues().catch(() => {});
    } catch (err) {
      setLedgerEditError(err.message || 'Save failed');
      if (el('ledgerEditStatus')) el('ledgerEditStatus').textContent = '';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  el('ledgerSearch')?.addEventListener('input', () => renderLedgerRows());
  el('ledgerRows')?.addEventListener('click', (event) => {
    const btn = event.target.closest('.ledger-edit');
    if (!btn) return;
    openLedgerEdit(btn.getAttribute('data-house'));
  });
  el('ledgerEditCancelBtn')?.addEventListener('click', () => closeLedgerEdit());
  el('ledgerEditForm')?.addEventListener('submit', saveLedgerEdit);
  ['ledgerEditPrevTotal', 'ledgerEditYearTotal', 'ledgerEditReceived'].forEach((id) => {
    el(id)?.addEventListener('input', () => recalcLedgerTotalsFromInputs());
  });
  ['ledgerEditTotalDue', 'ledgerEditPending'].forEach((id) => {
    el(id)?.addEventListener('input', () => {
      ledgerAutoRecalc = false;
      syncLedgerDerivedPreview();
    });
  });
  el('ledgerEditDialog')?.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeLedgerEdit();
  });

  el('ecEditBankBtn')?.addEventListener('click', () => { openBankEdit().catch(console.error); });
  document.addEventListener('click', (event) => {
    const btn = event.target.closest?.('.js-edit-bank');
    if (btn) {
      event.preventDefault();
      openBankEdit().catch(console.error);
    }
  });
  el('bankEditCancelBtn')?.addEventListener('click', () => closeBankEdit());
  el('bankEditForm')?.addEventListener('submit', saveBankDetails);
  el('bankEditQrOnlyBtn')?.addEventListener('click', () => uploadBankQrOnly());
  el('bankEditClearQrBtn')?.addEventListener('click', () => clearBankQr());
  el('bankEditDialog')?.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeBankEdit();
  });

  async function loadDirectory() {
    const data = await api('/api/rwa/directory');
    el('directoryRows').innerHTML = (data.residents || []).map((r) => `
      <tr>
        <td><code>${escapeHtml(r.houseId)}</code></td>
        <td>${escapeHtml(r.section)}</td>
        <td>${escapeHtml(r.name)}</td>
        <td>${escapeHtml(r.role)}${r.role === 'admin' && r.officialTitle ? ` · ${escapeHtml(r.officialTitle)}` : ''}</td>
      </tr>`).join('');
  }

  function switchPanel(name) {
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('is-active', t.dataset.panel === name));
    document.querySelectorAll('.panel').forEach((p) => {
      const on = p.id === `panel-${name}`;
      p.hidden = !on;
      p.classList.toggle('is-active', on);
    });
    if (name === 'home') loadHome().catch(console.error);
    if (name === 'dues') loadDues().catch((e) => { el('duesCard').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`; });
    if (name === 'concerns') loadMailbox().catch((e) => {
      if (el('mailboxList')) el('mailboxList').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
    });
    if (name === 'directory') loadDirectory().catch((e) => { el('directoryRows').innerHTML = `<tr><td colspan="4">${escapeHtml(e.message)}</td></tr>`; });
    if (name === 'admin') {
      loadSmtpStatus();
      loadBankDetails().catch((e) => { if (el('ecBankPreview')) el('ecBankPreview').innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`; });
      loadEcGrievances().catch((e) => { if (el('ecGrievanceStatus')) el('ecGrievanceStatus').textContent = e.message || 'Concerns failed'; });
      loadRoster().catch((e) => { if (el('rosterStatus')) el('rosterStatus').textContent = e.message || 'Roster failed'; });
      loadRevisions().catch((e) => { if (el('revisionStatus')) el('revisionStatus').textContent = e.message || 'History failed'; });
      if (isSuperAdmin()) loadSettings().catch((e) => { if (el('settingsStatus')) el('settingsStatus').textContent = e.message || 'Settings failed'; });
    }
  }

  function switchGate(mode) {
    const plot = mode !== 'admin';
    el('gateTabPlot')?.classList.toggle('is-active', plot);
    el('gateTabAdmin')?.classList.toggle('is-active', !plot);
    if (el('plotLoginPane')) el('plotLoginPane').hidden = !plot;
    if (el('adminLoginPane')) el('adminLoginPane').hidden = plot;
    showError('');
  }
  el('gateTabPlot')?.addEventListener('click', () => switchGate('plot'));
  el('gateTabAdmin')?.addEventListener('click', () => switchGate('admin'));

  el('adminLoginForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    el('adminLoginBtn').disabled = true;
    try {
      const data = await api('/api/rwa/login', {
        method: 'POST',
        body: JSON.stringify({
          username: el('adminUserInput').value.trim(),
          password: el('adminPassInput').value,
          website: '',
        }),
      });
      el('adminPassInput').value = '';
      setAuthed(data);
      await loadHome();
      switchPanel('admin');
    } catch (err) {
      showError(err.message || 'Sign-in failed');
    } finally {
      el('adminLoginBtn').disabled = false;
    }
  });

  function resetLoginForms() {
    el('otpRequestForm') && (el('otpRequestForm').hidden = false);
    el('otpContactForm') && (el('otpContactForm').hidden = true);
    el('otpVerifyForm') && (el('otpVerifyForm').hidden = true);
    if (el('otpInput')) el('otpInput').value = '';
    if (el('otpContactEmail')) el('otpContactEmail').value = '';
    if (el('otpContactPhone')) el('otpContactPhone').value = '';
    state.pendingHouse = '';
    state.pendingContact = false;
    state.missingEmail = false;
    state.missingPhone = false;
    showError('');
  }

  function showContactForm(data) {
    state.pendingHouse = data.houseId || state.pendingHouse;
    state.missingEmail = Boolean(data.missingEmail);
    state.missingPhone = Boolean(data.missingPhone);
    el('otpRequestForm').hidden = true;
    el('otpVerifyForm').hidden = true;
    el('otpContactForm').hidden = false;
    const name = data.name ? ` for ${data.name}` : '';
    el('otpContactHint').textContent = data.message
      || `Plot ${state.pendingHouse}${name} is missing contact details. Enter them below. They are saved only after you verify the emailed code.`;
    if (el('otpContactEmailWrap')) el('otpContactEmailWrap').hidden = !state.missingEmail;
    if (el('otpContactPhoneWrap')) el('otpContactPhoneWrap').hidden = !state.missingPhone;
    if (el('otpContactEmail')) {
      el('otpContactEmail').required = state.missingEmail;
      el('otpContactEmail').disabled = !state.missingEmail;
    }
    if (el('otpContactPhone')) {
      el('otpContactPhone').required = state.missingPhone;
      el('otpContactPhone').disabled = !state.missingPhone;
    }
  }

  function showVerifyForm(data) {
    state.pendingHouse = data.houseId || state.pendingHouse;
    state.pendingContact = Boolean(data.contactPending || data.pendingContact);
    el('otpRequestForm').hidden = true;
    el('otpContactForm').hidden = true;
    el('otpVerifyForm').hidden = false;
    let hint = `Code sent for plot <strong>${escapeHtml(state.pendingHouse)}</strong>`;
    if (data.emailMasked) hint += ` to ${escapeHtml(data.emailMasked)}`;
    if (data.devCode) hint += `. Dev code: <code>${escapeHtml(data.devCode)}</code>`;
    if (state.pendingContact) {
      hint += '. Enter the code to confirm — email/phone are saved only after verification.';
    }
    el('otpHint').innerHTML = hint;
  }

  async function requestOtp(payload) {
    return api('/api/rwa/otp/request', {
      method: 'POST',
      body: JSON.stringify({ website: '', ...payload }),
    });
  }

  el('otpRequestForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    const houseId = el('houseIdInput').value.trim();
    el('requestOtpBtn').disabled = true;
    try {
      const data = await requestOtp({ houseId });
      state.pendingHouse = data.houseId || houseId;
      if (data.needsContact) {
        showContactForm(data);
        return;
      }
      showVerifyForm(data);
    } catch (err) {
      showError(err.message || 'Could not send code');
    } finally {
      el('requestOtpBtn').disabled = false;
    }
  });

  el('otpContactForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    const btn = el('otpContactSubmitBtn');
    if (btn) btn.disabled = true;
    try {
      const payload = { houseId: state.pendingHouse || el('houseIdInput').value.trim() };
      if (state.missingEmail) payload.email = el('otpContactEmail').value.trim();
      if (state.missingPhone) payload.phone = el('otpContactPhone').value.trim();
      const data = await requestOtp(payload);
      if (data.needsContact) {
        showContactForm(data);
        showError(data.message || 'Please complete the contact details');
        return;
      }
      showVerifyForm(data);
    } catch (err) {
      showError(err.message || 'Could not send verification code');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('otpVerifyForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showError('');
    el('verifyOtpBtn').disabled = true;
    try {
      const data = await api('/api/rwa/otp/verify', {
        method: 'POST',
        body: JSON.stringify({ houseId: state.pendingHouse, code: el('otpInput').value.trim() }),
      });
      setAuthed(data);
      await loadHome();
      if (data.contactUpdated) {
        // Soft notice on home after contact verify
        const list = el('noticeList');
        if (list) {
          const note = document.createElement('p');
          note.className = 'muted';
          note.textContent = 'Your email/phone were verified and saved to the colony register.';
          list.prepend(note);
        }
      }
    } catch (err) {
      showError(err.message || 'Invalid code');
    } finally {
      el('verifyOtpBtn').disabled = false;
    }
  });

  el('otpContactBackBtn')?.addEventListener('click', () => resetLoginForms());
  el('restartLoginBtn')?.addEventListener('click', () => resetLoginForms());

  el('logoutBtn')?.addEventListener('click', async () => {
    try { await api('/api/rwa/logout', { method: 'POST', body: '{}' }); } catch (_e) { /* ignore */ }
    setAuthed(null);
    resetLoginForms();
  });

  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchPanel(tab.dataset.panel));
  });

  el('profileForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('profileStatus');
    status.textContent = 'Saving…';
    try {
      const body = {
        title: el('profileTitle')?.value.trim() || '',
        name: el('profileName').value.trim(),
        profession: el('profileProfession')?.value.trim() || '',
        employmentStatus: el('profileEmployment')?.value || 'unknown',
        email: el('profileEmail').value.trim(),
        phone: el('profilePhone').value.trim(),
      };
      if (isEcAdmin() && !isSuperAdmin()) {
        body.officialTitle = el('profileOfficialTitle')?.value.trim() || '';
      }
      const data = await api('/api/rwa/profile', {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      state.session.resident = data.resident;
      setAuthed(state.session);
      status.textContent = 'Saved.';
    } catch (err) {
      status.textContent = err.message || 'Save failed';
    }
  });

  el('noticeForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const fd = new FormData(form);
    const noticeId = String(fd.get('id') || '').trim();
    const status = el('noticeFormStatus');
    const btn = el('noticeSubmitBtn');
    if (status) status.textContent = noticeId ? 'Saving…' : 'Publishing…';
    if (btn) btn.disabled = true;
    try {
      const payload = {
        title: fd.get('title'),
        body: fd.get('body'),
        category: fd.get('category'),
        pinned: fd.get('pinned') === 'on',
      };
      if (noticeId) {
        await api(`/api/rwa/notices/${encodeURIComponent(noticeId)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
      } else {
        await api('/api/rwa/notices', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      resetNoticeForm();
      await loadHome();
      switchPanel('home');
    } catch (err) {
      if (status) status.textContent = err.message || 'Publish failed';
      else alert(err.message || 'Publish failed');
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('noticeCancelEditBtn')?.addEventListener('click', () => resetNoticeForm());

  el('noticeList')?.addEventListener('click', async (event) => {
    const editBtn = event.target.closest('.notice-edit');
    const pinBtn = event.target.closest('.notice-pin');
    const delBtn = event.target.closest('.notice-delete');
    const upBtn = event.target.closest('.notice-move-up');
    const downBtn = event.target.closest('.notice-move-down');
    if (!isEcAdmin()) return;

    if (editBtn) {
      const id = editBtn.getAttribute('data-id');
      const notice = noticesCache.find((n) => n.id === id);
      if (notice) startNoticeEdit(notice);
      return;
    }

    if (upBtn || downBtn) {
      const btn = upBtn || downBtn;
      const id = btn.getAttribute('data-id');
      const move = upBtn ? 'up' : 'down';
      btn.disabled = true;
      try {
        await api(`/api/rwa/notices/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ move }),
        });
        await loadHome();
      } catch (err) {
        alert(err.message || 'Could not reorder notice');
        btn.disabled = false;
      }
      return;
    }

    if (pinBtn) {
      const id = pinBtn.getAttribute('data-id');
      const pinned = pinBtn.getAttribute('data-pinned') === '1';
      pinBtn.disabled = true;
      try {
        await api(`/api/rwa/notices/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ pinned: !pinned }),
        });
        await loadHome();
      } catch (err) {
        alert(err.message || 'Could not update pin');
      } finally {
        pinBtn.disabled = false;
      }
      return;
    }

    if (delBtn) {
      const id = delBtn.getAttribute('data-id');
      const notice = noticesCache.find((n) => n.id === id);
      if (!window.confirm(`Delete notice “${notice?.title || id}”?`)) return;
      delBtn.disabled = true;
      try {
        await api(`/api/rwa/notices/${encodeURIComponent(id)}`, { method: 'DELETE', body: '{}' });
        await loadHome();
      } catch (err) {
        alert(err.message || 'Delete failed');
      } finally {
        delBtn.disabled = false;
      }
    }
  });

  function statusLabel(status) {
    return ({
      open: 'Open',
      in_progress: 'In progress',
      resolved: 'Resolved',
      closed: 'Closed',
    })[status] || status || 'Open';
  }

  function formatWhen(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
    } catch (_e) {
      return String(iso).slice(0, 16);
    }
  }

  function renderMessageTrail(messages) {
    const items = messages || [];
    if (!items.length) return '<p class="muted">No messages yet.</p>';
    return `<div class="msg-trail">${items.map((m) => `
      <article class="msg-bubble ${m.authorRole === 'ec' ? 'is-ec' : 'is-resident'}">
        <header>
          <strong>${escapeHtml(m.authorName || (m.authorRole === 'ec' ? 'EC' : 'Resident'))}</strong>
          <span>${m.authorRole === 'ec' ? 'EC' : 'Resident'}${m.authorHouseId ? ` · plot ${escapeHtml(m.authorHouseId)}` : ''}</span>
          <time>${escapeHtml(formatWhen(m.createdAt))}</time>
        </header>
        <p>${escapeHtml(m.body)}</p>
      </article>`).join('')}</div>`;
  }

  function renderMailboxCard(g, { ecMode = false } = {}) {
    const closed = g.status === 'closed';
    const replyBox = closed
      ? '<p class="muted">Thread closed.</p>'
      : `
        <form class="mailbox-reply" data-id="${escapeHtml(g.id)}">
          <label>
            <span class="sr-only">Reply</span>
            <textarea name="body" rows="2" required placeholder="${ecMode ? 'EC reply…' : 'Add a reply…'}"></textarea>
          </label>
          ${ecMode ? `
            <label class="mailbox-status-pick">
              Status
              <select name="status">
                <option value="in_progress"${g.status === 'in_progress' ? ' selected' : ''}>In progress</option>
                <option value="open"${g.status === 'open' ? ' selected' : ''}>Open</option>
                <option value="resolved"${g.status === 'resolved' ? ' selected' : ''}>Resolved</option>
                <option value="closed"${g.status === 'closed' ? ' selected' : ''}>Closed</option>
              </select>
            </label>` : ''}
          <div class="btn-row">
            <button type="submit" class="btn secondary compact">${ecMode ? 'Reply as EC' : 'Reply'}</button>
          </div>
          <p class="muted row-status" hidden></p>
        </form>`;
    return `
      <article class="grievance-card" data-id="${escapeHtml(g.id)}">
        <div class="grievance-card-head">
          <h4>${escapeHtml(g.subject)}</h4>
          <span class="grievance-badge is-${escapeHtml(g.status)}">${escapeHtml(statusLabel(g.status))}</span>
        </div>
        <p class="grievance-meta">
          ${escapeHtml(g.categoryLabel || g.category)}
          · plot <code>${escapeHtml(g.houseId)}</code>
          ${g.name ? ` · ${escapeHtml(g.name)}` : ''}
          · ${escapeHtml(formatWhen(g.updatedAt || g.createdAt))}
          · ${(g.messages || []).length} message${(g.messages || []).length === 1 ? '' : 's'}
        </p>
        ${renderMessageTrail(g.messages)}
        ${replyBox}
      </article>`;
  }

  async function loadMailbox() {
    const status = el('mailboxStatusFilter')?.value || 'all';
    const category = el('mailboxCategoryFilter')?.value || 'all';
    const qs = new URLSearchParams();
    if (status && status !== 'all') qs.set('status', status);
    if (category && category !== 'all') qs.set('category', category);
    const data = await api(`/api/rwa/grievances?${qs.toString()}`);
    const list = el('mailboxList');
    const stats = data.stats || {};
    if (el('mailboxStats')) {
      el('mailboxStats').textContent =
        `${stats.total || 0} threads · ${stats.open || 0} open · ${stats.inProgress || 0} in progress · ${stats.resolved || 0} resolved`;
    }
    const rows = data.grievances || [];
    if (!list) return;
    if (!rows.length) {
      list.innerHTML = '<p class="muted">No concerns in the mailbox yet. Post the first one above.</p>';
      return;
    }
    list.innerHTML = rows.map((g) => renderMailboxCard(g, { ecMode: isEcAdmin() })).join('');
  }

  async function loadEcGrievances() {
    if (!isEcAdmin()) return;
    const status = el('ecGrievanceStatusFilter')?.value || 'open';
    const category = el('ecGrievanceCategoryFilter')?.value || 'all';
    const qs = new URLSearchParams();
    if (status && status !== 'all') qs.set('status', status);
    if (category && category !== 'all') qs.set('category', category);
    const data = await api(`/api/rwa/grievances?${qs.toString()}`);
    const stats = data.stats || {};
    if (el('ecGrievanceStats')) {
      el('ecGrievanceStats').textContent =
        `${stats.open || 0} open · ${stats.inProgress || 0} in progress · ${stats.resolved || 0} resolved · ${stats.total || 0} total`;
    }
    const list = el('ecGrievanceList');
    const rows = data.grievances || [];
    if (!list) return;
    if (!rows.length) {
      list.innerHTML = '<p class="muted">No concerns match this filter.</p>';
      return;
    }
    list.innerHTML = rows.map((g) => renderMailboxCard(g, { ecMode: true })).join('');
    if (el('ecGrievanceStatus')) el('ecGrievanceStatus').textContent = '';
  }

  async function submitMailboxReply(form) {
    const id = form.getAttribute('data-id');
    const body = form.querySelector('textarea[name="body"]')?.value.trim() || '';
    const status = form.querySelector('select[name="status"]')?.value;
    const statusEl = form.querySelector('.row-status');
    const btn = form.querySelector('button[type="submit"]');
    if (!id || !body) return;
    if (statusEl) {
      statusEl.hidden = false;
      statusEl.textContent = 'Sending…';
    }
    if (btn) btn.disabled = true;
    try {
      const payload = { body };
      if (status) payload.status = status;
      if (isEcAdmin()) {
        await api(`/api/rwa/grievances/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ response: body, status: status || 'in_progress' }),
        });
      } else {
        await api(`/api/rwa/grievances/${encodeURIComponent(id)}/messages`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      }
      form.querySelector('textarea[name="body"]').value = '';
      await loadMailbox();
      if (isEcAdmin()) await loadEcGrievances().catch(() => {});
    } catch (err) {
      if (statusEl) statusEl.textContent = err.message || 'Reply failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  el('grievanceForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('grievanceFormStatus');
    const btn = el('grievanceSubmitBtn');
    if (status) status.textContent = 'Posting…';
    if (btn) btn.disabled = true;
    try {
      await api('/api/rwa/grievances', {
        method: 'POST',
        body: JSON.stringify({
          category: el('grievanceCategory').value,
          subject: el('grievanceSubject').value.trim(),
          body: el('grievanceBody').value.trim(),
        }),
      });
      el('grievanceForm').reset();
      if (status) status.textContent = 'Posted to the colony mailbox.';
      await loadMailbox();
      if (isEcAdmin()) await loadEcGrievances().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Could not post';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  el('mailboxList')?.addEventListener('submit', (event) => {
    const form = event.target.closest('form.mailbox-reply');
    if (!form) return;
    event.preventDefault();
    submitMailboxReply(form);
  });
  el('ecGrievanceList')?.addEventListener('submit', (event) => {
    const form = event.target.closest('form.mailbox-reply');
    if (!form) return;
    event.preventDefault();
    submitMailboxReply(form);
  });
  el('mailboxRefreshBtn')?.addEventListener('click', () => loadMailbox().catch(console.error));
  el('mailboxStatusFilter')?.addEventListener('change', () => loadMailbox().catch(console.error));
  el('mailboxCategoryFilter')?.addEventListener('change', () => loadMailbox().catch(console.error));
  el('ecGrievanceRefreshBtn')?.addEventListener('click', () => loadEcGrievances().catch(console.error));
  el('ecGrievanceStatusFilter')?.addEventListener('change', () => loadEcGrievances().catch(console.error));
  el('ecGrievanceCategoryFilter')?.addEventListener('change', () => loadEcGrievances().catch(console.error));

  el('ledgerImportForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = el('ledgerImportStatus');
    const fileInput = event.currentTarget.querySelector('input[type="file"]');
    if (!fileInput?.files?.length) return;
    status.textContent = 'Importing…';
    try {
      const body = new FormData();
      body.append('file', fileInput.files[0]);
      const headers = {};
      if (state.session?.token) headers['X-RWA-Token'] = state.session.token;
      const res = await fetch('/api/rwa/ledger/import', {
        method: 'POST',
        credentials: 'same-origin',
        headers,
        body,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || res.statusText);
      status.textContent = `Imported ${data.rows || data.residents || 0} rows (ledger ${data.ledgerId || ''}).`;
      await loadRoster().catch(() => {});
    } catch (err) {
      status.textContent = err.message || 'Import failed';
    }
  });

  let rosterCache = [];

  function renderRosterStats(stats) {
    const line = el('rosterStats');
    if (!line || !stats) return;
    line.textContent = `${stats.total} plots · ${stats.withPhone} with phone · ${stats.missingPhone} missing · ${stats.withEmail} with email`;
  }

  function rosterMatches(r, q, missingOnly) {
    if (missingOnly && r.phone) return false;
    if (!q) return true;
    const hay = `${r.houseId} ${r.plotNo} ${r.title || ''} ${r.name} ${r.profession || ''} ${r.phone || ''} ${r.email || ''} ${r.officialTitle || ''} ${r.role}`.toLowerCase();
    return hay.includes(q);
  }

  function renderRosterRows() {
    const tbody = el('rosterRows');
    if (!tbody) return;
    const q = (el('rosterSearch')?.value || '').trim().toLowerCase();
    const missingOnly = Boolean(el('rosterMissingPhone')?.checked);
    const rows = rosterCache.filter((r) => rosterMatches(r, q, missingOnly));
    const superOnly = isSuperAdmin();
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="12" class="muted">No matching residents.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map((r) => {
      const roleDisabled = superOnly ? '' : ' disabled';
      const statusDisabled = (superOnly || r.role !== 'admin') ? '' : ' disabled';
      const statusNote = (!superOnly && r.role === 'admin') ? ' title="Only super admin can suspend EC admins"' : '';
      return `
      <tr data-house="${escapeHtml(r.houseId)}" class="${r.phone ? '' : 'is-missing-phone'}">
        <td class="plot-cell">${escapeHtml(r.houseId)}<div class="muted" style="font-weight:500;font-size:0.7rem">${escapeHtml(r.section || '')}</div></td>
        <td><input name="title" value="${escapeHtml(r.title || '')}" placeholder="Mr/Mrs/Dr" aria-label="Title ${escapeHtml(r.houseId)}"></td>
        <td><input name="name" value="${escapeHtml(r.name || '')}" aria-label="Name ${escapeHtml(r.houseId)}"></td>
        <td><input name="profession" value="${escapeHtml(r.profession || '')}" placeholder="Profession" aria-label="Profession ${escapeHtml(r.houseId)}"></td>
        <td>
          <select name="employmentStatus" aria-label="Employment ${escapeHtml(r.houseId)}">
            <option value="unknown"${(r.employmentStatus || 'unknown') === 'unknown' ? ' selected' : ''}>—</option>
            <option value="working"${r.employmentStatus === 'working' ? ' selected' : ''}>Working</option>
            <option value="retired"${r.employmentStatus === 'retired' ? ' selected' : ''}>Retired</option>
          </select>
        </td>
        <td><input name="phone" type="tel" inputmode="tel" placeholder="mobile" value="${escapeHtml(r.phone || '')}" aria-label="Phone ${escapeHtml(r.houseId)}"></td>
        <td><input name="email" type="email" placeholder="email" value="${escapeHtml(r.email || '')}" aria-label="Email ${escapeHtml(r.houseId)}"></td>
        <td><input name="officialTitle" value="${escapeHtml(r.officialTitle || '')}" placeholder="EC title" aria-label="Official title ${escapeHtml(r.houseId)}"></td>
        <td><input name="notes" value="${escapeHtml(r.notes || '')}" placeholder="notes" aria-label="Notes ${escapeHtml(r.houseId)}"></td>
        <td>
          <select name="role" aria-label="Role ${escapeHtml(r.houseId)}"${roleDisabled}>
            <option value="resident"${r.role === 'resident' ? ' selected' : ''}>Resident</option>
            <option value="admin"${r.role === 'admin' ? ' selected' : ''}>EC admin</option>
          </select>
        </td>
        <td>
          <select name="status" aria-label="Status ${escapeHtml(r.houseId)}"${statusDisabled}${statusNote}>
            <option value="active"${(r.status || 'active') === 'active' ? ' selected' : ''}>Active</option>
            <option value="inactive"${r.status === 'inactive' ? ' selected' : ''}>Suspended</option>
          </select>
        </td>
        <td>
          <button type="button" class="btn secondary compact roster-save" data-house="${escapeHtml(r.houseId)}">Save</button>
          <div class="row-status"></div>
        </td>
      </tr>`;
    }).join('');
  }

  async function loadRoster() {
    if (!isEcAdmin()) return;
    const data = await api('/api/rwa/residents');
    rosterCache = data.residents || [];
    renderRosterStats(data.stats);
    renderRosterRows();
    if (el('rosterStatus')) el('rosterStatus').textContent = isSuperAdmin()
      ? 'Super admin: you can assign, remove, or suspend EC admins.'
      : 'EC: edit resident details. Role / EC suspend requires Super admin.';
  }

  function residentApiId(houseId) {
    return encodeURIComponent(String(houseId || ''));
  }

  async function saveRosterRow(houseId, tr) {
    const status = tr.querySelector('.row-status');
    const btn = tr.querySelector('.roster-save');
    const payload = {
      title: tr.querySelector('input[name="title"]')?.value.trim() || '',
      name: tr.querySelector('input[name="name"]')?.value.trim() || '',
      profession: tr.querySelector('input[name="profession"]')?.value.trim() || '',
      employmentStatus: tr.querySelector('select[name="employmentStatus"]')?.value || 'unknown',
      phone: tr.querySelector('input[name="phone"]')?.value.trim() || '',
      email: tr.querySelector('input[name="email"]')?.value.trim() || '',
      officialTitle: tr.querySelector('input[name="officialTitle"]')?.value.trim() || '',
      notes: tr.querySelector('input[name="notes"]')?.value.trim() || '',
    };
    if (isSuperAdmin()) {
      payload.role = tr.querySelector('select[name="role"]')?.value || 'resident';
      payload.status = tr.querySelector('select[name="status"]')?.value || 'active';
    } else {
      const st = tr.querySelector('select[name="status"]');
      if (st && !st.disabled) payload.status = st.value;
    }
    if (status) status.textContent = 'Saving…';
    if (btn) btn.disabled = true;
    try {
      const data = await api(`/api/rwa/residents/${residentApiId(houseId)}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      const updated = data.resident || {};
      const idx = rosterCache.findIndex((r) => r.houseId === houseId);
      if (idx >= 0) {
        rosterCache[idx] = { ...rosterCache[idx], ...updated, hasPhone: Boolean(updated.phone), hasEmail: Boolean(updated.email) };
      }
      renderRosterStats(data.stats);
      tr.classList.remove('is-dirty');
      tr.classList.toggle('is-missing-phone', !updated.phone);
      if (status) status.textContent = 'Saved';
      loadRevisions().catch(() => {});
    } catch (err) {
      if (status) status.textContent = err.message || 'Failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  el('rosterSearch')?.addEventListener('input', () => renderRosterRows());
  el('rosterMissingPhone')?.addEventListener('change', () => renderRosterRows());
  el('rosterRows')?.addEventListener('input', (event) => {
    const tr = event.target.closest('tr[data-house]');
    if (tr) tr.classList.add('is-dirty');
  });
  el('rosterRows')?.addEventListener('change', (event) => {
    const tr = event.target.closest('tr[data-house]');
    if (tr) tr.classList.add('is-dirty');
  });
  el('rosterRows')?.addEventListener('click', (event) => {
    const btn = event.target.closest('.roster-save');
    if (!btn) return;
    const houseId = btn.getAttribute('data-house');
    const tr = btn.closest('tr[data-house]');
    if (houseId && tr) saveRosterRow(houseId, tr);
  });
  el('rosterRows')?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    const tr = event.target.closest('tr[data-house]');
    if (!tr) return;
    event.preventDefault();
    saveRosterRow(tr.getAttribute('data-house'), tr);
  });

  function fieldDiffSummary(rev) {
    const fields = rev.fields || [];
    if (!fields.length) return '—';
    return fields.map((f) => {
      const before = rev.before?.[f] ?? '';
      const after = rev.after?.[f] ?? '';
      return `${f}: “${before || '—'}” → “${after || '—'}”`;
    }).join('; ');
  }

  async function loadRevisions() {
    if (!isEcAdmin()) return;
    const houseId = (el('revisionHouseFilter')?.value || '').trim();
    const qs = houseId ? `?houseId=${encodeURIComponent(houseId)}&limit=80` : '?limit=80';
    const data = await api(`/api/rwa/residents/revisions${qs}`);
    const tbody = el('revisionRows');
    const rows = data.revisions || [];
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted">No revisions yet.</td></tr>';
      if (el('revisionStatus')) el('revisionStatus').textContent = '';
      return;
    }
    tbody.innerHTML = rows.map((rev) => `
      <tr>
        <td>${escapeHtml((rev.changedAt || '').replace('T', ' ').replace('Z', ''))}</td>
        <td><code>${escapeHtml(rev.houseId)}</code></td>
        <td>${escapeHtml(rev.changedByName || rev.changedByHouseId || 'system')}<div class="muted" style="font-size:0.7rem">${escapeHtml(rev.source || '')}</div></td>
        <td>${escapeHtml((rev.fields || []).join(', ') || '—')}</td>
        <td class="muted">${escapeHtml(fieldDiffSummary(rev))}</td>
      </tr>`).join('');
    if (el('revisionStatus')) el('revisionStatus').textContent = `${rows.length} recent change(s)`;
  }

  el('revisionRefreshBtn')?.addEventListener('click', () => loadRevisions().catch(console.error));
  el('revisionHouseFilter')?.addEventListener('change', () => loadRevisions().catch(console.error));
  el('revisionHouseFilter')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      loadRevisions().catch(console.error);
    }
  });

  async function loadSmtpStatus() {
    const line = el('smtpStatusLine');
    if (!line || !isEcAdmin()) return;
    try {
      const data = await api('/api/rwa/smtp/status');
      line.textContent = data.configured
        ? `SMTP ready · ${data.provider} · from ${data.from}`
        : `SMTP not configured — set App Password in Platform settings (from ${data.from || 'vij.ksh@gmail.com'})`;
    } catch (_e) {
      line.textContent = 'SMTP status unavailable';
    }
  }

  async function loadSettings() {
    if (!isSuperAdmin()) return;
    const data = await api('/api/rwa/settings');
    const s = data.settings || {};
    const smtp = s.smtp || {};
    if (el('settingsSmtpProvider')) el('settingsSmtpProvider').value = smtp.provider || 'gmail';
    if (el('settingsSmtpHost')) el('settingsSmtpHost').value = smtp.host || '';
    if (el('settingsSmtpPort')) el('settingsSmtpPort').value = smtp.port || 587;
    if (el('settingsSmtpUser')) el('settingsSmtpUser').value = smtp.user || '';
    if (el('settingsSmtpFrom')) el('settingsSmtpFrom').value = smtp.from || '';
    if (el('settingsSmtpPass')) el('settingsSmtpPass').placeholder = smtp.passwordSet ? '•••••••• (leave blank to keep)' : 'Gmail App Password';
    if (el('settingsOtpTtl')) el('settingsOtpTtl').value = s.otpTtl || 600;
    if (el('settingsSaUser')) el('settingsSaUser').value = s.superadminUser || 'admin';
    if (el('settingsStatus')) {
      el('settingsStatus').textContent = smtp.configured
        ? `Configured · file ${s.envFile || 'data/smtp.env'}`
        : `Not fully configured · edit and save (${s.envFile || 'data/smtp.env'})`;
    }
  }

  el('settingsForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!isSuperAdmin()) return;
    const status = el('settingsStatus');
    const btn = el('settingsSaveBtn');
    if (status) status.textContent = 'Saving…';
    if (btn) btn.disabled = true;
    try {
      const payload = {
        smtp: {
          provider: el('settingsSmtpProvider')?.value || 'gmail',
          host: el('settingsSmtpHost')?.value.trim() || '',
          port: Number(el('settingsSmtpPort')?.value || 587),
          user: el('settingsSmtpUser')?.value.trim() || '',
          from: el('settingsSmtpFrom')?.value.trim() || '',
        },
        otpTtl: Number(el('settingsOtpTtl')?.value || 600),
        superadminUser: el('settingsSaUser')?.value.trim() || 'admin',
      };
      const pass = el('settingsSmtpPass')?.value || '';
      if (pass) payload.smtp.password = pass;
      const saPass = el('settingsSaPass')?.value || '';
      if (saPass) payload.superadminPassword = saPass;
      const data = await api('/api/rwa/settings', { method: 'PUT', body: JSON.stringify(payload) });
      if (el('settingsSmtpPass')) el('settingsSmtpPass').value = '';
      if (el('settingsSaPass')) el('settingsSaPass').value = '';
      const smtp = data.settings?.smtp || {};
      if (status) {
        status.textContent = smtp.configured
          ? 'Settings saved. SMTP ready.'
          : 'Settings saved. SMTP still needs an App Password.';
      }
      loadSmtpStatus();
    } catch (err) {
      if (status) status.textContent = err.message || 'Save failed';
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // Progressive Web App: service worker + install hint
  let deferredInstall = null;
  function showPwaHint(html) {
    const box = el('pwaInstallHint');
    if (!box) return;
    box.hidden = false;
    box.innerHTML = html;
  }
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredInstall = event;
    showPwaHint(
      'Install HBC Sanyard on your phone for one-tap access.' +
      ' <button type="button" class="btn secondary compact" id="pwaInstallBtn">Add to Home Screen</button>'
    );
    el('pwaInstallBtn')?.addEventListener('click', async () => {
      if (!deferredInstall) return;
      deferredInstall.prompt();
      try { await deferredInstall.userChoice; } catch (_e) { /* ignore */ }
      deferredInstall = null;
      const box = el('pwaInstallHint');
      if (box) box.hidden = true;
    }, { once: true });
  });
  window.addEventListener('appinstalled', () => {
    deferredInstall = null;
    const box = el('pwaInstallHint');
    if (box) {
      box.hidden = false;
      box.textContent = 'Installed. Open HBC Sanyard from your home screen anytime.';
    }
  });
  // iOS Safari has no beforeinstallprompt — show manual tip
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;
  if (isIos && !isStandalone) {
    showPwaHint('On iPhone: tap Share → <strong>Add to Home Screen</strong> to install HBC Sanyard.');
  }
  if ('serviceWorker' in navigator) {
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (refreshing) return;
      refreshing = true;
      window.location.reload();
    });

    const setRefreshStatus = (msg) => {
      const s = el('appRefreshStatus');
      if (s) s.textContent = msg;
    };

    async function hardRefreshApp() {
      setRefreshStatus('Updating…');
      try {
        if ('caches' in window) {
          const keys = await caches.keys();
          await Promise.all(keys.map((k) => caches.delete(k)));
        }
        const reg = await navigator.serviceWorker.getRegistration();
        if (reg) {
          await reg.update();
          if (reg.waiting) reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        }
      } catch (_e) { /* ignore */ }
      window.location.reload();
    }

    el('appRefreshBtn')?.addEventListener('click', () => hardRefreshApp());

    navigator.serviceWorker.register('/sw.js').then(async (reg) => {
      // Auto-check for a new service worker on launch and periodically
      try { await reg.update(); } catch (_e) { /* ignore */ }
      if (reg.waiting) {
        setRefreshStatus('Update ready — refreshing…');
        reg.waiting.postMessage({ type: 'SKIP_WAITING' });
      }
      reg.addEventListener('updatefound', () => {
        const sw = reg.installing;
        if (!sw) return;
        sw.addEventListener('statechange', () => {
          if (sw.state === 'installed' && navigator.serviceWorker.controller) {
            setRefreshStatus('Update ready — refreshing…');
            sw.postMessage({ type: 'SKIP_WAITING' });
          }
        });
      });
      setInterval(() => { reg.update().catch(() => {}); }, 5 * 60 * 1000);
    }).catch((err) => {
      console.warn('Service worker registration failed', err);
    });
  } else {
    el('appRefreshBtn')?.addEventListener('click', () => window.location.reload());
  }

  refreshSession().catch(() => setAuthed(null));
})();
