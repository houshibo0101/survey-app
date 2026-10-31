/* 调查问卷系统 - 前端单页应用（原生 JS，无构建步骤） */

const TYPE_LABEL = { single: '单选题', multi: '多选题', text: '填空题', scale: '量表题' };
const SCALE_DEFAULT = ['非常不同意', '不同意', '一般', '同意', '非常同意'];

const state = {
  me: null,
  authMode: 'login',
  admin: {
    selectedSurvey: 0,
    scope: 0,
    fake: { surveyId: 0, userId: 0 },
    ai: { generated: [], prompts: [] },
  },
};

/* ------------------------------------------------------------------ 工具 */

const $app = () => document.getElementById('app');

function esc(value) {
  return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

async function api(path, options) {
  const opts = Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } }, options || {});
  const response = await fetch(path, opts);
  let data = null;
  try { data = await response.json(); } catch (err) { data = null; }
  if (!response.ok) {
    throw new Error((data && data.error) || ('请求失败（HTTP ' + response.status + '）'));
  }
  return data || {};
}

let toastTimer = null;
function toast(message, isError) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = 'show' + (isError ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { el.className = ''; }, 3600);
}

function openModal(title, bodyHTML, onMount) {
  const root = document.getElementById('modal-root');
  root.innerHTML = '<div class="modal-mask"><div class="modal"><h3>' + esc(title) + '</h3>' + bodyHTML + '</div></div>';
  const mask = root.firstElementChild;
  mask.addEventListener('click', function (event) { if (event.target === mask) closeModal(); });
  if (onMount) onMount(mask);
  return mask;
}

function closeModal() { document.getElementById('modal-root').innerHTML = ''; }

function go(hash) {
  if (location.hash === hash) { render(); } else { location.hash = hash; }
}

function parseHash() {
  const raw = (location.hash || '').replace(/^#/, '') || '/surveys';
  return raw.split('/').filter(Boolean);
}

/* ------------------------------------------------------------------ 启动与路由 */

async function boot() {
  try {
    const data = await api('api/me');
    state.me = data.user || null;
  } catch (err) {
    state.me = null;
  }
  window.addEventListener('hashchange', render);
  render();
}

async function render() {
  if (!state.me) { renderAuth(); return; }
  const parts = parseHash();
  const first = parts[0] || 'surveys';
  try {
    if (first === 'survey' && parts[1]) await renderFill(parts[1]);
    else if (first === 'results' && parts[1]) await renderResults(parts[1]);
    else if (first === 'admin') await renderAdmin(parts[1] || 'users');
    else await renderSurveys();
  } catch (err) {
    $app().innerHTML = '<div class="container"><div class="card empty"><span class="icon">⚠️</span>' +
      esc(err.message) + '<div class="mt16"><button class="btn ghost sm" onclick="render()">重试</button></div></div></div>';
  }
}

/* ------------------------------------------------------------------ 登录 / 注册 */

function renderAuth() {
  const mode = state.authMode;
  $app().innerHTML =
    '<div class="auth-wrap"><div class="auth-card">' +
      '<div class="auth-logo">📋</div>' +
      '<h1>调查问卷系统</h1>' +
      '<div class="sub">' + (mode === 'login' ? '登录后即可填写问卷、查看授权结果' : '注册账号，开始参与问卷调研') + '</div>' +
      '<div class="auth-tabs">' +
        '<button data-mode="login" class="' + (mode === 'login' ? 'active' : '') + '">登录</button>' +
        '<button data-mode="register" class="' + (mode === 'register' ? 'active' : '') + '">注册</button>' +
      '</div>' +
      '<div class="auth-error" id="auth-error"></div>' +
      '<form id="auth-form">' +
        '<div class="field"><label>用户名</label><input type="text" id="auth-username" autocomplete="username" placeholder="请输入用户名"></div>' +
        (mode === 'register' ? '<div class="field"><label>显示名称（选填）</label><input type="text" id="auth-display" placeholder="将展示在答卷中"></div>' : '') +
        '<div class="field"><label>密码</label><input type="password" id="auth-password" autocomplete="' + (mode === 'login' ? 'current-password' : 'new-password') + '" placeholder="至少 6 位"></div>' +
        '<button class="btn block" type="submit">' + (mode === 'login' ? '登 录' : '注 册') + '</button>' +
      '</form>' +
      '<div class="auth-foot">管理员账号由部署者创建；普通参与者可直接注册。</div>' +
    '</div></div>';

  $app().querySelectorAll('.auth-tabs button').forEach(function (btn) {
    btn.onclick = function () {
      state.authMode = btn.dataset.mode;
      renderAuth();
    };
  });

  const form = document.getElementById('auth-form');
  const errorEl = document.getElementById('auth-error');
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value;
    const display = mode === 'register' ? document.getElementById('auth-display').value.trim() : '';
    errorEl.classList.remove('show');
    if (!username || !password) { errorEl.textContent = '请填写用户名和密码'; errorEl.classList.add('show'); return; }
    const submitBtn = form.querySelector('button[type=submit]');
    submitBtn.disabled = true;
    try {
      const payload = { username: username, password: password };
      if (mode === 'register') payload.display_name = display;
      const data = await api(mode === 'login' ? 'api/login' : 'api/register', { method: 'POST', body: JSON.stringify(payload) });
      state.me = data.user;
      toast(mode === 'login' ? '欢迎回来，' + data.user.display_name : '注册成功，欢迎加入');
      if (location.hash && location.hash !== '#/login' && location.hash !== '#/register' && location.hash !== '#/') {
        render();
      } else {
        go('#/surveys');
      }
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.add('show');
    } finally {
      submitBtn.disabled = false;
    }
  });
}

async function logout() {
  try { await api('api/logout', { method: 'POST' }); } catch (err) { /* 忽略 */ }
  state.me = null;
  go('#/surveys');
}

/* ------------------------------------------------------------------ 布局 */

function layout(inner, active) {
  const u = state.me;
  const initial = (u.display_name || u.username || '?').slice(0, 1).toUpperCase();
  const mobileNav = '<nav class="mobile-nav">' +
    '<a href="#/surveys" class="' + (active === 'surveys' ? 'active' : '') + '"><span class="ico">📋</span><span>问卷</span></a>' +
    (u.is_admin ? '<a href="#/admin/users" class="' + (active === 'admin' ? 'active' : '') + '"><span class="ico">⚙️</span><span>管理</span></a>' : '') +
    '<button type="button" data-act="pwd"><span class="ico">🔑</span><span>改密</span></button>' +
    '<button type="button" data-act="logout"><span class="ico">🚪</span><span>退出</span></button>' +
  '</nav>';
  return '<header class="topbar">' +
    '<div class="brand" data-act="home"><span class="logo">📋</span><span>调查问卷系统</span></div>' +
    '<nav class="topnav">' +
      '<a href="#/surveys" class="' + (active === 'surveys' ? 'active' : '') + '">问卷</a>' +
      (u.is_admin ? '<a href="#/admin/users" class="' + (active === 'admin' ? 'active' : '') + '">管理后台</a>' : '') +
    '</nav>' +
    '<div class="userbox">' +
      '<div class="avatar">' + esc(initial) + '</div>' +
      '<div class="userinfo"><div class="uname">' + esc(u.display_name) + '</div><div class="urole">' + (u.is_admin ? '管理员' : '参与者') + '</div></div>' +
      '<button class="btn ghost sm" data-act="pwd">修改密码</button>' +
      '<button class="btn ghost sm" data-act="logout">退出</button>' +
    '</div>' +
  '</header><main class="container">' + inner + '</main>' + mobileNav;
}

