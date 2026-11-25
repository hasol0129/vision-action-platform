// 관리자 대시보드: Django가 json_script로 넘긴 ORM 집계를 Chart.js로 그린다 (실제 DB 값만 사용)
(function () {
  'use strict';
  const el = document.getElementById('chart-data');
  if (!el || typeof Chart === 'undefined') return;
  const data = JSON.parse(el.textContent);

  const INDIGO = '#3b3fd8';
  const FONT = "'Pretendard Variable', Pretendard, 'Noto Sans KR', sans-serif";
  Chart.defaults.font.family = FONT;
  Chart.defaults.font.size = 13;
  Chart.defaults.color = '#6b7088';
  Chart.defaults.plugins.tooltip.backgroundColor = '#161a2e';
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.plugins.tooltip.titleFont = { family: FONT, weight: '700' };

  const sum = (arr) => arr.reduce((a, b) => a + b, 0);
  const narrow = window.matchMedia('(max-width: 600px)').matches;

  function emptyOverlay(canvas, text) {
    const box = canvas.parentElement;
    const div = document.createElement('div');
    div.className = 'chart-empty';
    div.textContent = text;
    box.appendChild(div);
  }

  // 막대 끝에 값 표시
  const barValueLabels = {
    id: 'barValueLabels',
    afterDatasetsDraw(chart, _args, opts) {
      const { ctx } = chart;
      const meta = chart.getDatasetMeta(0);
      const horizontal = chart.options.indexAxis === 'y';
      ctx.save();
      ctx.font = `700 13px ${FONT}`;
      ctx.fillStyle = '#161a2e';
      ctx.textBaseline = 'middle';
      meta.data.forEach((bar, i) => {
        const v = chart.data.datasets[0].data[i];
        const text = (opts && opts.format) ? opts.format(v) : String(v);
        if (horizontal) { ctx.textAlign = 'left'; ctx.fillText(text, bar.x + 8, bar.y); }
        else { ctx.textAlign = 'center'; ctx.fillText(text, bar.x, bar.y - 12); }
      });
      ctx.restore();
    },
  };

  // 도넛 가운데 "총 N건" + 조각 위 퍼센트
  const doughnutLabels = {
    id: 'doughnutLabels',
    afterDatasetsDraw(chart, _args, opts) {
      const { ctx } = chart;
      const values = chart.data.datasets[0].data;
      const total = sum(values);
      const meta = chart.getDatasetMeta(0);
      if (!meta.data.length) return;
      const { x, y } = meta.data[0];
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#6b7088';
      ctx.font = `600 13px ${FONT}`;
      ctx.fillText(opts.caption || '총', x, y - 14);
      ctx.fillStyle = '#161a2e';
      ctx.font = `800 26px ${FONT}`;
      ctx.fillText(`${total}${opts.unit || '건'}`, x, y + 12);
      if (total) {
        ctx.font = `700 12px ${FONT}`;
        ctx.fillStyle = '#fff';
        meta.data.forEach((arc, i) => {
          const share = values[i] / total;
          if (share < 0.06) return;
          const p = arc.tooltipPosition();
          ctx.fillText(`${Math.round(share * 100)}%`, p.x, p.y);
        });
      }
      ctx.restore();
    },
  };

  // 1) 동작별 예측 건수 — 가로 막대
  (function () {
    const canvas = document.getElementById('chart-actions');
    const d = data.actions;
    const max = Math.max(1, ...d.values);
    new Chart(canvas, {
      type: 'bar',
      // 좁은 화면(휴대폰)에서는 'A001' 코드를 빼고 동작 이름만 보여 줘서 라벨이 잘리지 않게 한다
      data: { labels: narrow ? d.labels.map((l) => l.replace(/^A\d{3}\s*/, '')) : d.labels,
        datasets: [{ data: d.values, backgroundColor: INDIGO, hoverBackgroundColor: '#2a2ea6', borderRadius: 6, barThickness: narrow ? 16 : 22 }] },
      options: {
        indexAxis: 'y', maintainAspectRatio: false,
        layout: { padding: { right: 36 } },
        plugins: { legend: { display: false }, barValueLabels: { format: (v) => `${v}건` },
          tooltip: { callbacks: { label: (c) => ` ${c.raw}건` } } },
        scales: {
          x: { beginAtZero: true, suggestedMax: Math.ceil(max * 1.15), ticks: { precision: 0 }, grid: { color: '#eef0f6' }, border: { display: false } },
          y: { grid: { display: false }, border: { display: false }, ticks: { color: '#3d4260', font: { weight: '600', size: narrow ? 11 : 13 } } },
        },
      },
      plugins: [barValueLabels],
    });
    if (!sum(d.values)) emptyOverlay(canvas, '아직 예측 결과가 없습니다');
  })();

  // 2) 작업 상태별 건수 — 도넛 + 오른쪽 범례
  (function () {
    const canvas = document.getElementById('chart-statuses');
    const d = data.statuses;
    const total = sum(d.values);
    new Chart(canvas, {
      type: 'doughnut',
      data: { labels: d.labels, datasets: [{ data: total ? d.values : [1], backgroundColor: total ? d.colors : ['#eef0f6'], borderWidth: 3, borderColor: '#fff', hoverOffset: 6 }] },
      options: { maintainAspectRatio: false, cutout: '64%',
        plugins: { legend: { display: false }, tooltip: { enabled: !!total }, doughnutLabels: { caption: '총' } } },
      plugins: [doughnutLabels],
    });
    if (!total) canvas.closest('.chart-box').dataset.empty = '1';
    document.getElementById('status-legend').innerHTML = d.labels.map((label, i) =>
      `<div class="legend-item"><i style="background:${d.colors[i]}"></i><span>${label}</span><b>${d.values[i]}건</b></div>`).join('');
  })();

  // 3) 입력 방식 비율 (선택)
  (function () {
    const canvas = document.getElementById('chart-inputs');
    const d = data.inputs;
    const total = sum(d.values);
    new Chart(canvas, {
      type: 'doughnut',
      data: { labels: d.labels, datasets: [{ data: total ? d.values : [1], backgroundColor: total ? [INDIGO, '#3ee0c0'] : ['#eef0f6'], borderWidth: 3, borderColor: '#fff' }] },
      options: { maintainAspectRatio: false, cutout: '62%',
        plugins: { legend: { position: 'right', labels: { usePointStyle: true, pointStyle: 'rectRounded', padding: 16,
          generateLabels: (chart) => d.labels.map((l, i) => ({ text: `${l}  ${d.values[i]}건`, fillStyle: [INDIGO, '#3ee0c0'][i], strokeStyle: 'transparent', index: i })) } },
          tooltip: { enabled: !!total }, doughnutLabels: { caption: '작업' } } },
      plugins: [doughnutLabels],
    });
  })();

  // 4) 입력 방식별 평균 처리 시간 (선택)
  (function () {
    const canvas = document.getElementById('chart-avg-time');
    const d = data.avg_time;
    new Chart(canvas, {
      type: 'bar',
      data: { labels: d.labels, datasets: [{ data: d.values, backgroundColor: ['#6f72e6', '#3ee0c0'], borderRadius: 8, barThickness: 56 }] },
      options: { maintainAspectRatio: false, layout: { padding: { top: 22 } },
        plugins: { legend: { display: false }, barValueLabels: { format: (v) => (v ? `${v}초` : '-') } },
        scales: { y: { beginAtZero: true, grid: { color: '#eef0f6' }, border: { display: false }, ticks: { callback: (v) => `${v}s` } },
          x: { grid: { display: false }, border: { display: false }, ticks: { color: '#3d4260', font: { weight: '600' } } } } },
      plugins: [barValueLabels],
    });
    if (!sum(d.values)) emptyOverlay(canvas, '완료된 작업이 없습니다');
  })();
})();
