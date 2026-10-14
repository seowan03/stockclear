function switchTab(tabName) {
      // 탭 컨텐츠 숨기기/보이기
      document.getElementById('tabContentDetail').classList.add('hidden');
      document.getElementById('tabContentAnalysis').classList.add('hidden');
      document.getElementById('tabContentHistory').classList.add('hidden');

      // 탭 버튼 스타일 초기화
      const tabs = ['Detail', 'Analysis', 'History'];
      tabs.forEach(tab => {
        const btn = document.getElementById(`tabBtn${tab}`);
        btn.className = "pb-3 text-gray-400 hover:text-white transition-colors";
      });

      // 선택된 탭 활성화
      if (tabName === 'detail') {
        document.getElementById('tabContentDetail').classList.remove('hidden');
        document.getElementById('tabBtnDetail').className = "pb-3 border-b-2 border-blue-500 text-blue-400 font-bold";
      } else if (tabName === 'analysis') {
        document.getElementById('tabContentAnalysis').classList.remove('hidden');
        document.getElementById('tabBtnAnalysis').className = "pb-3 border-b-2 border-blue-500 text-blue-400 font-bold";
      } else if (tabName === 'history') {
        document.getElementById('tabContentHistory').classList.remove('hidden');
        document.getElementById('tabBtnHistory').className = "pb-3 border-b-2 border-blue-500 text-blue-400 font-bold";
      }
    }


    let inventoryData = [];
    let selectedInventoryId = null;
    const currentUploadId = new URLSearchParams(window.location.search).get('upload_id');
    const today = new Date();
    const DAILY_METRIC_END_DATE = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    const HISTORY_WEEKDAYS = ['일요일', '월요일', '화요일', '수요일', '목요일', '금요일', '토요일'];
    let dailyMetricsByItemId = new Map();
    let dailyMetricsRequestId = 0;
    let inventoryDataLoaded = false;
    let gridPage = 0;
    const gridPageSize = 50;
    let gridSortField = null;
    let gridSortDirection = 1;
    const riskSortOrder = { '정상': 0, '주의': 1, '장기': 2, '악성': 3 };
    const pendingEdits = new Map();
    let savingEdits = false;
    const editableFields = ['product_name', 'stock_qty', 'purchase_price', 'selling_price', 'received_date', 'sales_qty'];
    const editFieldLabels = {
      product_name: '품목명', stock_qty: '기준 수량', purchase_price: '원가',
      selling_price: '기준 판매가', received_date: '입고일', sales_qty: '판매량'
    };

    function showGridValidationError(detail, items) {
      const issue = Array.isArray(detail) ? detail[0] : null;
      const index = issue?.loc?.[2];
      const field = issue?.loc?.[3];
      const item = Number.isInteger(index) ? items[index] : null;
      if (!item || !Object.hasOwn(editFieldLabels, field)) {
        updateEditStatus('입력값을 확인해 주세요.');
        return;
      }
      updateEditStatus(`품목 ${item.item_id} · ${editFieldLabels[field]}: 입력값을 확인해 주세요.`);
      const input = [...document.querySelectorAll('#inventoryBody input[data-field]')]
        .find((cell) => Number(cell.dataset.id) === item.item_id && cell.dataset.field === field);
      if (input) {
        input.classList.add('border-red-400');
        input.focus();
      }
    }

    function originalCellValue(item, field) {
      return String({
        product_name: item.name, stock_qty: item.currentQty,
        purchase_price: item.purchasePriceValue, selling_price: item.sellingPriceValue,
        received_date: item.date, sales_qty: item.salesQty
      }[field] ?? '');
    }

    function updateEditStatus(message) {
      const count = pendingEdits.size;
      document.getElementById('editStatus').textContent = message || (count ? `${count}개 품목 수정 중` : '');
      document.getElementById('saveEdits').disabled = !count || savingEdits;
      document.getElementById('discardEdits').disabled = !count || savingEdits;
    }

    function editCell(input) {
      if (savingEdits) return;
      const id = Number(input.dataset.id);
      const field = input.dataset.field;
      const item = inventoryData.find((row) => row.id === id);
      if (!item) return;
      const values = { ...pendingEdits.get(id), [field]: input.value };
      if (input.value === originalCellValue(item, field)) delete values[field];
      if (Object.keys(values).length) pendingEdits.set(id, values);
      else pendingEdits.delete(id);
      input.classList.toggle('bg-blue-950/60', Object.hasOwn(values, field));
      input.classList.toggle('ring-1', Object.hasOwn(values, field));
      input.classList.remove('border-red-400');
      updateEditStatus();
    }

    function navigateGrid(event) {
      if (event.key !== 'Enter' && event.key !== 'Tab') return;
      if (event.key === 'Enter') event.preventDefault();
      const inputs = [...document.querySelectorAll('#inventoryBody input[data-field]')].filter((input) => input.closest('tr').style.display !== 'none');
      const next = inputs[inputs.indexOf(event.target) + (event.shiftKey ? -1 : 1)];
      if (next) {
        if (event.key === 'Tab') event.preventDefault();
        next.focus();
        if (next.type === 'text') next.select();
      }
    }

    function discardGridEdits() {
      if (savingEdits) return;
      pendingEdits.clear();
      renderTable();
      updateEditStatus();
    }

    function changeGridPage(direction) {
      gridPage += direction;
      renderTable();
    }

    function sortGrid(field) {
      gridSortDirection = gridSortField === field ? -gridSortDirection : 1;
      gridSortField = field;
      document.getElementById('statusSortHeader').setAttribute('aria-sort', field === 'status' ? (gridSortDirection === 1 ? 'ascending' : 'descending') : 'none');
      gridPage = 0;
      renderTable();
    }

    async function saveGridEdits() {
      if (!pendingEdits.size || savingEdits) return;
      savingEdits = true;
      updateEditStatus('저장 중...');
      document.querySelectorAll('#inventoryBody input[data-field]').forEach((input) => { input.disabled = true; });
      try {
        const items = [...pendingEdits].map(([id, changes]) => {
          const original = inventoryData.find((row) => row.id === id);
          const values = Object.fromEntries(editableFields.map((field) => [field, changes[field] ?? originalCellValue(original, field)]));
          for (const field of ['stock_qty', 'purchase_price', 'selling_price', 'sales_qty']) {
            if (values[field] === '') throw new Error(`품목 ${id} · ${editFieldLabels[field]}: 값을 입력해 주세요.`);
            values[field] = Number(values[field]);
          }
          return { item_id: id, version: original.version, ...values };
        });
        const response = await fetch('/api/inventory/batch', {
          method: 'PATCH', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ items })
        });
        if (response.status === 401) return window.location.href = 'signin.html';
        if (!response.ok) {
          const error = await response.json();
          if (response.status === 422 && Array.isArray(error.detail)) {
            showGridValidationError(error.detail, items);
            return;
          }
          throw new Error(typeof error.detail === 'string' ? error.detail : '입력값을 확인해 주세요.');
        }
        pendingEdits.clear();
        await loadInventoryData();
        updateEditStatus('저장했습니다.');
      } catch (error) {
        updateEditStatus(error.message || '저장하지 못했습니다.');
      } finally {
        savingEdits = false;
        document.querySelectorAll('#inventoryBody input[data-field]').forEach((input) => { input.disabled = false; });
        document.getElementById('saveEdits').disabled = !pendingEdits.size;
        document.getElementById('discardEdits').disabled = !pendingEdits.size;
      }
    }

    window.addEventListener('beforeunload', (event) => {
      if (pendingEdits.size) event.preventDefault();
    });

    const { escapeHtml, formatRecommendationText } = StockClear;

    function formatRecommendationDiscount(actionPlans) {
      const value = String(actionPlans || '');
      const match = value.match(/(\d+(?:\.\d+)?)%\s*할인|할인율\s*(\d+(?:\.\d+)?)%/);
      if (match) return `${match[1] || match[2]}%`;
      return value.includes('할인 불필요') ? '0%' : '-';
    }

    function getRiskStyles(status) {
      return {
        text: StockClear.statusClass(status),
        badge: {
          '정상': 'bg-emerald-500/10 border border-emerald-500/20',
          '주의': 'bg-amber-500/10 border border-amber-500/20',
          '장기': 'bg-orange-500/10 border border-orange-500/20',
          '악성': 'bg-red-500/10 border border-red-500/20'
        }[status] || 'bg-gray-800/70 border border-gray-700'
      };
    }

    function needsReorder(item, dailyMetric) {
      if (dailyMetric?.remaining_stock_qty == null) return false;

      const currentQty = StockClear.number(dailyMetric.remaining_stock_qty);
      if (item.recommendedQty != null) return currentQty <= item.recommendedQty;

      return Number(dailyMetric.weekly_sales_recorded_days) === 7
        && currentQty <= StockClear.number(dailyMetric.weekly_sales_qty);
    }

    function setInventoryData(sourceInventory) {
      inventoryData = sourceInventory.map((item) => {
      const statusText = StockClear.riskCategory(item);
      return {
        id: Number(item.item_id),
        internalCode: String(item.item_id),
        name: item.product_name || '이름 없음',
        category: '-',
        currentQty: StockClear.number(item.stock_qty),
        recommendedQty: item.recommended_qty == null ? null : StockClear.number(item.recommended_qty),
        version: item.version,
        purchasePriceValue: StockClear.number(item.purchase_price),
        purchasePrice: `${StockClear.formatNumber(item.purchase_price)} 원`,
        sellingPrice: `${StockClear.formatNumber(item.selling_price)} 원`,
        sellingPriceValue: StockClear.number(item.selling_price),
        category: statusText,
        statusText,
        icon: 'fa-box-open',
        date: item.received_date || '-',
        salesQty: StockClear.number(item.sales_qty),
        inventoryValue: StockClear.number(item.inventory_value),
        finalScore: StockClear.number(item.final_score),
        aiDiagnosis: formatRecommendationText(item.ai_diagnosis || ''),
        actionPlans: formatRecommendationText(item.action_plans || ''),
        origPrice: `${StockClear.formatNumber(item.purchase_price)} 원`,
        currPrice: item.mock_market_price == null
          ? '-'
          : `${StockClear.formatNumber(item.mock_market_price)} 원`,
        exhaust: `${StockClear.formatNumber(item.days_to_sell)} 일`,
        depreciation: `${StockClear.number(item.depreciation_rate).toFixed(1)} %`,
        storage: `${StockClear.formatNumber(item.storage_days)} 일`,
        ratio: '-',
        riskScore: `${Math.round(StockClear.number(item.final_score))} / 100`,
        riskGrade: statusText,
        recDiscount: formatRecommendationDiscount(item.action_plans),
        recPrice: item.recommended_price == null
          ? '-'
          : `${StockClear.formatNumber(item.recommended_price)}원`
      };
      });
    }

    function formatDateInputValue(year, month, day) {
      return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    }

    function addDaysToDateInputValue(value, days) {
      const [year, month, day] = value.split('-').map(Number);
      const date = new Date(year, month - 1, day + days);
      return formatDateInputValue(date.getFullYear(), date.getMonth() + 1, date.getDate());
    }

    function updateHistoryDateLabel() {
      const datePicker = document.getElementById('historyDatePicker');
      const selectedDate = datePicker.value;
      if (!selectedDate) return;

      const [year, month, day] = selectedDate.split('-').map(Number);
      const weekday = HISTORY_WEEKDAYS[new Date(year, month - 1, day).getDay()];
      document.getElementById('historyDateLabel').textContent = `${year}. ${String(month).padStart(2, '0')}. ${String(day).padStart(2, '0')}.`;
      document.getElementById('historyWeekday').textContent = weekday;
    }

    function updateHistoryDateRange(archiveBefore) {
      const datePicker = document.getElementById('historyDatePicker');
      const inboundDates = inventoryData
        .map((item) => item.date)
        .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value || ''))
        .sort();

      const firstDate = inboundDates.length ? addDaysToDateInputValue(inboundDates[0], 1) : null;
      const dailyStart = firstDate && firstDate > archiveBefore ? firstDate : archiveBefore;
      if (!firstDate || dailyStart > DAILY_METRIC_END_DATE) {
        datePicker.disabled = true;
        datePicker.value = '';
        document.getElementById('historyDateLabel').textContent = '-';
        document.getElementById('historyWeekday').textContent = '';
        document.getElementById('dailyDataStatus').textContent = '조회 가능한 일별 데이터가 없습니다.';
        return;
      }

      datePicker.disabled = false;
      datePicker.min = dailyStart;
      datePicker.max = DAILY_METRIC_END_DATE;
      if (!datePicker.value || datePicker.value < datePicker.min || datePicker.value > datePicker.max) {
        datePicker.value = datePicker.max;
      }
      updateHistoryDateLabel();
    }

    function updateHistoryDate() {
      updateHistoryDateLabel();
      if (inventoryDataLoaded) {
        dailyMetricsByItemId = new Map();
        document.getElementById('dailyDataStatus').textContent = '일별 데이터 조회 중...';
        renderTable();
        loadDailyInventoryData();
      }
    }

    function openHistoryDatePicker() {
      const datePicker = document.getElementById('historyDatePicker');
      if (typeof datePicker.showPicker === 'function') {
        datePicker.showPicker();
      } else {
        datePicker.focus();
        datePicker.click();
      }
    }

    async function loadDailyInventoryData() {
      const requestId = ++dailyMetricsRequestId;
      const selectedDate = document.getElementById('historyDatePicker').value;
      const status = document.getElementById('dailyDataStatus');
        if (!selectedDate) {
          dailyMetricsByItemId = new Map();
          status.textContent = '조회 가능한 날짜 데이터가 없습니다.';
          renderTable();
          return;
        }
      const params = new URLSearchParams({ business_date: selectedDate });
      if (currentUploadId) params.set('upload_id', currentUploadId);

      try {
        const response = await fetch(`/api/inventory/daily?${params.toString()}`, { credentials: 'include' });
        if (requestId !== dailyMetricsRequestId) return;
        if (response.status === 401) {
          window.location.href = 'signin.html';
          return;
        }
        if (!response.ok) throw new Error('일별 데이터를 불러오지 못했습니다.');

        const payload = await response.json();
        if (requestId !== dailyMetricsRequestId) return;
        const items = Array.isArray(payload.items) ? payload.items : [];
        dailyMetricsByItemId = new Map(items.map((item) => [Number(item.item_id), item]));
        status.textContent = items.length
          ? `${items.length}개 품목의 저장된 일별 데이터`
          : '선택한 날짜의 일별 데이터가 없습니다.';
        renderTable();
      } catch (error) {
        if (requestId !== dailyMetricsRequestId) return;
        dailyMetricsByItemId = new Map();
        status.textContent = error.message || '일별 데이터를 불러오지 못했습니다.';
        renderTable();
      }
    }

    function renderTable() {
      const tbody = document.getElementById('inventoryBody');
      const active = document.activeElement;
      const focusedCell = active?.dataset?.field ? { id: active.dataset.id, field: active.dataset.field, start: active.selectionStart } : null;
      tbody.innerHTML = '';
      const search = document.getElementById('searchInput').value.trim().toLowerCase();
      const status = document.getElementById('statusFilter').value;
      const visibleItems = inventoryData.filter((item) =>
        (item.internalCode.toLowerCase().includes(search) || (pendingEdits.get(item.id)?.product_name ?? item.name).toLowerCase().includes(search)) &&
        (status === 'ALL' || item.category === status)
      );
      if (gridSortField) visibleItems.sort((left, right) => {
        if (gridSortField === 'status') {
          return gridSortDirection * ((riskSortOrder[left.category] ?? 4) - (riskSortOrder[right.category] ?? 4));
        }
        const leftValue = gridSortField === 'id' ? left.id : pendingEdits.get(left.id)?.[gridSortField] ?? originalCellValue(left, gridSortField);
        const rightValue = gridSortField === 'id' ? right.id : pendingEdits.get(right.id)?.[gridSortField] ?? originalCellValue(right, gridSortField);
        const numeric = ['id', 'stock_qty', 'purchase_price', 'selling_price', 'sales_qty'].includes(gridSortField);
        return gridSortDirection * (numeric ? Number(leftValue) - Number(rightValue) : String(leftValue).localeCompare(String(rightValue), 'ko'));
      });
      const pages = Math.max(1, Math.ceil(visibleItems.length / gridPageSize));
      gridPage = Math.min(gridPage, pages - 1);
      document.getElementById('gridPageLabel').textContent = `${visibleItems.length}개 · ${gridPage + 1}/${pages} 페이지`;
      document.getElementById('previousGridPage').disabled = gridPage === 0;
      document.getElementById('nextGridPage').disabled = gridPage + 1 === pages;

      if (visibleItems.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="py-8 text-center text-gray-400">${inventoryData.length ? '검색 결과가 없습니다.' : '등록된 재고 데이터가 없습니다.'}</td></tr>`;
      } else visibleItems.slice(gridPage * gridPageSize, (gridPage + 1) * gridPageSize).forEach((item) => {
        const riskStyles = getRiskStyles(item.category);
        const qtyClass = `${riskStyles.text} font-semibold`;
        const dailyMetric = dailyMetricsByItemId.get(item.id);
        const currentQty = dailyMetric?.remaining_stock_qty == null
          ? item.currentQty
          : StockClear.number(dailyMetric.remaining_stock_qty);
        const outOfStock = currentQty <= 0;
        const reorderNeeded = !outOfStock && needsReorder(item, dailyMetric);

        const tr = document.createElement('tr');
        tr.className = 'hover:bg-gray-800/30 transition-colors';
        tr.setAttribute('data-id', item.id);
        const cell = (field, type, width) => {
          const value = pendingEdits.get(item.id)?.[field] ?? originalCellValue(item, field);
          const changed = Object.hasOwn(pendingEdits.get(item.id) || {}, field);
          const step = ['stock_qty', 'sales_qty'].includes(field) ? '1' : '0.01';
          return `<input data-id="${item.id}" data-field="${field}" type="${type}" ${type === 'number' ? `min="0" step="${step}"` : ''} ${field === 'received_date' ? 'inputmode="numeric" placeholder="YYYY-MM-DD" maxlength="10"' : ''} ${savingEdits ? 'disabled' : ''} value="${escapeHtml(value)}" oninput="editCell(this)" onkeydown="navigateGrid(event)" aria-label="${escapeHtml(item.name)} ${field}" class="${width} max-w-full rounded-sm border border-transparent px-2 py-1.5 text-sm text-gray-100 outline-none focus:border-blue-400 focus:bg-gray-800 ${changed ? 'bg-blue-950/60 ring-1 ring-blue-600' : 'bg-transparent'}">`;
        };
        tr.innerHTML = `
          <td class="sticky left-0 z-10 bg-gray-900 py-2 px-3 font-mono font-medium">
            <button onclick="openDetailModal(${item.id})" class="text-blue-400 hover:text-blue-300 hover:underline text-left">${item.internalCode}</button>
          </td>
          <td class="py-2 px-2">${cell('product_name', 'text', 'w-48')}</td>
          <td class="py-2 px-3 ${qtyClass} whitespace-nowrap">${item.recommendedQty == null ? '-' : `${StockClear.formatNumber(item.recommendedQty)} 개`}</td>
          <td class="py-2 px-3 font-semibold text-gray-100 whitespace-nowrap">${StockClear.formatNumber(currentQty)} 개</td>
          <td class="py-2 px-3 text-gray-300 whitespace-nowrap">${dailyMetric?.daily_selling_price == null ? item.sellingPrice : `${StockClear.formatNumber(dailyMetric.daily_selling_price)} 원`}</td>
          <td class="py-2 px-2">${cell('received_date', 'text', 'w-36')}</td>
          <td class="py-2 px-3 text-gray-300 whitespace-nowrap">${dailyMetric ? `${StockClear.formatNumber(dailyMetric.daily_sales_qty)} 개` : '-'}</td>
          <td class="py-2 px-3">
            ${outOfStock
              ? '<span class="inline-block rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-xs font-semibold text-amber-300">발주 필요</span>'
              : `<span class="inline-block px-2.5 py-1 text-xs font-semibold rounded-full ${riskStyles.badge} ${riskStyles.text}">${escapeHtml(item.statusText)}</span>${reorderNeeded ? '<span class="ml-1 inline-block rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-semibold text-amber-300">발주 필요</span>' : ''}`}
          </td>
          <td class="py-2 px-3 text-right whitespace-nowrap space-x-2">
            <button class="p-2 text-gray-400 hover:text-red-400 transition-colors" onclick="deleteInventoryItem(${item.id})" title="삭제">
              <i class="fa-solid fa-trash-can"></i>
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      if (focusedCell) {
        const input = [...tbody.querySelectorAll('input[data-field]')].find((candidate) => candidate.dataset.id === focusedCell.id && candidate.dataset.field === focusedCell.field);
        if (input) {
          input.focus();
          if (input.type === 'text' && focusedCell.start != null) input.setSelectionRange(focusedCell.start, focusedCell.start);
        }
      }
    }

    function openDetailModal(id) {
      const item = inventoryData.find(i => i.id === id);
      if (!item) return;

      document.getElementById('modalItemTitle').innerText = item.name;
      document.getElementById('modalItemBadge').innerText = item.statusText;
      
      const riskStyles = getRiskStyles(item.category);
      const badge = document.getElementById('modalItemBadge');
      badge.className = `px-3 py-1 text-xs font-semibold rounded-full ${riskStyles.badge} ${riskStyles.text}`;

      document.getElementById('modalItemIcon').className = `fa-solid ${item.icon || 'fa-box-open'} text-6xl text-gray-700`;
      document.getElementById('modalItemCode').innerText = item.internalCode;
      document.getElementById('modalDate').innerText = item.date || '-';
      document.getElementById('modalOrigPrice').innerText = item.origPrice || '-';
      document.getElementById('modalCurrPrice').innerText = item.currPrice || '-';
      document.getElementById('detailStockQty').innerText = `${StockClear.formatNumber(item.currentQty)} 개`;
      document.getElementById('detailSalesQty').innerText = `${StockClear.formatNumber(item.salesQty)} 개`;
      document.getElementById('detailInventoryValue').innerText = `₩ ${StockClear.formatNumber(item.inventoryValue)}`;
      document.getElementById('historySalesQty').innerText = StockClear.formatNumber(item.salesQty);

      const dailyMetric = dailyMetricsByItemId.get(item.id);
      const dateBasedDaysToSell = dailyMetric?.days_to_sell_on_date;
      document.getElementById('valExhaust').innerText = dateBasedDaysToSell == null
        ? '산출 불가'
        : `${StockClear.formatNumber(dateBasedDaysToSell)} 일`;
      document.getElementById('valDepreciation').innerText = item.depreciation || '-';
      document.getElementById('valStorage').innerText = item.storage || '-';
      document.getElementById('valRatio').innerText = `₩ ${StockClear.formatNumber(item.inventoryValue)}`;

      document.getElementById('finalRiskScore').innerText = item.riskScore || '-';
      document.getElementById('finalRiskGrade').innerText = item.riskGrade || item.statusText;
      document.getElementById('finalRiskScore').className = `text-xl font-extrabold ${riskStyles.text}`;
      document.getElementById('finalRiskGrade').className = `text-xl font-extrabold ${riskStyles.text}`;

      document.getElementById('recDiscount').innerText = item.recDiscount || '-';
      document.getElementById('recPrice').innerText = item.recPrice || '-';
      document.getElementById('aiDiagnosis').innerText = item.aiDiagnosis || 'AI 진단 결과가 없습니다.';
      selectedInventoryId = item.id;

      const modal = document.getElementById('detailModal');
      modal.classList.remove('hidden');
      modal.classList.add('flex');
    }

    function closeDetailModal() {
      const modal = document.getElementById('detailModal');
      modal.classList.remove('flex');
      modal.classList.add('hidden');
    }

    async function deleteInventoryItem(id) {
      if (savingEdits) return;
      if (pendingEdits.size && !confirm('저장하지 않은 변경을 취소하고 삭제하시겠습니까?')) return;
      if (!confirm('재고를 삭제하면 되돌릴 수 없습니다. 삭제하시겠습니까?')) return;
      try {
        const response = await fetch(`/api/inventory/${id}`, { method: 'DELETE', credentials: 'include' });
        if (response.status === 401) return window.location.href = 'signin.html';
        if (!response.ok) return alert('재고를 삭제하지 못했습니다.');

        pendingEdits.clear();
        await loadInventoryData();
        updateEditStatus();
      } catch (error) {
        alert(error.message || '재고를 삭제하지 못했습니다.');
      }
    }

    // 검색 및 필터링
    function filterItems() {
      gridPage = 0;
      renderTable();
    }

    async function loadInventoryData() {
      const tbody = document.getElementById('inventoryBody');
      tbody.innerHTML = '<tr><td colspan="9" class="py-8 text-center text-gray-400">재고 데이터를 불러오는 중...</td></tr>';
      try {
        const inventoryUrl = currentUploadId
          ? `/api/inventory?upload_id=${encodeURIComponent(currentUploadId)}`
          : '/api/inventory';
        const response = await fetch(inventoryUrl, { credentials: 'include' });
        if (response.status === 401) {
          window.location.href = 'signin.html';
          return;
        }
        if (!response.ok) {
          let detail = '';
          try {
            const errorPayload = await response.json();
            detail = typeof errorPayload.detail === 'string' ? errorPayload.detail : '';
          } catch (error) {
            // The server may return a non-JSON error response.
          }
          const message = detail || `재고 데이터를 불러오지 못했습니다. (HTTP ${response.status})`;
          throw new Error(message);
        }
        const payload = await response.json();
        setInventoryData(Array.isArray(payload.items) ? payload.items : []);
        updateHistoryDateRange(payload.daily_window_start);
        inventoryDataLoaded = true;
        if (currentUploadId) {
          document.getElementById('inventoryTitle').textContent = payload.upload_file_name
            ? `${payload.upload_file_name} 재고`
            : '선택한 업로드 파일의 재고';
          document.getElementById('allInventoryLink').classList.remove('hidden');
        }
        if (!inventoryData.length) {
          dailyMetricsByItemId = new Map();
          document.getElementById('dailyDataStatus').textContent = '등록된 재고 데이터가 없습니다.';
          renderTable();
          return;
        }
        await loadDailyInventoryData();
      } catch (error) {
        console.error('재고 데이터 로딩 실패:', error);
        if (currentUploadId) {
          document.getElementById('allInventoryLink').classList.remove('hidden');
        }
        tbody.innerHTML = `<tr><td colspan="9" class="py-8 text-center text-rose-400">${escapeHtml(error.message || '재고 데이터를 불러오지 못했습니다.')}</td></tr>`;
      }
    }

    updateHistoryDate();
    loadInventoryData();
