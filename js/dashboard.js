document.addEventListener('DOMContentLoaded', async () => {
  const main = document.querySelector('main');
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
    document.getElementById('totalSku').textContent = `${Number(dashboard.total_sku || 0).toLocaleString('ko-KR')} 개`;
    document.getElementById('inventoryValue').textContent = `₩ ${Number(dashboard.monthly_saving || 0).toLocaleString('ko-KR')}`;
    document.getElementById('deficitCount').textContent = `${Number(dashboard.risk_count || 0).toLocaleString('ko-KR')} 개 품목`;
    document.getElementById('staleCount').textContent = `${Number(dashboard.aging_count || 0).toLocaleString('ko-KR')} 개 품목`;

    const grades = Array.isArray(dashboard.grades) ? dashboard.grades : [];
    const riskItems = Array.isArray(dashboard.risk_items) ? dashboard.risk_items : [];
    if (!grades.length && !riskItems.length) {
      showMessage('분석된 재고 데이터가 없습니다. 먼저 재고 파일을 업로드해주세요.', 'border-blue-500/30 bg-blue-500/10 text-blue-300');
      return;
    }

    const chartTextColor = '#cbd5e1';
    const chartGridColor = 'rgba(148, 163, 184, 0.14)';
    const chartOptions = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'right',
          labels: {
            color: chartTextColor,
            boxWidth: 10,
            boxHeight: 10,
            padding: 14,
            font: { size: 12, weight: '600' }
          }
        },
        tooltip: {
          backgroundColor: '#0f172a',
          borderColor: '#334155',
          borderWidth: 1,
          titleColor: '#f8fafc',
          bodyColor: chartTextColor
        }
      }
    };

    const doughnutCenterText = {
      id: 'doughnutCenterText',
      afterDraw(chart) {
        const { ctx, chartArea } = chart;
        const total = grades.reduce((sum, grade) => sum + Number(grade.count || 0), 0);
        const centerX = (chartArea.left + chartArea.right) / 2;
        const centerY = (chartArea.top + chartArea.bottom) / 2;

        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#f8fafc';
        ctx.font = '700 24px Pretendard, sans-serif';
        ctx.fillText(total.toLocaleString('ko-KR'), centerX, centerY - 8);
        ctx.fillStyle = '#94a3b8';
        ctx.font = '500 11px Pretendard, sans-serif';
        ctx.fillText('전체 품목', centerX, centerY + 14);
        ctx.restore();
      }
    };

    const doughnutSegmentLabels = {
      id: 'doughnutSegmentLabels',
      afterDatasetsDraw(chart) {
        const segments = chart.getDatasetMeta(0).data;

        chart.ctx.save();
        chart.ctx.textAlign = 'center';
        chart.ctx.textBaseline = 'middle';
        chart.ctx.font = '700 11px Pretendard, sans-serif';
        chart.ctx.lineWidth = 3;
        chart.ctx.strokeStyle = '#0f172a';
        chart.ctx.fillStyle = '#f8fafc';

        segments.forEach((segment, index) => {
          const value = Number(grades[index]?.count || 0);
          if (!value) return;

          const position = segment.tooltipPosition();
          const label = value.toLocaleString('ko-KR');
          chart.ctx.strokeText(label, position.x, position.y);
          chart.ctx.fillText(label, position.x, position.y);
        });

        chart.ctx.restore();
      }
    };

    new Chart(document.getElementById('trendChart'), {
      type: 'doughnut',
      data: {
        labels: grades.map((grade) => `${grade.name} (${grade.count})`),
        datasets: [{
          data: grades.map((grade) => grade.count),
          backgroundColor: grades.map((grade, index) => [
            '#22c55e', '#fbbf24', '#fb923c', '#f43f5e', '#64748b'
          ][index] || '#64748b'),
          borderColor: '#111827',
          borderWidth: 3
        }]
      },
      plugins: [doughnutCenterText, doughnutSegmentLabels],
      options: { ...chartOptions, cutout: '68%' }
    });

    new Chart(document.getElementById('categoryChart'), {
      type: 'bar',
      data: {
        labels: riskItems.slice(0, 5).map((item, index) => `${index + 1}. ${item.product_name || '이름 없음'}`),
        datasets: [{
          label: '위험 점수',
          data: riskItems.slice(0, 5).map((item) => Math.round(Number(item.final_score) || 0)),
          backgroundColor: '#f43f5e',
          hoverBackgroundColor: '#fb7185',
          borderRadius: 5,
          barThickness: 14
        }]
      },
      options: {
        ...chartOptions,
        indexAxis: 'y',
        plugins: { legend: { display: false } },
        scales: {
          x: {
            beginAtZero: true,
            max: 100,
            border: { display: false },
            grid: { color: chartGridColor },
            ticks: { color: '#94a3b8', font: { size: 11 } }
          },
          y: {
            border: { display: false },
            grid: { display: false },
            ticks: { color: chartTextColor, font: { size: 11, weight: '600' } }
          }
        }
      }
    });
  } catch (error) {
    console.error('대시보드 로딩 실패:', error);
    showMessage('대시보드 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.', 'border-rose-200 bg-rose-50 text-rose-700');
  }
});
