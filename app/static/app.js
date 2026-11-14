'use strict';

const $ = (id) => document.getElementById(id);

const state = {csrf: '', accounts: [], posts: [], config: {}, user: null, quota: null, apiKeys: [], media: null, blob: null, batch: crypto.randomUUID(), view: 'compose', busy: false, uploading: false};

const labels = {draft:'Draft',queued:'Queued',posting:'Publishing',submitted:'Delivered',failed:'Failed',unknown:'Review needed',cancelled:'Cancelled'};

const platformName = (p) => ({youtube:'YouTube',facebook:'Facebook Page',tiktok:'TikTok',instagram:'Instagram',linkedin:'LinkedIn',x:'X',pinterest:'Pinterest'}[p]||p);

function el(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; }

function icon(provider) { return el('span', `platform-icon ${provider}`, ({youtube:'▶',facebook:'f',tiktok:'♪',instagram:'◎',linkedin:'in',x:'𝕏',pinterest:'p'}[provider]||'•')); }

let noticeTimer = null;
function notice(message, error = false, duration = 4500) {
  const n = $('notice');
  if (!n) return;
  if (noticeTimer) clearTimeout(noticeTimer);
  n.replaceChildren();
  const msg = el('span', 'notice-msg', message);
  const btn = el('button', 'notice-close-btn', '✕');
  btn.type = 'button';
  btn.onclick = () => { n.hidden = true; };
  n.append(msg, btn);
  n.className = 'notice' + (error ? ' error' : '');
  n.hidden = false;
  noticeTimer = setTimeout(() => { n.hidden = true; }, error ? 6500 : duration);
}

function loggedOut() { state.csrf=''; $('workspace').hidden=true; $('login-screen').hidden=false; }

async function api(path, options={}) {

  const headers={...(options.headers||{})};

  if(options.body && !(options.body instanceof FormData)) headers['Content-Type']='application/json';

  if(options.method && options.method!=='GET') headers['X-CSRF-Token']=state.csrf;

  const response=await fetch(path,{...options,headers});

  const data=await response.json();

  if(!response.ok) {

    if(response.status===401 && path!=='/api/login') loggedOut();

    const detail=typeof data.detail==='string'?data.detail:'Some fields are invalid. Please review your inputs.';

    throw new Error(detail);

  }

  return data;

}

function changeView(view) {

  state.view=view;

  for(const name of ['dashboard','compose','history','accounts','calendar','analytics','developer','settings']) $(name+'-view').hidden=name!==view;

  document.querySelectorAll('.nav-button').forEach(n=>n.classList.toggle('active',n.dataset.view===view));

  $('breadcrumb-view').textContent={dashboard:'Overview',compose:'Create post',history:'Posts',accounts:'Social accounts',calendar:'Calendar',analytics:'Analytics',developer:'Automations & API',settings:'Settings'}[view];

  if(view==='history'||view==='calendar'||view==='dashboard') refreshPosts().catch(e=>notice(e.message,true));
  if(view==='analytics') { refreshPosts().then(() => renderAnalytics()).catch(e=>notice(e.message,true)); }
  if(view==='settings') { renderSettings(); } if(view==='developer') renderApiKeys().catch(e=>notice(e.message,true));

}

document.addEventListener('click',event=>{const trigger=event.target.closest('[data-view]');if(trigger)changeView(trigger.dataset.view);});

function preview() {

  $('title-count').textContent=`${$('title').value.length} / 100`;

  $('preview-title').textContent=$('title').value||'Your post title';

  $('preview-description').textContent=$('description').value||'Your caption and hashtags will appear here.';

  const checked=[...document.querySelectorAll('#channel-picker input:checked')].map(n=>state.accounts.find(a=>a.id===n.value)?.name).filter(Boolean);

  $('preview-channel').textContent=checked.join(' · ')||'Choose a channel to get started';

}



function renderQuota() {

  if (!state.quota) return;

  const q = state.quota;

  const isUnl = q.is_unlimited || q.tier === 'agency' || q.tier === 'pro';

  $('sidebar-plan-label').textContent = isUnl ? `GÓI ${(q.tier||'PRO').toUpperCase()}` : 'GÓI MIỄN PHÍ';

  if (isUnl) {

    $('sidebar-quota-count').textContent = 'Không giới hạn';

    const fill = $('sidebar-quota-fill');

    fill.style.width = '100%';

    fill.className = 'quota-fill';

    $('sidebar-upgrade-btn').textContent = '💎 Bạn đang dùng gói Pro';

    $('sidebar-upgrade-btn').style.opacity = '0.6';

    if ($('topbar-upgrade-btn')) $('topbar-upgrade-btn').hidden = true;

  } else {

    $('sidebar-quota-count').textContent = `${q.posts_used} / ${q.posts_limit} bài`;

    const pct = Math.min(100, Math.round((q.posts_used / q.posts_limit) * 100));

    const fill = $('sidebar-quota-fill');

    fill.style.width = `${pct}%`;

    fill.className = 'quota-fill' + (pct >= 100 ? ' exhausted' : pct >= 70 ? ' warning' : '');

    $('sidebar-upgrade-btn').textContent = '💎 Nâng cấp gói Pro';

    $('sidebar-upgrade-btn').style.opacity = '1';

    if ($('topbar-upgrade-btn')) $('topbar-upgrade-btn').hidden = false;

  }

}



