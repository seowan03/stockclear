(() => {
  const dialog = document.getElementById('inquiryDialog');
  const openButton = document.getElementById('openInquiryForm');
  const closeButton = document.getElementById('closeInquiryForm');
  const cancelButton = document.getElementById('cancelInquiryForm');
  const form = document.getElementById('inquiryForm');
  const submitButton = document.getElementById('submitInquiry');
  const statusMessage = document.getElementById('inquiryStatus');
  const replyLookupForm = document.getElementById('inquiryReplyLookupForm');
  const replyLookupButton = document.getElementById('lookupInquiryReply');
  const replyLookupStatus = document.getElementById('inquiryReplyStatus');

  if (!dialog || !openButton || !form || !submitButton || !statusMessage) return;

  const closeDialog = () => dialog.close();

  openButton.addEventListener('click', () => {
    statusMessage.textContent = '';
    statusMessage.classList.remove('is-error');
    dialog.showModal();
  });
  closeButton?.addEventListener('click', closeDialog);
  cancelButton?.addEventListener('click', closeDialog);

  form.addEventListener('submit', async event => {
    event.preventDefault();
    statusMessage.textContent = '';
    statusMessage.classList.remove('is-error');
    submitButton.disabled = true;

    const formData = new FormData(form);
    const inquiry = {
      inquiry_type: formData.get('inquiry_type'),
      subject: formData.get('subject'),
      content: formData.get('content')
    };

    try {
      const response = await fetch('/api/inquiries', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(inquiry)
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(typeof result.detail === 'string' ? result.detail : '문의 접수에 실패했습니다. 입력 내용을 확인해주세요.');
      }

      form.reset();
      statusMessage.textContent = result.reply_token
        ? `문의가 접수되었습니다. 접수 번호: ${result.inquiry_id}. 답변 조회 코드: ${result.reply_token} (나중에 답변 확인에 필요합니다.)`
        : `문의가 접수되었습니다. 접수 번호: ${result.inquiry_id}`;
      if (replyLookupForm) {
        replyLookupForm.elements.inquiry_id.value = result.inquiry_id;
        replyLookupForm.elements.reply_token.value = result.reply_token || '';
      }
    } catch (error) {
      statusMessage.classList.add('is-error');
      statusMessage.textContent = error.message || '문의 접수 중 오류가 발생했습니다. 다시 시도해주세요.';
    } finally {
      submitButton.disabled = false;
    }
  });

  replyLookupForm?.addEventListener('submit', async event => {
    event.preventDefault();
    if (!replyLookupStatus || !replyLookupButton) return;
    replyLookupStatus.textContent = '';
    replyLookupButton.disabled = true;

    const formData = new FormData(replyLookupForm);
    const inquiryId = String(formData.get('inquiry_id') || '').trim();
    const token = String(formData.get('reply_token') || '').trim();
    const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : '';

    try {
      const response = await fetch(
        `/api/inquiries/${encodeURIComponent(inquiryId)}/reply${tokenQuery}`,
        { credentials: 'include' },
      );
      const result = await response.json();
      if (!response.ok) {
        throw new Error(typeof result.detail === 'string' ? result.detail : '답변을 조회하지 못했습니다.');
      }

      replyLookupStatus.textContent = result.status === '답변 완료'
        ? `답변 완료: ${result.reply || ''}`
        : '문의가 접수되어 답변을 기다리는 중입니다.';
    } catch (error) {
      replyLookupStatus.classList.add('is-error');
      replyLookupStatus.textContent = error.message || '답변을 조회하지 못했습니다.';
    } finally {
      replyLookupButton.disabled = false;
    }
  });
})();