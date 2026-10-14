  // 파일 크기(byte) -> 사람이 읽기 쉬운 단위로 변환
  function formatFileSize(bytes) {
    if (!bytes) return '-';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  // 파일명 확장자에 따른 아이콘/색상
  function fileIcon(filename) {
    const lower = String(filename || '').toLowerCase();
    const icon = document.createElement('i');
    icon.className = lower.endsWith('.xlsx') || lower.endsWith('.xls')
      ? 'fa-solid fa-file-excel text-emerald-400 mr-2'
      : 'fa-solid fa-file-csv text-blue-400 mr-2';
    return icon;
  }

  // 상태값에 따른 배지 스타일
  function statusBadge(status) {
    const badge = document.createElement('span');
    const style = {
      '성공': 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
      '실패': 'bg-red-500/10 border-red-500/30 text-red-400'
    }[status] || 'bg-gray-500/10 border-gray-500/30 text-gray-400';
    badge.className = `px-2 py-0.5 rounded border font-bold ${style}`;
    badge.textContent = String(status ?? '-');
    return badge;
  }

  // 셀 생성 헬퍼: 사용자 값은 항상 텍스트로만 삽입
  function createCell(className, ...children) {
    const cell = document.createElement('td');
    cell.className = className;
    cell.append(...children);
    return cell;
  }

  // DB에서 업로드 기록을 가져와 테이블 렌더링
  async function loadHistory() {
    const tbody = document.getElementById('historyTableBody');
    try {
      const res = await fetch('/api/history', { credentials: 'include' });
      if (res.status === 401) {
        tbody.innerHTML = `<tr><td colspan="5" class="px-6 py-8 text-center text-gray-500">로그인 후 이용 가능합니다. <a href="signin.html" class="text-blue-400 hover:underline">로그인하기</a></td></tr>`;
        updateCount();
        return;
      }
      if (!res.ok) throw new Error('요청 실패');
      const rows = await res.json();

      if (rows.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="px-6 py-8 text-center text-gray-500">업로드 기록이 없습니다.</td></tr>`;
      } else {
        tbody.replaceChildren(...rows.map(row => {
          const tr = document.createElement('tr');
          tr.className = 'hover:bg-gray-800/40 transition-colors';
          tr.dataset.historyId = String(Number(row.id));

          const deleteButton = document.createElement('button');
          deleteButton.className = 'px-2.5 py-1.5 bg-red-900/30 hover:bg-red-800/50 text-red-400 rounded-lg text-[11px] transition-colors';
          deleteButton.innerHTML = '<i class="fa-solid fa-xmark"></i>';
          deleteButton.addEventListener('click', () => deleteRow(deleteButton, Number(row.id)));

          const filenameCell = createCell('px-6 py-4 font-bold text-white', fileIcon(row.file_name), String(row.file_name ?? ''));
          if (row.edited) {
            const changed = document.createElement('span');
            changed.className = 'ml-2 text-xs font-normal text-amber-300';
            changed.textContent = '업로드 후 수정됨';
            filenameCell.append(changed);
          }

          tr.append(
            createCell('px-6 py-4 font-mono text-gray-400', row.upload_date ? String(row.upload_date).replace('T', ' ').slice(0, 16) : '-'),
            filenameCell,
            createCell('px-6 py-4 text-gray-400', formatFileSize(row.size)),
            createCell('px-6 py-4', statusBadge(row.status)),
            createCell('px-6 py-4 text-right', deleteButton)
          );
          return tr;
        }));
      }
      updateCount();
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="5" class="px-6 py-8 text-center text-red-400">기록을 불러오지 못했습니다.</td></tr>`;
    }
  }

  // 개별 행 삭제 함수 (DB에서도 삭제)
  async function deleteRow(button, historyId) {
    if (!confirm("이 업로드 기록과 해당 파일에서 생성된 재고·분석 데이터를 함께 삭제하시겠습니까?")) return;
    try {
      const res = await fetch(`/api/history/${historyId}`, { method: 'DELETE', credentials: 'include' });
      if (!res.ok) throw new Error('삭제 실패');
      button.closest('tr').remove();
      updateCount();
    } catch (err) {
      alert('삭제 중 오류가 발생했습니다.');
    }
  }

  // 전체 기록 삭제 함수 (DB에서도 삭제)
  async function clearHistory() {
    if (!confirm("모든 업로드 기록과 해당 파일들에서 생성된 재고·분석 데이터를 함께 삭제하시겠습니까?")) return;
    try {
      const res = await fetch('/api/history', { method: 'DELETE', credentials: 'include' });
      if (!res.ok) throw new Error('삭제 실패');
      document.getElementById('historyTableBody').innerHTML = `
        <tr>
          <td colspan="5" class="px-6 py-8 text-center text-gray-500">업로드 기록이 없습니다.</td>
        </tr>`;
      updateCount();
    } catch (err) {
      alert('삭제 중 오류가 발생했습니다.');
    }
  }

  // 실시간 파일명 검색 필터 함수
  function filterHistory() {
    const input = document.getElementById('searchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#historyTableBody tr');

    rows.forEach(row => {
      const fileName = row.cells[1]?.innerText.toLowerCase() || '';
      if (fileName.includes(input)) {
        row.style.display = '';
      } else {
        row.style.display = 'none';
      }
    });
  }

  // 총 개수 업데이트 함수
  function updateCount() {
    const visibleRows = document.querySelectorAll('#historyTableBody tr[data-history-id]').length;
    document.getElementById('totalCount').innerText = visibleRows;
  }

  loadHistory();