function bindCommon() {
  $app().querySelectorAll('[data-act]').forEach(function (el) {
    const act = el.dataset.act;
    if (act === 'home') el.onclick = function () { go('#/surveys'); };
    else if (act === 'logout') el.onclick = logout;
    else if (act === 'pwd') el.onclick = openPasswordModal;
  });
}

function mount(inner, active) {
  $app().innerHTML = layout(inner, active);
  bindCommon();
}

/* ------------------------------------------------------------------ 问卷列表 */

async function renderSurveys() {
  const data = await api('api/surveys');
  const surveys = data.surveys || [];
  const hero = '<div class="hero">' +
    '<div class="hero-glow"></div><div class="hero-glow two"></div>' +
    '<h2>让每一次调研都有据可依</h2>' +
    '<p>注册登录后即可参与问卷；谁能查看谁的答卷，由管理员按人授权；题目也可以交给 AI 按提示词快速生成。</p>' +
  '</div>';

  const cards = surveys.map(function (s) {
    return '<div class="survey-card">' +
      '<div class="top">' +
        '<span class="chip ' + (s.status === 'open' ? 'open' : 'closed') + '">' + (s.status === 'open' ? '进行中' : '已结束') + '</span>' +
        '<span class="muted small">' + s.question_count + ' 题</span>' +
      '</div>' +
      '<h3>' + esc(s.title) + '</h3>' +
      '<p>' + (esc(s.description) || '暂无说明') + '</p>' +
      '<div class="meta"><span>已收集 ' + s.response_count + ' 份</span>' + (s.answered ? '<span class="chip self">已填写</span>' : '') + '</div>' +
      '<div class="actions">' +
        '<a class="btn sm" href="#/survey/' + s.id + '">' + (s.answered ? '修改答卷' : '开始填写') + '</a>' +
        '<a class="btn ghost sm" href="#/results/' + s.id + '">查看结果</a>' +
      '</div>' +
    '</div>';
  }).join('');

  const list = surveys.length
    ? '<div class="grid cards">' + cards + '</div>'
    : '<div class="card empty"><span class="icon">🗂️</span>还没有可填写的问卷，请联系管理员创建。</div>';

  mount(hero + list, 'surveys');
}

/* ------------------------------------------------------------------ 填写问卷 */

function questionHTML(question, index, answers, closed) {
  const value = answers[String(question.id)];
  const required = question.required ? ' · <span class="req">必答</span>' : '';
  const head = '<div class="qtitle"><span class="num">' + (index + 1) + '.</span><span>' + esc(question.title) + '</span></div>' +
    '<div class="qtype">' + (TYPE_LABEL[question.qtype] || question.qtype) + required + '</div>';
  let controls = '';
  const options = question.options || [];

  if (question.qtype === 'single') {
    controls = options.map(function (opt) {
      const checked = value === opt;
      return '<label class="opt' + (checked ? ' checked' : '') + '">' +
        '<input type="radio" name="q' + question.id + '" value="' + esc(opt) + '"' + (checked ? ' checked' : '') + (closed ? ' disabled' : '') + '>' +
        '<span>' + esc(opt) + '</span></label>';
    }).join('');
  } else if (question.qtype === 'multi') {
    const list = Array.isArray(value) ? value : [];
    controls = options.map(function (opt) {
      const checked = list.indexOf(opt) >= 0;
      return '<label class="opt' + (checked ? ' checked' : '') + '">' +
        '<input type="checkbox" name="q' + question.id + '" value="' + esc(opt) + '"' + (checked ? ' checked' : '') + (closed ? ' disabled' : '') + '>' +
        '<span>' + esc(opt) + '</span></label>';
    }).join('');
  } else if (question.qtype === 'scale') {
    const labels = options.length === 5 ? options : SCALE_DEFAULT;
    const current = Number(value) || 0;
    controls = '<div class="scale-row">' + labels.map(function (label, i) {
      const checked = current === i + 1;
      return '<label class="opt scale-opt' + (checked ? ' checked' : '') + '">' +
        '<input type="radio" name="q' + question.id + '" value="' + (i + 1) + '"' + (checked ? ' checked' : '') + (closed ? ' disabled' : '') + '>' +
        '<span>' + esc(label) + '</span></label>';
    }).join('') + '</div>';
  } else {
    controls = '<textarea name="q' + question.id + '" rows="4" placeholder="请输入你的回答"' + (closed ? ' disabled' : '') + '>' +
      esc(value || '') + '</textarea>';
  }

  return '<div class="question">' + head + controls + '</div>';
}

function collectAnswers(questions) {
  const answers = {};
  questions.forEach(function (q) {
    const name = 'q' + q.id;
    if (q.qtype === 'multi') {
      answers[q.id] = Array.from(document.querySelectorAll('input[name="' + name + '"]:checked')).map(function (input) { return input.value; });
    } else if (q.qtype === 'text') {
      const el = document.querySelector('[name="' + name + '"]');
      answers[q.id] = el ? el.value.trim() : '';
    } else if (q.qtype === 'scale') {
      const checked = document.querySelector('input[name="' + name + '"]:checked');
      answers[q.id] = checked ? Number(checked.value) : null;
    } else {
      const checked = document.querySelector('input[name="' + name + '"]:checked');
      answers[q.id] = checked ? checked.value : null;
    }
  });
  return answers;
}

async function renderFill(id) {
  const data = await api('api/surveys/' + id);
  const survey = data.survey;
  const questions = data.questions || [];
  const closed = survey.status !== 'open';

  const body = questions.map(function (q, index) {
    return questionHTML(q, index, data.answers || {}, closed);
  }).join('');

  mount(
    '<div class="page-head"><div><h1>' + esc(survey.title) + '</h1><div class="sub">' + (esc(survey.description) || '') + '</div></div>' +
      '<a class="btn ghost sm" href="#/surveys">返回列表</a></div>' +
    (closed ? '<div class="tip">该问卷已结束，仅可查看内容，无法提交。</div>' : '') +
    (data.answered ? '<div class="tip info">你已经提交过这份问卷，再次提交将覆盖之前的答卷。</div>' : '') +
    '<form id="fill-form">' + body + '</form>' +
    '<div class="flex mt16">' +
      '<button class="btn" id="fill-submit"' + (closed ? ' disabled' : '') + '>提交答卷</button>' +
      '<span class="muted small">共 ' + questions.length + ' 题' + (data.answered ? ' · 已填写过' : '') + '</span>' +
    '</div>',
    'surveys'
  );

  const form = document.getElementById('fill-form');
  if (!form) return;
  form.addEventListener('change', function (event) {
    const input = event.target;
    if (!input.matches('input[type=radio],input[type=checkbox]')) return;
    if (input.type === 'radio') {
      form.querySelectorAll('input[name="' + input.name + '"]').forEach(function (radio) {
        radio.closest('.opt').classList.toggle('checked', radio.checked);
      });
    } else {
      input.closest('.opt').classList.toggle('checked', input.checked);
    }
  });

  const submitBtn = document.getElementById('fill-submit');
  if (submitBtn && !closed) {
    submitBtn.onclick = async function () {
      submitBtn.disabled = true;
      try {
        await api('api/surveys/' + id + '/submit', { method: 'POST', body: JSON.stringify({ answers: collectAnswers(questions) }) });
        toast('提交成功');
        go('#/results/' + id);
      } catch (err) {
        toast(err.message, true);
        submitBtn.disabled = false;
      }
    };
  }
}

