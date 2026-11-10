(() => {
  const form = $('checkinAccessForm');
  let loading = false;
  function paint(data) {
    for (const kind of ['checkin', 'field']) {
      form.elements[kind + '_mode'].value = data.rules[kind].mode;
      form.elements[kind + '_entries'].value = data.rules[kind].entries;
    }
    const access = data.network_access;
    $('checkinAccessPeer').textContent = `当前来源 IP：${access.ip}；打卡：${access.checkin ? '允许' : '禁止'}；外勤：${access.field ? '允许' : '禁止'}。`;
  }
  window.loadCheckinAccess = async () => {
    if (loading) return;
    loading = true;
    const controls = [...form.elements];
    controls.forEach(control => control.disabled = true);
    $('checkinAccessStatus').textContent = '正在加载网络规则…';
    try {
      paint(await api('/api/admin/checkin-access'));
      $('checkinAccessStatus').textContent = '';
      controls.forEach(control => control.disabled = false);
    } catch (err) { $('checkinAccessStatus').textContent = err.message; }
    finally { loading = false; }
  };
  form.onsubmit = async event => {
    event.preventDefault();
    const submit = form.querySelector('[type=submit]');
    const body = Object.fromEntries(['checkin', 'field'].map(kind => [kind, {
      mode: form.elements[kind + '_mode'].value,
      entries: form.elements[kind + '_entries'].value,
    }]));
    submit.disabled = true;
    try {
      paint(await api('/api/admin/checkin-access', 'PUT', body));
      $('checkinAccessStatus').textContent = '网络规则已保存。成员端会自动刷新按钮状态。';
    } catch (err) { $('checkinAccessStatus').textContent = err.message; }
    finally { submit.disabled = false; }
  };
})();
