// Attendance window: mirrors the server's early/late/absent minute thresholds.
async function loadRules() {
  $('rulesStatus').textContent = '正在加载设置…';
  try {
    const rules = await api('/api/admin/rules');
    for (const key of ['early_minutes', 'late_minutes', 'absent_minutes']) {
      $('rulesForm').elements[key].value = rules[key];
    }
    $('rulesStatus').textContent = '';
  } catch (err) {
    $('rulesStatus').textContent = err.message;
    if (err.status === 401) $('rulesStatus').textContent = '登录状态已失效，请重新登录。';
  }
}
$('settingsTab').onclick = () => { showPage('settings'); loadRules(); };
$('rulesForm').onsubmit = async e => {
  e.preventDefault();
  const form = e.currentTarget, submit = form.querySelector('[type=submit]');
  const body = {
    early_minutes: form.elements.early_minutes.value,
    late_minutes: form.elements.late_minutes.value,
    absent_minutes: form.elements.absent_minutes.value,
  };
  if (Number(body.absent_minutes) <= Number(body.late_minutes)) {
    $('rulesStatus').textContent = '旷班时间必须大于迟到时间，两者都从班次开始时间起算。';
    return;
  }
  submit.disabled = true;
  try {
    const saved = await api('/api/admin/rules', 'PUT', body);
    rules = saved;
    $('rulesStatus').textContent = '值班时间设置已保存，签到页面会自动使用新规则。';
  } catch (err) { $('rulesStatus').textContent = err.message; }
  finally { submit.disabled = false; }
};

// 系统时间：自动设置，或从手动指定的小时:分钟:00 开始计时。
let clockTimer = 0;

function renderClock(state) {
  $('clockAutomatic').checked = !!state.automatic;
  $('clockManual').hidden = !!state.automatic;
  if (!state.automatic) {
    $('clockDate').value = state.date || '';
    $('clockHour').value = state.hour;
    $('clockMinute').value = state.minute;
  } else if (!$('clockDate').value) {
    $('clockDate').value = state.date || '';
  }
  paintClockNow(state.current);
}

function paintClockNow(iso) {
  const at = iso ? new Date(iso) : new Date(clockNow());
  const text = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(at);
  $('clockNow').textContent = text;
}

async function loadClock() {
  try {
    const state = await api('/api/admin/clock');
    syncClock(state);
    renderClock(state);
  } catch (err) { $('clockStatus').textContent = err.message; }
}

// Tick locally between server reads so the clock reads like a real clock.
function tickClock() {
  if (!$('clockNow') || $('settingsPage').hidden) return;
  // Derive from the page clock so date rollovers are handled correctly.
  paintClockNow(new Date(clockNow()).toISOString());
}

$('clockAutomatic').onchange = () => { $('clockManual').hidden = $('clockAutomatic').checked; };
$('clockForm').onsubmit = async e => {
  e.preventDefault();
  const submit = e.currentTarget.querySelector('[type=submit]');
  submit.disabled = true;
  $('clockStatus').textContent = '';
  try {
    const automatic = $('clockAutomatic').checked;
    const state = await api('/api/admin/clock', 'PUT', {
      automatic,
      date: automatic ? undefined : $('clockDate').value,
      hour: Number($('clockHour').value || 0),
      minute: Number($('clockMinute').value || 0),
    });
    renderClock(state);
    $('clockStatus').textContent = automatic
      ? '已恢复自动设置，使用真实时间。'
      : `已设为手动时间，从 ${state.date} ${String(state.hour).padStart(2, '0')}:${String(state.minute).padStart(2, '0')}:00 开始计时。`;
  } catch (err) { $('clockStatus').textContent = err.message; }
  finally { submit.disabled = false; }
};

const originalSettingsClick = $('settingsTab').onclick;
$('settingsTab').onclick = () => {
  originalSettingsClick();
  loadClock();
  clearInterval(clockTimer);
  clockTimer = setInterval(tickClock, 1000);
};