async function renderApiKeys() {

  const tbody = $('apikey-list-body');

  if (!tbody) return;

  try {

    state.apiKeys = await api('/api/user/api-keys');

    tbody.replaceChildren();

    if (!state.apiKeys.length) {

      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:18px;color:var(--muted)">Chưa có API Key nào. Hãy bấm "Tạo API Key mới" để kết nối với n8n.</td></tr>';

      return;

    }

    for (const k of state.apiKeys) {

      const tr = el('tr');

      const tdName = el('td'); tdName.innerHTML = `<strong>${k.name}</strong>`;

      const tdPrefix = el('td'); tdPrefix.innerHTML = `<span class="code-badge">${k.key_prefix}</span>`;

      const tdDate = el('td', '', new Date(k.created_at * 1000).toLocaleDateString('vi-VN'));

      const tdStatus = el('td'); tdStatus.innerHTML = `<span class="${k.active ? 'status-badge-active' : 'status-badge-revoked'}">${k.active ? '● Hoạt động' : 'Đã thu hồi'}</span>`;

      const tdAction = el('td');

      if (k.active) {

        const btnRevoke = el('button', 'text-button', 'Thu hồi');

        btnRevoke.type = 'button';

        btnRevoke.onclick = async () => {

          if (!confirm(`Thu hồi API Key "${k.name}"? Các luồng n8n sử dụng key này sẽ không thể gọi API nữa.`)) return;

          btnRevoke.disabled = true;

          try {

            await api(`/api/user/api-keys/${k.id}`, { method: 'DELETE' });

            notice('Đã thu hồi API Key thành công.');

            await renderApiKeys();

          } catch (e) {

            notice(e.message, true);

            btnRevoke.disabled = false;

          }

        };

        tdAction.append(btnRevoke);

      } else {

        tdAction.textContent = '—';

      }

      tr.append(tdName, tdPrefix, tdDate, tdStatus, tdAction);

      tbody.append(tr);

    }

  } catch (e) {

    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--red);padding:14px;">Lỗi tải API Keys: ${e.message}</td></tr>`;

  }

}



function showPricingModal() {
  const modal = $('modal-pricing');
  if (!modal) return;
  modal.hidden = false;
}



function renderAccounts() {

  $('channel-picker').replaceChildren(); $('connected-list').replaceChildren();

  $('no-accounts').hidden=state.accounts.length>0; $('account-count').textContent=`${state.accounts.length} connected`;

  for(const account of state.accounts) {

    const option=el('label','channel-option'); const checkbox=el('input'); checkbox.type='checkbox';checkbox.value=account.id;checkbox.addEventListener('change',preview);

    const copy=el('span','',account.name);copy.append(el('small','',platformName(account.provider))); option.append(checkbox,icon(account.provider),copy);$('channel-picker').append(option);

    const row=el('div','account-row');const detail=el('div');detail.append(el('strong','',account.name),el('small','',`${platformName(account.provider)} · ${account.external_id}`));

const disconnect=el('button','text-button','Disconnect');disconnect.type='button';disconnect.onclick=async()=>{

 if(!confirm(`Disconnect ${account.name}? Queued posts for this channel will be stopped.`))return;

      disconnect.disabled=true;try{await api(`/api/accounts/${account.id}/disconnect`,{method:'POST'});await load();notice('Đã xóa token của kênh khỏi công cụ.');}catch(e){notice(e.message,true);disconnect.disabled=false;}

    };row.append(icon(account.provider),detail,disconnect);$('connected-list').append(row);

  }

  if(!state.accounts.length) $('connected-list').append(el('p','empty-hint','No accounts connected. Configure OAuth to enable account linking.'));

  $('provider-list').replaceChildren();

  for(const provider of ['youtube','facebook','tiktok','instagram','linkedin','x','pinterest']) {
    const card = el('article', 'card provider-card');
    const body = el('div', 'provider-card-body');
    const ready = state.config.providers?.[provider];
    const myAccounts = state.accounts.filter(a => a.provider === provider && a.active !== false);
    const isConnected = myAccounts.length > 0;

    const head = el('div', 'provider-card-head');
    head.append(el('h2', '', platformName(provider)));
    head.append(el('span', `pill ${isConnected ? 'positive' : 'neutral'}`, isConnected ? `● Đã kết nối (${myAccounts.length})` : (ready ? 'Khả dụng' : 'Sắp ra mắt')));
    body.append(head);

    if (isConnected) {
      const chList = el('div', 'provider-connected-list');
      for (const acc of myAccounts) {
        const item = el('div', 'provider-connected-item');
        const info = el('div', 'ch-info');
        info.append(el('strong', '', acc.name), el('small', '', `${platformName(provider)} · ID: ${acc.external_id}`));
        const discBtn = el('button', 'text-button danger-btn', 'Ngắt kết nối');
        discBtn.type = 'button';
        discBtn.onclick = async () => {
          if (!confirm(`Ngắt kết nối tài khoản "${acc.name}"?`)) return;
          discBtn.disabled = true;
          try {
            await api(`/api/accounts/${acc.id}`, { method: 'DELETE' });
            await load();
            notice(`Đã ngắt kết nối tài khoản ${acc.name}.`);
          } catch (e) {
            notice(e.message, true);
            discBtn.disabled = false;
          }
        };
        item.append(info, discBtn);
        chList.append(item);
      }
      body.append(chList);

      if (['youtube', 'facebook'].includes(provider)) {
        const addMore = el('button', 'text-button add-more-btn', '＋ Kết nối thêm kênh khác');
        addMore.type = 'button';
        addMore.onclick = async () => {
          addMore.disabled = true;
          try {
            const r = await api(`/api/oauth/${provider}/start`, { method: 'POST' });
            location.assign(r.url);
          } catch (e) {
            notice(e.message, true);
            addMore.disabled = false;
          }
        };
        body.append(addMore);
      }
    } else {
      const descriptions = {
        youtube: 'Xuất bản video và Shorts kèm kiểm soát quyền riêng tư.',
        facebook: 'Xuất bản video Reels và bài viết lên Fanpage Facebook.',
        tiktok: 'Xuất bản video trực tiếp lên tài khoản TikTok.',
        instagram: 'Đăng video lên Instagram Business & Reels.',
        linkedin: 'Chia sẻ bài viết chuyên nghiệp lên trang LinkedIn.',
        x: 'Xuất bản bài viết lên X (Twitter).',
        pinterest: 'Ghim video lên các bảng tin Pinterest.'
      };
      body.append(el('p', 'provider-desc', descriptions[provider] || ''));
      const button = el('button', 'secondary', ready ? 'Connect account ↗' : (['youtube', 'facebook'].includes(provider) ? 'Cần cấu hình OAuth' : 'Sắp ra mắt'));
      button.disabled = !ready;
      button.onclick = async () => {
        button.disabled = true;
        try {
          const r = await api(`/api/oauth/${provider}/start`, { method: 'POST' });
          location.assign(r.url);
        } catch (e) {
          notice(e.message, true);
          button.disabled = false;
        }
      };
      body.append(button);
      if (!ready && ['youtube', 'facebook'].includes(provider)) {
        body.append(el('p', 'field-help', 'Thêm cấu hình OAuth trong file .env để kích hoạt kết nối.'));
      }
    }
    card.append(icon(provider), body);
    $('provider-list').append(card);
  }

  $('environment-info').replaceChildren();

  for(const [k,v] of [['Database',state.config.database],['Publishing worker',state.config.worker?'Running':'Stopped'],['Video storage',`On server · removed after ${state.config.retention_days} days when no longer queued`]]){const row=el('div','environment-line');row.append(el('span','',k),el('strong','',v));$('environment-info').append(row);}

  $('upload-limit').textContent=`MP4 · up to ${state.config.max_upload_mb} MB`;

  renderSettings();

  renderDashboard();

  preview();

}

