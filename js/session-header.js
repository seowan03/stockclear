document.addEventListener('DOMContentLoaded', async () => {
  const authLinks = [...document.querySelectorAll('header a[href="signin.html"]')];
  if (!authLinks.length) return;

  const accountArea = authLinks[0].parentElement;
  const authMarkup = accountArea.innerHTML;
  const showAccount = accountName => {
    accountArea.innerHTML = `<span class="inline-flex items-center gap-2 px-3 py-2 text-xs font-semibold text-blue-100 bg-blue-500/10 border border-blue-400/20 rounded-xl"><i class="fa-solid fa-user"></i>${accountName}</span>`;
  };
  const showAuthLinks = () => {
    accountArea.innerHTML = authMarkup;
    accountArea.querySelectorAll('a[href="signin.html"]').forEach(link => {
      link.style.visibility = 'visible';
    });
  };

  const cachedAccountName = localStorage.getItem('stockclear-account-name');
  if (cachedAccountName) showAccount(cachedAccountName);

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