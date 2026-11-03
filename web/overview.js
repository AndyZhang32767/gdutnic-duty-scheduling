// Admin overview: monthly attendance stats, current-duty timeline, and this week's board.
const WEEK_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const STATUS_TEXT = {normal:'正常', late:'迟到', absent:'旷班', pending:'待签到'};
let overviewData = null, overviewToken = 0;

const monthInput = () => $('month');
const shiftTime = s => `${s.start} — ${s.end < s.start ? '次日 ' : ''}${s.end}`;
const memberLine = m => `${m.name} · ${STATUS_TEXT[m.status] || '待签到'}`;

function overviewCard(s) {
  const late = s.members.filter(m => m.status === 'late');
  const absent = s.members.filter(m => m.status === 'absent');
  const tone = absent.length ? 'danger' : late.length ? 'warn' : s.phase === 'current' ? 'current'
    : s.phase === 'future' ? 'future' : 'ok';
  const card = el('button', `week-card ${tone}`);
  card.type = 'button';
  card.append(el('strong', 'week-card-time', shiftTime(s)));
  card.append(el('span', 'week-card-count', `${s.members.length} 人`));
  // Reserve room for three names so every card keeps the same height; extra names are collapsed.
  const flagged = [...absent.map(m => ({m, status:'absent'})), ...late.map(m => ({m, status:'late'}))];
  for (let i = 0; i < 3; i++) {
    const item = flagged[i];
    card.append(el('span', `week-card-name${item ? ' ' + item.status : ' blank'}`,
      item ? `${item.m.name} · ${STATUS_TEXT[item.m.status]}` : ' '));
  }
  if (flagged.length > 3) card.append(el('span', 'week-card-more', `另有 ${flagged.length - 3} 人`));
  card.onclick = () => openDetail(s);
  return card;
}

function renderWeek(week, today) {
  $('weekRange').textContent = `${week.start} 至 ${week.end}`;
  const board = $('weekBoard');
  board.replaceChildren();
  // One grid row per shift index keeps Monday–Sunday cards aligned horizontally.
  const rows = Math.max(1, ...week.days.map(d => d.shifts.length));
  const boardHead = el('div', 'week-row week-head-row');
  boardHead.style.gridRow = '1';
  boardHead.append(el('div', 'week-day-head', '星期'));
  for (const day of week.days) {
    boardHead.append(el('div', 'week-day-head', `${WEEK_NAMES[day.weekday]} ${day.day.slice(5)}${day.day === today ? ' · 今天' : ''}`));
  }
  board.append(boardHead);
  for (let index = 0; index < rows; index++) {
    const row = el('div', 'week-row');
    row.style.gridRow = String(index + 2);
    row.append(el('div', 'week-slot-label', `第 ${index + 1} 班`));
    for (const day of week.days) {
      const cell = el('div', 'week-cell' + (day.day === today ? ' today' : ''));
      const shift = day.shifts[index];
      if (shift) cell.append(overviewCard(shift));
      row.append(cell);
    }
    board.append(row);
  }
}

function openDetail(s) {
  $('detailTitle').textContent = `${s.day} ${shiftTime(s)}`;
  $('detailMeta').textContent = `${s.note || '值班班次'} · ${s.members.length} 人`;
  const list = $('detailMembers');
  list.replaceChildren();
  for (const m of s.members) {
    const row = el('button', `detail-member clickable ${m.status || 'pending'}`);
    row.type = 'button';
    row.append(el('span', 'detail-name', m.name), el('span', 'detail-status', STATUS_TEXT[m.status] || '待签到'));
    row.append(el('span', 'detail-time', m.checked_at
      ? new Date(m.checked_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'})
      : '未签到'));
    row.title = '点击更改考勤状态';
    row.onclick = () => editAttendance(s, m);
    list.append(row);
  }
  $('detailDialog').showModal();
}

// Manual fixes take precedence over the automatic late/absent calculation.
function editAttendance(shift, member) {
  if (!window.canEditStatus) return;
  openStatusEditor({
    title: '更改考勤状态',
    meta: `${member.name} · ${shift.day} ${shiftTime(shift)}`,
    kind: 'attendance',
    current: member.status === 'pending' ? 'normal' : member.status,
    extraNote: member.checked_at
      ? '已签到：手动状态将覆盖系统根据签到时间计算的结果。'
      : '未签到：可手动改判为准时、迟到或旷班。',
    onSave: async status => {
      await api('/api/admin/overview/attendance', 'PUT',
        {shift_id: shift.id, name: member.name, status});
      await loadOverview();
      // Reopen the refreshed shift so the dialog shows the new status.
      const fresh = overviewData && overviewData.timeline.find(item => item.id === shift.id);
      if (fresh) openDetail(fresh);
      $('status').textContent = `已将「${member.name}」的考勤状态改为${STATUS_TEXT[status]}。`;
    },
  });
}

async function loadOverview() {
  const month = monthInput().value || today().slice(0, 7);
  const token = ++overviewToken;
  $('status').textContent = '正在加载概览…';
  try {
    const data = await api('/api/admin/overview?month=' + encodeURIComponent(month));
    if (token !== overviewToken) return;
    overviewData = data;
    renderOverview();
    $('status').textContent = '';
  } catch (err) {
    if (token === overviewToken) $('status').textContent = err.message;
  }
}

function renderOverview() {
  if (!overviewData) return;
  const stats = overviewData.stats;
  $('attendanceRate').textContent = stats.rate === null ? '—' : `${stats.rate}%`;
  $('attendanceDetail').textContent = `本月出勤率（正常 ${stats.normal} / 总出勤 ${stats.total}）`;
  $('lateCount').textContent = stats.late;
  $('absentCount').textContent = stats.absent;
  items = overviewData.timeline;
  window.updateShiftTimeline(items);
  renderWeek(overviewData.week, overviewData.today);
}

// Navigation mirrors the account's permission groups.
function applyPermissions(granted) {
  // A missing list means the server predates permissions: show everything instead of an empty nav.
  if (!Array.isArray(granted)) {
    for (const id of ['dailyTab', 'weeklyTab', 'specialTab', 'fieldTab', 'membersTab', 'settingsTab']) {
      const node = $(id);
      if (node) node.hidden = false;
    }
    return;
  }
  const held = new Set(granted);
  const needs = {dailyTab: 'schedule', weeklyTab: 'schedule', specialTab: 'schedule',
                 fieldTab: 'field', settingsTab: 'schedule'};
  // Any of the account permissions unlocks the user-management page.
  if ($('membersTab')) $('membersTab').hidden = !['accounts', 'accounts_manage', 'accounts_protected'].some(p => held.has(p));
  let firstVisible = null;
  for (const [id, permission] of Object.entries(needs)) {
    const node = $(id);
    if (!node) continue;
    node.hidden = !held.has(permission);
    if (!node.hidden && !firstVisible) firstVisible = id;
  }
  const active = document.querySelector('.ga-nav-item.active');
  if (active && active.hidden && firstVisible) $(firstVisible).click();
}

function initOverview() {
  monthInput().value = today().slice(0, 7);
  monthInput().onchange = loadOverview;
  $('today').onclick = () => {
    monthInput().value = today().slice(0, 7);
    loadOverview();
  };
  $('refresh').onclick = loadOverview;
  $('closeDetail').onclick = () => $('detailDialog').close();
  window.loadOverview = loadOverview;
  window.applyPermissions = applyPermissions;
  window.renderOverview = renderOverview;
}
if (document.body.dataset.admin === 'true') initOverview();
