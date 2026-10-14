    let mode = 'login';

    function switchMode(newMode) {
      mode = newMode;
      const isLogin = mode === 'login';
      const isSignup = mode === 'signup';
      const isReset = mode === 'reset';
      document.getElementById('tabLogin').classList.toggle('is-active', isLogin);
      document.getElementById('tabLogin').setAttribute('aria-pressed', String(isLogin));
      document.getElementById('tabSignup').classList.toggle('is-active', isSignup);
      document.getElementById('tabSignup').setAttribute('aria-pressed', String(isSignup));
      document.getElementById('usernameField').classList.toggle('hidden', isLogin);
      document.getElementById('usernameInput').required = !isLogin;
      document.getElementById('passwordInput').autocomplete = isLogin ? 'current-password' : 'new-password';
      document.getElementById('passwordLabel').innerText = isReset ? 'New password' : 'Password';
      document.getElementById('passwordInput').placeholder = isReset ? 'Enter new password' : 'Enter your password';
      document.getElementById('passwordChecklist').classList.toggle('hidden', isLogin);
      document.getElementById('authOptions').classList.toggle('hidden', !isLogin);
      document.getElementById('resetBackRow').classList.toggle('hidden', !isReset);
      document.getElementById('authTitle').innerText = isLogin ? 'Login' : isSignup ? 'Create account' : 'Reset password';
      document.getElementById('authSubtitle').innerText = isLogin
        ? 'Sign in to continue to StockClear.'
        : isSignup
          ? 'Create an account to get started.'
          : 'Enter your name and email to set a new password.';
      document.getElementById('authSubmitBtn').innerText = isLogin ? 'Sign in' : isSignup ? 'Create account' : 'Reset password';
      document.getElementById('welcomeTitle').innerText = isLogin ? 'Welcome Back' : 'Welcome to StockClear';
      document.getElementById('welcomeCopy').innerText = isLogin
        ? 'Manage your inventory with clear insights and make confident decisions.'
        : 'Start turning your inventory data into clear, practical next steps.';
      document.getElementById('authError').classList.add('hidden');
    }

    function extractErrorMessage(data) {
      const detail = data && data.detail;
      if (!detail) return null;
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((item) => String((item && item.msg) || item).replace(/^Value error,\s*/, ''))
          .join(' ');
      }
      return null;
    }

    function updatePasswordChecklist() {
      const password = document.getElementById('passwordInput').value;
      const lengthOk = password.length >= 8;
      const specialOk = /[^A-Za-z0-9]/.test(password);
      const lengthItem = document.getElementById('checkLength');
      const specialItem = document.getElementById('checkSpecial');
      lengthItem.classList.toggle('is-met', lengthOk);
      lengthItem.querySelector('i').className = lengthOk ? 'fa-solid fa-circle-check' : 'fa-solid fa-circle';
      specialItem.classList.toggle('is-met', specialOk);
      specialItem.querySelector('i').className = specialOk ? 'fa-solid fa-circle-check' : 'fa-solid fa-circle';
    }

    const rememberedEmail = localStorage.getItem('stockclear.rememberedEmail');
    if (rememberedEmail) {
      document.getElementById('emailInput').value = rememberedEmail;
      document.getElementById('rememberEmail').checked = true;
    }

    document.getElementById('authForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errorBox = document.getElementById('authError');
      errorBox.classList.add('hidden');

      const email = document.getElementById('emailInput').value.trim();
      const password = document.getElementById('passwordInput').value;
      const username = document.getElementById('usernameInput').value.trim();

      if (mode === 'login' && document.getElementById('rememberEmail').checked) {
        localStorage.setItem('stockclear.rememberedEmail', email);
      } else if (mode === 'login') {
        localStorage.removeItem('stockclear.rememberedEmail');
      }

      const endpoint = mode === 'login' ? '/api/auth/login' : mode === 'signup' ? '/api/auth/signup' : '/api/auth/reset-password';
      const payload = mode === 'login'
        ? { email, password }
        : mode === 'signup'
          ? { email, password, username }
          : { email, username, new_password: password };

      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (!res.ok) {
          errorBox.innerText = extractErrorMessage(data) || '요청 처리 중 오류가 발생했습니다.';
          errorBox.classList.remove('hidden');
          return;
        }

        if (mode === 'reset') {
          document.getElementById('authForm').reset();
          switchMode('login');
          errorBox.innerText = '비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요.';
          errorBox.classList.remove('hidden', 'auth-error');
          errorBox.classList.add('auth-success');
          return;
        }

        window.location.href = 'dashboard.html';
      } catch (err) {
        errorBox.innerText = '서버에 연결할 수 없습니다.';
        errorBox.classList.remove('hidden');
      }
    });