/* ------------------------------------------------------------------ 结果 */

function formatAnswer(question, value) {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) {
    return '<span class="muted">—</span>';
  }
  if (question.qtype === 'multi' && Array.isArray(value)) {
    return value.map(esc).join('、');
  }
  return esc(value);
}

function renderAggregate(item) {
  if (item.qtype === 'text') {
    const list = (item.texts || []).map(function (t) { return '<li>' + esc(t) + '</li>'; }).join('');
    return '<div class="agg"><div class="agg-title">' + esc(item.title) + ' <span class="muted small">共 ' + item.total + ' 份</span></div>' +
      (list ? '<ul class="text-list">' + list + '</ul>' : '<div class="muted small">暂无文字回答</div>') + '</div>';
  }
  const total = item.total || 0;
  const counts = item.counts || [];
  const max = Math.max.apply(null, [1].concat(counts.map(function (c) { return c.count; })));
  const rows = counts.map(function (c) {
    let label = c.option;
    if (item.qtype === 'scale') label = (item.options && item.options[Number(c.option) - 1]) || c.option;
    const pct = total ? Math.round((c.count / total) * 100) : 0;
    return '<div class="bar-row">' +
      '<div class="bar-label" title="' + esc(label) + '">' + esc(label) + '</div>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + Math.max((c.count / max) * 100, c.count ? 3 : 0) + '%"></div></div>' +
      '<div class="bar-count">' + c.count + ' · ' + pct + '%</div>' +
    '</div>';
  }).join('');
  return '<div class="agg"><div class="agg-title">' + esc(item.title) + ' <span class="muted small">共 ' + total + ' 份</span></div>' + rows + '</div>';
}

async function renderResults(id) {
  const data = await api('api/surveys/' + id + '/results');
  const survey = data.survey;
  const questions = data.questions || [];
  const responses = data.responses || [];

  let aggregateHTML = '';
  if (data.can_view_aggregate) {
    const items = (data.aggregate || []).map(renderAggregate).join('');
    aggregateHTML = '<div class="card"><h3>统计概览</h3>' + (items || '<div class="empty">暂无答卷</div>') + '</div>';
  }

  let tableHTML = '';
  if (responses.length) {
    const head = '<tr><th>提交人</th><th>提交时间</th>' +
      questions.map(function (q) { return '<th title="' + esc(q.title) + '">' + esc(q.title.slice(0, 14)) + (q.title.length > 14 ? '…' : '') + '</th>'; }).join('') +
      '</tr>';
    const rows = responses.map(function (r) {
      const cells = questions.map(function (q) {
        const label = q.title.length > 12 ? q.title.slice(0, 12) + '…' : q.title;
        return '<td data-label="' + esc(label) + '">' + formatAnswer(q, r.answers[String(q.id)]) + '</td>';
      }).join('');
      return '<tr><td class="nowrap" data-label="提交人">' + esc(r.display_name) + (r.is_self ? ' <span class="chip self">我</span>' : '') +
        '<div class="muted small">@' + esc(r.username) + '</div></td>' +
        '<td class="nowrap muted" data-label="提交时间">' + esc(r.submitted_at) + '</td>' + cells + '</tr>';
    }).join('');
    tableHTML = '<div class="table-wrap"><table class="data results-table"><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div>';
  } else {
    tableHTML = '<div class="empty"><span class="icon">📭</span>暂无可查看的答卷</div>';
  }

  const scopeTip = data.can_view_all
    ? '<div class="tip ok">你是管理员，可以查看全部答卷与统计。</div>'
    : '<div class="tip info">你当前可以查看：管理员授权给你的成员，以及你自己的答卷。</div>';

  mount(
    '<div class="page-head"><div><h1>' + esc(survey.title) + ' · 结果</h1>' +
      '<div class="sub">' + esc(survey.description || '') + '</div></div>' +
      '<div class="flex"><a class="btn ghost sm" href="#/survey/' + survey.id + '">去填写</a>' +
      '<a class="btn ghost sm" href="#/surveys">返回列表</a></div></div>' +
    scopeTip +
    '<div class="card"><div class="flex mb16"><h3 style="margin:0">答卷明细 <span class="muted small">（' + responses.length + ' 份）</span></h3>' +
      '<span class="chip ' + (survey.status === 'open' ? 'open' : 'closed') + ' right">' + (survey.status === 'open' ? '进行中' : '已结束') + '</span></div>' +
      tableHTML + '</div>' +
    aggregateHTML,
    'surveys'
  );
}

/* ------------------------------------------------------------------ 管理后台 */

const ADMIN_TABS = [
  ['users', '用户管理'],
  ['surveys', '问卷管理'],
  ['visibility', '结果可见性'],
  ['fake', '虚假选项'],
  ['ai', 'AI 出题'],
  ['settings', '系统设置'],
];

async function renderAdmin(tab) {
  if (!state.me.is_admin) { toast('需要管理员权限', true); go('#/surveys'); return; }
  const nav = '<div class="admin-nav">' + ADMIN_TABS.map(function (item) {
    return '<a href="#/admin/' + item[0] + '" class="' + (item[0] === tab ? 'active' : '') + '">' + item[1] + '</a>';
  }).join('') + '</div>';

  $app().innerHTML = layout('<div class="admin-layout">' + nav +
    '<div class="admin-body" id="admin-body"><div class="loading">加载中…</div></div></div>', 'admin');
  bindCommon();

  const body = document.getElementById('admin-body');
  if (tab === 'surveys') await adminSurveys(body);
  else if (tab === 'visibility') await adminVisibility(body);
  else if (tab === 'fake') await adminFake(body);
  else if (tab === 'ai') await adminAi(body);
  else if (tab === 'settings') await adminSettings(body);
  else await adminUsers(body);
}

/* ------------------------------------------------------------------ 管理：用户 */

