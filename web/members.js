let memberItems = [], deletingMember = '', memberMeta = {permissions: [], tree: [], groups: [], me: '', can_grant: false};
let memberQuery = '';
const memberMatches = member => !memberQuery || member.username.toLowerCase().includes(memberQuery);

function permissionLabel(id) {
  const found = memberMeta.permissions.find(p => p.id === id);
  return found ? found.label : id;
}

function renderMembers() {
  $('memberList').replaceChildren();
  const visible = memberItems.filter(memberMatches);
  for (const member of visible) {
    const row = el('article', 'card member-account'), title = el('div');
    title.append(el('h2', '', member.username), el('p', '', member.active ? '账号已启用' : '账号已停用'));
    const tags = el('div', 'permission-tags');
    const held = member.permissions || [];
    if (!held.length) tags.append(el('span', 'permission-tag muted', '无权限'));
    for (const id of held) tags.append(el('span', 'permission-tag', permissionLabel(id)));
    title.append(tags);
    const actions = el('div', 'actions');
    actions.append(
      button('更改权限', 'secondary', () => openPermission(member)),
      button('更改密码', 'secondary', () => openPassword(member)),
      button('重置密码', 'secondary', async () => {
        if (!confirm(`将「${member.username}」的密码重置为 gg2017？`)) return;
        try { await api('/api/admin/members', 'PATCH', {username:member.username, reset_password:true}); $('membersStatus').textContent = '密码已重置，该用户需重新登录。'; }
        catch (err) { $('membersStatus').textContent = err.message; }
      }),
      button(member.active ? '停用账号' : '启用账号', member.active ? 'secondary' : 'primary', async () => {
        try { await api('/api/admin/members', 'PATCH', {username:member.username, active:!member.active}); await loadMembers(); }
        catch (err) { $('membersStatus').textContent = err.message; }
      }),
      button('删除账号', 'delete', async () => {
        if (deletingMember === member.username) return;
        if (!confirm(`确认删除「${member.username}」的账号？该操作无法撤销，已有排班和签到记录会保留。`)) return;
        deletingMember = member.username;
        try { await api('/api/admin/members?username=' + encodeURIComponent(member.username), 'DELETE'); await loadMembers(); $('membersStatus').textContent = `已删除「${member.username}」的账号。`; }
        catch (err) { $('membersStatus').textContent = err.message; }
        finally { deletingMember = ''; }
      })
    );
    row.append(title, actions);
    $('memberList').append(row);
  }
  const filtered = memberQuery ? `，筛选出 ${visible.length} 个` : '';
  $('membersStatus').textContent = `共 ${memberItems.length} 个账号${filtered}${memberMeta.can_grant ? '' : '；当前账号不能更改他人权限'}。`;
  if (!visible.length && memberItems.length) {
    const empty = el('div', 'empty');
    empty.append(el('h2', '', '没有匹配的账号'), el('p', '', `没有姓名包含“${memberQuery}”的账号。`));
    $('memberList').append(empty);
  }
}

async function loadMembers() {
  if (Array.isArray(window.adminPermissions) &&
      !['accounts', 'accounts_manage', 'accounts_protected'].some(p => window.adminPermissions.includes(p))) {
    $('membersStatus').textContent = '当前账号没有用户管理权限。';
    return;
  }
  $('membersStatus').textContent = '正在加载用户…';
  try {
    const data = await api('/api/admin/members');
    memberItems = data.items;
    memberMeta = {permissions: data.permissions || [], tree: data.tree || [], groups: data.groups || [],
      me: data.me || '', can_grant: !!data.can_grant};
    renderMembers();
  } catch (err) {
    $('membersStatus').textContent = err.message;
    if (err.status === 401) $('membersStatus').textContent = '登录状态已失效，请重新登录。';
  }
}

// Collapsible permission tree: a parent checkbox mirrors its leaves, and ticking a
// parent expands its children so the effect is visible immediately.
function collectLeaves(node, out = []) {
  for (const leaf of node.children || []) {
    if (leaf.children) collectLeaves(leaf, out);
    else out.push(leaf.id);
  }
  return out;
}

function syncTreeState(nodeEl) {
  const children = [...nodeEl.querySelectorAll(':scope > .permission-children > .permission-node')];
  if (!children.length) return;
  const leafIds = children.flatMap(child => child.dataset.leafIds.split(',').filter(Boolean));
  const states = children.map(child => {
    const box = child.querySelector(':scope > .permission-option input');
    return box.checked ? 'checked' : box.indeterminate ? 'partial' : 'empty';
  });
  const self = nodeEl.querySelector(':scope > .permission-option input');
  self.checked = states.every(state => state === 'checked');
  self.indeterminate = !self.checked && states.some(state => state !== 'empty');
  nodeEl.dataset.leafIds = leafIds.join(',');
}

function deepestFirst(root) {
  const nodes = [...root.querySelectorAll('.permission-node')];
  return nodes.sort((a, b) => b.querySelectorAll('.permission-node').length - a.querySelectorAll('.permission-node').length);
}

