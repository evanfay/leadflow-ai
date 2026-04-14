/**
 * LeadFlow AI — Main JavaScript
 */

/* ─────────────────────────────────────────────
   1. NAV BADGE COUNTS
   ───────────────────────────────────────────── */
function updateNavCounts() {
  fetch('/api/nav-counts')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
      const taskBadge = document.getElementById('nav-tasks-badge');
      const inboxBadge = document.getElementById('nav-inbox-badge');
      if (taskBadge) {
        taskBadge.textContent = data.tasks || '';
        taskBadge.style.display = data.tasks ? 'inline-flex' : 'none';
      }
      if (inboxBadge) {
        inboxBadge.textContent = data.replies || '';
        inboxBadge.style.display = data.replies ? 'inline-flex' : 'none';
      }
    })
    .catch(() => {});
}

/* ─────────────────────────────────────────────
   2. TOAST NOTIFICATIONS
   ───────────────────────────────────────────── */
(function initToasts() {
  const container = document.createElement('div');
  container.id = 'toast-container';
  container.style.cssText = [
    'position:fixed', 'bottom:1.5rem', 'right:1.5rem',
    'display:flex', 'flex-direction:column', 'gap:0.5rem',
    'z-index:9999', 'pointer-events:none'
  ].join(';');
  document.body.appendChild(container);
})();

window.showToast = function(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const icons = {
    success: 'check-circle',
    error:   'x-circle',
    warning: 'alert-triangle',
    info:    'info'
  };
  const colors = {
    success: 'var(--accent-1)',
    error:   'var(--danger)',
    warning: 'var(--accent-2)',
    info:    'var(--text-muted)'
  };

  const toast = document.createElement('div');
  toast.style.cssText = [
    'display:flex', 'align-items:center', 'gap:0.625rem',
    'background:var(--bg-card)', 'border:1px solid var(--border)',
    'border-radius:var(--radius)', 'padding:0.75rem 1rem',
    'box-shadow:var(--shadow-md)', 'pointer-events:all',
    'max-width:360px', 'font-size:0.875rem',
    'animation:fadeInUp 0.2s ease'
  ].join(';');

  toast.innerHTML = `
    <i data-lucide="${icons[type] || 'info'}" style="width:16px;height:16px;color:${colors[type]};flex-shrink:0;"></i>
    <span style="color:var(--text-body);flex:1;">${message}</span>
    <button onclick="this.parentElement.remove()" style="background:none;border:none;cursor:pointer;color:var(--text-muted);padding:0;display:flex;align-items:center;">
      <i data-lucide="x" style="width:14px;height:14px;"></i>
    </button>
  `;

  container.appendChild(toast);
  if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [toast] });

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
};

/* ─────────────────────────────────────────────
   3. FLASH MESSAGE → TOAST BRIDGE
   ───────────────────────────────────────────── */
function flashesToToasts() {
  document.querySelectorAll('.flash-message').forEach(el => {
    const type = el.dataset.type || 'info';
    const map = { danger: 'error', success: 'success', warning: 'warning', info: 'info' };
    showToast(el.textContent.trim(), map[type] || 'info');
    el.remove();
  });
}

/* ─────────────────────────────────────────────
   4. MODAL HELPERS
   ───────────────────────────────────────────── */
window.openModal = function(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'flex';
};

window.closeModal = function(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'none';
};

function initModalOverlayClose() {
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.style.display = 'none';
    });
  });
}

function initModalCloseBtns() {
  document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', () => {
      const modal = btn.closest('.modal-overlay');
      if (modal) modal.style.display = 'none';
    });
  });
}

/* ─────────────────────────────────────────────
   5. CONFIRM DIALOGS (destructive actions)
   ───────────────────────────────────────────── */
function initConfirmForms() {
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', e => {
      const msg = form.dataset.confirm || 'Are you sure?';
      if (!confirm(msg)) e.preventDefault();
    });
  });
}

/* ─────────────────────────────────────────────
   6. CAMPAIGN DETAIL TABS
   ───────────────────────────────────────────── */
