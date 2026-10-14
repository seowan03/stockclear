    let loadedItems = [];
    let inventoryDetailsPromise;
    let activeExportItemId = null;
    let summaryUploadId = null;
    const pendingDiagnoses = new Set();
    const safetyStockResults = new Map();
    const pendingSafetyStock = new Set();
    let pendingSellItems = [];

    const { escapeHtml, formatRecommendationText } = StockClear;

    function formatNumber(num) {
        return StockClear.formatNumber(num);
    }

    function getStatusClass(status) {
        return StockClear.statusClass(status);
    }

    function getExportItemStatus(item) {
        return StockClear.riskCategory(item);
    }

        async function loadExportData() {
            const tbody = document.getElementById('reportBody');
            try {
                const response = await fetch('/api/export', { credentials: 'include' });
                if (response.status === 401) {
                    window.location.href = 'signin.html';
                    return;
                }
                if (!response.ok) throw new Error('내보내기 데이터를 불러오지 못했습니다.');

                const report = await response.json();
                loadedItems = Array.isArray(report.items) ? report.items : [];
                document.getElementById('reportCount').textContent = `총 ${loadedItems.length.toLocaleString('ko-KR')}개 항목 선택됨`;

                const summary = report.summary || {};
                summaryUploadId = summary.summary_upload_id || null;
                const canGenerateSummary = ['failed', 'unavailable'].includes(summary.ai_summary_status);
                document.getElementById('retrySummaryButton').classList.toggle(
                    'hidden',
                    !canGenerateSummary || !summaryUploadId,
                );
                document.getElementById('retrySummaryLabel').textContent =
                    summary.ai_summary_status === 'unavailable'
                        ? 'AI 종합진단 생성'
                        : 'AI 종합진단 다시 생성';
                document.getElementById('reportSummary').textContent = summary.ai_summary
                    || '저장된 AI 종합진단이 없습니다.';
                const riskCount = loadedItems.filter((item) => item.risk_grade === '악성').length;
                const agingCount = loadedItems.filter((item) => item.risk_grade === '장기').length;
                const itemCount = loadedItems.length;
                const inventoryValue = loadedItems.reduce(
                    (total, item) => total + Number(item.stock_qty || 0) * Number(item.purchase_price || 0),
                    0,
                );
                document.getElementById('reportOverview').textContent =
                    `${itemCount.toLocaleString('ko-KR')}개 품목 중 악성 등급은 ${riskCount.toLocaleString('ko-KR')}개, 장기 등급은 ${agingCount.toLocaleString('ko-KR')}개입니다.`;
                document.getElementById('reportAdvice').textContent = riskCount
                    ? '악성 등급 품목의 판매가와 시세를 확인하고, 원가 이하가 되지 않는 범위에서 할인 여부를 검토하세요.'
                    : agingCount
                        ? '장기 보관 품목의 판매 흐름을 확인하고 재고 회전 개선을 검토하세요.'
                        : '현재 분류 기준에서 우선 조치가 필요한 품목은 없습니다.';
                document.getElementById('reportMetrics').textContent =
                    `전체 ${itemCount.toLocaleString('ko-KR')}개  ·  악성 ${riskCount.toLocaleString('ko-KR')}개  ·  장기 ${agingCount.toLocaleString('ko-KR')}개  ·  총 재고 자산 ${formatNumber(inventoryValue)}원`;
                const reportScopeNote = document.getElementById('reportScopeNote');
                if (summary.scope === 'account_active_inventory' && report.upload_file_name) {
                    reportScopeNote.textContent = `AI 종합진단은 ${report.summary_source_file_name || '업로드 당시'}의 전체 누적 재고 기준이고, 위 집계와 표는 선택한 파일 기준입니다.`;
                } else if (summary.scope === 'account_active_inventory' || summary.scope === 'current_account') {
                    reportScopeNote.textContent = 'AI 종합진단은 전체 활성 재고 누적 기준입니다. 위 집계는 현재 표에 표시된 품목 기준입니다.';
                } else if (summary.scope === 'selected_upload') {
                    reportScopeNote.textContent = 'AI 종합진단과 표는 선택한 업로드 기준입니다.';
                } else {
                    reportScopeNote.textContent = '';
                }

                tbody.innerHTML = loadedItems.length
                    ? loadedItems.map((item, index) => {
                        const status = getExportItemStatus(item);
                        const mockMarketPrice = item.mock_market_price == null
                            ? '-'
                            : `${StockClear.formatNumber(item.mock_market_price)}원`;
                        const recommendedPrice = item.recommended_price == null
                            ? '-'
                            : `${StockClear.formatNumber(item.recommended_price)}원`;

                        const recommendedQty = safetyStockResults.get(Number(item.item_id))?.recommended_qty ?? item.recommended_qty;
                        return `<tr class="hover:bg-gray-800/40"><td class="py-3 px-4 text-center"><input type="checkbox" class="item-checkbox w-4 h-4 rounded bg-gray-800 border-gray-700 text-blue-600 focus:ring-blue-500 cursor-pointer" data-index="${index}"></td><td class="py-3 px-4 font-semibold text-white"><button type="button" class="text-left hover:text-blue-300 hover:underline" onclick="openExportItemDetail(${Number(item.item_id)}, 'detail')">${escapeHtml(item.product_name || '-')}</button></td><td class="py-3 px-4 whitespace-nowrap tabular-nums">${mockMarketPrice}</td><td class="py-3 px-4 whitespace-nowrap tabular-nums">${recommendedPrice}</td><td class="py-3 px-4">${StockClear.formatNumber(item.stock_qty)}개</td><td class="py-3 px-4 whitespace-nowrap"><span data-safety-stock-id="${Number(item.item_id)}">${recommendedQty == null ? '-' : `${formatNumber(recommendedQty)}개`}</span></td><td class="py-3 px-4 ${StockClear.statusClass(status)} font-bold">${escapeHtml(status)}</td><td class="py-3 px-4 text-left"><button type="button" class="inline-flex items-center gap-1.5 px-0 py-0 text-xs font-semibold text-blue-300 transition-colors hover:text-blue-200 disabled:opacity-50" onclick="diagnoseExportItem(${Number(item.item_id)}, this)"><i class="fa-solid fa-wand-magic-sparkles"></i>AI 진단</button></td></tr>`;
                    }).join('')
                    : '<tr><td colspan="8" class="py-8 text-center text-gray-500">내보낼 재고 데이터가 없습니다.</td></tr>';
            } catch (error) {
                console.error('내보내기 데이터 로딩 실패:', error);
                tbody.innerHTML = '<tr><td colspan="8" class="py-8 text-center text-rose-400">데이터를 불러오지 못했습니다.</td></tr>';
            }
        }

        async function retryUploadSummary() {
            const button = document.getElementById('retrySummaryButton');
            const label = document.getElementById('retrySummaryLabel');
            const message = document.getElementById('reportSummary');
            if (!summaryUploadId || button.disabled) return;

            button.disabled = true;
            label.textContent = '생성 중...';
            message.textContent = 'AI 종합진단을 다시 생성하고 있습니다.';
            try {
                const response = await fetch(`/api/upload/${summaryUploadId}/summary/retry`, {
                    method: 'POST',
                    credentials: 'include',
                });
                if (response.status === 401) {
                    window.location.href = 'signin.html';
                    return;
                }
                const result = await response.json();
                if (!response.ok) throw new Error(result.detail || 'AI 종합진단 재생성에 실패했습니다.');
                if (result.status !== 'complete') {
                    throw new Error(result.message || 'AI 종합진단을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.');
                }
                await loadExportData();
            } catch (error) {
                message.textContent = error.message || 'AI 종합진단 재생성에 실패했습니다.';
                label.textContent = '다시 시도';
            } finally {
                button.disabled = false;
                if (label.textContent === '생성 중...') label.textContent = 'AI 종합진단 다시 생성';
            }
        }

    async function loadInventoryDetails() {
        if (!inventoryDetailsPromise) {
            inventoryDetailsPromise = fetch('/api/inventory', { credentials: 'include' }).then(async response => {
                if (response.status === 401) {
                    window.location.href = 'signin.html';
                    return [];
                }
                if (!response.ok) throw new Error('상품 상세 정보를 불러오지 못했습니다.');
                const inventory = await response.json();
                return Array.isArray(inventory.items) ? inventory.items : [];
            });
        }
        return inventoryDetailsPromise;
    }

    function switchExportDetailTab(tab) {
        const panels = {
            detail: ['exportDetailTab', 'exportDetailTabButton'],
            analysis: ['exportAnalysisTab', 'exportAnalysisTabButton'],
            history: ['exportHistoryTab', 'exportHistoryTabButton']
        };
        Object.entries(panels).forEach(([name, [panelId, buttonId]]) => {
            document.getElementById(panelId).classList.toggle('hidden', name !== tab);
            document.getElementById(buttonId).className = name === tab
                ? 'pb-3 border-b-2 border-blue-500 text-blue-400 font-bold'
                : 'pb-3 text-gray-400 hover:text-white transition-colors';
        });
    }

    async function openExportItemDetail(itemId, initialTab = 'detail') {
        activeExportItemId = Number(itemId);
        document.getElementById('exportDiagnosisFallbackActions').classList.add('hidden');
        const modal = document.getElementById('exportDetailModal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.getElementById('exportDetailTitle').textContent = '상세 정보를 불러오는 중입니다.';
        document.getElementById('safetyStockForm').reset();
        document.getElementById('calculateSafetyStock').disabled = true;
        document.getElementById('exportDetailRecommendedQty').textContent = '-';
        document.getElementById('safetyStockStatus').textContent = '';
        document.getElementById('safetyStockSource').textContent = '일별 판매량 조회 중...';
        switchExportDetailTab(initialTab);

        try {
            const [items, salesResponse] = await Promise.all([
                loadInventoryDetails(),
                fetch(`/api/inventory/${Number(itemId)}/safety-stock`, { credentials: 'include' })
            ]);
            if (activeExportItemId !== Number(itemId)) return;
            if (salesResponse.status === 401) {
                window.location.href = 'signin.html';
                return;
            }
            if (!salesResponse.ok) throw new Error('일별 판매량 초기값을 불러오지 못했습니다.');
            const salesDefaults = await salesResponse.json();
            if (activeExportItemId !== Number(itemId)) return;
            const item = items.find(row => Number(row.item_id) === Number(itemId));
            if (!item) throw new Error('해당 상품 정보를 찾을 수 없습니다.');

            const status = getExportItemStatus(item);
            const statusClass = getStatusClass(status);
            const formatCurrency = value => value == null ? '-' : `₩ ${formatNumber(value)}`;
            const formatDays = value => value == null ? '-' : `${formatNumber(value)} 일`;
            const discountMatch = String(item.action_plans || '').match(/(\d+(?:\.\d+)?)\s*%/);

            document.getElementById('exportDetailTitle').textContent = item.product_name || '이름 없음';
            const badge = document.getElementById('exportDetailBadge');
            badge.textContent = status;
            const badgeClass = StockClear.statusBadgeClass(status);
            badge.className = `px-3 py-1 text-xs font-semibold rounded-full ${badgeClass} border`;
            document.getElementById('exportDetailCode').textContent = item.item_id;
            document.getElementById('exportDetailDate').textContent = item.received_date || '-';
            document.getElementById('exportDetailPurchasePrice').textContent = formatCurrency(item.purchase_price);
            document.getElementById('exportDetailSellingPrice').textContent = formatCurrency(item.mock_market_price);
            document.getElementById('exportDetailStock').textContent = `${formatNumber(item.stock_qty)} 개`;
            const safetyStock = safetyStockResults.get(Number(itemId));
            const inputs = safetyStock?.inputs ?? salesDefaults.inputs;
            document.getElementById('maxDailySales').value = inputs?.max_daily_sales ?? '';
            document.getElementById('averageDailySales').value = inputs?.average_daily_sales ?? item.sales_speed ?? 0;
            document.getElementById('maxLeadTime').value = inputs?.max_lead_time_days ?? 5;
            document.getElementById('averageLeadTime').value = inputs?.average_lead_time_days ?? 2;
            const recommendedQty = safetyStock?.recommended_qty ?? item.recommended_qty;
            document.getElementById('exportDetailRecommendedQty').textContent = recommendedQty == null ? '-' : `${formatNumber(recommendedQty)} 개`;
            document.getElementById('calculateSafetyStock').disabled = pendingSafetyStock.has(Number(itemId));
            document.getElementById('safetyStockSource').textContent = safetyStock
                ? '직전 계산 입력값'
                : salesDefaults.recorded_days
                    ? `일별 데모 데이터 ${salesDefaults.recorded_days}일 · ${salesDefaults.window_start} ~ ${salesDefaults.window_end}`
                    : '일별 기록 없음 · 평균은 추정값';
            document.getElementById('exportDetailSales').textContent = `${formatNumber(item.sales_qty)} 개`;
            document.getElementById('exportDetailInventoryValue').textContent = formatCurrency(item.inventory_value);
            document.getElementById('exportDetailDaysToSell').textContent = formatDays(item.days_to_sell);
            document.getElementById('exportDetailDepreciation').textContent = `${formatNumber(item.depreciation_rate)} %`;
            document.getElementById('exportDetailStorage').textContent = formatDays(item.storage_days);
            document.getElementById('exportDetailAnalysisValue').textContent = formatCurrency(item.inventory_value);
            document.getElementById('exportDetailRiskScore').textContent = `${Math.round(Number(item.final_score) || 0)} / 100`;
            document.getElementById('exportDetailRiskGrade').textContent = status;
            document.getElementById('exportDetailRiskScore').className = `text-xl font-extrabold ${statusClass}`;
            document.getElementById('exportDetailRiskGrade').className = `text-xl font-extrabold ${statusClass}`;
            document.getElementById('exportDetailDiscount').textContent = discountMatch ? `${discountMatch[1]}%` : '-';
            document.getElementById('exportDetailRecommendedPrice').textContent = item.recommended_price == null ? '-' : `${formatNumber(item.recommended_price)}원`;
            const diagnosisText = item.ai_diagnosis || item.action_plans || 'AI 진단 결과가 없습니다.';
            document.getElementById('exportDetailDiagnosis').textContent = diagnosisText;
            const diagnosisFallback = item.diagnosis_source === 'rule_based_fallback'
                || diagnosisText.includes('AI 설명을 만들지 못해 서버 분석 기준으로 안내합니다.');
            document.getElementById('exportDiagnosisFallbackActions').classList.toggle('hidden', !diagnosisFallback);
            document.getElementById('exportDetailHistorySales').textContent = formatNumber(item.sales_qty);
        } catch (error) {
            if (activeExportItemId === Number(itemId)) {
                document.getElementById('exportDetailTitle').textContent = error.message || '상품 상세 정보를 불러오지 못했습니다.';
            }
        }
    }

    async function calculateExportSafetyStock(event) {
        event.preventDefault();
        const id = activeExportItemId;
        if (id == null || pendingSafetyStock.has(id)) return;
        const payload = {
            max_daily_sales: Number(document.getElementById('maxDailySales').value),
            average_daily_sales: Number(document.getElementById('averageDailySales').value),
            max_lead_time_days: Number(document.getElementById('maxLeadTime').value),
            average_lead_time_days: Number(document.getElementById('averageLeadTime').value)
        };
        pendingSafetyStock.add(id);
        document.getElementById('calculateSafetyStock').disabled = true;
        document.getElementById('safetyStockStatus').textContent = '계산 중...';
        try {
            const response = await fetch(`/api/inventory/${id}/safety-stock`, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (response.status === 401) {
                window.location.href = 'signin.html';
                return;
            }
            const result = await response.json();
            if (!response.ok) {
                const detail = Array.isArray(result.detail) ? result.detail[0]?.msg : result.detail;
                throw new Error(detail || '권장 수량을 계산하지 못했습니다.');
            }
            safetyStockResults.set(id, result);
            const cell = document.querySelector(`[data-safety-stock-id="${id}"]`);
            if (cell) cell.textContent = `${formatNumber(result.recommended_qty)}개`;
            if (activeExportItemId === id) {
                document.getElementById('exportDetailRecommendedQty').textContent = `${formatNumber(result.recommended_qty)} 개`;
                document.getElementById('safetyStockStatus').textContent = `안전재고 ${formatNumber(result.recommended_qty)}개`;
            }
        } catch (error) {
            if (activeExportItemId === id) document.getElementById('safetyStockStatus').textContent = error.message;
        } finally {
            pendingSafetyStock.delete(id);
            if (activeExportItemId === id) document.getElementById('calculateSafetyStock').disabled = false;
        }
    }

    async function diagnoseExportItem(itemId, button) {
        const id = Number(itemId);
        if (pendingDiagnoses.has(id)) return;
        pendingDiagnoses.add(id);
        const fallbackActions = document.getElementById('exportDiagnosisFallbackActions');
        const retryButton = document.getElementById('retryItemDiagnosisButton');
        fallbackActions.classList.add('hidden');
        retryButton.disabled = true;
        const originalLabel = button.innerHTML;
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        button.textContent = '진단 중...';

        try {
            await openExportItemDetail(id, 'analysis');
            if (activeExportItemId === id) {
                document.getElementById('exportDetailDiagnosis').textContent = 'AI 진단을 생성하는 중입니다.';
            }
            const response = await fetch(`/api/inventory/${id}/ai-diagnose`, {
                method: 'POST',
                credentials: 'include'
            });
            if (response.status === 401) {
                window.location.href = 'signin.html';
                return;
            }
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'AI 진단을 생성하지 못했습니다.');

            const item = loadedItems.find(row => Number(row.item_id) === id);
            if (item) {
                item.ai_diagnosis = result.judgment;
                item.action_plans = result.action_plans;
                item.recommended_price = result.recommended_price;
                item.diagnosis_source = result.diagnosis_detail?.source;
            }
            button.closest('tr').cells[3].textContent = result.recommended_price == null
                ? '-'
                : `${formatNumber(result.recommended_price)}원`;
            inventoryDetailsPromise = undefined;
            if (activeExportItemId === id) {
                await openExportItemDetail(id, 'analysis');
                if (result.diagnosis_detail?.source === 'rule_based_fallback') {
                    document.getElementById('exportDiagnosisFallbackMessage').textContent =
                        'AI 설명을 생성하지 못했습니다. 위험등급·점수·가격은 서버 분석 결과입니다. 잠시 후 다시 요청할 수 있습니다.';
                    fallbackActions.classList.remove('hidden');
                }
            }
        } catch (error) {
            const message = error.message || 'AI 진단을 생성하지 못했습니다.';
            if (activeExportItemId === id) {
                document.getElementById('exportDetailDiagnosis').textContent = message;
                document.getElementById('exportDiagnosisFallbackMessage').textContent =
                    '진단 요청에 실패했습니다. 표시 중인 재고 분석 결과를 확인하고 잠시 후 다시 요청해 주세요.';
                fallbackActions.classList.remove('hidden');
            } else {
                alert(message);
            }
        } finally {
            pendingDiagnoses.delete(id);
            button.disabled = false;
            button.removeAttribute('aria-busy');
            button.innerHTML = originalLabel;
            retryButton.disabled = false;
        }
    }

    function retryCurrentItemDiagnosis() {
        if (activeExportItemId == null) return;
        const itemIndex = loadedItems.findIndex(
            item => Number(item.item_id) === Number(activeExportItemId),
        );
        if (itemIndex < 0) return;
        const checkbox = document.querySelector(`.item-checkbox[data-index="${itemIndex}"]`);
        const trigger = checkbox?.closest('tr')?.querySelector('td:last-child button');
        if (trigger) diagnoseExportItem(activeExportItemId, trigger);
    }

    function closeExportItemDetail() {
        activeExportItemId = null;
        const modal = document.getElementById('exportDetailModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }

    // DOM 완성 후 안전하게 데이터 수신
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadExportData);
    } else {
        loadExportData();
    }

    // 전체 선택/해제 기능
    function toggleSelectAll(selectAllCheckbox) {
        const checkboxes = document.querySelectorAll('.item-checkbox');
        checkboxes.forEach(cb => cb.checked = selectAllCheckbox.checked);
    }

    function createSellSetupField(labelText, type, value, fieldName, options = {}) {
        const label = document.createElement('label');
        label.className = 'sell-setup-field';
        label.textContent = labelText;

        const control = type === 'textarea'
            ? document.createElement('textarea')
            : document.createElement('input');
        if (type !== 'textarea') control.type = type;
        control.className = 'sell-setup-input';
        control.dataset.field = fieldName;
        control.value = value;
        if (options.min !== undefined) control.min = String(options.min);
        if (options.max !== undefined) control.max = String(options.max);
        if (options.step !== undefined) control.step = String(options.step);
        if (options.maxLength !== undefined) control.maxLength = options.maxLength;
        if (options.required) control.required = true;
        if (options.rows) control.rows = options.rows;
        label.append(control);
        return { label, control };
    }

    function renderSellSetupItems(items) {
        const container = document.getElementById('sellListingItems');
        container.replaceChildren();

        items.forEach(item => {
            const itemId = Number(item.item_id || item.id);
            const availableQuantity = Math.max(0, Number(item.stock_qty || 0));
            const defaultPrice = Number(item.recommended_price || item.mock_market_price || item.selling_price || 0);
            const card = document.createElement('article');
            card.className = 'sell-setup-item';
            card.dataset.itemId = String(itemId);

            const heading = document.createElement('h3');
            heading.className = 'sell-setup-item-title';
            heading.textContent = item.product_name || '이름 없는 품목';

            const layout = document.createElement('div');
            layout.className = 'sell-setup-item-layout';
            const fields = document.createElement('div');
            fields.className = 'sell-setup-fields';

            const titleField = createSellSetupField('게시 제목', 'text', item.listing_title || item.product_name || '', 'title', { maxLength: 100, required: true });
            const priceField = createSellSetupField('판매 가격 (원)', 'number', String(item.listing_price ?? defaultPrice), 'price', { min: 1, step: 1, required: true });
            const quantityField = createSellSetupField('판매 수량 (개)', 'number', String(item.listing_quantity ?? availableQuantity), 'quantity', { min: 1, max: availableQuantity, step: 1, required: true });
            const descriptionField = createSellSetupField('상품 설명', 'textarea', item.listing_description || '', 'description', { maxLength: 500, rows: 3 });
            const photoField = createSellSetupField('상품 사진', 'file', '', 'photo');
            photoField.control.accept = 'image/jpeg,image/png,image/webp';

            const preview = document.createElement('div');
            preview.className = 'sell-setup-photo-preview';
            const previewImage = document.createElement('img');
            previewImage.alt = '';
            previewImage.hidden = true;
            const previewPlaceholder = document.createElement('span');
            previewPlaceholder.innerHTML = '<i class="fa-regular fa-image" aria-hidden="true"></i><span>사진 미리보기</span>';
            preview.append(previewImage, previewPlaceholder);
            photoField.control.addEventListener('change', () => {
                const file = photoField.control.files?.[0];
                if (!file) return;
                previewImage.src = URL.createObjectURL(file);
                previewImage.hidden = false;
                previewPlaceholder.hidden = true;
            });

            fields.append(titleField.label, priceField.label, quantityField.label, descriptionField.label, photoField.label);
            layout.append(fields, preview);
            card.append(heading, layout);
            container.append(card);
        });
    }

    function openSellSetup() {
        const selectedCheckboxes = document.querySelectorAll('.item-checkbox:checked');
        if (selectedCheckboxes.length === 0) {
            alert('판매할 제품을 하나 이상 선택해 주세요.');
            return;
        }

        pendingSellItems = Array.from(selectedCheckboxes).map(cb => {
            const idx = cb.getAttribute('data-index');
            return loadedItems[idx];
        });
        renderSellSetupItems(pendingSellItems);
        document.getElementById('sellSetupStatus').textContent = '';
        const modal = document.getElementById('sellSetupModal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        document.body.style.overflow = 'hidden';
        document.querySelector('#sellListingItems [data-field="title"]')?.focus();
    }

    function closeSellSetup() {
        const button = document.getElementById('publishSellItemsButton');
        if (button.disabled) return;
        const modal = document.getElementById('sellSetupModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.body.style.overflow = '';
        pendingSellItems = [];
    }

    function readCompressedSellImage(file) {
        if (!file) return Promise.resolve('');
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(new Error('사진 파일을 읽지 못했습니다.'));
            reader.onload = () => {
                const image = new Image();
                image.onerror = () => reject(new Error('지원하지 않는 이미지 파일입니다.'));
                image.onload = () => {
                    const canvas = document.createElement('canvas');
                    let maxDimension = 800;
                    let quality = 0.68;
                    let compressedImage = '';
                    for (let attempt = 0; attempt < 4; attempt += 1) {
                        const scale = Math.min(1, maxDimension / Math.max(image.width, image.height));
                        canvas.width = Math.max(1, Math.round(image.width * scale));
                        canvas.height = Math.max(1, Math.round(image.height * scale));
                        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
                        compressedImage = canvas.toDataURL('image/jpeg', quality);
                        if (compressedImage.length <= 160000) break;
                        maxDimension *= 0.8;
                        quality *= 0.9;
                    }
                    resolve(compressedImage);
                };
                image.src = reader.result;
            };
            reader.readAsDataURL(file);
        });
    }

    async function publishSellItems() {
        const button = document.getElementById('publishSellItemsButton');
        const status = document.getElementById('sellSetupStatus');
        const cards = Array.from(document.querySelectorAll('.sell-setup-item'));
        const configuredItems = [];

        for (const card of cards) {
            const item = pendingSellItems.find(row => Number(row.item_id || row.id) === Number(card.dataset.itemId));
            const titleInput = card.querySelector('[data-field="title"]');
            const priceInput = card.querySelector('[data-field="price"]');
            const quantityInput = card.querySelector('[data-field="quantity"]');
            const title = titleInput.value.trim();
            const price = Number(priceInput.value);
            const quantity = Number(quantityInput.value);
            const availableQuantity = Number(item?.stock_qty || 0);

            if (!title) {
                titleInput.focus();
                status.textContent = '게시 제목을 입력해 주세요.';
                return;
            }
            if (!Number.isInteger(price) || price < 1) {
                priceInput.focus();
                status.textContent = '판매 가격을 1원 이상 입력해 주세요.';
                return;
            }
            if (!Number.isInteger(quantity) || quantity < 1 || quantity > availableQuantity) {
                quantityInput.focus();
                status.textContent = `판매 수량은 보유 수량 ${availableQuantity.toLocaleString('ko-KR')}개 이내로 입력해 주세요.`;
                return;
            }

            configuredItems.push({
                ...item,
                listing_title: title,
                listing_price: price,
                listing_quantity: quantity,
                listing_description: card.querySelector('[data-field="description"]').value.trim(),
                listing_image: ''
            });
        }

        button.disabled = true;
        status.textContent = '사진을 준비하고 판매 상품을 등록하고 있습니다.';
        const previousListings = localStorage.getItem('selectedSellItems');
        let listingsSaved = false;

        try {
            for (let index = 0; index < cards.length; index += 1) {
                const file = cards[index].querySelector('[data-field="photo"]').files?.[0];
                configuredItems[index].listing_image = await readCompressedSellImage(file);
            }
            localStorage.setItem('selectedSellItems', JSON.stringify(configuredItems));
            listingsSaved = true;

            const response = await fetch('/api/inventory/selling', {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    item_ids: configuredItems.map(item => item.item_id || item.id),
                    is_selling: true
                })
            });
            if (response.status === 401) {
                if (previousListings === null) localStorage.removeItem('selectedSellItems');
                else localStorage.setItem('selectedSellItems', previousListings);
                window.location.href = 'signin.html';
                return;
            }
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || '판매 상품 등록에 실패했습니다.');

            window.location.href = 'sellpage/Sellpage.html';
        } catch (error) {
            if (listingsSaved) {
                if (previousListings === null) localStorage.removeItem('selectedSellItems');
                else localStorage.setItem('selectedSellItems', previousListings);
            }
            status.textContent = error.name === 'QuotaExceededError'
                ? '사진 저장 공간이 부족합니다. 사진 크기를 줄이거나 선택 상품을 나눠 등록해 주세요.'
                : error.message || '판매 상품 등록에 실패했습니다.';
            button.disabled = false;
        }
    }

    function goToSellPage() {
        openSellSetup();
    }
