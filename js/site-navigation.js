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
  const uploadId = new URLSearchParams(window.location.search).get('upload_id');

  document.querySelectorAll('.site-navigation').forEach(navigation => {
    navigation.innerHTML = navigationItems.map(item => {
      const isActive = item.href === currentPage;
      const scopedHref = uploadId && ['dashboard.html', 'inventory.html', 'export.html'].includes(item.href)
        ? `${item.href}?upload_id=${encodeURIComponent(uploadId)}`
        : item.href;
      return `<a href="${scopedHref}" class="site-navigation__item${isActive ? ' is-active' : ''}" style="--navigation-item-width: ${item.width}"><i class="fa-solid ${item.icon}" aria-hidden="true"></i><span>${item.label}</span></a>`;
    }).join('');

    let supportLink = navigation.nextElementSibling;
    if (!supportLink?.classList.contains('site-navigation-support')) {
      supportLink = document.createElement('a');
      supportLink.className = 'site-navigation-support';
      supportLink.innerHTML = '<i class="fa-solid fa-headset" aria-hidden="true"></i><span>고객센터</span>';
      navigation.insertAdjacentElement('afterend', supportLink);
    }
    supportLink.href = '/customer-center.html';
    supportLink.classList.toggle('is-active', currentPage === 'customer-center.html');
    supportLink.setAttribute('aria-label', '고객센터');
  });
})();