function initCampaignTabs() {
  const tabBar = document.querySelector('.tabs');
  if (!tabBar) return;

  const tabs    = tabBar.querySelectorAll('.tab');
  const panels  = document.querySelectorAll('.tab-panel');

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab;
      tabs.forEach(t => t.classList.toggle('active', t === tab));
      panels.forEach(p => {
        p.style.display = p.id === `panel-${target}` ? '' : 'none';
      });
      // persist in URL hash
      history.replaceState(null, '', `#${target}`);
    });
  });

  // restore from hash
  const hash = location.hash.replace('#', '');
  if (hash) {
    const match = tabBar.querySelector(`.tab[data-tab="${hash}"]`);
    if (match) match.click();
  }
}

/* ─────────────────────────────────────────────
   7. SEQUENCE BUILDER
   ───────────────────────────────────────────── */
function initSequenceBuilder() {
  const container = document.getElementById('steps-container');
  if (!container) return;

  // Add step button
  const addBtn = document.getElementById('add-step-btn');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      const stepCount = container.querySelectorAll('.builder-step').length;
      addBuilderStep(container, stepCount + 1);
    });
  }

  // Remove step delegation
  container.addEventListener('click', e => {
    const removeBtn = e.target.closest('.remove-step-btn');
    if (!removeBtn) return;
    const step = removeBtn.closest('.builder-step');
    if (step) {
      step.style.opacity = '0';
      step.style.transition = 'opacity 0.2s';
      setTimeout(() => {
        step.remove();
        renumberSteps(container);
      }, 200);
    }
  });

  // Touch-type change → show/hide subject field
  container.addEventListener('change', e => {
    if (e.target.matches('select[name$="[touch_type]"]')) {
      const step = e.target.closest('.builder-step');
      updateStepUI(step, e.target.value);
    }
  });
}

function addBuilderStep(container, index) {
  const html = `
    <div class="builder-step" data-index="${index}" style="animation:fadeInUp 0.2s ease;">
      <div class="builder-step-header">
        <span class="step-number">Step ${index}</span>
        <button type="button" class="remove-step-btn btn btn-xs btn-danger-ghost">
          <i data-lucide="trash-2"></i>
        </button>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Touch Type</label>
          <select name="steps[${index}][touch_type]" class="form-control">
            <option value="email">Email</option>
            <option value="linkedin_connect">LinkedIn Connect</option>
            <option value="linkedin_dm">LinkedIn DM</option>
            <option value="voicemail">Voicemail</option>
            <option value="live_call">Live Call</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Day Offset</label>
          <input type="number" name="steps[${index}][day_offset]" class="form-control"
                 value="${(index - 1) * 3}" min="0" max="365">
        </div>
      </div>
    </div>`;

  const el = document.createElement('div');
  el.innerHTML = html.trim();
  const step = el.firstChild;
  container.appendChild(step);
  if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [step] });
}

function renumberSteps(container) {
  container.querySelectorAll('.builder-step').forEach((step, i) => {
    const num = i + 1;
    step.dataset.index = num;
    const numEl = step.querySelector('.step-number');
    if (numEl) numEl.textContent = `Step ${num}`;
    step.querySelectorAll('[name]').forEach(el => {
      el.name = el.name.replace(/steps\[\d+\]/, `steps[${num}]`);
    });
  });
}

function updateStepUI(step, touchType) {
  const emailTypes = ['email'];
  const subjectRow = step.querySelector('.subject-row');
  if (subjectRow) {
    subjectRow.style.display = emailTypes.includes(touchType) ? '' : 'none';
  }
}

/* ─────────────────────────────────────────────
   8. LEAD UPLOAD — COLUMN MAPPING
   ───────────────────────────────────────────── */
function initUploadMapping() {
  const form = document.getElementById('upload-form');
  if (!form) return;

  const fileInput = form.querySelector('input[type="file"]');
  const dropzone  = form.querySelector('.dropzone');
  const mappingSection = document.getElementById('mapping-section');

  if (!fileInput) return;

  // Dropzone highlight
  if (dropzone) {
    dropzone.addEventListener('dragover', e => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', e => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        fileInput.dispatchEvent(new Event('change'));
      }
    });
    dropzone.addEventListener('click', () => fileInput.click());
  }

  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (!file) return;

    const label = form.querySelector('.dropzone-label');
    if (label) label.textContent = file.name;

    // Show preview / mapping hint
    if (mappingSection) mappingSection.style.display = '';
  });

  // Column mapping selects — auto-match by header name
  const mapSelects = form.querySelectorAll('select[data-field]');
  mapSelects.forEach(sel => {
    sel.addEventListener('change', () => highlightMappedColumns(form));
  });
}

