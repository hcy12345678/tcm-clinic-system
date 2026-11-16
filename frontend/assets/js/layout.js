/* 公共布局：顶栏 + 侧边菜单，菜单项由接口返回的权限动态生成 */
const Layout = (function () {
  const MENUS = [
    { key: 'index', href: 'index.html', label: '工作台', icon: 'bi-speedometer2', perm: null },
    { key: 'users', href: 'users.html', label: '用户管理', icon: 'bi-people', perm: 'can_user' },
    { key: 'permissions', href: 'permissions.html', label: '角色菜单权限', icon: 'bi-shield-lock', perm: 'can_user' },
    { key: 'schedules', href: 'schedules.html', label: '医师排班', icon: 'bi-calendar3', perm: 'can_schedule' },
    { key: 'appointments', href: 'appointments.html', label: '预约挂号', icon: 'bi-clipboard2-pulse', perm: 'can_appointment' },
    { key: 'visits', href: 'visits.html', label: '就诊登记', icon: 'bi-journal-medical', perm: 'can_visit' },
    { key: 'statistics', href: 'statistics.html', label: '查询统计', icon: 'bi-bar-chart', perm: 'can_statistics' },
    { key: 'logs', href: 'logs.html', label: '操作日志', icon: 'bi-clock-history', perm: 'can_statistics', adminOnly: true },
  ];

  let state = { user: null, perms: {} };

  function menuHtml(active) {
    return MENUS.filter((menu) => {
      if (menu.adminOnly && state.user.role !== 'ADMIN') return false;
      return !menu.perm || state.perms[menu.perm];
    }).map((menu) => `
      <a class="side-link ${menu.key === active ? 'is-active' : ''}" href="${menu.href}">
        <i class="bi ${menu.icon}"></i><span>${menu.label}</span>
      </a>`).join('');
  }

  function render(active) {
    const topbar = document.getElementById('layout-topbar');
    const sidebar = document.getElementById('layout-sidebar');
    if (topbar) {
      topbar.innerHTML = `
        <div class="topbar-inner">
          <button type="button" class="icon-btn" id="sidebar-toggle" title="收起菜单">
            <i class="bi bi-list"></i>
          </button>
          <a class="brand" href="index.html">
            <i class="bi bi-heart-pulse"></i>
            <span>中医门诊预约与医师排班管理系统</span>
          </a>
          <div class="topbar-right">
            <span class="role-chip">${state.user.role_display}</span>
            <a class="user-name" href="profile.html">${state.user.display_name}</a>
            <button type="button" class="icon-btn" id="logout-btn" title="退出登录">
              <i class="bi bi-box-arrow-right"></i>
            </button>
          </div>
        </div>`;
    }
    if (sidebar) {
      sidebar.innerHTML = `
        <div class="side-user">
          <div class="avatar">${state.user.display_name.slice(0, 1)}</div>
          <div class="side-user-meta">
            <strong>${state.user.display_name}</strong>
            <span>${state.user.role_display} · ${state.user.username}</span>
          </div>
        </div>
        <nav class="side-nav">${menuHtml(active)}</nav>
        <div class="side-foot">前后端分离版 · Session 认证</div>`;
    }

    const toggle = document.getElementById('sidebar-toggle');
    if (toggle) {
      toggle.addEventListener('click', () => document.body.classList.toggle('sidebar-collapsed'));
    }
    const logout = document.getElementById('logout-btn');
    if (logout) {
      logout.addEventListener('click', async () => {
        const confirmed = await UI.confirm('确定要退出登录吗？', { title: '退出登录', okText: '退出' });
        if (!confirmed) return;
        try {
          await API.post('/auth/logout/');
        } catch (error) {
          /* 忽略退出接口异常，直接回登录页 */
        }
        location.href = '/app/login.html';
      });
    }
  }

  async function mount(active) {
    try {
      const me = await API.get('/auth/me/');
      if (!me || !me.authenticated) {
        sessionStorage.setItem('redirect_after_login', location.href);
        location.href = '/app/login.html';
        return null;
      }
      state = { user: me.user, perms: me.perms || {} };
      render(active);
      return state;
    } catch (error) {
      location.href = '/app/login.html';
      return null;
    }
  }

  return { mount, state: () => state };
})();
