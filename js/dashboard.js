document.addEventListener('DOMContentLoaded', async () => {
  const main = document.querySelector('main');
  const escapeHtml = (value) => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
  const showMessage = (message, className) => {
    main?.insertAdjacentHTML(
      'afterbegin',
      `<div class="rounded-xl border px-4 py-3 text-sm ${className}">${message}</div>`
    );
  };

  try {
    const response = await fetch('/api/dashboard', { credentials: 'include' });
    if (response.status === 401) {
      window.location.href = 'signin.html';
      return;
    }
    if (!response.ok) throw new Error('대시보드 데이터를 불러오지 못했습니다.');

    const dashboard = await response.json();
    const inventoryResponse = await fetch('/api/inventory', { credentials: 'include' });
    if (inventoryResponse.status === 401) {
      window.location.href = 'signin.html';
      return;
    }
    if (!inventoryResponse.ok) throw new Error('재고 목록을 불러오지 못했습니다.');
    const inventoryItems = (await inventoryResponse.json()).items || [];

    document.getElementById('totalSku').textContent = `${Number(dashboard.total_sku || 0).toLocaleString('ko-KR')} 개`;
    document.getElementById('inventoryValue').textContent = `₩ ${Number(dashboard.monthly_saving || 0).toLocaleString('ko-KR')}`;
    document.getElementById('deficitCount').textContent = `${Number(dashboard.risk_count || 0).toLocaleString('ko-KR')} 개 품목`;
    document.getElementById('staleCount').textContent = `${Number(dashboard.aging_count || 0).toLocaleString('ko-KR')} 개 품목`;

    const urgentTitle = document.getElementById('urgentInsightTitle');
    const staleTitle = document.getElementById('staleInsightTitle');
    if (urgentTitle) urgentTitle.lastChild.textContent = ` 긴급 발주 제안 (${Number(dashboard.risk_count || 0)}건)`;
    if (staleTitle) staleTitle.lastChild.textContent = ` 과다 재고 소진 제안 (${Number(dashboard.aging_count || 0)}건)`;
    document.getElementById('urgentInsightText').textContent = dashboard.risk_count
      ? `위험 재고 ${dashboard.risk_count}건이 확인되었습니다. 재고 회전과 처분 계획을 검토하세요.`
      : '현재 위험 재고가 없습니다.';
    document.getElementById('staleInsightText').textContent = dashboard.aging_count
      ? `장기 체류 재고 ${dashboard.aging_count}건이 확인되었습니다. 할인 또는 소진 프로모션을 검토하세요.`
      : '현재 장기 체류 재고가 없습니다.';

    const tableBody = document.getElementById('inventory-table-body');
    tableBody.innerHTML = inventoryItems.length
      ? inventoryItems.slice(0, 5).map((item) => `<tr class="hover:bg-gray-50/80 transition-colors">
          <td class="py-4 px-6 text-gray-400">${escapeHtml(item.item_id)}</td>
          <td class="py-4 px-6 text-gray-900 font-bold">${escapeHtml(item.product_name || '이름 없음')}</td>
          <td class="py-4 px-6">-</td>
          <td class="py-4 px-6 text-right font-semibold text-gray-800">${Number(item.stock_qty || 0).toLocaleString('ko-KR')} 개</td>
          <td class="py-4 px-6 text-right text-gray-500">-</td>
          <td class="py-4 px-6 text-right">₩ ${Number(item.purchase_price || 0).toLocaleString('ko-KR')}</td>
          <td class="py-4 px-6 text-center"><span class="px-2.5 py-1 bg-gray-100 text-gray-700 rounded-full font-semibold">${escapeHtml(item.risk_grade || '정상')}</span></td>
        </tr>`).join('')
      : '<tr><td colspan="7" class="py-8 px-6 text-center text-gray-400">등록된 재고 데이터가 없습니다.</td></tr>';

    const grades = Array.isArray(dashboard.grades) ? dashboard.grades : [];
    const riskItems = Array.isArray(dashboard.risk_items) ? dashboard.risk_items : [];
    if (!grades.length && !riskItems.length) {
      showMessage('분석된 재고 데이터가 없습니다. 먼저 재고 파일을 업로드해주세요.', 'border-blue-200 bg-blue-50 text-blue-700');
      return;
    }

    const chartOptions = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom' } }
    };

    new Chart(document.getElementById('trendChart'), {
      type: 'doughnut',
      data: {
        labels: grades.map((grade) => `${grade.name} (${grade.count})`),
        datasets: [{
          data: grades.map((grade) => grade.count),
          backgroundColor: grades.map((grade) => grade.color || '#64748b'),
          borderWidth: 0
        }]
      },
      options: { ...chartOptions, cutout: '70%' }
    });

    new Chart(document.getElementById('categoryChart'), {
      type: 'bar',
      data: {
        labels: riskItems.map((item, index) => `${index + 1}. ${item.product_name || '이름 없음'}`),
        datasets: [{
          label: '위험 점수',
          data: riskItems.map((item) => Math.round(Number(item.final_score) || 0)),
          backgroundColor: '#ef4444',
          borderRadius: 4,
          barThickness: 12
        }]
      },
      options: {
        ...chartOptions,
        indexAxis: 'y',
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, max: 100 } }
      }
    });
  } catch (error) {
    console.error('대시보드 로딩 실패:', error);
    showMessage('대시보드 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.', 'border-rose-200 bg-rose-50 text-rose-700');
  }
});