function highlightMappedColumns(form) {
  // Visual feedback — could expand to preview rows
  const mapped = [];
  form.querySelectorAll('select[data-field]').forEach(sel => {
    if (sel.value) mapped.push(sel.value);
  });
}

/* ─────────────────────────────────────────────
   9. REPLY INBOX — TAB FILTER
   ───────────────────────────────────────────── */
function initInboxTabs() {
  const tabBar = document.querySelector('.filter-tabs');
  if (!tabBar) return;

  tabBar.querySelectorAll('.filter-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      tabBar.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const cat = tab.dataset.category;
      filterReplyCards(cat);
    });
  });
}

function filterReplyCards(category) {
  document.querySelectorAll('.reply-card').forEach(card => {
    const match = !category || category === 'all' || card.dataset.category === category;
    card.style.display = match ? '' : 'none';
  });
}

/* ─────────────────────────────────────────────
   10. TASK QUEUE — FILTER & SORT
   ───────────────────────────────────────────── */
function initTaskFilters() {
  const filterBar = document.querySelector('.task-filter-bar');
  if (!filterBar) return;

  filterBar.querySelectorAll('[data-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      filterBar.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const val = btn.dataset.filter;
      filterTaskCards(val);
    });
  });
}

function filterTaskCards(type) {
  document.querySelectorAll('.task-card').forEach(card => {
    const match = !type || type === 'all' || card.dataset.type === type;
    card.style.display = match ? '' : 'none';
  });
}

/* ─────────────────────────────────────────────
   11. BULK SELECTION (leads pool)
   ───────────────────────────────────────────── */
function initBulkSelect() {
  const selectAll = document.getElementById('select-all');
  if (!selectAll) return;

  const checkboxes = () => document.querySelectorAll('.lead-checkbox');
  const bulkBar    = document.getElementById('bulk-action-bar');
  const bulkCount  = document.getElementById('bulk-count');

  selectAll.addEventListener('change', () => {
    checkboxes().forEach(cb => cb.checked = selectAll.checked);
    updateBulkBar();
  });

  document.addEventListener('change', e => {
    if (!e.target.classList.contains('lead-checkbox')) return;
    const all  = checkboxes();
    const checked = [...all].filter(cb => cb.checked);
    selectAll.checked = checked.length === all.length;
    selectAll.indeterminate = checked.length > 0 && checked.length < all.length;
    updateBulkBar();
  });

  function updateBulkBar() {
    const checked = [...checkboxes()].filter(cb => cb.checked);
    if (bulkBar)   bulkBar.style.display   = checked.length ? 'flex' : 'none';
    if (bulkCount) bulkCount.textContent   = `${checked.length} selected`;
  }

  // Bulk action forms — inject selected IDs before submit
  document.querySelectorAll('.bulk-action-form').forEach(form => {
    form.addEventListener('submit', () => {
      const checked = [...checkboxes()].filter(cb => cb.checked);
      // Remove previous hidden inputs
      form.querySelectorAll('input[name="lead_ids"]').forEach(el => el.remove());
      checked.forEach(cb => {
        const input = document.createElement('input');
        input.type  = 'hidden';
        input.name  = 'lead_ids';
        input.value = cb.value;
        form.appendChild(input);
      });
    });
  });
}

/* ─────────────────────────────────────────────
   12. CAMPAIGN CONTENT MODE TOGGLE
   ───────────────────────────────────────────── */
function initContentModeRadios() {
  const radios = document.querySelectorAll('input[name="content_mode"]');
  if (!radios.length) return;

  const reviewNote = document.getElementById('review-mode-note');

  radios.forEach(radio => {
    radio.addEventListener('change', () => {
      if (reviewNote) {
        reviewNote.style.display = radio.value === 'review' ? '' : 'none';
      }
    });
  });

  // Trigger on load
  const checked = document.querySelector('input[name="content_mode"]:checked');
  if (checked) checked.dispatchEvent(new Event('change'));
}

/* ─────────────────────────────────────────────
   13. INLINE EDITABLE FIELDS
   ───────────────────────────────────────────── */
function initInlineEdit() {
  document.querySelectorAll('[data-inline-edit]').forEach(wrapper => {
    const display = wrapper.querySelector('.inline-display');
    const form    = wrapper.querySelector('.inline-form');
    const editBtn = wrapper.querySelector('.inline-edit-btn');
    const cancelBtn = wrapper.querySelector('.inline-cancel-btn');

    if (!display || !form) return;

    editBtn?.addEventListener('click', () => {
      display.style.display = 'none';
      form.style.display    = '';
    });
    cancelBtn?.addEventListener('click', () => {
      form.style.display    = 'none';
      display.style.display = '';
    });
  });
}

