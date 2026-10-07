(() => {
  const dialog = document.getElementById('inquiryDialog');
  const openButton = document.getElementById('openInquiryForm');
  const closeButton = document.getElementById('closeInquiryForm');
  const cancelButton = document.getElementById('cancelInquiryForm');
  const form = document.getElementById('inquiryForm');
  const submitButton = document.getElementById('submitInquiry');
  const statusMessage = document.getElementById('inquiryStatus');

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
      statusMessage.textContent = `문의가 접수되었습니다. 접수 번호: ${result.inquiry_id}`;
    } catch (error) {
      statusMessage.classList.add('is-error');
      statusMessage.textContent = error.message || '문의 접수 중 오류가 발생했습니다. 다시 시도해주세요.';
    } finally {
      submitButton.disabled = false;
    }
  });
})();