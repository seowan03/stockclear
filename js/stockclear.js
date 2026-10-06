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

  // riskCategory와 classify 지원
  function riskCategory(item) {
    const status = String(item.risk_grade ?? item.status ?? '');
    if (status === '위험' || status === '처분 권장' || status === '위험 재고') return '위험 재고';
    if (status === '주의' || status === '주의 재고') return '주의 재고';
    if (status === '장기 체류' || status === '장기 재고' || number(item.storage_days ?? item.aging_days) >= 60) return '장기 재고';
    
    // 조건 수치 기반 처리
    const storageDays = number(item.storage_days);
    const stockQty = number(item.stock_qty);
    const salesSpeed = number(item.sales_speed);

    if (stockQty <= 0) return '악성';
    if (storageDays >= 60 || (salesSpeed === 0 && storageDays > 30)) return '장기';
    if (storageDays >= 30) return '주의';
    return '정상';
  }

  function statusClass(status) {
    return {
      '정상': 'text-emerald-400',
      '주의': 'text-yellow-400',
      '장기': 'text-orange-400',
      '악성': 'text-red-400'
    }[status] || 'text-gray-400';
  }

  function formatNumber(value) {
    return new Intl.NumberFormat('ko-KR').format(Math.round(number(value)));
  }

  // window 객체에 모두 포함
  window.StockClear = { 
    getInventory, 
    number, 
    classify: riskCategory, 
    riskCategory, 
    statusClass, 
    formatNumber 
  };
})();