function buildPermissionNode(node, held, depth = 0) {
  const wrapper = el('div', `permission-node depth-${depth}`);
  const row = el('label', 'permission-option');
  const input = el('input');
  input.type = 'checkbox';
  input.dataset.id = node.id;
  const hasChildren = !!(node.children && node.children.length);
  if (!hasChildren) {
    input.value = node.id;
    input.checked = held.has(node.id);
    wrapper.dataset.leafIds = node.id;
  }
  const text = el('span');
  text.append(el('strong', '', node.label));
  if (node.hint) text.append(el('small', '', node.hint));
  row.append(input, text);
  if (hasChildren) {
    const toggle = el('button', 'permission-toggle', '展开');
    toggle.type = 'button';
    row.append(toggle);
  }
  wrapper.append(row);

  if (hasChildren) {
    const children = el('div', 'permission-children');
    children.hidden = true;
    for (const child of node.children) children.append(buildPermissionNode(child, held, depth + 1));
    wrapper.append(children);
    wrapper.dataset.leafIds = collectLeaves(node).join(',');
    const leaves = collectLeaves(node);
    input.checked = leaves.length > 0 && leaves.every(id => held.has(id));
    input.indeterminate = !input.checked && leaves.some(id => held.has(id));

    const toggleButton = row.querySelector('.permission-toggle');
    const setExpanded = expanded => {
      children.hidden = !expanded;
      toggleButton.textContent = expanded ? '收起' : '展开';
      wrapper.classList.toggle('expanded', expanded);
    };
    toggleButton.onclick = event => { event.preventDefault(); setExpanded(children.hidden); };
    input.onchange = () => {
      if (input.checked) {
        setExpanded(true);
        for (const sub of wrapper.querySelectorAll('.permission-children')) sub.hidden = false;
        for (const btn of wrapper.querySelectorAll('.permission-toggle')) btn.textContent = '收起';
      }
      // Every descendant box follows the parent, then each sub-group recomputes itself.
      for (const box of children.querySelectorAll('input[type=checkbox]')) {
        box.checked = input.checked;
        box.indeterminate = false;
      }
      // Recompute bottom-up so parents see their children's final state.
      for (const sub of deepestFirst(wrapper)) syncTreeState(sub);
    };
    if (input.checked) setExpanded(true);
    // Bubble changes from any child up through its groups.
    children.addEventListener('change', event => {
      if (event.target.matches('input[type=checkbox]')) {
        for (const sub of deepestFirst(wrapper)) syncTreeState(sub);
      }
    });
  }
  return wrapper;
}

function openPermission(member) {
  if (!memberMeta.can_grant) {
    $('membersStatus').textContent = '当前账号没有更改权限的资格。';
    return;
  }
  $('permissionTitle').textContent = `更改权限 · ${member.username}`;
  $('permissionStatus').textContent = '';
  const box = $('permissionList');
  box.replaceChildren();
  const held = new Set(member.permissions || []);
  for (const node of (memberMeta.tree || [])) box.append(buildPermissionNode(node, held));
  $('permissionForm').dataset.username = member.username;
  $('permissionDialog').showModal();
}

function openPassword(member) {
  $('memberPasswordForm').reset();
  $('memberPasswordTitle').textContent = `更改密码 · ${member.username}`;
  $('memberPasswordStatus').textContent = '';
  $('memberPasswordForm').dataset.username = member.username;
  $('memberPasswordDialog').showModal();
}

$('membersTab').onclick = () => {
  showPage('members');
  loadMembers();
};
// Filtering is local: the account list is already loaded, so typing never re-queries.
$('memberSearch').addEventListener('input', e => {
  memberQuery = e.target.value.trim().toLowerCase();
  if (memberItems.length) {
    renderMembers();
  } else {
    loadMembers();
  }
});
$('addMember').onclick = () => { $('memberForm').reset(); $('memberFormStatus').textContent = ''; $('memberEditor').showModal(); };
$('closeMember').onclick = () => $('memberEditor').close();
$('closePermission').onclick = () => $('permissionDialog').close();
$('closeMemberPassword').onclick = () => $('memberPasswordDialog').close();

$('memberForm').onsubmit = async e => {
  e.preventDefault();
  const form = e.currentTarget, submit = form.querySelector('[type=submit]');
  submit.disabled = true;
  try {
    const name = form.elements.username.value.trim();
    await api('/api/admin/members', 'POST', {username:name});
    // Close the dialog only after the request succeeds; errors stay visible inside it.
    $('memberEditor').close();
    await loadMembers();
    $('membersStatus').textContent = `账号「${name}」已创建，初始密码为 gg2017。`;
  } catch (err) { $('memberFormStatus').textContent = err.message; }
  finally { submit.disabled = false; }
};

$('permissionForm').onsubmit = async e => {
  e.preventDefault();
  const form = e.currentTarget, submit = form.querySelector('[type=submit]');
  const chosen = [...form.querySelectorAll('#permissionList input[type=checkbox]:checked')]
    .map(i => i.dataset.id).filter(id => !(memberMeta.groups || []).includes(id));
  submit.disabled = true;
  try {
    await api('/api/admin/members/permissions', 'PUT', {username:form.dataset.username, permissions:chosen});
    $('permissionDialog').close();
    await loadMembers();
    $('membersStatus').textContent = `已更新「${form.dataset.username}」的权限。`;
  } catch (err) { $('permissionStatus').textContent = err.message; }
  finally { submit.disabled = false; }
};

$('memberPasswordForm').onsubmit = async e => {
  e.preventDefault();
  const form = e.currentTarget, submit = form.querySelector('[type=submit]');
  submit.disabled = true;
  try {
    await api('/api/admin/members/password', 'PUT', {
      username: form.dataset.username,
      password: form.elements.password.value,
    });
    const name = form.dataset.username;
    $('memberPasswordDialog').close();
    $('membersStatus').textContent = `已更改「${name}」的密码，该账号需重新登录。`;
  } catch (err) { $('memberPasswordStatus').textContent = err.message; }
  finally { submit.disabled = false; }
};
