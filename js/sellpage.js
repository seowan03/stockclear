const selectedSellItems = JSON.parse(localStorage.getItem('selectedSellItems') || '[]');
const selectedItemsTitle = document.getElementById('selectedItemsTitle');

if (selectedSellItems.length > 0) {
	selectedItemsTitle.textContent = `판매 등록 상품 (${selectedSellItems.length}개)`;
	const productGrid = document.querySelector('.grid-container');

	productGrid.innerHTML = selectedSellItems.map((item) => {
		const name = item.listing_title || item.product_name || '상품명 없음';
		const initial = name.substring(0, 2).toUpperCase();
		const hasListingSettings = item.listing_price !== undefined && item.listing_price !== null;
		const sellPrice = Number(hasListingSettings ? item.listing_price : item.mock_market_price || item.selling_price || 0);
		const rawOriginalPrice = item.original_price || item.regular_price || item.cost_price || item.mock_market_price || item.selling_price;
		const originalPrice = rawOriginalPrice ? Number(rawOriginalPrice) : Math.round(sellPrice * 1.25 / 100) * 100;
		const discountRate = originalPrice > sellPrice && originalPrice > 0
			? Math.round(((originalPrice - sellPrice) / originalPrice) * 100)
			: Number(item.discount_rate || item.discount || 0);
		const safeImage = /^data:image\/(?:jpeg|png|webp);base64,/i.test(item.listing_image || '')
			? `<img class="product-photo" src="${escapeHtml(item.listing_image)}" alt="${escapeHtml(name)}">`
			: `<div class="thumb-bg bg-stock"></div><div class="thumb-content"><span class="brand-initial">${escapeHtml(initial)}</span><span class="brand-sub">STOCK CLEAR</span></div>`;
		const priceMarkup = discountRate > 0
			? `<span class="discount">${discountRate}%</span><span class="price">${sellPrice.toLocaleString('ko-KR')}원</span><span class="original-price">${originalPrice.toLocaleString('ko-KR')}원</span>`
			: `<span class="price">${sellPrice.toLocaleString('ko-KR')}원</span>`;
		const descriptionMarkup = item.listing_description
			? `<p class="product-description">${escapeHtml(item.listing_description)}</p>`
			: '';
		const quantityMarkup = item.listing_quantity != null
			? `<p class="product-stock">판매 수량 ${Number(item.listing_quantity).toLocaleString('ko-KR')}개</p>`
			: '';

		return `
		<div class="product-card">
			<div class="product-thumb">
				${safeImage}
			</div>
			<div class="product-details">
				<div>
					<span class="product-tag">StockClear 판매 중</span>
					<div class="product-title">${escapeHtml(name)}</div>
					${descriptionMarkup}
				</div>
				<div>${quantityMarkup}<div class="price-group">${priceMarkup}</div></div>
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
