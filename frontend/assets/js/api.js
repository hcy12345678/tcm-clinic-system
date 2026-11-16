/* 与后端 /api/ 通信的唯一出口：统一处理 CSRF、401 跳转、错误提示 */
const API = (function () {
  const BASE = '/api';

  function getCookie(name) {
    const hit = document.cookie.split('; ').find((item) => item.startsWith(name + '='));
    return hit ? decodeURIComponent(hit.split('=').slice(1).join('=')) : '';
  }

  function isLoginPage() {
    return /login\.html|register\.html/.test(location.pathname);
  }

  function buildUrl(path, params) {
    let url = BASE + path;
    if (params) {
      const qs = new URLSearchParams();
      Object.keys(params).forEach((key) => {
        const value = params[key];
        if (value !== undefined && value !== null && value !== '') qs.append(key, value);
      });
      const query = qs.toString();
      if (query) url += '?' + query;
    }
    return url;
  }

  async function request(path, options) {
    const opts = Object.assign({ method: 'GET', body: null, params: null }, options || {});
    const headers = { 'X-Requested-With': 'XMLHttpRequest' };
    const token = getCookie('csrftoken');
    if (token) headers['X-CSRFToken'] = token;

    const init = { method: opts.method, headers, credentials: 'same-origin' };
    if (opts.body instanceof FormData) {
      init.body = opts.body;
    } else if (opts.body !== null && opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }

    const response = await fetch(buildUrl(path, opts.params), init);

    if (response.status === 401) {
      if (!isLoginPage()) {
        sessionStorage.setItem('redirect_after_login', location.href);
        location.href = '/app/login.html';
      }
      const error = new Error('登录状态已失效');
      error.status = 401;
      throw error;
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (err) {
      payload = null;
    }

    if (!response.ok) {
      const error = new Error((payload && payload.message) || `请求失败（${response.status}）`);
      error.status = response.status;
      error.code = payload && payload.code;
      error.errors = (payload && payload.errors) || null;
      throw error;
    }

    return payload && Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : payload;
  }

  return {
    get: (path, params) => request(path, { method: 'GET', params }),
    post: (path, body) => request(path, { method: 'POST', body: body === undefined ? {} : body }),
    put: (path, body) => request(path, { method: 'PUT', body }),
    del: (path) => request(path, { method: 'DELETE' }),
    upload: (path, formData) => request(path, { method: 'POST', body: formData }),
    url: buildUrl,
    csrfToken: () => getCookie('csrftoken'),
  };
})();
