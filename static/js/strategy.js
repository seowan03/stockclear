    async function loadStrategyData() {
      const response = await fetch('/api/strategy', { credentials: 'include' });
      if (response.status === 401) {
        window.redirectToSignIn();
        return;
      }
      if (!response.ok) throw new Error('전략 데이터를 불러오지 못했습니다.');
      const strategy = await response.json();
      document.getElementById('urgentCount').textContent = Number(strategy.order_count || 0);
      document.getElementById('promotionCount').textContent = Number(strategy.promotion_count || 0);
      await loadStrategyActions();
    }

    async function loadStrategyActions() {
      const response = await fetch('/api/strategy/actions', { credentials: 'include' });
      if (!response.ok) throw new Error('작업 기록을 불러오지 못했습니다.');
      const payload = await response.json();
      const container = document.getElementById('actionHistory');
      container.replaceChildren();
      const labels = { order: '발주 검토', promotion: '프로모션 검토' };
      (payload.actions || []).forEach((action) => {
        const row = document.createElement('div');
        row.className = 'flex flex-wrap justify-between gap-2 py-3';
        const title = document.createElement('span');
        title.textContent = `${labels[action.action_type] || action.action_type} · ${action.item_count}개 품목`;
        const status = document.createElement('span');
        status.className = 'text-gray-500';
        status.textContent = `${action.status} · ${action.created_at ? new Date(action.created_at).toLocaleString('ko-KR') : ''}`;
        row.append(title, status);
        container.appendChild(row);
      });
      if (!container.childElementCount) {
        const empty = document.createElement('p');
        empty.className = 'py-3 text-gray-500';
        empty.textContent = '저장된 작업 기록이 없습니다.';
        container.appendChild(empty);
      }
    }

    async function createStrategyAction(actionType) {
      const response = await fetch(`/api/strategy/actions?action_type=${encodeURIComponent(actionType)}`, {
        method: 'POST',
        credentials: 'include'
      });
      const result = await response.json();
      if (response.status === 401) {
        window.redirectToSignIn();
        return;
      }
      if (!response.ok) {
        alert(result.detail || '작업 기록을 저장하지 못했습니다.');
        return;
      }
      await loadStrategyActions();
      alert(`${result.item_count}개 품목의 내부 검토 기록을 저장했습니다. 외부 작업은 실행되지 않았습니다.`);
    }

    async function createRecommendedActions() {
      const recorded = [];
      const skipped = [];
      for (const actionType of ['order', 'promotion']) {
        const response = await fetch(`/api/strategy/actions?action_type=${actionType}`, {
          method: 'POST',
          credentials: 'include'
        });
        if (response.status === 401) {
          window.redirectToSignIn();
          return;
        }
        const result = await response.json();
        if (response.ok) recorded.push(result);
        else if (response.status === 409) skipped.push(actionType);
        else throw new Error(result.detail || '작업 기록을 저장하지 못했습니다.');
      }
      await loadStrategyActions();
      const total = recorded.reduce((sum, action) => sum + action.item_count, 0);
      alert(`${recorded.length}개 작업 기록, ${total}개 품목을 저장했습니다. 대상이 없는 작업 ${skipped.length}개는 건너뛰었습니다. 외부 작업은 실행되지 않았습니다.`);
    }

    loadStrategyData().catch((error) => {
      console.error('전략 데이터 로딩 실패:', error);
      document.getElementById('urgentCount').textContent = '-';
      document.getElementById('promotionCount').textContent = '-';
    });
