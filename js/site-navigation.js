(() => {
  const navigationItems = [
    { href: 'mainpage.html', label: '메인 Home', icon: 'fa-house', width: '104px' },
    { href: 'upload.html', label: '업로드', icon: 'fa-cloud-arrow-up', width: '88px' },
    { href: 'history.html', label: '업로드 기록', icon: 'fa-clock-rotate-left', width: '112px' },
    { href: 'dashboard.html', label: '대시보드', icon: 'fa-chart-pie', width: '96px' },
    { href: 'inventory.html', label: '재고 목록', icon: 'fa-boxes-stacked', width: '104px' },
    { href: 'export.html', label: '내보내기', icon: 'fa-file-export', width: '104px' }
  ];

  const currentPage = window.location.pathname.split('/').pop() || 'mainpage.html';

  document.querySelectorAll('.site-navigation').forEach(navigation => {
    navigation.innerHTML = navigationItems.map(item => {
      const isActive = item.href === currentPage;
      return `<a href="${item.href}" class="site-navigation__item${isActive ? ' is-active' : ''}" style="--navigation-item-width: ${item.width}"><i class="fa-solid ${item.icon}" aria-hidden="true"></i><span>${item.label}</span></a>`;
    }).join('');
  });
})();