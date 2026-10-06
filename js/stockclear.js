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
    if (['정상', '주의', '장기', '악성'].includes(status)) return status;

    const score = Number(item.final_score);
    if (Number.isFinite(score) && item.final_score != null) {
      if (score >= 70) return '악성';
      if (score >= 45) return '장기';
      if (score >= 25) return '주의';
      return '정상';
    }

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
      '정상': 'grade-normal',
      '정상 재고': 'grade-normal',
      '주의': 'grade-caution',
      '주의 재고': 'grade-caution',
      '장기': 'grade-aging',
      '장기 체류': 'grade-aging',
      '장기 재고': 'grade-aging',
      '악성': 'grade-risk',
      '위험': 'grade-risk',
      '처분 권장': 'grade-risk',
      '위험 재고': 'grade-risk'
    }[status] || 'text-gray-400';
  }

  function statusBadgeClass(status) {
    return {
      '정상': 'grade-badge-normal',
      '주의': 'grade-badge-caution',
      '장기': 'grade-badge-aging',
      '악성': 'grade-badge-risk'
    }[status] || 'grade-badge-normal';
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
    statusBadgeClass,
    formatNumber 
  };
})();