function renderDashboard() {
  const published = (state.posts || []).filter(p => p.status === 'submitted').length;
  const queued = (state.posts || []).filter(p => ['queued', 'posting'].includes(p.status)).length;

  if ($('dash-published')) $('dash-published').textContent = published;
  if ($('dash-queued')) $('dash-queued').textContent = queued;
  if ($('analytics-published')) $('analytics-published').textContent = published;
  if ($('analytics-total-published')) $('analytics-total-published').textContent = published;
  if ($('dash-accounts')) $('dash-accounts').textContent = (state.accounts || []).length;

  const sampleProcessing = !queued && /demo/i.test(state.config?.database || '');
  if ($('processing-label')) {
    $('processing-label').textContent = queued ? `${queued} post${queued === 1 ? '' : 's'} in the publishing queue` : sampleProcessing ? 'Sample TikTok ingestion · converting to 9:16' : 'Waiting for your next post';
  }
  if ($('processing-percent')) {
    $('processing-percent').textContent = queued ? 'In queue' : sampleProcessing ? '65% · Demo' : 'Ready';
  }
  const progress = $('processing-progress');
  if (progress) {
    progress.style.width = sampleProcessing ? '65%' : '0%';
    progress.setAttribute('aria-valuenow', sampleProcessing ? '65' : '0');
    progress.setAttribute('aria-label', sampleProcessing ? 'Demo video ingestion progress' : 'Publishing queue progress');
  }
  if ($('processing-foot')) {
    $('processing-foot').textContent = queued ? 'Your publishing worker will process these posts' : sampleProcessing ? 'Illustrative progress only · no live media job is running' : 'Your channels are standing by';
  }

  const dDate = $('dashboard-date');
  if (dDate) {
    dDate.textContent = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' }).toUpperCase();
  }

  const channels = $('dashboard-channels');
  if (channels) {
    channels.replaceChildren();
    for (const provider of ['youtube', 'facebook']) {
      const matched = (state.accounts || []).filter(a => a.provider === provider);
      const row = el('div', 'channel-summary');
      row.append(icon(provider));
      const copy = el('span');
      copy.append(el('strong', '', platformName(provider)), el('small', '', matched.length ? `${matched.length} connected` : 'Not connected'));
      row.append(copy, el('span', 'channel-status', matched.length ? 'Connected' : '—'));
      channels.append(row);
    }
  }

  const target = $('dashboard-posts');
  if (target) {
    target.replaceChildren();
    const recent = (state.posts || []).slice(0, 4);
    if (!recent.length) {
      const blank = el('div', 'empty-state');
      blank.append(el('strong', '', 'Your publishing story starts here'), el('p', '', 'Once you create a post, its progress will show up here.'));
      const create = el('button', 'secondary', 'Create your first post');
      create.type = 'button';
      create.dataset.view = 'compose';
      blank.append(create);
      target.append(blank);
    } else {
      for (const post of recent) {
        const row = el('div', 'dashboard-post-row');
        row.append(icon(post.provider));
        const copy = el('div', 'dashboard-post-copy');
        copy.append(el('strong', '', post.title), el('small', '', `${post.account_name} · ${new Date(post.created_at * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`));
        row.append(copy, el('span', `status ${post.status}`, labels[post.status] || post.status));
        target.append(row);
      }
    }
  }

  if (typeof renderCalendar === 'function') renderCalendar();
}

function renderCalendar() {

  const target=$('calendar-list');if(!target)return;target.replaceChildren();

  const upcoming=state.posts.filter(p=>['queued','posting','submitted'].includes(p.status)).slice(0,8);

  if(!upcoming.length){const blank=el('div','empty-state');blank.append(el('strong','', 'Your calendar is ready when you are'),el('p','', 'Schedule a post to see it here.'));const create=el('button','secondary','Create a scheduled post');create.type='button';create.dataset.view='compose';blank.append(create);target.append(blank);return;}

  for(const post of upcoming){const row=el('div','calendar-row'),when=new Date((post.scheduled_at||post.created_at)*1000),date=el('span','calendar-date');date.append(el('strong','',String(when.getDate()).padStart(2,'0')),document.createTextNode(when.toLocaleDateString('en-US',{month:'short'})));const copy=el('div');copy.append(el('strong','',post.title),el('small','',`${when.toLocaleString('en-US',{weekday:'short',hour:'numeric',minute:'2-digit'})} · ${post.account_name}`));row.append(date,copy,el('span',`status ${post.status}`,labels[post.status]||post.status));target.append(row);}

}

