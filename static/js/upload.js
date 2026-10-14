    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const fileNameDisplay = document.getElementById('file-name-display');
    const uploadForm = document.getElementById('upload-form');
    const uploadStatus = document.getElementById('upload-status');

    // 드래그 존 클릭 시 파일 선택창 열기
    dropZone.addEventListener('click', () => fileInput.click());

    // 드래그 앤 드롭 이벤트를 제어하기 위한 핸들러
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
      e.preventDefault();
      e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
      dropZone.addEventListener(eventName, () => {
        dropZone.classList.add('border-blue-500', 'bg-blue-500/10');
      }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, () => {
        dropZone.classList.remove('border-blue-500', 'bg-blue-500/10');
      }, false);
    });

    // 드롭 시 파일 적용
    dropZone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files.length > 0) {
        fileInput.files = files;
        updateFileName(files[0].name);
      }
    });

    // 파일 창에서 클릭으로 선택 시 파일명 표시
    function handleFileSelect(event) {
      if (event.target.files.length > 0) {
        updateFileName(event.target.files[0].name);
      }
    }

    function updateFileName(name) {
      fileNameDisplay.textContent = `'${name}' 파일이 선택되었습니다.`;
      fileNameDisplay.classList.add('text-blue-400');
    }

    function showUploadStatus(message, isError = false) {
      uploadStatus.textContent = message;
      uploadStatus.className = `rounded-xl px-4 py-3 text-sm ${isError ? 'bg-rose-500/10 text-rose-300 border border-rose-500/30' : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/30'}`;
    }

    uploadForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const submitButton = uploadForm.querySelector('button[type="submit"]');
      submitButton.disabled = true;
      submitButton.classList.add('opacity-60', 'cursor-not-allowed');
      showUploadStatus('재고 파일을 분석하는 중입니다.');

      try {
        const response = await fetch(uploadForm.action, {
          method: uploadForm.method,
          body: new FormData(uploadForm),
          credentials: 'include'
        });
        const result = await response.json().catch(() => ({}));

        if (response.status === 401) {
          window.location.href = 'signin.html';
          return;
        }
        if (!response.ok) {
          throw new Error(result.detail || '업로드 처리 중 오류가 발생했습니다.');
        }

        if (result.ai_summary_status === 'failed') {
          showUploadStatus(
            result.ai_summary_message || '파일 업로드와 재고 분석은 완료됐지만 AI 요약을 만들지 못했습니다. 내보내기 화면에서 다시 생성할 수 있습니다.',
            true,
          );
          submitButton.disabled = false;
          submitButton.classList.remove('opacity-60', 'cursor-not-allowed');
          return;
        }

        showUploadStatus('분석이 완료되었습니다. 대시보드로 이동합니다.');
        window.location.href = 'dashboard.html';
      } catch (error) {
        showUploadStatus(error.message || '서버에 연결할 수 없습니다.', true);
        submitButton.disabled = false;
        submitButton.classList.remove('opacity-60', 'cursor-not-allowed');
      }
    });
