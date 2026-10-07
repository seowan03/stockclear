(() => {
  const list = document.getElementById('adminInquiryList');
  const status = document.getElementById('adminInquiryStatus');
  const filter = document.getElementById('inquiryStatusFilter');
  const refreshButton = document.getElementById('refreshInquiries');

  if (!list || !status || !filter || !refreshButton) return;

  function addText(parent, tagName, className, text) {
    const element = document.createElement(tagName);
    element.className = className;
    element.textContent = text || '';
    parent.appendChild(element);
    return element;
  }

  function makeInquiryCard(inquiry) {
    const article = document.createElement('article');
    article.className = 'rounded-xl border border-gray-800 bg-gray-900/70 p-5';

    const heading = document.createElement('div');
    heading.className = 'flex flex-wrap items-start justify-between gap-3';
    article.appendChild(heading);
    addText(heading, 'h2', 'text-base font-semibold text-white', inquiry.subject);
    const meta = document.createElement('p');
    meta.className = 'mt-2 text-xs text-gray-400';
    meta.textContent = `#${inquiry.inquiry_id} · ${inquiry.inquiry_type} · ${inquiry.user_email || '비회원'} · ${inquiry.created_at || ''}`;
    heading.appendChild(meta);
    const state = document.createElement('span');
    state.className = inquiry.status === '답변 완료'
      ? 'rounded-full bg-emerald-900/50 px-2.5 py-1 text-xs text-emerald-300'
      : 'rounded-full bg-amber-900/50 px-2.5 py-1 text-xs text-amber-300';
    state.textContent = inquiry.status;
    heading.appendChild(state);

    const content = addText(article, 'p', 'mt-4 whitespace-pre-wrap break-words text-sm leading-6 text-gray-200', inquiry.content);
    content.setAttribute('aria-label', '문의 내용');

    const form = document.createElement('form');
    form.className = 'mt-4 space-y-3 border-t border-gray-800 pt-4';
    article.appendChild(form);
    const label = addText(form, 'label', 'block text-xs font-medium text-gray-400', '관리자 답변');
    const textarea = document.createElement('textarea');
    textarea.name = 'reply';
    textarea.rows = 4;
    textarea.maxLength = 5000;
    textarea.required = true;
    textarea.value = inquiry.reply || '';
    textarea.className = 'mt-2 block w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-sm leading-6 text-gray-100 outline-none focus:border-blue-500';
    label.appendChild(textarea);

    const actions = document.createElement('div');
    actions.className = 'flex flex-wrap items-center justify-between gap-3';
    form.appendChild(actions);
    addText(actions, 'p', 'text-xs text-gray-500', inquiry.replied_at ? `마지막 답변: ${inquiry.replied_at}` : '아직 답변하지 않았습니다.');
    const saveButton = document.createElement('button');
    saveButton.type = 'submit';
    saveButton.className = 'rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50';
    saveButton.innerHTML = '<i class="fa-solid fa-paper-plane mr-1" aria-hidden="true"></i>답변 저장';
    actions.appendChild(saveButton);
    const result = addText(form, 'p', 'text-sm text-gray-400', '');
    result.setAttribute('role', 'status');
    result.setAttribute('aria-live', 'polite');

    form.addEventListener('submit', async event => {
      event.preventDefault();
      saveButton.disabled = true;
      result.textContent = '저장 중...';
      try {
        const response = await fetch(`/api/admin/inquiries/${inquiry.inquiry_id}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reply: textarea.value }),
        });
        if (response.status === 401) {
          window.location.href = '/signin.html';
          return;
        }
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || '답변을 저장하지 못했습니다.');
        result.textContent = '답변을 저장했습니다.';
        await loadInquiries();
      } catch (error) {
        result.textContent = error.message || '답변을 저장하지 못했습니다.';
      } finally {
        saveButton.disabled = false;
      }
    });

    return article;
  }

  async function loadInquiries() {
    list.replaceChildren();
    status.textContent = '문의 목록을 불러오는 중입니다.';
    refreshButton.disabled = true;
    const query = filter.value ? `?status=${encodeURIComponent(filter.value)}` : '';

    try {
      const response = await fetch(`/api/admin/inquiries${query}`, { credentials: 'include' });
      if (response.status === 401) {
        window.location.href = '/signin.html';
        return;
      }
      const payload = await response.json();
      if (response.status === 403) throw new Error('관리자 권한이 있는 계정으로 로그인해야 합니다.');
      if (!response.ok) throw new Error(payload.detail || '문의 목록을 불러오지 못했습니다.');

      const inquiries = Array.isArray(payload.items) ? payload.items : [];
      status.textContent = inquiries.length ? `${inquiries.length}건의 문의` : '표시할 문의가 없습니다.';
      inquiries.forEach(inquiry => list.appendChild(makeInquiryCard(inquiry)));
    } catch (error) {
      status.textContent = error.message || '문의 목록을 불러오지 못했습니다.';
    } finally {
      refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener('click', loadInquiries);
  filter.addEventListener('change', loadInquiries);
  loadInquiries();
})();