function renderSettings() {
  const dbEl = document.getElementById('infra-db-val');
  if (dbEl) dbEl.textContent = state.config?.database || 'Supabase / PostgreSQL';
  const workerEl = document.getElementById('infra-worker-val');
  if (workerEl) workerEl.textContent = state.config?.worker ? 'Hàng đợi nền đang chạy' : 'Tạm dừng';
  const storageEl = document.getElementById('infra-storage-val');
  if (storageEl) storageEl.textContent = `Tự dọn dẹp sau ${state.config?.retention_days || 7} ngày`;
  if (typeof renderUserProfile === 'function') renderUserProfile();
}

function renderPosts() {

  const rows=state.posts; $('nav-count').textContent=rows.length;

  $('stat-total').textContent=rows.length; $('stat-queued').textContent=rows.filter(p=>['queued','posting'].includes(p.status)).length;

  $('stat-submitted').textContent=rows.filter(p=>p.status==='submitted').length;$('stat-errors').textContent=rows.filter(p=>['failed','unknown'].includes(p.status)).length;

  const filter=$('status-filter').value;const selected=rows.filter(p=>filter==='all'||p.status===filter);$('post-list').replaceChildren();

  if(!selected.length){const blank=el('div','empty-state');blank.append(el('strong','',rows.length?'No posts in this status':'Your publishing story starts here'),el('p','',rows.length?'Choose another status to view posts.':'Create a post, choose a channel, and save it as a draft or add it to the queue.'));$('post-list').append(blank);}

  for(const post of selected){

    const card=el('article','card post-card'),body=el('div','post-body');body.append(el('h2','',post.title),el('p','',`${post.account_name} · ${new Date(post.created_at*1000).toLocaleString('en-US')}`));

    if(post.status==='queued')body.append(el('p','',`Giờ gửi: ${new Date(post.scheduled_at*1000).toLocaleString()}`));

    if(post.error)body.append(el('p','post-error',post.error));

    const actions=el('div','post-actions');

    if(post.remote_url){const link=el('a','',`Open on ${platformName(post.provider)} ↗`);link.href=post.remote_url;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);}

    for(const [action,text] of [['queue',post.status==='failed'?'Retry':'Add to queue'],['cancel','Cancel']]){

      if(!(action==='queue'?['draft','failed']:['draft','queued']).includes(post.status))continue;

      const b=el('button','text-button',text);b.onclick=async()=>{if(action==='queue'&&!confirm('Gửi bài này lên nền tảng?'))return;b.disabled=true;try{await api(`/api/posts/${post.id}/${action}`,{method:'POST'});await refreshPosts();}catch(e){notice(e.message,true);b.disabled=false;}};actions.append(b);

    }

    const delBtn = el('button', 'text-button delete-post-btn', '🗑️ Xóa');
    delBtn.type = 'button';
    delBtn.onclick = async () => {
      if (!confirm(`Xóa bài "${post.title}" khỏi lịch sử?`)) return;
      delBtn.disabled = true;
      try {
        await api(`/api/posts/${post.id}`, { method: 'DELETE' });
        await refreshPosts();
        notice('Đã xóa bài đăng khỏi lịch sử.');
      } catch (e) {
        notice(e.message, true);
        delBtn.disabled = false;
      }
    };
    actions.append(delBtn);

    if(post.status==='unknown')body.append(el('p','field-help','Trạng thái xuất bản chưa rõ ràng. Kiểm tra trực tiếp trên kênh trước khi thử lại.'));

    body.append(actions);card.append(icon(post.provider),body,el('span',`status ${post.status}`,labels[post.status]||post.status));$('post-list').append(card);

  }

  renderDashboard();

}

async function refreshPosts(){state.posts=await api('/api/posts');renderPosts();}

async function load(){[state.config,state.accounts,state.quota]=await Promise.all([api('/api/config'),api('/api/accounts'),api('/api/user/quota')]);renderAccounts();renderQuota();await refreshPosts();}

async function enter(userProfile){
  if (userProfile) state.user = userProfile;
  if ($('login-screen')) $('login-screen').hidden = true;
  if ($('workspace')) $('workspace').hidden = false;
  try {
    await load();
  } catch (err) {
    console.warn('load() warning:', err);
  }
  try {
    if (typeof renderUserProfile === 'function') renderUserProfile();
  } catch (err) {
    console.warn('renderUserProfile() warning:', err);
  }

const connection=new URLSearchParams(location.search).get('connection');if(connection){notice(connection==='success'?'Account connected.':'Authorization cancelled.');history.replaceState({},'',location.pathname);}

  const urlParams = new URLSearchParams(window.location.search);
  const authStatus = urlParams.get('auth');
  const authErr = urlParams.get('auth_error');
  if (authStatus === 'registered') {
    notice('🎉 Đăng ký thành công! Bạn nhận được 10 bài đăng miễn phí mỗi tháng.');
    history.replaceState({}, '', window.location.pathname);
  } else if (authStatus === 'success') {
    notice('Đăng nhập Google thành công!');
    history.replaceState({}, '', window.location.pathname);
  } else if (authErr) {
    notice('Đăng nhập Google không thành công (' + authErr + ').', true);
    history.replaceState({}, '', window.location.pathname);
  }

}



// Auth Tabs Switching

$('tab-login').onclick = () => {

  $('tab-login').classList.add('active');

  $('tab-register').classList.remove('active');

  $('login-form').hidden = false;

  $('register-form').hidden = true;

};

