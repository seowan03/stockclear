document.addEventListener('DOMContentLoaded', () => {
	const inventory = StockClear.getInventory();
	const counts = { 정상: 0, 주의: 0, '장기 체류': 0, '처분 권장': 0 };

	inventory.forEach((item) => {
		counts[StockClear.classify(item)] += 1;
	});

	document.getElementById('totalSku').textContent = `${inventory.length.toLocaleString('ko-KR')} 개`;
	document.getElementById('deficitCount').textContent = `${counts['처분 권장'].toLocaleString('ko-KR')} 개`;
	document.getElementById('staleCount').textContent = `${(counts['장기 체류'] + counts['주의']).toLocaleString('ko-KR')} 개`;
	document.getElementById('inventoryValue').textContent = `₩ ${StockClear.formatNumber(
		inventory.reduce((total, item) => total + StockClear.number(item.inventory_value), 0)
	)}`;

	const riskItems = inventory
		.map((item) => ({
			name: item.product_name || '이름 없음',
			score: Math.min(100, Math.round(
				StockClear.number(item.storage_days) / 1.2 + StockClear.number(item.depreciation_rate)
			))
		}))
		.sort((a, b) => b.score - a.score)
		.slice(0, 5);

	const chartOptions = {
		responsive: true,
		maintainAspectRatio: false,
		plugins: { legend: { labels: { color: '#94a3b8', padding: 14 } } }
	};

	new Chart(document.getElementById('donutChart'), {
		type: 'doughnut',
		data: {
			labels: Object.keys(counts).map((label) => `${label} (${counts[label]})`),
			datasets: [{ data: Object.values(counts), backgroundColor: ['#22c55e', '#eab308', '#f97316', '#ef4444'], borderWidth: 0 }]
		},
		options: { ...chartOptions, cutout: '70%' }
	});

	new Chart(document.getElementById('barChart'), {
		type: 'bar',
		data: {
			labels: riskItems.map((item, index) => `${index + 1}. ${item.name}`),
			datasets: [{ data: riskItems.map((item) => item.score), backgroundColor: '#ef4444', borderRadius: 4, barThickness: 12 }]
		},
		options: {
			...chartOptions,
			indexAxis: 'y',
			plugins: { legend: { display: false } },
			scales: {
				x: { max: 100, grid: { color: '#1e293b' }, ticks: { color: '#64748b' } },
				y: { grid: { display: false }, ticks: { color: '#cbd5e1', font: { size: 12 } } }
			}
		}
	});
});