/* ─────────────────────────────────────────────
   14. COPY TO CLIPBOARD
   ───────────────────────────────────────────── */
function initCopyButtons() {
  document.querySelectorAll('[data-copy]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = document.querySelector(btn.dataset.copy);
      const text   = target ? target.textContent : btn.dataset.copyText || '';
      navigator.clipboard.writeText(text.trim()).then(() => {
        showToast('Copied to clipboard', 'success', 2000);
      }).catch(() => {
        showToast('Could not copy', 'error', 2000);
      });
    });
  });
}

/* ─────────────────────────────────────────────
   15. SCRAPER — STATUS POLLING
   ───────────────────────────────────────────── */
function initScraperPolling() {
  const statusBox = document.getElementById('scraper-status');
  if (!statusBox) return;

  let interval = null;

  function poll() {
    fetch('/scraper/status')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) return;
        updateScraperUI(data);
        if (!data.running && interval) {
          clearInterval(interval);
          interval = null;
          // Refresh lead table
          refreshScraperLeads();
        }
      })
      .catch(() => {});
  }

  window.startScraperPolling = function() {
    if (interval) return;
    interval = setInterval(poll, 2000);
    poll();
  };

  // Auto-start if already running
  fetch('/scraper/status')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data && data.running) startScraperPolling();
    })
    .catch(() => {});
}

function updateScraperUI(data) {
  const statusBox   = document.getElementById('scraper-status');
  const progressBar = document.getElementById('scraper-progress');
  const statusText  = document.getElementById('scraper-status-text');
  const countEl     = document.getElementById('scraper-count');
  const runBtn      = document.getElementById('scraper-run-btn');
  const stopBtn     = document.getElementById('scraper-stop-btn');

  if (statusBox) statusBox.style.display = '';

  if (statusText) {
    statusText.textContent = data.status || (data.running ? 'Running…' : 'Idle');
  }
  if (progressBar && data.progress !== undefined) {
    progressBar.style.width = `${data.progress}%`;
    progressBar.setAttribute('aria-valuenow', data.progress);
  }
  if (countEl && data.found !== undefined) {
    countEl.textContent = `${data.found} leads found`;
  }
  if (runBtn)  runBtn.disabled  = data.running;
  if (stopBtn) stopBtn.disabled = !data.running;
}

function refreshScraperLeads() {
  fetch('/scraper/leads')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
      renderScraperLeads(data.leads || []);
    })
    .catch(() => {});
}

function renderScraperLeads(leads) {
  const tbody = document.getElementById('scraper-leads-tbody');
  if (!tbody) return;

  if (!leads.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:2rem;">No leads found yet.</td></tr>';
    return;
  }

  tbody.innerHTML = leads.map(l => `
    <tr>
      <td>${escHtml(l.business_name || '—')}</td>
      <td>${escHtml(l.industry || '—')}</td>
      <td>${escHtml(l.city || '—')}</td>
      <td>${escHtml(l.phone || '—')}</td>
      <td>${escHtml(l.website || '—')}</td>
      <td>
        ${l.rating ? `<span class="badge badge-amber">${l.rating}★</span>` : '—'}
      </td>
      <td>
        <button class="btn btn-xs btn-ghost"
                onclick="addScraperLeadToPool(${l.id}, this)">
          <i data-lucide="user-plus"></i> Add
        </button>
      </td>
    </tr>
  `).join('');

  if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [tbody] });
}

function addScraperLeadToPool(id, btn) {
  btn.disabled = true;
  fetch(`/scraper/leads/${id}/add-to-pool`, { method: 'POST', headers: getCsrfHeaders() })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        showToast('Lead added to pool', 'success');
        btn.innerHTML = '<i data-lucide="check"></i> Added';
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [btn] });
      } else {
        showToast(data.error || 'Error adding lead', 'error');
        btn.disabled = false;
      }
    })
    .catch(() => { showToast('Network error', 'error'); btn.disabled = false; });
}

/* ─────────────────────────────────────────────
   16. CSRF HELPER
   ───────────────────────────────────────────── */
function getCsrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content
      || document.querySelector('input[name="csrf_token"]')?.value
      || '';
}