async function adminUsers(body) {
  const data = await api('api/admin/users');
  const users = data.users || [];
  const rows = users.map(function (u) {
    return '<tr>' +
      '<td class="nowrap muted" data-label="ID">' + u.id + '</td>' +
      '<td data-label="用户名"><strong>' + esc(u.username) + '</strong></td>' +
      '<td data-label="显示名称">' + esc(u.display_name) + '</td>' +
      '<td data-label="角色">' + (u.is_admin ? '<span class="chip admin">管理员</span>' : '<span class="chip">参与者</span>') + '</td>' +
      '<td data-label="答卷数">' + u.response_count + '</td>' +
      '<td class="nowrap muted" data-label="创建时间">' + esc(u.created_at) + '</td>' +
      '<td class="nowrap" data-label="操作"><div class="row-actions">' +
        (u.is_admin
          ? '<button class="btn ghost sm" data-op="demote" data-id="' + u.id + '">取消管理员</button>'
          : '<button class="btn soft sm" data-op="promote" data-id="' + u.id + '">设为管理员</button>') +
        '<button class="btn ghost sm" data-op="reset" data-id="' + u.id + '" data-name="' + esc(u.username) + '">重置密码</button>' +
        '<button class="btn danger-ghost sm" data-op="del" data-id="' + u.id + '" data-name="' + esc(u.username) + '">删除</button>' +
      '</div></td>' +
    '</tr>';
  }).join('');

  body.innerHTML =
    '<div class="card">' +
      '<h3>新增用户</h3>' +
      '<form id="user-form" class="form-row three">' +
        '<div class="field"><label>用户名</label><input id="u-username" type="text" placeholder="登录用户名"></div>' +
        '<div class="field"><label>显示名称</label><input id="u-display" type="text" placeholder="选填"></div>' +
        '<div class="field"><label>初始密码</label><input id="u-password" type="text" placeholder="至少 6 位"></div>' +
        '<div class="field" style="grid-column:1/-1"><label class="check"><input type="checkbox" id="u-admin"> 设为管理员</label></div>' +
        '<div class="field" style="grid-column:1/-1"><button class="btn sm" type="submit">创建用户</button></div>' +
      '</form>' +
    '</div>' +
    '<div class="card"><h3>用户列表（' + users.length + '）</h3>' +
      '<div class="table-wrap"><table class="data"><thead><tr><th>ID</th><th>用户名</th><th>显示名称</th><th>角色</th><th>答卷数</th><th>创建时间</th><th>操作</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="7" class="muted">暂无用户</td></tr>') + '</tbody></table></div></div>';

  const form = document.getElementById('user-form');
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    try {
      await api('api/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          username: document.getElementById('u-username').value.trim(),
          display_name: document.getElementById('u-display').value.trim(),
          password: document.getElementById('u-password').value,
          is_admin: document.getElementById('u-admin').checked,
        }),
      });
      toast('用户已创建');
      await adminUsers(body);
    } catch (err) { toast(err.message, true); }
  });

  body.querySelector('table').addEventListener('click', async function (event) {
    const btn = event.target.closest('[data-op]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const name = btn.dataset.name || '';
    try {
      if (btn.dataset.op === 'promote') {
        await api('api/admin/users/' + id, { method: 'PATCH', body: JSON.stringify({ is_admin: true }) });
        toast('已设为管理员');
      } else if (btn.dataset.op === 'demote') {
        await api('api/admin/users/' + id, { method: 'PATCH', body: JSON.stringify({ is_admin: false }) });
        toast('已取消管理员');
      } else if (btn.dataset.op === 'reset') {
        const password = window.prompt('为「' + name + '」设置新密码（至少 6 位）');
        if (!password) return;
        await api('api/admin/users/' + id + '/password', { method: 'POST', body: JSON.stringify({ password: password }) });
        toast('密码已重置');
      } else if (btn.dataset.op === 'del') {
        if (!window.confirm('确定删除用户「' + name + '」？该用户的答卷会一并删除。')) return;
        await api('api/admin/users/' + id, { method: 'DELETE' });
        toast('用户已删除');
      }
      await adminUsers(body);
    } catch (err) { toast(err.message, true); }
  });
}

/* ------------------------------------------------------------------ 管理：问卷 */

async function adminSurveys(body) {
  const data = await api('api/surveys');
  const surveys = data.surveys || [];
  if (!state.admin.selectedSurvey && surveys.length) state.admin.selectedSurvey = surveys[0].id;
  if (state.admin.selectedSurvey && !surveys.some(function (s) { return s.id === state.admin.selectedSurvey; })) {
    state.admin.selectedSurvey = surveys.length ? surveys[0].id : 0;
  }
  const selected = state.admin.selectedSurvey;

  const options = surveys.map(function (s) {
    return '<option value="' + s.id + '"' + (s.id === selected ? ' selected' : '') + '>' + esc(s.title) + '</option>';
  }).join('');

  body.innerHTML =
    '<div class="card">' +
      '<div class="toolbar">' +
        '<select id="survey-select">' + (options || '<option value="">暂无问卷</option>') + '</select>' +
        '<button class="btn soft sm" data-op="new">＋ 新建问卷</button>' +
        (selected ? '<a class="btn ghost sm" href="#/results/' + selected + '">查看结果</a>' : '') +
        (selected ? '<button class="btn danger-ghost sm" data-op="del-survey">删除问卷</button>' : '') +
      '</div>' +
      (selected ? '<div id="survey-editor"></div>' : '<div class="empty"><span class="icon">🗂️</span>还没有问卷，点击「新建问卷」创建第一份。</div>') +
    '</div>';

  const select = document.getElementById('survey-select');
  select.onchange = function () {
    state.admin.selectedSurvey = Number(select.value) || 0;
    adminSurveys(body);
  };

  body.addEventListener('click', async function (event) {
    const btn = event.target.closest('[data-op]');
    if (!btn || btn.dataset.op !== 'new') return;
    openModal('新建问卷',
      '<div class="field"><label>问卷标题</label><input id="ns-title" type="text" placeholder="例如：秋季用户满意度调研"></div>' +
      '<div class="field"><label>问卷说明</label><textarea id="ns-desc" rows="3" placeholder="选填"></textarea></div>' +
      '<div class="modal-actions"><button class="btn ghost" id="ns-cancel">取消</button><button class="btn" id="ns-ok">创建</button></div>',
      function (mask) {
        mask.querySelector('#ns-cancel').onclick = closeModal;
        mask.querySelector('#ns-ok').onclick = async function () {
          try {
            const title = mask.querySelector('#ns-title').value.trim();
            const description = mask.querySelector('#ns-desc').value.trim();
            const created = await api('api/admin/surveys', { method: 'POST', body: JSON.stringify({ title: title, description: description }) });
            state.admin.selectedSurvey = created.survey.id;
            closeModal();
            toast('问卷已创建');
            await adminSurveys(body);
          } catch (err) { toast(err.message, true); }
        };
      });
  });

  if (selected) {
    const delBtn = body.querySelector('[data-op="del-survey"]');
    if (delBtn) {
      delBtn.onclick = async function () {
        if (!window.confirm('确定删除这份问卷及其全部答卷？此操作不可恢复。')) return;
        try {
          await api('api/admin/surveys/' + selected, { method: 'DELETE' });
          toast('问卷已删除');
          state.admin.selectedSurvey = 0;
          await adminSurveys(body);
        } catch (err) { toast(err.message, true); }
      };
    }
    await renderSurveyEditor(document.getElementById('survey-editor'), selected);
  }
}

