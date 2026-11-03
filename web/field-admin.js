// Admin field-duty board: who registered this month and who has not.
function fieldCard(item, month) {
  const card = el('article', `field-person ${item.registered ? 'done' : 'missing'} clickable`);
  card.append(el('strong', '', item.username));
  card.append(el('span', '', item.registered
    ? new Date(item.registered_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'})
    : '未参加外勤'));
  if (item.manual) card.append(el('span', 'manual-flag', '管理员修改'));
  card.title = '点击更改外勤参与状态';
  card.onclick = () => editParticipation(item, month);
  return card;
}

function editParticipation(item, month) {
  if (!window.canEditField) return;
  openStatusEditor({
    title: '更改外勤状态',
    meta: `${item.username} · ${month}`,
    kind: 'field',
    current: item.registered ? 'yes' : 'no',
    extraNote: '改为已参加时若无登记时间，将使用当前时间记录。',
    onSave: async value => {
      await api('/api/admin/field-duty', 'PUT',
        {username: item.username, registered: value === 'yes', month});
      await loadFieldBoard();
      $('fieldAdminStatus').textContent = `已更新「${item.username}」的外勤状态。`;
    },
  });
}

async function loadFieldBoard() {
  const month = $('fieldMonth').value || today().slice(0, 7);
  $('fieldAdminStatus').textContent = '正在加载外勤记录…';
  try {
    const data = await api('/api/admin/field-duty?month=' + encodeURIComponent(month));
    $('fieldRegistered').textContent = data.registered;
    $('fieldSummary').textContent = `本月已参加外勤 / 共 ${data.total} 人`;
    const board = $('fieldBoard');
    board.replaceChildren();
    if (!data.items.length) board.append(el('p', 'hint', '本月暂无可用账号。'));
    for (const item of data.items) board.append(fieldCard(item, data.month));
    $('fieldAdminStatus').textContent = '';
  } catch (err) {
    $('fieldAdminStatus').textContent = err.message;
  }
}

$('fieldTab').onclick = () => { showPage('field'); loadFieldBoard(); };
$('fieldMonth').value = today().slice(0, 7);
$('fieldMonth').onchange = loadFieldBoard;
$('fieldToday').onclick = () => { $('fieldMonth').value = today().slice(0, 7); loadFieldBoard(); };
