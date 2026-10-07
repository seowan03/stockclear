// ChartDataLabels 플러그인 전역 등록
if (typeof ChartDataLabels !== 'undefined') {
  Chart.register(ChartDataLabels);
}

document.addEventListener("DOMContentLoaded", async () => {
  const params = new URLSearchParams(window.location.search);
  const uploadId = params.get('upload_id');
  const uploadQuery = uploadId ? `?upload_id=${encodeURIComponent(uploadId)}` : '';

  try {
    const [dashboardResponse, inventoryResponse] = await Promise.all([
      fetch(`/api/dashboard${uploadQuery}`, { credentials: 'include' }),
      fetch(`/api/inventory${uploadQuery}`, { credentials: 'include' })
    ]);
    if (dashboardResponse.status === 401 || inventoryResponse.status === 401) {
      window.location.href = 'signin.html';
      return;
    }
    if (!dashboardResponse.ok || !inventoryResponse.ok) {
      throw new Error('Dashboard data request failed');
    }

    const dashboard = await dashboardResponse.json();
    const inventory = await inventoryResponse.json();
    const inventoryItems = Array.isArray(inventory.items) ? inventory.items : [];
    const riskItems = Array.isArray(dashboard.risk_items) ? dashboard.risk_items : [];

    const title = document.getElementById('dashboardTitle');
    if (title && dashboard.upload_file_name) {
      title.textContent = `${dashboard.upload_file_name} 분석 결과`;
    }
    const updatedAt = document.getElementById('dashboardUpdatedAt');
    if (updatedAt && dashboard.generated_at) {
      updatedAt.textContent = `${new Date(dashboard.generated_at).toLocaleString('ko-KR')} 기준`;
    }

    document.getElementById('totalSku').innerHTML = `${Number(dashboard.total_sku || 0).toLocaleString('ko-KR')} <span class="text-xs font-normal text-gray-400">개</span>`;
    document.getElementById('inventoryValue').textContent = `₩ ${Number(dashboard.inventory_value || 0).toLocaleString('ko-KR')}`;
    document.getElementById('deficitCount').innerHTML = `${Number(dashboard.risk_count || 0).toLocaleString('ko-KR')} <span class="text-xs font-normal text-gray-400">개 품목</span>`;
    document.getElementById('staleCount').innerHTML = `${Number(dashboard.aging_count || 0).toLocaleString('ko-KR')} <span class="text-xs font-normal text-gray-400">개 품목</span>`;
    renderInventoryGradePopover('deficitItemsPopover', '악성', inventoryItems);
    renderInventoryGradePopover('staleItemsPopover', '장기', inventoryItems);

    if (!inventoryItems.length && !riskItems.length) {
      showErrorMessage('분석된 재고 데이터가 없습니다. 먼저 재고 파일을 업로드해주세요.');
      return;
    }

    renderTrendChart(inventoryItems);
    renderCategoryChart(riskItems);
    renderRiskItemsList(inventoryItems.length ? inventoryItems : riskItems);
  } catch (error) {
    console.error('Dashboard Load Error:', error);
    showErrorMessage('대시보드 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.');
  }
});

function renderRiskItemsList(items) {
  const list = document.getElementById('riskItemsList');
  const toggle = document.getElementById('riskItemsToggle');
  const panel = document.getElementById('riskItemsPanel');
  const total = document.getElementById('riskItemsTotal');
  if (!list || !toggle || !panel || !total) return;

  const sortedItems = [...items].sort((firstItem, secondItem) =>
    Number(secondItem.final_score || 0) - Number(firstItem.final_score || 0)
  );
  total.textContent = `${sortedItems.length}개`;
  list.replaceChildren();

  if (!sortedItems.length) {
    const emptyItem = document.createElement('li');
    emptyItem.className = 'dashboard-risk-list__empty';
    emptyItem.textContent = '표시할 상품이 없습니다.';
    list.append(emptyItem);
  } else {
    sortedItems.forEach((item, index) => {
      const row = document.createElement('li');
      row.className = 'dashboard-risk-list__item';

      const rank = document.createElement('span');
      rank.className = 'dashboard-risk-list__rank';
      rank.textContent = String(index + 1).padStart(2, '0');

      const name = document.createElement('span');
      name.className = 'dashboard-risk-list__name';
      name.textContent = item.product_name || '이름 없는 품목';

      const details = document.createElement('span');
      details.className = 'dashboard-risk-list__details';
      details.textContent = `${item.risk_grade || '미분류'} · ${Number(item.final_score || 0).toLocaleString('ko-KR')}점`;

      row.append(rank, name, details);
      list.append(row);
    });
  }

  toggle.addEventListener('click', () => {
    const isExpanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!isExpanded));
    panel.hidden = isExpanded;
  });

  document.addEventListener('click', event => {
    if (!event.target.closest('.dashboard-risk-list-control')) {
      toggle.setAttribute('aria-expanded', 'false');
      panel.hidden = true;
    }
  });

  toggle.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      toggle.setAttribute('aria-expanded', 'false');
      panel.hidden = true;
      toggle.focus();
    }
  });
}

