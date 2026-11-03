// Member-side field duty (外勤) registration for the current month.
function showMemberPage(field) {
  $('dutyPage').hidden = field;
  $('fieldPage').hidden = !field;
  $('dutyTab').classList.toggle('active', !field);
  $('fieldTab').classList.toggle('active', field);
}

// Three stages: idle "点击登记" → hover "确认登记" → after clicking "登记完成" (locked green).
const FIELD_IDLE = '点击登记';
const FIELD_HOVER = '确认登记';
const FIELD_DONE = '登记完成';

function setFieldLabel(text) {
  const label = $('fieldButtonText');
  if (label) label.textContent = text;
}

function paintFieldStatus(data) {
  const button = $('fieldButton');
  const done = !!data.registered;
  $('fieldCount').textContent = done ? '1' : '0';
  button.classList.toggle('registered', done);
  // A registered button stays green and never returns to the idle copy.
  setFieldLabel(done ? FIELD_DONE : (button.matches(':hover') ? FIELD_HOVER : FIELD_IDLE));
  button.disabled = done;
  $('fieldStatus').textContent = done
    ? `本月已于 ${new Date(data.registered_at).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'})} 登记外勤。`
    : '';
}

async function loadFieldDuty() {
  $('fieldStatus').textContent = '';
  try { paintFieldStatus(await api('/api/member/field-duty')); }
  catch (err) { $('fieldStatus').textContent = err.message; }
}

$('fieldButton').addEventListener('mouseenter', () => {
  if (!$('fieldButton').classList.contains('registered')) setFieldLabel(FIELD_HOVER);
});
$('fieldButton').addEventListener('mouseleave', () => {
  if (!$('fieldButton').classList.contains('registered')) setFieldLabel(FIELD_IDLE);
});
// Pressing shows the confirm copy immediately; the success copy lands with the response.
$('fieldButton').addEventListener('pointerdown', () => {
  if (!$('fieldButton').classList.contains('registered')) setFieldLabel(FIELD_HOVER);
});

$('dutyTab').onclick = () => { showMemberPage(false); load(); };
$('fieldTab').onclick = () => { showMemberPage(true); loadFieldDuty(); };
$('fieldButton').onclick = async () => {
  const button = $('fieldButton');
  if (button.classList.contains('registered')) return;
  try {
    paintFieldStatus(await api('/api/member/field-duty', 'POST'));
  } catch (err) {
    $('fieldStatus').textContent = err.message;
    setFieldLabel(button.matches(':hover') ? FIELD_HOVER : FIELD_IDLE);
  }
};
