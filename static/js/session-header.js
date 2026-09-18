document.addEventListener('DOMContentLoaded', async () => {
  const authLinks = [...document.querySelectorAll('header a[href="signin.html"]')];
  if (!authLinks.length) return;

  const accountArea = authLinks[0].parentElement;
  const authMarkup = accountArea.innerHTML;
  const showAccount = accountName => {
    accountArea.innerHTML = `
      <div class="session-controls">
        <span class="session-account"><i class="fa-solid fa-user"></i>${accountName}</span>
        <button type="button" class="session-logout">로그아웃</button>
      </div>
    `;
    accountArea.querySelector('.session-logout').addEventListener('click', logout);
  };
  const showAuthLinks = () => {
    accountArea.innerHTML = authMarkup;
    accountArea.querySelectorAll('a[href="signin.html"]').forEach(link => {
      link.style.visibility = 'visible';
    });
  };

  const cachedAccountName = localStorage.getItem('stockclear-account-name');
  if (cachedAccountName) showAccount(cachedAccountName);

  async function logout() {
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST' });
      if (!response.ok) throw new Error('Logout failed');
      localStorage.removeItem('stockclear-account-name');
      window.location.href = 'mainpage.html';
    } catch {
      window.alert('로그아웃 처리 중 오류가 발생했습니다.');
    }
  }

  try {
    const response = await fetch('/api/auth/me');
    if (!response.ok) throw new Error('Session request failed');

    const user = await response.json();
    if (user.logged_in && user.email) {
      const accountName = user.email.split('@')[0];
      localStorage.setItem('stockclear-account-name', accountName);
      showAccount(accountName);
      return;
    }

    localStorage.removeItem('stockclear-account-name');
    showAuthLinks();
  } catch {
    if (!cachedAccountName) showAuthLinks();
  }
});