function getCsrfHeaders() {
  return {
    'Content-Type': 'application/json',
    'X-CSRFToken': getCsrfToken()
  };
}

/* ─────────────────────────────────────────────
   17. HTML ESCAPE HELPER
   ───────────────────────────────────────────── */
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ─────────────────────────────────────────────
   18. CAMPAIGN STATS CHART (if Chart.js loaded)
   ───────────────────────────────────────────── */
function initCampaignStatsChart(campaignId) {
  const canvas = document.getElementById('campaign-stats-chart');
  if (!canvas || typeof Chart === 'undefined') return;

  fetch(`/campaigns/${campaignId}/stats`)
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) return;
      new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
          labels: data.labels || [],
          datasets: [{
            label: 'Sent',
            data:  data.sent  || [],
            backgroundColor: 'rgba(249,115,22,0.7)'
          }, {
            label: 'Replies',
            data:  data.replies || [],
            backgroundColor: 'rgba(245,158,11,0.7)'
          }]
        },
        options: {
          responsive: true,
          plugins: { legend: { position: 'top' } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      });
    })
    .catch(() => {});
}

/* ─────────────────────────────────────────────
   19. INBOX REENROLL — CAMPAIGN SELECT
   ───────────────────────────────────────────── */
function initReenrollForms() {
  document.querySelectorAll('.reenroll-form').forEach(form => {
    const toggle = form.querySelector('.reenroll-toggle');
    const panel  = form.querySelector('.reenroll-panel');
    if (toggle && panel) {
      toggle.addEventListener('click', () => {
        const open = panel.style.display !== 'none';
        panel.style.display = open ? 'none' : '';
      });
    }
  });
}

/* ─────────────────────────────────────────────
   20. SETTINGS — SMTP PASSWORD TOGGLE
   ───────────────────────────────────────────── */
function initPasswordToggles() {
  document.querySelectorAll('[data-password-toggle]').forEach(btn => {
    const targetId = btn.dataset.passwordToggle;
    const input = document.getElementById(targetId);
    if (!input) return;
    btn.addEventListener('click', () => {
      const isPass = input.type === 'password';
      input.type = isPass ? 'text' : 'password';
      const icon = btn.querySelector('i[data-lucide]');
      if (icon) {
        icon.setAttribute('data-lucide', isPass ? 'eye-off' : 'eye');
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [btn] });
      }
    });
  });
}

/* ─────────────────────────────────────────────
   21. AUTO-DISMISS ALERTS
   ───────────────────────────────────────────── */
function initAutoDismissAlerts() {
  document.querySelectorAll('.alert[data-autodismiss]').forEach(alert => {
    const ms = parseInt(alert.dataset.autodismiss) || 5000;
    setTimeout(() => {
      alert.style.opacity = '0';
      alert.style.transition = 'opacity 0.4s ease';
      setTimeout(() => alert.remove(), 400);
    }, ms);
  });
}

/* ─────────────────────────────────────────────
   22. KEYBOARD SHORTCUTS
   ───────────────────────────────────────────── */
function initKeyboardShortcuts() {
  document.addEventListener('keydown', e => {
    // Escape closes any open modal
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-overlay[style*="flex"]').forEach(m => {
        m.style.display = 'none';
      });
    }
  });
}

/* ─────────────────────────────────────────────
   INIT — run everything on DOMContentLoaded
   ───────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  // Lucide icons
  if (typeof lucide !== 'undefined') lucide.createIcons();

  // Nav counts (update immediately then every 60s)
  updateNavCounts();
  setInterval(updateNavCounts, 60000);

  // Flash → toasts
  flashesToToasts();

  // UI modules
  initModalOverlayClose();
  initModalCloseBtns();
  initConfirmForms();
  initCampaignTabs();
  initSequenceBuilder();
  initUploadMapping();
  initInboxTabs();
  initTaskFilters();
  initBulkSelect();
  initContentModeRadios();
  initInlineEdit();
  initCopyButtons();
  initScraperPolling();
  initReenrollForms();
  initPasswordToggles();
  initAutoDismissAlerts();
  initKeyboardShortcuts();

  // Campaign stats chart — only on detail page with data attribute
  const chartCanvas = document.getElementById('campaign-stats-chart');
  if (chartCanvas && chartCanvas.dataset.campaignId) {
    initCampaignStatsChart(chartCanvas.dataset.campaignId);
  }
});
