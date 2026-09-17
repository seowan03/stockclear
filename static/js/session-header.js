document.addEventListener('DOMContentLoaded', async () => {
  const authLinks = [...document.querySelectorAll('header a[href="signin.html"]')];
  if (!authLinks.length) return;

  try {
    const response = await fetch('/api/auth/me');
    if (!response.ok) return;

    const user = await response.json();
    if (!user.logged_in || !user.email) return;

    const accountName = user.email.split('@')[0];
    const accountArea = authLinks[0].parentElement;
    accountArea.innerHTML = `<span class="inline-flex items-center gap-2 px-3 py-2 text-xs font-semibold text-blue-100 bg-blue-500/10 border border-blue-400/20 rounded-xl"><i class="fa-solid fa-user"></i>${accountName}</span>`;
  } catch {
    // Keep the sign-in links available when the session check cannot be completed.
  }
});