$('tab-register').onclick = () => {

  $('tab-register').classList.add('active');

  $('tab-login').classList.remove('active');

  $('register-form').hidden = false;

  $('login-form').hidden = true;

};



// Login Form Submit

$('login-form').addEventListener('submit', async e => {

  e.preventDefault();

  const b = e.submitter;

  b.disabled = true;

  $('login-error').textContent = '';

  try {

    const emailVal = $('login-email')?.value?.trim() || undefined;

    const r = await api('/api/login', {

      method: 'POST',

      body: JSON.stringify({ email: emailVal, password: $('password').value })

    });

    state.csrf = r.csrf;

    $('password').value = '';

    const sess = await api('/api/session');

    await enter(sess.user);

  } catch (err) {

    $('login-error').textContent = err.message;

  } finally {

    b.disabled = false;

  }

});



// Register Form Submit

$('register-form').addEventListener('submit', async e => {

  e.preventDefault();

  const b = e.submitter;

  b.disabled = true;

  $('reg-error').textContent = '';

  try {

    const r = await api('/api/register', {

      method: 'POST',

      body: JSON.stringify({

        name: $('reg-name').value.trim(),

        email: $('reg-email').value.trim(),

        password: $('reg-password').value

      })

    });

    state.csrf = r.csrf;

    $('reg-name').value = '';

    $('reg-email').value = '';

    $('reg-password').value = '';

    const sess = await api('/api/session');

    await enter(sess.user);

    if (r.default_api_key) {

      $('new-key-display').textContent = r.default_api_key;

      $('modal-new-key').hidden = false;

    }

    notice(r.message || 'Đăng ký thành công!');

  } catch (err) {

    $('reg-error').textContent = err.message;

  } finally {

    b.disabled = false;

  }

});



// Create API Key Button

$('btn-create-key').onclick = async () => {

  const name = prompt('Nhập tên mô tả cho API Key (ví dụ: n8n Studio, Telegram Bot):', 'n8n Workflow');

  if (!name || !name.trim()) return;

  try {

    const r = await api('/api/user/api-keys', {

      method: 'POST',

      body: JSON.stringify({ name: name.trim() })

    });

    $('new-key-display').textContent = r.raw_key;

    $('modal-new-key').hidden = false;

    await renderApiKeys();

  } catch (e) {

    notice(e.message, true);

  }

};



// Copy API Key Button

$('btn-copy-new-key').onclick = () => {

  const key = $('new-key-display').textContent;

  if (!key) return;

  navigator.clipboard.writeText(key).then(() => {

    notice('Đã sao chép API Key vào bộ nhớ tạm.');

    $('modal-new-key').hidden = true;

  }).catch(() => {

    notice('Không thể tự động sao chép. Hãy chọn và copy bằng tay.', true);

  });

};



// Pricing Modal Triggers

$('sidebar-upgrade-btn').onclick = showPricingModal;

if ($('topbar-upgrade-btn')) $('topbar-upgrade-btn').onclick = showPricingModal;

if ($('btn-quick-pricing')) $('btn-quick-pricing').onclick = showPricingModal;



$('logout').onclick=async()=>{try{await api('/api/logout',{method:'POST'});loggedOut();}catch(e){notice(e.message,true);}};

document.querySelectorAll('[data-preview]').forEach(tab=>tab.addEventListener('click',()=>{document.querySelectorAll('[data-preview]').forEach(item=>item.classList.toggle('active',item===tab));const platform=tab.dataset.preview;$('preview-channel').textContent=platform==='youtube'?($('shorts')?.checked?'YouTube Shorts preview':'YouTube Video preview (16:9)'):platform==='tiktok'?'TikTok preview · channel connection unavailable':'Facebook Reels preview';}));

$('ingest-button').addEventListener('click',()=>{const input=$('ingest-url');if(!input.reportValidity()||!input.value)return;notice('💡 Để tự động xuất bản từ link TikTok sang YouTube không cần tải video về máy, hãy gửi link vào Telegram Bot hoặc n8n Workflow của bạn (Xem tab Automations & API)!');});

$('title').oninput=preview;$('description').oninput=preview;$('status-filter').onchange=renderPosts;$('refresh-posts').onclick=()=>refreshPosts().catch(e=>notice(e.message,true));

async function upload(file){

  if(!file||state.uploading)return;

  state.uploading=true;state.media=null;$('upload-info').hidden=false;$('upload-info').textContent='Uploading and checking your video…';$('video').disabled=true;

  try{if(!file.name.toLowerCase().endsWith('.mp4'))throw new Error('Choose an MP4 file.');if(file.size>state.config.max_upload_mb*1024*1024)throw new Error('The video exceeds the size limit.');

    const data=new FormData();data.append('file',file);state.media=await api('/api/media',{method:'POST',body:data});

    $('upload-info').textContent=`${state.media.filename} · ${(state.media.size/1024/1024).toFixed(1)} MB · ${Math.round(state.media.duration)} giây · ${state.media.width} × ${state.media.height}`;

    if(state.blob)URL.revokeObjectURL(state.blob);state.blob=URL.createObjectURL(file);$('video-preview').src=state.blob;$('video-preview').hidden=false;$('preview-placeholder').hidden=true;
    if (state.media && typeof setPublishFormat === 'function') {
      if (state.media.width > state.media.height || state.media.duration > 180) {
        setPublishFormat(false, true);
      } else {
        setPublishFormat(true, false);
      }
    }


  }catch(e){$('upload-info').textContent=e.message;notice(e.message,true);$('video-preview').hidden=true;$('preview-placeholder').hidden=false;}

  finally{state.uploading=false;$('video').disabled=false;}

}

$('video').onchange=e=>upload(e.target.files[0]);

for(const type of ['dragenter','dragover'])$('dropzone').addEventListener(type,e=>{e.preventDefault();$('dropzone').classList.add('dragging');});

