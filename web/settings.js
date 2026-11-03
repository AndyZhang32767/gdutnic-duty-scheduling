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