async function renderSurveyEditor(container, surveyId) {
  if (!container) return;
  const data = await api('api/admin/surveys/' + surveyId);
  const survey = data.survey;
  const questions = data.questions || [];

  const questionRows = questions.map(function (q, index) {
    const optionText = (q.options || []).join(' / ');
    return '<tr>' +
      '<td class="nowrap muted" data-label="#">' + (index + 1) + '</td>' +
      '<td class="nowrap" data-label="题型">' + (TYPE_LABEL[q.qtype] || q.qtype) + '</td>' +
      '<td data-label="题干">' + esc(q.title) + (q.required ? ' <span class="chip">必答</span>' : '') + '</td>' +
      '<td class="muted small" data-label="选项">' + (optionText ? esc(optionText.slice(0, 60)) + (optionText.length > 60 ? '…' : '') : '—') + '</td>' +
      '<td class="nowrap" data-label="操作"><div class="row-actions">' +
        '<button class="btn ghost sm" data-op="edit-q" data-id="' + q.id + '">编辑</button>' +
        '<button class="btn danger-ghost sm" data-op="del-q" data-id="' + q.id + '">删除</button>' +
      '</div></td>' +
    '</tr>';
  }).join('');

  container.innerHTML =
    '<div class="divider"></div>' +
    '<form id="survey-meta" class="form-row three">' +
      '<div class="field" style="grid-column:1/3"><label>问卷标题</label><input id="s-title" type="text" value="' + esc(survey.title) + '"></div>' +
      '<div class="field"><label>状态</label><select id="s-status">' +
        '<option value="open"' + (survey.status === 'open' ? ' selected' : '') + '>进行中</option>' +
        '<option value="closed"' + (survey.status === 'closed' ? ' selected' : '') + '>已结束</option>' +
      '</select></div>' +
      '<div class="field" style="grid-column:1/-1"><label>问卷说明</label><textarea id="s-desc" rows="2">' + esc(survey.description) + '</textarea></div>' +
      '<div class="field" style="grid-column:1/-1"><button class="btn sm" type="submit">保存问卷信息</button></div>' +
    '</form>' +
    '<h3 class="mt16">题目（' + questions.length + '）</h3>' +
    (questions.length
      ? '<div class="table-wrap"><table class="data"><thead><tr><th>#</th><th>题型</th><th>题干</th><th>选项</th><th>操作</th></tr></thead><tbody>' + questionRows + '</tbody></table></div>'
      : '<div class="empty">还没有题目，可以在下面添加，或到「AI 出题」批量生成。</div>') +
    '<div class="divider"></div>' +
    '<h3 id="q-form-title">新增题目</h3>' +
    '<form id="q-form">' +
      '<div class="form-row">' +
        '<div class="field"><label>题型</label><select id="q-type">' +
          '<option value="single">单选题</option><option value="multi">多选题</option><option value="text">填空题</option><option value="scale">量表题</option>' +
        '</select></div>' +
        '<div class="field"><label>题干</label><input id="q-title" type="text" placeholder="例如：你对本次活动的整体满意度是？"></div>' +
      '</div>' +
      '<div class="field"><label>选项（每行一个，选择题必填）</label><textarea id="q-options" rows="3" placeholder="非常满意&#10;满意&#10;一般&#10;不满意"></textarea></div>' +
      '<div class="flex"><label class="check"><input type="checkbox" id="q-required" checked> 必答</label>' +
        '<button class="btn sm right" type="submit" id="q-submit">添加到问卷</button>' +
        '<button class="btn ghost sm" type="button" id="q-cancel" style="display:none">取消编辑</button>' +
      '</div>' +
    '</form>';

  let editingId = 0;

  document.getElementById('survey-meta').addEventListener('submit', async function (event) {
    event.preventDefault();
    try {
      await api('api/admin/surveys/' + surveyId, {
        method: 'PUT',
        body: JSON.stringify({
          title: document.getElementById('s-title').value.trim(),
          description: document.getElementById('s-desc').value.trim(),
          status: document.getElementById('s-status').value,
        }),
      });
      toast('问卷信息已保存');
    } catch (err) { toast(err.message, true); }
  });

  const typeSelect = document.getElementById('q-type');
  typeSelect.onchange = function () {
    const isText = typeSelect.value === 'text';
    const optionsBox = document.getElementById('q-options');
    optionsBox.disabled = isText;
    optionsBox.style.opacity = isText ? '.5' : '1';
    if (typeSelect.value === 'scale') {
      optionsBox.value = SCALE_DEFAULT.join('\n');
      optionsBox.disabled = false;
      optionsBox.style.opacity = '1';
    }
  };

  const form = document.getElementById('q-form');
  const submitBtn = document.getElementById('q-submit');

  function resetForm() {
    editingId = 0;
    form.reset();
    document.getElementById('q-type').value = 'single';
    document.getElementById('q-title').value = '';
    document.getElementById('q-options').value = '';
    document.getElementById('q-options').disabled = false;
    document.getElementById('q-options').style.opacity = '1';
    document.getElementById('q-required').checked = true;
    document.getElementById('q-form-title').textContent = '新增题目';
    submitBtn.textContent = '添加到问卷';
    document.getElementById('q-cancel').style.display = 'none';
  }

  document.getElementById('q-cancel').onclick = resetForm;

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    const payload = {
      qtype: document.getElementById('q-type').value,
      title: document.getElementById('q-title').value.trim(),
      options: document.getElementById('q-options').value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean),
      required: document.getElementById('q-required').checked,
    };
    try {
      if (editingId) {
        await api('api/admin/questions/' + editingId, { method: 'PUT', body: JSON.stringify(payload) });
        toast('题目已更新');
      } else {
        await api('api/admin/surveys/' + surveyId + '/questions', { method: 'POST', body: JSON.stringify(payload) });
        toast('题目已添加');
      }
      await renderSurveyEditor(container, surveyId);
    } catch (err) { toast(err.message, true); }
  });

  container.addEventListener('click', async function (event) {
    const btn = event.target.closest('[data-op]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    if (btn.dataset.op === 'del-q') {
      if (!window.confirm('删除这道题目？')) return;
      try {
        await api('api/admin/questions/' + id, { method: 'DELETE' });
        toast('题目已删除');
        await renderSurveyEditor(container, surveyId);
      } catch (err) { toast(err.message, true); }
    } else if (btn.dataset.op === 'edit-q') {
      const question = questions.find(function (q) { return q.id === id; });
      if (!question) return;
      editingId = id;
      document.getElementById('q-form-title').textContent = '编辑题目';
      submitBtn.textContent = '保存修改';
      document.getElementById('q-cancel').style.display = '';
      document.getElementById('q-type').value = question.qtype;
      document.getElementById('q-title').value = question.title;
      const optionsBox = document.getElementById('q-options');
      optionsBox.value = (question.options || []).join('\n');
      optionsBox.disabled = question.qtype === 'text';
      optionsBox.style.opacity = question.qtype === 'text' ? '.5' : '1';
      document.getElementById('q-required').checked = !!question.required;
      container.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
}

/* ------------------------------------------------------------------ 管理：可见性 */

async function adminVisibility(body) {
  const data = await api('api/admin/visibility');
  const users = data.users || [];
  const pairs = data.pairs || [];
  const surveys = data.surveys || [];
  const scope = state.admin.scope || 0;

  function hasPair(viewerId, targetId) {
    return pairs.some(function (p) { return p.viewer_id === viewerId && p.target_id === targetId && p.survey_id === scope; });
  }

  const scopeOptions = '<option value="0"' + (scope === 0 ? ' selected' : '') + '>全部问卷</option>' +
    surveys.map(function (s) {
      return '<option value="' + s.id + '"' + (scope === s.id ? ' selected' : '') + '>' + esc(s.title) + '</option>';
    }).join('');

  const head = '<tr><th class="corner">被查看者 ↓ ／ 查看者 →</th>' +
    users.map(function (u) { return '<th>' + esc(u.display_name) + '</th>'; }).join('') + '</tr>';

  const rows = users.map(function (target) {
    const cells = users.map(function (viewer) {
      if (viewer.id === target.id) return '<td class="diag">—</td>';
      const checked = hasPair(viewer.id, target.id);
      return '<td><input type="checkbox" data-v="' + viewer.id + '" data-t="' + target.id + '"' + (checked ? ' checked' : '') + '></td>';
    }).join('');
    return '<tr><td class="rowhead">' + esc(target.display_name) + '</td>' + cells + '</tr>';
  }).join('');

  body.innerHTML =
    '<div class="card">' +
      '<div class="flex mb16">' +
        '<div class="field" style="margin:0"><label>适用范围</label><select id="scope-select">' + scopeOptions + '</select></div>' +
        '<button class="btn ghost sm right" data-op="clear">清空当前范围</button>' +
      '</div>' +
      '<div class="tip info">勾选表示「查看者」可以查看「被查看者」的答卷。管理员始终可以查看全部结果，无需在此配置。</div>' +
      '<div class="matrix-wrap"><table class="matrix"><thead>' + head + '</thead><tbody>' + rows + '</tbody></table></div>' +
      '<div class="muted small mt8">提示：「全部问卷」中的授权对所有问卷生效；选择具体问卷时，只显示该问卷的授权。</div>' +
    '</div>';

  document.getElementById('scope-select').onchange = function (event) {
    state.admin.scope = Number(event.target.value) || 0;
    adminVisibility(body);
  };

  body.querySelector('.matrix').addEventListener('change', async function (event) {
    const input = event.target;
    if (!input.matches('input[type=checkbox]')) return;
    const viewerId = Number(input.dataset.v);
    const targetId = Number(input.dataset.t);
    input.disabled = true;
    try {
      await api('api/admin/visibility', {
        method: 'PUT',
        body: JSON.stringify({ viewer_id: viewerId, target_id: targetId, survey_id: scope, enabled: input.checked }),
      });
      toast(input.checked ? '已授权查看' : '已取消授权');
    } catch (err) {
      input.checked = !input.checked;
      toast(err.message, true);
    } finally {
      input.disabled = false;
    }
  });

  body.querySelector('[data-op="clear"]').onclick = async function () {
    if (!window.confirm('清空当前范围下的全部授权？')) return;
    try {
      await api('api/admin/visibility/clear', { method: 'POST', body: JSON.stringify({ survey_id: scope }) });
      toast('已清空');
      await adminVisibility(body);
    } catch (err) { toast(err.message, true); }
  };
}

/* ------------------------------------------------------------------ 管理：虚假选项 */

async function adminFake(body) {
  const [userData, surveyData] = await Promise.all([api('api/admin/users'), api('api/surveys')]);
  const users = userData.users || [];
  const surveys = surveyData.surveys || [];
  const fake = state.admin.fake;
  if (!fake.surveyId && surveys.length) fake.surveyId = surveys[0].id;
  if (!fake.userId && users.length) fake.userId = users[0].id;
  if (!surveys.some(function (s) { return s.id === fake.surveyId; })) fake.surveyId = surveys.length ? surveys[0].id : 0;
  if (!users.some(function (u) { return u.id === fake.userId; })) fake.userId = users.length ? users[0].id : 0;

  const surveyOptions = surveys.map(function (s) {
    return '<option value="' + s.id + '"' + (s.id === fake.surveyId ? ' selected' : '') + '>' + esc(s.title) + '</option>';
  }).join('');
  const userOptions = users.map(function (u) {
    return '<option value="' + u.id + '"' + (u.id === fake.userId ? ' selected' : '') + '>' + esc(u.display_name) + '（' + esc(u.username) + '）</option>';
  }).join('');

  body.innerHTML =
    '<div class="card">' +
      '<div class="flex mb16">' +
        '<div class="field" style="margin:0"><label>问卷</label><select id="fake-survey">' + (surveyOptions || '<option value="">暂无问卷</option>') + '</select></div>' +
        '<div class="field" style="margin:0"><label>受访者</label><select id="fake-user">' + (userOptions || '<option value="">暂无用户</option>') + '</select></div>' +
      '</div>' +
      '<div class="tip">为指定用户替换他在问卷中看到的选择项（例如把真实搭档姓名换成虚构姓名）。该设置只影响这位用户的作答界面，提交后按他实际看到的内容保存。</div>' +
      '<div id="fake-list"><div class="loading">加载中…</div></div>' +
    '</div>';

  document.getElementById('fake-survey').onchange = function (event) {
    state.admin.fake.surveyId = Number(event.target.value) || 0;
    adminFake(body);
  };
  document.getElementById('fake-user').onchange = function (event) {
    state.admin.fake.userId = Number(event.target.value) || 0;
    adminFake(body);
  };

  const list = document.getElementById('fake-list');
  if (!fake.surveyId || !fake.userId) {
    list.innerHTML = '<div class="empty">请先创建问卷和用户。</div>';
    return;
  }

  const preview = await api('api/admin/fake-options/preview?user_id=' + fake.userId + '&survey_id=' + fake.surveyId);
  const questions = preview.questions || [];

  list.innerHTML = questions.map(function (q) {
    const editable = q.qtype === 'single' || q.qtype === 'multi';
    const real = (q.real_options || []).join('、');
    const seen = q.faked ? (q.seen_options || []).join('，') : '';
    return '<div class="ai-q">' +
      '<div class="ai-q-title">' + esc(q.title) + ' <span class="tag">' + (TYPE_LABEL[q.qtype] || q.qtype) + '</span>' +
        (q.faked ? ' <span class="chip fake">已伪装</span>' : '') + '</div>' +
      '<div class="ai-q-opts">真实选项：' + (real ? esc(real) : '（无，填空/量表）') + '</div>' +
      (editable
        ? '<div class="field mt8" style="margin-bottom:8px"><label>该用户看到的选项（用逗号分隔；留空则恢复真实选项）</label>' +
            '<input type="text" data-q="' + q.id + '" value="' + esc(seen) + '" placeholder="例如：张三，李四，王五"></div>' +
          '<div class="flex"><button class="btn sm" data-save="' + q.id + '">保存伪装</button>' +
            (q.faked ? '<button class="btn ghost sm" data-clear="' + q.id + '">恢复真实选项</button>' : '') + '</div>'
        : '<div class="muted small">仅选择题支持设置虚假选项。</div>') +
    '</div>';
  }).join('') || '<div class="empty">该问卷暂无题目</div>';

  list.addEventListener('click', async function (event) {
    const saveBtn = event.target.closest('[data-save]');
    const clearBtn = event.target.closest('[data-clear]');
    if (!saveBtn && !clearBtn) return;
    const questionId = Number((saveBtn || clearBtn).dataset.save || (saveBtn || clearBtn).dataset.clear);
    try {
      if (clearBtn) {
        await api('api/admin/fake-options', { method: 'PUT', body: JSON.stringify({ user_id: fake.userId, question_id: questionId, options: [] }) });
        toast('已恢复真实选项');
      } else {
        const input = list.querySelector('input[data-q="' + questionId + '"]');
        const options = (input ? input.value : '').split(/[,，、;；]+/).map(function (s) { return s.trim(); }).filter(Boolean);
        await api('api/admin/fake-options', { method: 'PUT', body: JSON.stringify({ user_id: fake.userId, question_id: questionId, options: options }) });
        toast('伪装选项已保存');
      }
      await adminFake(body);
    } catch (err) { toast(err.message, true); }
  });
}

/* ------------------------------------------------------------------ 管理：AI 出题 */

async function adminAi(body) {
  const [promptData, surveyData, settingData] = await Promise.all([
    api('api/admin/prompts'),
    api('api/surveys'),
    api('api/admin/settings'),
  ]);
  state.admin.ai.prompts = promptData.prompts || [];
  const surveys = surveyData.surveys || [];
  const generated = state.admin.ai.generated || [];

  const templateOptions = '<option value="">不使用模板</option>' + state.admin.ai.prompts.map(function (p) {
    return '<option value="' + p.id + '">' + esc(p.name) + '</option>';
  }).join('');

  const targetOptions = surveys.map(function (s) {
    return '<option value="' + s.id + '">' + esc(s.title) + '</option>';
  }).join('');

  const keyTip = settingData.has_api_key
    ? ''
    : '<div class="tip">还没有配置 AI 模型 API Key，点击右上「系统设置」填写后即可出题。</div>';

  const generatedHTML = generated.length
    ? generated.map(function (q, index) {
        return '<div class="ai-q"><label class="ai-q-head"><input type="checkbox" data-idx="' + index + '" checked>' +
          '<div><div class="ai-q-title">' + esc(q.title) + '<span class="tag">' + (TYPE_LABEL[q.type] || q.type) + '</span></div>' +
          '<div class="ai-q-opts">' + ((q.options || []).length ? q.options.map(esc).join(' ／ ') : '（无选项）') + '</div></div></label></div>';
      }).join('')
    : '<div class="empty">生成结果会显示在这里</div>';

  body.innerHTML =
    '<div class="grid two">' +
      '<div class="card">' +
        '<h3>提示词</h3>' + keyTip +
        '<div class="field"><label>描述你想要的题目</label>' +
          '<textarea id="ai-prompt" rows="6" placeholder="例如：围绕大学生对线上课程的学习体验设计问题，覆盖平台易用性、互动性、作业反馈三个维度，语言口语化。"></textarea></div>' +
        '<div class="form-row">' +
          '<div class="field"><label>题目数量</label><input id="ai-count" type="number" min="1" max="20" value="5"></div>' +
          '<div class="field"><label>提示词模板</label><select id="ai-template">' + templateOptions + '</select></div>' +
        '</div>' +
        '<div class="field"><label>题型（可多选，选中多种时会平均分配且每种至少 1 道）</label>' +
          '<div class="flex" id="ai-types">' +
            [['single', '单选题'], ['multi', '多选题'], ['text', '填空题'], ['scale', '量表题']].map(function (item, index) {
              return '<label class="check"><input type="checkbox" value="' + item[0] + '"' + (index === 0 ? ' checked' : '') + '> ' + item[1] + '</label>';
            }).join('') +
          '</div></div>' +
        '<div class="flex"><button class="btn" id="ai-generate">生成题目</button>' +
          '<button class="btn danger-ghost sm" id="ai-tpl-del" style="display:none">删除该模板</button>' +
          '<span class="muted small" id="ai-status"></span></div>' +
        '<div class="divider"></div>' +
        '<div class="field"><label>把当前提示词保存为模板</label>' +
          '<div class="flex"><input id="ai-tpl-name" type="text" placeholder="模板名称"><button class="btn ghost sm" id="ai-tpl-save">保存模板</button></div></div>' +
      '</div>' +
      '<div class="card">' +
        '<div class="flex mb16"><h3 style="margin:0">生成结果</h3>' +
          '<button class="btn ghost sm right" id="ai-clear" style="display:' + (generated.length ? 'inline-flex' : 'none') + '">清空</button></div>' +
        '<div class="ai-output" id="ai-output">' + generatedHTML + '</div>' +
        '<div class="divider"></div>' +
        '<div class="flex"><select id="ai-target" style="max-width:320px">' + (targetOptions || '<option value="">暂无问卷</option>') + '</select>' +
          '<button class="btn" id="ai-apply"' + (generated.length && targetOptions ? '' : ' disabled') + '>添加到所选问卷</button></div>' +
        '<div class="muted small mt8">添加后可在「问卷管理」中微调题目与选项。</div>' +
      '</div>' +
    '</div>';

  const promptEl = document.getElementById('ai-prompt');
  const templateSelect = document.getElementById('ai-template');
  const deleteTemplateBtn = document.getElementById('ai-tpl-del');

  templateSelect.onchange = function () {
    const id = Number(templateSelect.value);
    const template = state.admin.ai.prompts.find(function (p) { return p.id === id; });
    if (template) promptEl.value = template.content;
    deleteTemplateBtn.style.display = id ? 'inline-flex' : 'none';
  };

  deleteTemplateBtn.onclick = async function () {
    const id = Number(templateSelect.value);
    if (!id || !window.confirm('删除这个提示词模板？')) return;
    try {
      await api('api/admin/prompts/' + id, { method: 'DELETE' });
      toast('模板已删除');
      state.admin.ai.generated = generated;
      await adminAi(body);
    } catch (err) { toast(err.message, true); }
  };

  document.getElementById('ai-tpl-save').onclick = async function () {
    const name = document.getElementById('ai-tpl-name').value.trim();
    const content = promptEl.value.trim();
    if (!name || !content) return toast('请填写模板名称和提示词内容', true);
    try {
      await api('api/admin/prompts', { method: 'POST', body: JSON.stringify({ name: name, content: content }) });
      toast('模板已保存');
      state.admin.ai.generated = generated;
      await adminAi(body);
    } catch (err) { toast(err.message, true); }
  };

  document.getElementById('ai-generate').onclick = async function () {
    const button = this;
    const statusEl = document.getElementById('ai-status');
    const qtypes = Array.from(document.querySelectorAll('#ai-types input[type=checkbox]:checked')).map(function (input) {
      return input.value;
    });
    if (!qtypes.length) {
      toast('请至少选择一种题型', true);
      return;
    }
    button.disabled = true;
    statusEl.textContent = '正在请求 AI，请稍候…';
    try {
      const data = await api('api/admin/ai/generate', {
        method: 'POST',
        body: JSON.stringify({
          prompt: promptEl.value,
          count: Number(document.getElementById('ai-count').value) || 5,
          qtypes: qtypes,
        }),
      });
      state.admin.ai.generated = data.questions || [];
      toast('已生成 ' + data.questions.length + ' 道题目');
      await adminAi(body);
    } catch (err) {
      toast(err.message, true);
      statusEl.textContent = '';
    } finally {
      button.disabled = false;
    }
  };

  document.getElementById('ai-clear').onclick = async function () {
    state.admin.ai.generated = [];
    await adminAi(body);
  };

  document.getElementById('ai-apply').onclick = async function () {
    const target = Number(document.getElementById('ai-target').value);
    if (!target) return toast('请先选择目标问卷', true);
    const checked = Array.from(document.querySelectorAll('#ai-output input[type=checkbox]:checked'))
      .map(function (input) { return Number(input.dataset.idx); });
    const questions = checked.map(function (index) { return state.admin.ai.generated[index]; }).filter(Boolean);
    if (!questions.length) return toast('请至少勾选一道题目', true);
    try {
      await api('api/admin/surveys/' + target + '/questions/bulk', {
        method: 'POST',
        body: JSON.stringify({ questions: questions }),
      });
      toast('已添加到问卷');
      state.admin.ai.generated = [];
      state.admin.selectedSurvey = target;
      go('#/admin/surveys');
    } catch (err) { toast(err.message, true); }
  };
}

/* ------------------------------------------------------------------ 管理：设置 */

async function adminSettings(body) {
  const settings = await api('api/admin/settings');
  body.innerHTML =
    '<div class="card">' +
      '<h3>AI 模型配置</h3>' +
      '<div class="tip info">填写 OpenAI 兼容接口即可。示例：DeepSeek → 地址 <code>https://api.deepseek.com/v1</code>、模型 <code>deepseek-chat</code>；' +
        '火山方舟 → 地址 <code>https://ark.cn-beijing.volces.com/api/v3</code>、模型填控制台已开通的模型名或推理接入点 ID（<code>ep-...</code>）。密钥只保存在服务器本地。</div>' +
      '<form id="settings-form">' +
        '<div class="form-row">' +
          '<div class="field"><label>接口地址</label><input id="set-base" type="text" value="' + esc(settings.ai_base_url) + '" placeholder="https://api.deepseek.com/v1"></div>' +
          '<div class="field"><label>模型名称</label><input id="set-model" type="text" value="' + esc(settings.ai_model) + '" placeholder="deepseek-chat"></div>' +
        '</div>' +
        '<div class="form-row">' +
          '<div class="field"><label>API Key</label><input id="set-key" type="password" placeholder="' +
            (settings.has_api_key ? '已配置（' + esc(settings.api_key_hint) + '），留空则不修改' : 'sk-...') + '"></div>' +
          '<div class="field"><label>温度（0~2，越高越发散）</label><input id="set-temp" type="text" value="' + esc(settings.ai_temperature) + '"></div>' +
        '</div>' +
        '<div class="field"><label>系统提示词（每次生成都会附加）</label>' +
          '<textarea id="set-system" rows="4">' + esc(settings.ai_system_prompt) + '</textarea></div>' +
        '<div class="flex"><button class="btn" type="submit">保存设置</button>' +
          '<button class="btn ghost sm" type="button" id="set-test">测试连接</button>' +
          '<button class="btn danger-ghost sm" type="button" id="set-clear-key">清除 API Key</button>' +
          '<span class="muted small" id="set-test-result"></span></div>' +
      '</form>' +
    '</div>' +
    '<div class="card">' +
      '<h3>部署信息</h3>' +
      '<div class="muted small">数据保存在服务器 <code>' + 'data/survey.db' + '</code>；' +
      '管理员可通过「结果可见性」按人授权查看范围，通过「虚假选项」为指定用户替换作答界面中的选项。</div>' +
    '</div>';

  document.getElementById('settings-form').addEventListener('submit', async function (event) {
    event.preventDefault();
    const payload = {
      ai_base_url: document.getElementById('set-base').value.trim(),
      ai_model: document.getElementById('set-model').value.trim(),
      ai_temperature: document.getElementById('set-temp').value.trim(),
      ai_system_prompt: document.getElementById('set-system').value,
    };
    const key = document.getElementById('set-key').value.trim();
    if (key) payload.ai_api_key = key;
    try {
      await api('api/admin/settings', { method: 'PUT', body: JSON.stringify(payload) });
      toast('设置已保存');
      await adminSettings(body);
    } catch (err) { toast(err.message, true); }
  });

  document.getElementById('set-clear-key').onclick = async function () {
    if (!window.confirm('确定清除已保存的 API Key？')) return;
    try {
      await api('api/admin/settings', { method: 'PUT', body: JSON.stringify({ clear_api_key: true }) });
      toast('已清除');
      await adminSettings(body);
    } catch (err) { toast(err.message, true); }
  };

  document.getElementById('set-test').onclick = async function () {
    const resultEl = document.getElementById('set-test-result');
    const button = this;
    button.disabled = true;
    resultEl.style.color = 'var(--muted)';
    resultEl.textContent = '正在连接…';
    try {
      const payload = {
        ai_base_url: document.getElementById('set-base').value.trim(),
        ai_model: document.getElementById('set-model').value.trim(),
        ai_temperature: document.getElementById('set-temp').value.trim(),
      };
      const key = document.getElementById('set-key').value.trim();
      if (key) payload.ai_api_key = key;
      const data = await api('api/admin/ai/test', { method: 'POST', body: JSON.stringify(payload) });
      resultEl.style.color = 'var(--success)';
      resultEl.textContent = '连接成功：' + (data.reply || 'OK');
    } catch (err) {
      resultEl.style.color = 'var(--danger)';
      resultEl.textContent = '连接失败：' + err.message;
    } finally {
      button.disabled = false;
    }
  };
}

/* ------------------------------------------------------------------ 修改密码 */

function openPasswordModal() {
  openModal('修改密码',
    '<div class="field"><label>原密码</label><input id="pw-old" type="password" autocomplete="current-password"></div>' +
    '<div class="field"><label>新密码</label><input id="pw-new" type="password" autocomplete="new-password" placeholder="至少 6 位"></div>' +
    '<div class="field"><label>确认新密码</label><input id="pw-confirm" type="password" autocomplete="new-password"></div>' +
    '<div class="modal-actions"><button class="btn ghost" id="pw-cancel">取消</button><button class="btn" id="pw-save">保存</button></div>',
    function (mask) {
      mask.querySelector('#pw-cancel').onclick = closeModal;
      mask.querySelector('#pw-save').onclick = async function () {
        const oldPassword = mask.querySelector('#pw-old').value;
        const newPassword = mask.querySelector('#pw-new').value;
        const confirm = mask.querySelector('#pw-confirm').value;
        if (newPassword.length < 6) return toast('新密码至少需要 6 位', true);
        if (newPassword !== confirm) return toast('两次输入的新密码不一致', true);
        try {
          await api('api/me/password', { method: 'POST', body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }) });
          closeModal();
          toast('密码已更新');
        } catch (err) { toast(err.message, true); }
      };
    });
}

boot();