for(const type of ['dragleave','drop'])$('dropzone').addEventListener(type,e=>{e.preventDefault();$('dropzone').classList.remove('dragging');if(type==='drop')upload(e.dataTransfer.files[0]);});

async function submit(action){

  if(state.busy)return;if(state.uploading){notice('Wait for the video upload to finish.',true);return;}if(!$('post-form').reportValidity())return;

  const ids=[...document.querySelectorAll('#channel-picker input:checked')].map(n=>n.value);if(!ids.length){notice('Choose at least one publishing channel.',true);return;}

  if(action==='queue'&&!confirm(`Queue this post for ${ids.length} selected channel(s)? YouTube privacy: ${$('privacy').selectedOptions[0].textContent}.`))return;

  state.busy=true;$('queue-button').disabled=true;$('draft-button').disabled=true;

  try{await api('/api/posts',{method:'POST',body:JSON.stringify({batch_key:state.batch,account_ids:ids,title:$('title').value,description:$('description').value,

    tags:$('tags').value.split(',').map(t=>t.trim()).filter(Boolean),media_id:state.media?.id||null,privacy:$('privacy').value,made_for_kids:$('kids').checked,shorts:$('shorts').checked,action,

    scheduled_at:$('schedule').value?new Date($('schedule').value).toISOString():null})});

    state.batch=crypto.randomUUID();state.media=null;$('post-form').reset();$('upload-info').hidden=true;$('video-preview').pause();$('video-preview').removeAttribute('src');$('video-preview').hidden=true;$('preview-placeholder').hidden=false;if(state.blob){URL.revokeObjectURL(state.blob);state.blob=null;}preview();changeView('history');notice(action==='draft'?'Draft saved.':'Post added to the queue. Follow its progress below.');await refreshPosts();

  }catch(e){notice(e.message,true);}finally{state.busy=false;$('queue-button').disabled=false;$('draft-button').disabled=false;}

}

$('post-form').onsubmit=e=>{e.preventDefault();submit('queue');};$('draft-button').onclick=()=>submit('draft');

$('timezone-label').textContent=`Your local time zone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Stored and processed in UTC.`;

setInterval(()=>{if(state.csrf&&!document.hidden)refreshPosts().catch(e=>notice(e.message,true));},12000);

(async()=>{
  initGoogleAuth();
  try{
    const r=await api('/api/session');
    state.csrf=r.csrf;
    await enter(r.user);
  }catch(e){
    loggedOut();
    if(!e.message.includes('Đăng nhập')&&!e.message.includes('hết hạn'))$('login-error').textContent=e.message;
  }
})();



// Google OAuth & 1-Click Sign-In
async function initGoogleAuth() {
  try {
    const btn = $('btn-google-auth');
    if (btn) {
      btn.onclick = () => {
        window.location.href = '/api/auth/google/start';
      };
    }

    const cfg = await api('/api/auth/config');
    if (!cfg.google_enabled || !cfg.google_client_id) return;

    if (window.google && window.google.accounts && window.google.accounts.id) {
      window.google.accounts.id.initialize({
        client_id: cfg.google_client_id,
        callback: handleGoogleCredentialResponse,
        auto_select: false
      });
      const holder = $('g-signin-placeholder');
      if (holder) {
        window.google.accounts.id.renderButton(holder, {
          theme: 'outline',
          size: 'large',
          text: 'continue_with',
          shape: 'rectangular',
          width: 320
        });
      }
    }
  } catch (e) {
    // Fallback silently
  }
}

async function handleGoogleCredentialResponse(response) {
  if (!response || !response.credential) return;
  try {
    const r = await fetch('/api/auth/google/credential', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Origin': window.location.origin
      },
      body: JSON.stringify({ credential: response.credential })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'Đăng nhập Google thất bại');
    state.csrf = data.csrf;
    const sess = await api('/api/session');
    await enter(sess.user);
    if (data.default_api_key) {
      $('new-key-display').textContent = data.default_api_key;
      $('modal-new-key').hidden = false;
    }
    notice(data.message || 'Đăng nhập Google thành công!');
  } catch (err) {
    $('login-error').textContent = err.message;
    notice(err.message, true);
  }
}


// --- Video Format and Smart Paste Helpers ---
function setPublishFormat(isShorts, notifyUser) {
  var box = document.getElementById('shorts');
  var btnS = document.getElementById('fmt-shorts-btn');
  var btnR = document.getElementById('fmt-regular-btn');
  var tabYt = document.getElementById('preview-tab-youtube');
  var pBox = document.getElementById('preview-placeholder');
  var pVid = document.getElementById('video-preview');

  if (box) box.checked = isShorts;
  if (btnS && btnR) {
    btnS.classList.toggle('active', !!isShorts);
    btnR.classList.toggle('active', !isShorts);
  }
  if (tabYt) {
    tabYt.textContent = isShorts ? 'YouTube Shorts' : 'YouTube Video (16:9)';
  }
  if (pBox) {
    pBox.classList.toggle('is-shorts', !!isShorts);
    pBox.classList.toggle('is-regular', !isShorts);
  }
  if (pVid) {
    pVid.classList.toggle('is-shorts', !!isShorts);
    pVid.classList.toggle('is-regular', !isShorts);
  }
  var previewTab = document.querySelector('.preview-tab.active');
  if (previewTab && previewTab.dataset.preview === 'youtube') {
    var pChan = document.getElementById('preview-channel');
    if (pChan) pChan.textContent = isShorts ? 'YouTube Shorts preview' : 'YouTube Video preview (16:9)';
  }
  if (notifyUser) {
    notice(isShorts 
      ? 'Đã tự động chọn "YouTube Shorts" (video dọc ≤ 3 phút).' 
      : 'Đã tự động chọn "Video thường / dài" (video ngang 16:9 hoặc > 3 phút).'
    );
  }
}

