  if (window.Chart) {
    if (typeof ChartDataLabels !== 'undefined') Chart.register(ChartDataLabels);
    Chart.defaults.font.family = "Pretendard, sans-serif";
    Chart.defaults.color = "#64748b";

    new Chart(document.getElementById('landingRiskChart'), {
      type: 'doughnut',
      data: {
        labels: ['악성', '장기', '주의', '정상'],
        datasets: [{
          data: [12, 18, 25, 45],
          backgroundColor: ['#EF4444', '#F97316', '#EAB308', '#22C55E'],
          borderColor: '#ffffff',
          borderWidth: 4,
          hoverOffset: 5
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '70%',
        layout: {
          padding: { top: 55, bottom: 70, left: 45, right: 0 }
        },
        plugins: {
          legend: {
            position: 'right',
            labels: {
              boxWidth: 14,
              padding: 12,
              usePointStyle: true,
              font: { size: 10 },
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
            font: { family: 'Pretendard', size: 13, weight: 'bold' },
            formatter: (value, context) => {
              const total = context.chart.data.datasets[0].data.reduce((sum, count) => sum + count, 0);
              const percentage = total > 0 ? (value / total * 100).toFixed(1) : '0.0';
              return `${context.chart.data.labels[context.dataIndex]}\n${percentage}%`;
            }
          }
        }
      }
    });

    new Chart(document.getElementById('landingTopRiskChart'), {
      type: 'bar',
      data: {
        labels: ['무선 키보드', '보관 용기 세트', '데스크 조명', 'USB 허브', '모바일 액세서리'],
        datasets: [{
          data: [92, 84, 78, 71, 64],
          backgroundColor: '#EF4444',
          borderRadius: 5,
          borderSkipped: false,
          barThickness: 13
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            beginAtZero: true,
            max: 100,
            grid: { color: '#eef2f7' },
            ticks: { stepSize: 25, font: { size: 10 } },
            border: { display: false }
          },
          y: {
            grid: { display: false },
            ticks: { font: { size: 10, weight: '500' } },
            border: { display: false }
          }
        },
        plugins: { legend: { display: false } }
      }
    });
  }
