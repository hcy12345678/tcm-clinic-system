/* 轻量 UI 工具：提示、确认框、分页、表格渲染、表单序列化 */
const UI = (function () {
  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function toast(message, type) {
    const host = $('#toast-host') || (() => {
      const node = document.createElement('div');
      node.id = 'toast-host';
      node.className = 'toast-host';
      document.body.appendChild(node);
      return node;
    })();
    const item = document.createElement('div');
    item.className = 'toast-item toast-' + (type || 'success');
    item.textContent = message;
    host.appendChild(item);
    setTimeout(() => {
      item.classList.add('toast-out');
      setTimeout(() => item.remove(), 300);
    }, 2600);
  }

  function confirmDialog(message, options) {
    const opts = Object.assign({ title: '操作确认', okText: '确定', danger: false }, options || {});
    return new Promise((resolve) => {
      const wrapper = document.createElement('div');
      wrapper.className = 'ui-mask';
      wrapper.innerHTML = `
        <div class="ui-dialog">
          <h3>${escapeHtml(opts.title)}</h3>
          <p>${escapeHtml(message)}</p>
          <div class="ui-dialog-actions">
            <button type="button" class="btn btn-light" data-act="cancel">取消</button>
            <button type="button" class="btn ${opts.danger ? 'btn-danger' : 'btn-primary'}" data-act="ok">${escapeHtml(opts.okText)}</button>
          </div>
        </div>`;
      document.body.appendChild(wrapper);
      wrapper.addEventListener('click', (event) => {
        const act = event.target.getAttribute('data-act');
        if (act) {
          wrapper.remove();
          resolve(act === 'ok');
        } else if (event.target === wrapper) {
          wrapper.remove();
          resolve(false);
        }
      });
    });
  }

  function badge(status, text) {
    const map = {
      OPEN: 'success', STOPPED: 'secondary',
      BOOKED: 'primary', CANCELLED: 'secondary', COMPLETED: 'success',
      PENDING: 'warning', IN_PROGRESS: 'info', FINISHED: 'success',
    };
    const tone = map[status] || 'secondary';
    return `<span class="pill pill-${tone}">${escapeHtml(text || status)}</span>`;
  }

  function renderPagination(container, page, onPage) {
    if (!container) return;
    const totalPages = page.total_pages || 1;
    const current = page.page || 1;
    if (!page.count) {
      container.innerHTML = '';
      return;
    }
    const buttons = [];
    buttons.push(`<button type="button" class="page-btn" data-page="${current - 1}" ${current <= 1 ? 'disabled' : ''}>上一页</button>`);
    const start = Math.max(1, current - 2);
    const end = Math.min(totalPages, start + 4);
    for (let i = start; i <= end; i += 1) {
      buttons.push(`<button type="button" class="page-btn ${i === current ? 'is-active' : ''}" data-page="${i}">${i}</button>`);
    }
    buttons.push(`<button type="button" class="page-btn" data-page="${current + 1}" ${current >= totalPages ? 'disabled' : ''}>下一页</button>`);
    container.innerHTML = `
      <span class="page-info">共 ${page.count} 条 · 第 ${current}/${totalPages} 页</span>
      <div class="page-buttons">${buttons.join('')}</div>`;
    $$('.page-btn', container).forEach((button) => {
      button.addEventListener('click', () => {
        const target = Number(button.getAttribute('data-page'));
        if (!button.disabled && target >= 1 && target <= totalPages) onPage(target);
      });
    });
  }

  function table(columns, rows, options) {
    const opts = options || {};
    if (!rows || !rows.length) {
      return `<div class="empty-state">${escapeHtml(opts.empty || '暂无数据')}</div>`;
    }
    const head = columns.map((col) => `<th>${escapeHtml(col.title)}</th>`).join('');
    const body = rows.map((row) => {
      const cells = columns.map((col) => {
        const value = col.render ? col.render(row) : escapeHtml(row[col.key]);
        return `<td>${value}</td>`;
      }).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    return `<div class="table-wrap"><table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function formToObject(form) {
    const result = {};
    new FormData(form).forEach((value, key) => {
      if (typeof value === 'string') result[key] = value.trim();
    });
    return result;
  }

  function setLoading(button, loading, text) {
    if (!button) return;
    if (loading) {
      button.dataset.original = button.textContent;
      button.disabled = true;
      button.textContent = text || '处理中…';
    } else {
      button.disabled = false;
      if (button.dataset.original) button.textContent = button.dataset.original;
    }
  }

  function showFieldErrors(error) {
    if (!error || !error.errors) return;
    const parts = Object.keys(error.errors).map((field) => error.errors[field].join('；'));
    if (parts.length) toast(parts.join('；'), 'error');
  }

  function qs(name) {
    return new URLSearchParams(location.search).get(name) || '';
  }

  return {
    $, $$, escapeHtml, toast, confirm: confirmDialog, badge,
    pagination: renderPagination, table, formToObject, setLoading, showFieldErrors, qs,
  };
})();

/* 本地 SVG 图标：不依赖任何 CDN，离线/内网也能正常显示 */
(function () {
  const PATHS = {
    'bi-list': 'M4 7h16M4 12h16M4 17h16',
    'bi-heart-pulse': 'M3 12h3.5l2-4 3 8 2-4H21',
    'bi-box-arrow-in-right': 'M4 5h9v14H4zM14 12h6M17.5 9l3 3-3 3',
    'bi-box-arrow-right': 'M5 5h8v14H5zM13 12h7M17 9l3 3-3 3',
    'bi-person-plus': 'M10 11a3.2 3.2 0 1 0 0-6.4A3.2 3.2 0 0 0 10 11zM4 20c0-3.4 2.7-5.2 6-5.2s6 1.8 6 5.2M18 8v6M15 11h6',
    'bi-check2-circle': 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM8.5 12.4l2.4 2.4 4.6-5',
    'bi-speedometer2': 'M4 17a8 8 0 1 1 16 0M12 13l3.8-3.8',
    'bi-people': 'M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3 20c0-3 2.6-4.6 6-4.6s6 1.6 6 4.6M17 11a2.4 2.4 0 1 0 0-4.8M16 15.4c3 .2 5 1.7 5 4.6',
    'bi-shield-lock': 'M12 3l7 3v6c0 4.2-2.9 7.4-7 9-4.1-1.6-7-4.8-7-9V6zM9.5 11.5h5v3.5h-5z',
    'bi-calendar3': 'M4 6h16v14H4zM8 3v5M16 3v5M4 11h16',
    'bi-clipboard2-pulse': 'M6 4h12v17H6zM9.5 4h5v3h-5zM8 14h2.5l1.5-3 2 6 1.5-3H16',
    'bi-journal-medical': 'M5 3h14v18H5zM12 8v6M9 11h6',
    'bi-bar-chart': 'M5 19v-7M12 19V6M19 19v-4M3 21h18',
    'bi-clock-history': 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM12 7.5V12l3 2',
    'bi-plus-lg': 'M12 5v14M5 12h14',
    'bi-search': 'M11 17a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM20 20l-4.6-4.6',
    'bi-save': 'M5 4h11l3 3v13H5zM8.5 4v5h7V4M8 14h8v6H8z',
    'bi-pencil': 'M4 20h4L18 10l-4-4L4 16zM14 6l4 4',
    'bi-arrow-left': 'M19 12H5M11 6l-6 6 6 6',
    'bi-x-circle': 'M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6',
    'bi-download': 'M12 4v10M8 11l4 4 4-4M5 19h14',
    'bi-printer': 'M7 8V4h10v4M4 8h16v8H4zM7 14h10v6H7z',
    'bi-heart-pulse-fallback': 'M12 20s-7-4.3-7-9a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 4.7-7 9-7 9z',
  };

  function paint() {
    document.querySelectorAll('i.bi').forEach(function (node) {
      if (node.dataset.iconReady) return;
      const name = Array.prototype.slice.call(node.classList).find(function (cls) {
        return cls !== 'bi' && PATHS[cls];
      });
      if (!name) return;
      node.dataset.iconReady = '1';
      node.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="' + PATHS[name] + '"/></svg>';
    });
  }

  document.addEventListener('DOMContentLoaded', paint);
  new MutationObserver(function () { paint(); }).observe(document.body, { childList: true, subtree: true });
})();
