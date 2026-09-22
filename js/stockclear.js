(() => {
  const STORAGE_KEY = 'stockclearInventory';

  function getInventory() {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      return Array.isArray(value) ? value : [];
    } catch (error) {
      console.error('재고 데이터 읽기 실패:', error);
      return [];
    }
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function classify(item) {
    const storageDays = number(item.storage_days);
    const stockQty = number(item.stock_qty);
    const salesSpeed = number(item.sales_speed);

    if (stockQty <= 0) return '처분 권장';
    if (storageDays >= 60 || (salesSpeed === 0 && storageDays > 30)) return '장기 체류';
    if (storageDays >= 30) return '주의';
    return '정상';
  }

  function statusClass(status) {
    return {
      '정상': 'text-emerald-400',
      '주의': 'text-yellow-400',
      '장기 체류': 'text-orange-400',
      '처분 권장': 'text-red-400'
    }[status] || 'text-gray-400';
  }

  function formatNumber(value) {
    return new Intl.NumberFormat('ko-KR').format(Math.round(number(value)));
  }

  window.StockClear = { getInventory, number, classify, statusClass, formatNumber };
})();