// Bind button clicks
var btnShortsEl = document.getElementById('fmt-shorts-btn');
if (btnShortsEl) {
  btnShortsEl.onclick = function() { setPublishFormat(true); };
}
var btnRegEl = document.getElementById('fmt-regular-btn');
if (btnRegEl) {
  btnRegEl.onclick = function() { setPublishFormat(false); };
}

// Smart paste handler for Post Title
var titleInputEl = document.getElementById('title');
if (titleInputEl) {
  titleInputEl.addEventListener('paste', function(e) {
    e.preventDefault();
    var clip = (e.clipboardData || window.clipboardData).getData('text') || '';
    var clean = clip.replace(/[\r\n\t]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
    var start = this.selectionStart || 0;
    var end = this.selectionEnd || 0;
    var oldVal = this.value;
    var avail = 100 - (oldVal.length - (end - start));
    var insert = clean.slice(0, Math.max(0, avail));
    var newVal = oldVal.slice(0, start) + insert + oldVal.slice(end);
    this.value = newVal.slice(0, 100);
    this.selectionStart = this.selectionEnd = start + insert.length;
    if (typeof preview === 'function') preview();
  });
}

// Smart paste handler for Description
var descInputEl = document.getElementById('description');
if (descInputEl) {
  descInputEl.addEventListener('paste', function() {
    if (typeof preview === 'function') setTimeout(preview, 25);
  });
}


// --- DYNAMIC USER PROFILE & DASHBOARD LOGIC ---
function renderUserProfile() {
  if (!state.user) return;
  const rawName = state.user.name || (state.user.email ? state.user.email.split('@')[0] : 'bạn');
  const cleanName = rawName.charAt(0).toUpperCase() + rawName.slice(1);
  const avatarChar = cleanName.charAt(0).toUpperCase() || 'U';
  const isAdmin = (state.user.role === 'admin' || state.user.email === 'admin@toomi.vn' || state.user.email === 'khuongtran227@gmail.com');
  const isPro = (state.user.tier === 'pro' || state.user.tier === 'agency' || (state.user.posts_limit && state.user.posts_limit >= 999999) || isAdmin);
  const tierLabel = isPro ? (isAdmin ? 'Gói Agency / Quản trị' : 'Gói Pro (Không giới hạn)') : 'Gói Miễn phí (10 bài/tháng)';
  const wsLabel = isPro ? 'Pro workspace' : 'Free workspace';
  const wsName = `${cleanName}'s Studio`;

  // Update avatars
  document.querySelectorAll('.admin-avatar').forEach(a => a.textContent = avatarChar);
  const wsAvatar = document.getElementById('workspace-avatar');
  if (wsAvatar) wsAvatar.textContent = avatarChar;

  // Update greeting and date
  const now = new Date();
  const hours = now.getHours();
  let timeGreeting = 'Good morning';
  if (hours >= 12 && hours < 18) timeGreeting = 'Good afternoon';
  else if (hours >= 18) timeGreeting = 'Good evening';

  const gTime = document.getElementById('dashboard-greeting-time');
  if (gTime) gTime.textContent = timeGreeting;
  const gName = document.getElementById('dashboard-user-name');
  if (gName) gName.textContent = cleanName;

  const dateOptions = { weekday: 'long', month: 'long', day: 'numeric' };
  const dateStr = now.toLocaleDateString('en-US', dateOptions).toUpperCase();
  const dDate = document.getElementById('dashboard-date');
  if (dDate) dDate.textContent = dateStr;

  // Update Workspace Name & Tier
  const wsNameEl = document.getElementById('workspace-name');
  if (wsNameEl) wsNameEl.textContent = wsName;
  const wsTierEl = document.getElementById('workspace-tier');
  if (wsTierEl) wsTierEl.textContent = wsLabel;
  const topCrumbEl = document.getElementById('topbar-workspace-name');
  if (topCrumbEl) topCrumbEl.textContent = wsName;

  // Update Sidebar profile row
  const pName = document.getElementById('profile-name');
  if (pName) pName.textContent = cleanName;
  const pPlan = document.getElementById('profile-plan');
  if (pPlan) pPlan.textContent = tierLabel;

  // Update Settings Team row
  const sName = document.getElementById('settings-user-name');
  if (sName) sName.textContent = cleanName;
  const sEmail = document.getElementById('settings-user-email');
  if (sEmail) sEmail.textContent = state.user.email || '';
  const sId = document.getElementById('settings-user-id');
  if (sId) sId.textContent = `ID: ${state.user.id || 'usr_27e2530c-2ea'}`;

  const sRoleBadge = document.getElementById('settings-role-badge');
  if (sRoleBadge) {
    sRoleBadge.textContent = isAdmin ? '👑 Super Admin' : 'Thành viên';
    sRoleBadge.className = isAdmin ? 'badge-super-admin' : 'pill neutral';
  }
  const sPlanBadge = document.getElementById('settings-plan-badge');
  if (sPlanBadge) {
    sPlanBadge.textContent = isPro ? '💎 Gói Pro Không Giới Hạn' : 'Gói Miễn Phí (10 bài/tháng)';
    sPlanBadge.className = isPro ? 'badge-tier-pro' : 'pill neutral';
  }

  // Hide Topbar upgrade button if already Pro
  const topUp = document.getElementById('topbar-upgrade-btn');
  if (topUp) topUp.hidden = isPro;

  // Dynamic n8n workflow button: only visible to Admin
  const n8nBtn = document.getElementById('btn-open-n8n');
  if (n8nBtn) {
    if (isAdmin) {
      n8nBtn.hidden = false;
      n8nBtn.textContent = 'Mở Workflow n8n (Admin) ↗';
      n8nBtn.onclick = () => window.open('https://n8n.toomi.vn/workflow/rg3KCmFJycBM7HaK', '_blank');
    } else {
      n8nBtn.hidden = true;
    }
  }

  // Update cURL sample in Developer view with dynamic host and user api key if available
  const sampleHost = window.location.origin;
  const curlBox = document.querySelector('.apikey-section + .card .curl-box');
  if (curlBox) {
    const activeKey = state.apiKeys && state.apiKeys.length > 0 ? (state.apiKeys[0].prefix + '...') : '<MÃ_API_KEY_CỦA_BẠN>';
    curlBox.innerHTML = `
<b>Method:</b> POST<br>
<b>URL:</b> ${sampleHost}/api/v1/publish<br>
<b>Headers:</b><br>
&nbsp;&nbsp;Authorization: Bearer ${activeKey}<br>
&nbsp;&nbsp;Content-Type: application/json<br>
<b>Body (JSON):</b><br>
{<br>
&nbsp;&nbsp;"source_url": "https://www.tiktok.com/@khan.linh6/video/7699443199626071317",<br>
&nbsp;&nbsp;"title": "Video từ n8n (tùy chọn)",<br>
&nbsp;&nbsp;"description": "#Shorts"<br>
}
    `.trim();
  }
}


// --- ANIMATED DYNAMIC ANALYTICS ENGINE (Chart.js) ---
let analyticsChartInstance = null;
let currentAnalyticsDays = 7;

function renderAnalytics(days = currentAnalyticsDays) {
  currentAnalyticsDays = days;
  const posts = state.posts || [];
  const publishedPosts = posts.filter(p => p.status === 'submitted');
  const queuedPosts = posts.filter(p => ['queued', 'posting'].includes(p.status));
  const failedPosts = posts.filter(p => p.status === 'failed');

  const publishedCount = publishedPosts.length;
  const queuedCount = queuedPosts.length;
  const successRate = (publishedCount + failedPosts.length) > 0 
    ? Math.round((publishedCount / (publishedCount + failedPosts.length)) * 100) 
    : 100;

  if (document.getElementById('analytics-total-published')) {
    document.getElementById('analytics-total-published').textContent = publishedCount;
  }
  if (document.getElementById('analytics-success-rate')) {
    document.getElementById('analytics-success-rate').textContent = `${successRate}%`;
  }
  if (document.getElementById('analytics-in-queue')) {
    document.getElementById('analytics-in-queue').textContent = queuedCount;
  }
  if (document.getElementById('analytics-active-channels')) {
    document.getElementById('analytics-active-channels').textContent = state.accounts?.length || 0;
  }

  // Build daily timeline
  const labels = [];
  const publishedData = [];
  const otherData = [];
  const now = new Date();

  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const dateStr = d.toISOString().slice(0, 10);
    labels.push(d.toLocaleDateString('vi-VN', { month: 'numeric', day: 'numeric' }));

    const pubForDay = publishedPosts.filter(p => {
      const pDate = new Date((p.created_at || 0) * 1000).toISOString().slice(0, 10);
      return pDate === dateStr;
    }).length;

    const otherForDay = posts.filter(p => {
      if (p.status === 'submitted') return false;
      const pDate = new Date((p.created_at || 0) * 1000).toISOString().slice(0, 10);
      return pDate === dateStr;
    }).length;

    publishedData.push(pubForDay);
    otherData.push(otherForDay);
  }

  // Update timeframe buttons
  document.querySelectorAll('.analytics-tf-btn').forEach(btn => {
    btn.classList.toggle('active', parseInt(btn.dataset.days) === days);
  });

  const canvas = document.getElementById('analyticsChart');
  if (!canvas || !window.Chart) return;

  const ctx = canvas.getContext('2d');
  if (analyticsChartInstance) {
    analyticsChartInstance.destroy();
  }

  const gradPub = ctx.createLinearGradient(0, 0, 0, 260);
  gradPub.addColorStop(0, 'rgba(99, 102, 241, 0.45)');
  gradPub.addColorStop(1, 'rgba(99, 102, 241, 0.0)');

  const gradOther = ctx.createLinearGradient(0, 0, 0, 260);
  gradOther.addColorStop(0, 'rgba(245, 158, 11, 0.35)');
  gradOther.addColorStop(1, 'rgba(245, 158, 11, 0.0)');

  analyticsChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Video đã xuất bản',
          data: publishedData,
          borderColor: '#6366f1',
          borderWidth: 3,
          backgroundColor: gradPub,
          fill: true,
          tension: 0.38,
          pointBackgroundColor: '#818cf8',
          pointBorderColor: '#ffffff',
          pointBorderWidth: 1.5,
          pointRadius: 4,
          pointHoverRadius: 7
        },
        {
          label: 'Đang xếp hàng / lỗi',
          data: otherData,
          borderColor: '#f59e0b',
          borderWidth: 2,
          borderDash: [5, 5],
          backgroundColor: gradOther,
          fill: true,
          tension: 0.38,
          pointBackgroundColor: '#fbbf24',
          pointBorderColor: '#ffffff',
          pointBorderWidth: 1.5,
          pointRadius: 3,
          pointHoverRadius: 6
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: 900,
        easing: 'easeOutQuart'
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 10,
          displayColors: true,
          cornerRadius: 8,
          callbacks: {
            label: function(ctx) {
              return ` ${ctx.dataset.label}: ${ctx.parsed.y} video`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#64748b', font: { size: 11, family: 'DM Sans' } }
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: {
            stepSize: 1,
            color: '#64748b',
            font: { size: 11, family: 'DM Sans' }
          }
        }
      }
    }
  });
}

// Timeframe selector clicks
document.addEventListener('click', function(e) {
  const btn = e.target.closest('.analytics-tf-btn');
  if (btn && btn.dataset.days) {
    renderAnalytics(parseInt(btn.dataset.days));
  }
});
