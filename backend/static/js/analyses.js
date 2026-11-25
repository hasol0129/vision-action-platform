// Vision AI 분석 화면
// 입력 선택(업로드 / IP Webcam) → POST /api/analyses/ → 작업 ID로 1.5초마다 상태 조회 → 결과·Skeleton Overlay 표시
(function () {
  'use strict';

  const API = '/api/v1/analyses/';
  const POLL_MS = 1500;
  const LIVE_MS = 500;
  const STEPS = ['QUEUED', 'COLLECTING', 'INFERRING', 'DONE'];

  // ---------- 공통 ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const icons = () => window.lucide && window.lucide.createIcons();
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pct = (v) => (Number(v) * 100).toFixed(1) + '%';
  const jobNo = (id) => '#' + String(id).padStart(3, '0');
  const shortAction = (display, label) => (display || label || '').replace(/^A\d{3}\s*/, '');
  const fmtTime = (iso) => {
    if (!iso) return '-';
    const d = new Date(iso);
    const p = (n) => String(n).padStart(2, '0');
    return `${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  const fmtSize = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + 'MB' : Math.ceil(b / 1024) + 'KB');

  function csrfToken() {
    const input = $('[name=csrfmiddlewaretoken]');
    if (input) return input.value;
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  async function api(url, options = {}) {
    const headers = Object.assign({ 'X-CSRFToken': csrfToken(), Accept: 'application/json' }, options.headers || {});
    let res;
    try {
      res = await fetch(url, Object.assign({ credentials: 'same-origin' }, options, { headers }));
    } catch (e) {
      return { ok: false, status: 0, data: { detail: '서버에 연결할 수 없습니다. 네트워크를 확인하세요.' } };
    }
    let data = null;
    if (res.status !== 204) { try { data = await res.json(); } catch (e) { data = null; } }
    return { ok: res.ok, status: res.status, data };
  }

  function errorText(data) {
    if (!data) return '요청을 처리하지 못했습니다.';
    if (typeof data === 'string') return data;
    if (data.detail) return data.detail;
    return Object.values(data).map((v) => [].concat(v).join(' ')).join(' ');
  }

  function toast(text, icon = 'check-circle-2') {
    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = `<i data-lucide="${icon}"></i>${esc(text)}`;
    document.body.appendChild(el);
    icons();
    setTimeout(() => el.remove(), 2600);
  }

  // ---------- 결과 렌더링 (분석 화면·상세 화면 공용) ----------
  function predictionRows(preds) {
    return preds.map((p) => {
      const name = shortAction(p.action_label_display, p.action_label);
      return `<tr class="fade-in">
        <td><span class="track-chip">#${p.track_id}</span></td>
        <td><div class="action-cell"><b>${esc(name)}</b><small>${esc(p.action_label)}</small></div></td>
        <td><div class="conf">
          <div class="conf-top"><span class="conf-val">${pct(p.confidence)}</span>
            ${p.is_uncertain ? '<span class="badge uncertain"><i data-lucide="circle-help"></i>판단 불확실</span>' : ''}</div>
          <div class="conf-bar${p.is_uncertain ? ' warn' : ''}"><i style="width:${Math.max(2, p.confidence * 100)}%"></i></div>
        </div></td>
      </tr>`;
    }).join('');
  }

  function compareBadge(job) {
    if (!job.expected_action) return '<span class="badge neutral">선택 안 함</span>';
    const top = job.predictions[0];
    if (!top) return '<span class="badge neutral">예측 없음</span>';
    return top.action_label === job.expected_action
      ? '<span class="badge ok"><i data-lucide="check"></i>일치</span>'
      : '<span class="badge bad"><i data-lucide="x"></i>불일치</span>';
  }

  function failureHint(msg) {
    if (/카메라/.test(msg)) return '휴대폰 IP Webcam 앱이 켜져 있고 같은 네트워크인지 확인한 뒤 다시 시도하세요.';
    if (/열 수 없|Frame|형식/.test(msg)) return '영상 파일이 손상되었거나 지원하지 않는 형식입니다. 다른 파일로 다시 시도하세요.';
    if (/AI 서버/.test(msg)) return 'AI 추론 서버(fastapi) 상태를 확인하세요.';
    return '잠시 후 다시 시도하세요.';
  }

  function resultHtml(job) {
    if (job.status === 'FAILURE') {
      return `<div class="alert error fade-in"><i data-lucide="octagon-x"></i>
        <div><b>분석에 실패했습니다</b>${esc(job.error_message)}<div style="margin-top:6px;opacity:.85">${esc(failureHint(job.error_message))}</div></div></div>`;
    }
    if (!job.predictions.length) {
      return `<div class="empty-state fade-in"><span class="ring"><i data-lucide="user-x"></i></span>
        <b>${esc(job.result_message || '예측 결과가 없습니다')}</b><span>사람이 화면에 충분히 크게, 전신이 보이도록 촬영해 보세요.</span></div>`;
    }
    const top = job.predictions[0];
    return `<div class="table-wrap fade-in"><table class="table">
        <thead><tr><th>Track ID</th><th>예측 동작</th><th>신뢰도</th></tr></thead>
        <tbody>${predictionRows(job.predictions)}</tbody></table></div>
      <div class="meta-grid fade-in">
        <div class="meta-item"><div class="k"><i data-lucide="${job.input_type === 'ip_webcam' ? 'cctv' : 'upload'}"></i>입력 방식</div>
          <div class="v">${esc(job.input_type_display)}</div></div>
        <div class="meta-item"><div class="k"><i data-lucide="timer"></i>AI 처리 시간</div>
          <div class="v">${job.processing_time_sec != null ? job.processing_time_sec.toFixed(2) + '초' : '-'}
          <span class="muted" style="font-weight:500;font-size:13px">${job.frame_count ?? '-'} Frame</span></div></div>
        <div class="meta-item wide"><div class="k"><i data-lucide="git-compare"></i>수행하려는 동작 → 예측 (Track #${top.track_id})</div>
          <div class="v">${esc(shortAction(job.expected_action_display, '') || '-')}
            <i data-lucide="arrow-right" style="width:15px;height:15px;color:var(--subtle)"></i>
            ${esc(shortAction(top.action_label_display, top.action_label))} ${compareBadge(job)}</div></div>
      </div>`;
  }

  // ---------- 분석 화면 ----------
  const form = $('#analysis-form');
  if (form) initIndex();

  function initIndex() {
    const captureSec = form.dataset.captureSeconds;
    const maxMb = Number(form.dataset.maxMb);
    const inputType = $('[name=input_type]', form);
    const fileInput = $('#video-input');
    const preview = $('#preview');
    const previewEmpty = $('#preview-empty');
    const previewTitle = $('#preview-title');
    const previewActions = $('#preview-actions');
    const startBtn = $('#start-btn');
    const startLabel = $('#start-label');
    const heroMeta = $('#hero-meta');
    const formError = $('#form-error');
    const camInput = $('[name=camera_key]', form);

    let objectUrl = null;
    let liveTimer = null;
    let liveOn = false;
    let pollTimer = null;
    let clockTimer = null;
    let running = false;
    let currentJob = null;

    // --- 미리보기 영역 ---
    function clearPreviewMedia() {
      $$('video, img.frame, .preview-badge', preview).forEach((el) => el.remove());
      previewActions.innerHTML = '';
    }
    function setEmpty(icon, title, sub, withPick) {
      clearPreviewMedia();
      previewEmpty.innerHTML = `<span class="ring"><i data-lucide="${icon}"></i></span><b>${esc(title)}</b><span>${esc(sub)}</span>
        ${withPick ? '<button type="button" class="btn sm" id="pick-btn" style="margin-top:6px"><i data-lucide="folder-open"></i>파일 선택</button>' : ''}`;
      previewEmpty.classList.remove('hidden');
      const pick = $('#pick-btn');
      if (pick) pick.addEventListener('click', () => fileInput.click());
      icons();
    }
    function badge(html, cls = '') {
      const b = document.createElement('span');
      b.className = 'preview-badge ' + cls;
      b.innerHTML = html;
      preview.appendChild(b);
    }
    function showVideo(url) {
      clearPreviewMedia();
      previewEmpty.classList.add('hidden');
      const v = document.createElement('video');
      v.src = url; v.controls = true; v.muted = true; v.playsInline = true; v.preload = 'metadata';
      v.addEventListener('loadedmetadata', () => {
        if (isFinite(v.duration)) {
          heroMeta.innerHTML = `<i data-lucide="film"></i><span>영상 길이 <b>${v.duration.toFixed(1)}초</b> 전체를 분석합니다</span>`;
          $('#file-meta').textContent = `${fmtSize(fileInput.files[0].size)} · ${v.duration.toFixed(1)}초 · ${v.videoWidth}×${v.videoHeight}`;
          icons();
        }
      });
      preview.appendChild(v);
      badge('<i data-lucide="eye"></i>미리보기');
      icons();
    }
    function showKeyframe(url) {
      stopLive();
      clearPreviewMedia();
      previewEmpty.classList.add('hidden');
      const img = document.createElement('img');
      img.className = 'frame fade-in'; img.src = url; img.alt = 'Skeleton Overlay';
      preview.appendChild(img);
      badge('<i data-lucide="bone"></i>Skeleton Overlay', 'mint');
      const back = document.createElement('button');
      back.type = 'button'; back.className = 'btn sm';
      back.innerHTML = '<i data-lucide="rotate-ccw"></i>입력 화면으로';
      back.addEventListener('click', resetPreview);
      previewActions.appendChild(back);
      icons();
    }
    function resetPreview() {
      if (inputType.value === 'upload') {
        if (fileInput.files[0] && objectUrl) showVideo(objectUrl);
        else setEmpty('upload-cloud', '분석할 영상을 선택하세요', `여기로 끌어다 놓거나 아래 버튼으로 선택 · 최대 ${maxMb}MB`, true);
      } else {
        startLive();
      }
    }

    // --- IP Webcam 실시간 미리보기 (Django 프록시 경유, 카메라 주소는 브라우저에 노출되지 않음) ---
    function startLive() {
      if (!camInput) { setEmpty('camera-off', '등록된 카메라가 없습니다', '관리자에게 카메라 등록을 요청하세요', false); return; }
      stopLive();
      liveOn = true;
      clearPreviewMedia();
      setEmpty('loader', '카메라에 연결하는 중…', camInput.value, false);
      const img = document.createElement('img');
      img.className = 'frame hidden';
      img.alt = 'IP Webcam 미리보기';
      preview.appendChild(img);
      let first = true;
      let lastUrl = null;
      // fetch로 받아야 409(카메라 사용 중)·502(연결 실패) 이유를 화면에 보여 줄 수 있다
      const tick = async () => {
        if (!liveOn) return;
        let res;
        try {
          res = await fetch(`/api/v1/cameras/${encodeURIComponent(camInput.value)}/snapshot/?t=${Date.now()}`,
            { credentials: 'same-origin', cache: 'no-store' });
        } catch (e) { res = null; }
        if (!liveOn) return;
        if (res && res.ok) {
          const url = URL.createObjectURL(await res.blob());
          img.onload = () => { if (lastUrl) URL.revokeObjectURL(lastUrl); lastUrl = url; };
          img.src = url;
          if (first) {
            first = false;
            previewEmpty.classList.add('hidden');
            img.classList.remove('hidden');
            badge(`<span class="dot"></span>LIVE · ${esc(camInput.value)}`);
          }
          liveTimer = setTimeout(tick, LIVE_MS);
          return;
        }
        let detail = '휴대폰 카메라 앱이 켜져 있고 같은 네트워크인지 확인하세요';
        let busy = false;
        if (res) { try { const d = await res.json(); detail = d.detail || detail; busy = !!d.busy; } catch (e) { /* 무시 */ } }
        first = true;
        $$('.preview-badge', preview).forEach((b) => b.remove());
        img.classList.add('hidden');
        setEmpty(busy ? 'hourglass' : 'camera-off', busy ? '카메라가 다른 곳에서 사용 중입니다' : '카메라에 연결할 수 없습니다',
          `${detail} · 3초 후 다시 시도`, false);
        preview.appendChild(img);
        liveTimer = setTimeout(tick, 3000);
      };
      tick();
    }

    // DroidCam처럼 한 번에 1개 연결만 받는 카메라: Worker가 수집하는 동안 미리보기를 멈춘다
    function pauseLiveForCapture() {
      stopLive();
      clearPreviewMedia();
      setEmpty('video', `카메라에서 ${captureSec}초 동안 수집 중`, '지금 카메라 앞에서 동작하세요 · 수집이 끝나면 결과가 여기에 표시됩니다', false);
    }
    function stopLive() {
      liveOn = false;
      clearTimeout(liveTimer);
    }

    // --- 탭 ---
    $$('.tab').forEach((tab) => tab.addEventListener('click', () => {
      if (running) return;
      $$('.tab').forEach((t) => t.classList.toggle('active', t === tab));
      inputType.value = tab.dataset.input;
      $$('.panel').forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== tab.dataset.input));
      hideError();
      if (tab.dataset.input === 'upload') {
        stopLive();
        previewTitle.textContent = '영상 미리보기';
        heroMeta.innerHTML = '<i data-lucide="film"></i><span>영상 전체를 분석합니다</span>';
      } else {
        previewTitle.textContent = 'IP Webcam 미리보기';
        heroMeta.innerHTML = `<i data-lucide="timer"></i><span>수집 시간 <b>${captureSec}초</b> · 시작을 누르면 카메라 앞에서 동작하세요</span>`;
      }
      resetPreview();
      if (!currentJob) {
        $('#status-line .left').innerHTML = tab.dataset.input === 'upload'
          ? '<i data-lucide="info"></i><span>영상을 고르고 AI 분석 시작을 누르세요.</span>'
          : '<i data-lucide="info"></i><span>카메라 화면에 전신이 보이는지 확인하고 AI 분석 시작을 누르세요.</span>';
      }
      icons();
    }));

    $$('.cam-pill').forEach((pill) => pill.addEventListener('click', () => {
      $$('.cam-pill').forEach((p) => p.classList.toggle('active', p === pill));
      camInput.value = pill.dataset.cam;
      startLive();
    }));

    // --- 파일 선택 / 드래그 ---
    $('#pick-btn').addEventListener('click', () => fileInput.click());
    $('#change-btn').addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => onFile(fileInput.files[0]));
    ['dragenter', 'dragover'].forEach((ev) => preview.addEventListener(ev, (e) => {
      if (inputType.value !== 'upload' || running) return;
      e.preventDefault(); preview.classList.add('drag');
    }));
    ['dragleave', 'drop'].forEach((ev) => preview.addEventListener(ev, () => preview.classList.remove('drag')));
    preview.addEventListener('drop', (e) => {
      if (inputType.value !== 'upload' || running) return;
      e.preventDefault();
      const f = e.dataTransfer.files[0];
      if (!f) return;
      const dt = new DataTransfer(); dt.items.add(f); fileInput.files = dt.files;
      onFile(f);
    });

    function onFile(f) {
      hideError();
      if (!f) return;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(f);
      $('#file-row').classList.remove('hidden');
      $('#file-name').textContent = f.name;
      $('#file-meta').textContent = fmtSize(f.size);
      if (f.size > maxMb * 1048576) showError(`파일이 너무 큽니다 (${fmtSize(f.size)}). ${maxMb}MB 이하만 올릴 수 있습니다.`);
      showVideo(objectUrl);
    }

    function showError(msg) {
      formError.classList.remove('hidden');
      $('div', formError).textContent = msg;
    }
    function hideError() { formError.classList.add('hidden'); }

    // --- 스텝퍼 ---
    function renderStepper(job) {
      const idx = job ? Math.max(0, STEPS.indexOf(job.stage)) : -1;
      $$('.step').forEach((el, i) => {
        el.className = 'step';
        const dot = $('.step-dot', el);
        let icon = dot.dataset.icon || (dot.dataset.icon = $('[data-lucide], svg', dot).getAttribute('data-lucide'));
        if (!job) { /* 대기 상태 */ }
        else if (job.status === 'SUCCESS') { el.classList.add(i === STEPS.length - 1 ? 'success' : 'done'); icon = 'check'; }
        else if (job.status === 'FAILURE') {
          if (i < idx) { el.classList.add('done'); icon = 'check'; }
          else if (i === idx) { el.classList.add('failed'); icon = 'x'; }
        } else if (i < idx) { el.classList.add('done'); icon = 'check'; }
        else if (i === idx) { el.classList.add('active'); }
        dot.innerHTML = `<i data-lucide="${icon}"></i>`;
        if (job && job.status === 'FAILURE' && i === STEPS.length - 1) $('.step-label', el).textContent = '실패';
        else if (i === STEPS.length - 1) $('.step-label', el).textContent = '완료';
      });
      icons();
    }

    function statusText(job) {
      if (job.status === 'FAILURE') return ['circle-x', job.error_message || '분석에 실패했습니다.'];
      if (job.status === 'SUCCESS') return ['circle-check', job.result_message || '분석이 끝났습니다.'];
      const webcam = job.input_type === 'ip_webcam';
      switch (job.stage) {
        case 'COLLECTING': return ['video', webcam ? `카메라에서 ${captureSec}초 동안 영상을 수집하고 있습니다 · 카메라 앞에서 동작하세요` : '업로드한 영상을 준비하고 있습니다'];
        case 'INFERRING': return ['brain-circuit', 'AI가 사람별 자세를 추적하고 동작을 분석하고 있습니다'];
        default: return ['hourglass', `작업 대기열에 등록되었습니다 · ${jobNo(job.id)}`];
      }
    }

    function renderStatus(job) {
      $('#job-chip').textContent = jobNo(job.id);
      $('#job-chip').classList.remove('hidden');
      const pill = $('#job-pill');
      pill.className = 'pill ' + job.status;
      pill.textContent = job.status_display;
      const [icon, text] = statusText(job);
      $('#status-line .left').innerHTML = `<i data-lucide="${icon}"></i><span>${esc(text)}</span>`;
      renderStepper(job);
    }

    function startClock() {
      const t0 = Date.now();
      const el = $('#status-timer');
      el.classList.remove('hidden');
      clearInterval(clockTimer);
      const tick = () => {
        const s = Math.floor((Date.now() - t0) / 1000);
        el.textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
      };
      tick();
      clockTimer = setInterval(tick, 500);
    }

    // --- 제출 → 폴링 ---
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (running) return;
      hideError();
      const fd = new FormData(form);
      if (inputType.value === 'upload') {
        fd.delete('camera_key');
        if (!fileInput.files[0]) { showError('분석할 영상 파일을 선택하세요.'); return; }
        if (fileInput.files[0].size > maxMb * 1048576) { showError(`${maxMb}MB 이하 파일만 올릴 수 있습니다.`); return; }
      } else {
        fd.delete('video');
        if (!camInput) { showError('등록된 카메라가 없습니다.'); return; }
      }

      setRunning(true, '요청 보내는 중…');
      const webcam = inputType.value === 'ip_webcam';
      if (webcam) pauseLiveForCapture();  // 카메라 연결을 Worker에게 넘겨준다
      const r = await api(API, { method: 'POST', body: fd });
      if (!r.ok) { setRunning(false); showError(errorText(r.data)); if (webcam) startLive(); return; }

      currentJob = r.data;
      $('#result-body').innerHTML = `<div class="empty-state"><span class="ring"><i data-lucide="loader"></i></span>
        <b>분석 중입니다</b><span>작업 ID ${jobNo(currentJob.id)} · 페이지를 떠나도 분석은 계속되며 이력에서 확인할 수 있습니다.</span></div>`;
      $('#result-actions').innerHTML = '';
      icons();
      renderStatus(currentJob);
      startClock();
      setRunning(true, '분석 진행 중…');
      loadHistory();
      poll(currentJob.id);
    });

    function setRunning(on, label) {
      running = on;
      startBtn.disabled = on;
      startLabel.textContent = on ? label : 'AI 분석 시작';
      $$('.tab').forEach((t) => (t.disabled = on));
    }

    async function poll(id) {
      const r = await api(`${API}${id}/status/`);
      if (!r.ok) {
        $('#status-line .left').innerHTML = `<i data-lucide="wifi-off"></i><span>상태 조회 실패 (HTTP ${r.status}) · 다시 시도합니다</span>`;
        icons();
        pollTimer = setTimeout(() => poll(id), POLL_MS * 2);
        return;
      }
      renderStatus(Object.assign({}, currentJob, r.data));
      if (!r.data.is_finished) { pollTimer = setTimeout(() => poll(id), POLL_MS); return; }

      clearInterval(clockTimer);
      const d = await api(`${API}${id}/`);
      const job = d.ok ? d.data : Object.assign({}, currentJob, r.data, { predictions: [] });
      renderStatus(job);
      $('#result-body').innerHTML = resultHtml(job);
      $('#result-actions').innerHTML = `<a class="btn sm" href="/analyses/${job.id}/"><i data-lucide="external-link"></i>상세 보기</a>`;
      if (job.keyframe) showKeyframe(job.keyframe);
      else if (inputType.value === 'ip_webcam') startLive();  // 수집이 끝났으니 미리보기 다시 시작
      icons();
      setRunning(false);
      loadHistory();
      toast(job.status === 'SUCCESS' ? `${jobNo(job.id)} 분석 완료` : `${jobNo(job.id)} 분석 실패`, job.status === 'SUCCESS' ? 'check-circle-2' : 'circle-x');
    }

    renderStepper(null);
    loadHistory();
  }

  async function loadHistory() {
    const body = $('#history-body');
    if (!body) return;
    const r = await api(API);
    if (!r.ok) {
      body.innerHTML = '<tr><td colspan="9"><div class="alert error"><i data-lucide="circle-alert"></i><div>이력을 불러오지 못했습니다.</div></div></td></tr>';
      icons(); return;
    }
    const jobs = r.data.slice(0, 8);
    if (!jobs.length) {
      body.innerHTML = `<tr><td colspan="9"><div class="empty-state"><span class="ring"><i data-lucide="inbox"></i></span>
        <b>아직 분석 기록이 없습니다</b><span>첫 영상을 분석하면 여기에 쌓입니다.</span></div></td></tr>`;
      icons(); return;
    }
    body.innerHTML = jobs.map((j) => {
      const preds = j.predictions.length
        ? j.predictions.slice(0, 3).map((p) => `<span class="badge ${p.is_uncertain ? 'uncertain' : 'neutral'}" style="margin:2px 4px 2px 0">#${p.track_id} ${esc(shortAction(p.action_label_display, p.action_label))} ${(p.confidence * 100).toFixed(0)}%</span>`).join('')
        : (j.status === 'FAILURE' ? `<span class="truncate muted" title="${esc(j.error_message)}">${esc(j.error_message)}</span>` : '<span class="muted">-</span>');
      return `<tr>
        <td><span class="job-chip">${jobNo(j.id)}</span></td>
        <td><span class="truncate" style="max-width:160px">${esc(j.title || '제목 없음')}</span></td>
        <td><span class="cell-icon"><i data-lucide="${j.input_type === 'ip_webcam' ? 'cctv' : 'upload'}"></i>${esc(j.input_type_display)}</span></td>
        <td>${esc(shortAction(j.expected_action_display, '') || '-')}</td>
        <td>${preds}</td>
        <td><span class="pill ${j.status}">${esc(j.status_display)}</span></td>
        <td class="num">${j.processing_time_sec != null ? j.processing_time_sec.toFixed(2) + '초' : '-'}</td>
        <td class="muted">${fmtTime(j.created_at)}</td>
        <td><a class="link-cell" href="/analyses/${j.id}/">상세<i data-lucide="chevron-right"></i></a></td>
      </tr>`;
    }).join('');
    icons();
  }

  // ---------- 상세 화면 ----------
  const detail = $('#job-detail');
  if (detail) {
    const jobId = detail.dataset.jobId;
    if (detail.dataset.finished === '0') {
      const tick = async () => {
        const r = await api(`${API}${jobId}/status/`);
        if (r.ok && r.data.is_finished) return window.location.reload();
        setTimeout(tick, POLL_MS);
      };
      setTimeout(tick, POLL_MS);
    }

    $$('.seg button').forEach((b) => b.addEventListener('click', () => {
      $$('.seg button').forEach((x) => x.classList.toggle('active', x === b));
      $$('[data-view]').forEach((v) => v.classList.toggle('hidden', v.dataset.view !== b.dataset.show));
    }));

    const editForm = $('#edit-form');
    if (editForm) {
      editForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const r = await api(`${API}${jobId}/`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: editForm.title.value, memo: editForm.memo.value }),
        });
        if (r.ok) { toast('저장했습니다'); $('#detail-title').textContent = r.data.title || '제목 없음'; }
        else toast(errorText(r.data), 'circle-x');
      });
      $('#delete-btn').addEventListener('click', async () => {
        if (!confirm('이 분석 기록을 삭제할까요?\n사람별 예측, 영상, Skeleton Overlay 파일도 함께 삭제되며 되돌릴 수 없습니다.')) return;
        const r = await api(`${API}${jobId}/`, { method: 'DELETE' });
        if (r.ok) window.location.href = '/analyses/';
        else toast(errorText(r.data), 'circle-x');
      });
    }
  }
})();