function renderInventoryGradePopover(popoverId, grade, inventoryItems) {
  const popover = document.getElementById(popoverId);
  if (!popover) return;

  const matchingItems = inventoryItems.filter(item => item.risk_grade === grade);
  const title = document.createElement('p');
  title.className = 'dashboard-items-popover__title';
  title.textContent = `${grade} 재고 품목 (${matchingItems.length}개)`;
  popover.replaceChildren(title);

  if (!matchingItems.length) {
    const emptyMessage = document.createElement('p');
    emptyMessage.className = 'dashboard-items-popover__empty';
    emptyMessage.textContent = '해당 등급의 재고가 없습니다.';
    popover.append(emptyMessage);
    return;
  }

  const list = document.createElement('ul');
  list.className = 'dashboard-items-popover__list';
  matchingItems.forEach(item => {
    const listItem = document.createElement('li');
    listItem.className = 'dashboard-items-popover__item';

    const productName = document.createElement('span');
    productName.className = 'dashboard-items-popover__name';
    productName.textContent = item.product_name || '이름 없는 품목';

    const quantity = document.createElement('span');
    quantity.className = 'dashboard-items-popover__quantity';
    const stockQuantity = item.stock_qty;
    quantity.textContent = stockQuantity === null || stockQuantity === undefined || stockQuantity === ''
      ? '수량 정보 없음'
      : `${Number(stockQuantity).toLocaleString('ko-KR')}개`;

    listItem.append(productName, quantity);
    list.append(listItem);
  });
  popover.append(list);
}

// 도넛 차트 (항상 4개 범주 표시)
function renderTrendChart(items) {
  const ctx = document.getElementById('trendChart');
  if (!ctx) return;

  const existingChart = Chart.getChart(ctx);
  if (existingChart) existingChart.destroy();

  const categories = [
    { name: '악성', count: 0, color: '#EF4444' },
    { name: '장기', count: 0, color: '#F97316' },
    { name: '주의', count: 0, color: '#EAB308' },
    { name: '정상', count: 0, color: '#22C55E' }
  ];

  items.forEach(item => {
    const category = categories.find(candidate => candidate.name === item.risk_grade);
    if (category) category.count += 1;
  });

  // 필터링 없이 전체 categories 4개를 모두 전달
  const total = categories.reduce((sum, category) => sum + category.count, 0);

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: categories.map(category => category.name),
      datasets: [{
        data: categories.map(category => category.count),
        backgroundColor: categories.map(category => category.color),
        borderColor: '#ffffff',
        borderWidth: 3,
        hoverOffset: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '70%',
      layout: {
        padding: {
          top: 55,
          bottom: 70,
          left: 45,
          right: 45
        }
      },
      plugins: {
        legend: {
          display: true,
          position: 'right',
          labels: {
            color: '#475569',
            boxWidth: 14,
            padding: 12,
            generateLabels: chart => Chart.overrides.doughnut.plugins.legend.labels.generateLabels(chart).map(label => ({
              ...label,
              text: `${label.text} (${chart.data.datasets[0].data[label.index]})`
            }))
          }
        },
        datalabels: {
          clamp: true,
          anchor: 'end',
          align: 'end',
          offset: 12,
          color: '#1e293b',
          textAlign: 'center',
          font: {
            family: 'Pretendard',
            size: 13,
            weight: 'bold'
          },
          formatter: (value, context) => {
            if (value === 0) return ''; // 수량이 0인 라벨은 차트 표기 생략 (범례에는 표시됨)
            const label = context.chart.data.labels[context.dataIndex];
            const percentage = total > 0 ? (value / total * 100).toFixed(1) : '0.0';
            return `${label}\n${percentage}%`;
          }
        },
        tooltip: {
          titleFont: { family: 'Pretendard', size: 14 },
          bodyFont: { family: 'Pretendard', size: 13 },
          padding: 12,
          cornerRadius: 10
        }
      }
    }
  });
}

// 위험 상품 TOP 5 (완전 빨간색)
function renderCategoryChart(items) {
  const ctx = document.getElementById('categoryChart');
  if (!ctx) return;

  const existingChart = Chart.getChart(ctx);
  if (existingChart) existingChart.destroy();

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: items.map(item => item.product_name),
      datasets: [{
        label: '위험도 점수',
        data: items.map(item => item.final_score),
        backgroundColor: '#EF4444',
        borderRadius: 8,
        borderSkipped: false,
        barThickness: 13
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      scales: {
        x: {
          beginAtZero: true,
          max: 100,
          grid: { color: 'rgba(15, 23, 42, 0.10)' },
          ticks: { stepSize: 20, color: '#475569', font: { family: 'Pretendard' } }
        },
        y: {
          grid: { display: false },
          ticks: { color: '#1e293b', font: { family: 'Pretendard', weight: '600' } }
        }
      },
      plugins: {
        legend: { display: false },
        datalabels: {
          display: false
        },
        tooltip: {
          titleFont: { family: 'Pretendard', size: 14 },
          bodyFont: { family: 'Pretendard', size: 13 },
          padding: 12,
          cornerRadius: 10
        }
      }
    }
  });
}

function showErrorMessage(message) {
  let errBox = document.getElementById('dashboardErrorMessage');
  if (!errBox) {
    errBox = document.createElement('div');
    errBox.id = 'dashboardErrorMessage';
    errBox.className = 'bg-rose-500/10 border border-rose-500/20 text-rose-400 p-4 rounded-xl text-sm mb-6';
    const main = document.querySelector('main');
    if (main) main.insertBefore(errBox, main.firstChild);
  }
  errBox.innerText = message;
}