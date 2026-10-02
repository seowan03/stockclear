const selectedSellItems = JSON.parse(localStorage.getItem('selectedSellItems') || '[]');
const selectedItemsTitle = document.getElementById('selectedItemsTitle');

if (selectedSellItems.length > 0) {
	selectedItemsTitle.textContent = `판매 등록 상품 (${selectedSellItems.length}개)`;
	const productGrid = document.querySelector('.grid-container');

	productGrid.innerHTML = selectedSellItems.map((item) => {
		const name = item.product_name || '상품명 없음';
		const initial = name.substring(0, 2).toUpperCase();

		// 판매가
		const sellPrice = Number(item.mock_market_price || item.selling_price || 0);

		// 원가 (데이터에 원가 정보가 있을 경우 사용하고, 없으면 약 25% 업라이트 계산)
		const rawOriginalPrice = item.original_price || item.regular_price || item.cost_price;
		const originalPrice = rawOriginalPrice ? Number(rawOriginalPrice) : Math.round(sellPrice * 1.25 / 100) * 100;

		// 할인율 계산
		let discountRate = item.discount_rate || item.discount;
		if (!discountRate && originalPrice > sellPrice && originalPrice > 0) {
			discountRate = Math.round(((originalPrice - sellPrice) / originalPrice) * 100);
		} else if (!discountRate) {
			discountRate = 20; // 기본값
		}

		return `
		<div class="product-card">
			<div class="product-thumb">
				<div class="thumb-bg bg-stock"></div>
				<div class="thumb-content">
					<span class="brand-initial">${escapeHtml(initial)}</span>
					<span class="brand-sub">STOCK CLEAR</span>
				</div>
			</div>
			<div class="product-details">
				<div>
					<span class="product-tag">StockClear 판매 중</span>
					<div class="product-title">${escapeHtml(name)}</div>
				</div>
				<div class="price-group">
					<span class="discount">${discountRate}%</span>
					<span class="price">${sellPrice.toLocaleString('ko-KR')}원</span>
					<span class="original-price">${originalPrice.toLocaleString('ko-KR')}원</span>
				</div>
			</div>
		</div>`;
	}).join('');
}

function escapeHtml(value) {
	return String(value)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#039;');
}
