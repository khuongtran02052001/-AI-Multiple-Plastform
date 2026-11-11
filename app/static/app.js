'use strict';
const $ = (id) => document.getElementById(id);
const state = {csrf: '', accounts: [], posts: [], config: {}, media: null, blob: null, batch: crypto.randomUUID(), view: 'compose', busy: false, uploading: false};
const labels = {draft:'Bản nháp',queued:'Đang chờ',posting:'Đang gửi',submitted:'Đã gửi nền tảng',failed:'Bị từ chối',unknown:'Cần kiểm tra',cancelled:'Đã hủy'};
const platformName = (p) => p === 'youtube' ? 'YouTube' : 'Facebook Page';
function el(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; }
function icon(provider) { return el('span', `platform-icon ${provider}`, provider==='youtube'?'▶':'f'); }
function notice(message, error=false) { $('notice').textContent=message; $('notice').classList.toggle('error',error); $('notice').hidden=false; }
function loggedOut() { state.csrf=''; $('workspace').hidden=true; $('login-screen').hidden=false; }
async function api(path, options={}) {
  const headers={...(options.headers||{})};
  if(options.body && !(options.body instanceof FormData)) headers['Content-Type']='application/json';
  if(options.method && options.method!=='GET') headers['X-CSRF-Token']=state.csrf;
  const response=await fetch(path,{...options,headers});
  const data=await response.json();
  if(!response.ok) {
    if(response.status===401 && path!=='/api/login') loggedOut();
    const detail=typeof data.detail==='string'?data.detail:'Dữ liệu chưa hợp lệ. Kiểm tra các trường nhập.';
    throw new Error(detail);
  }
  return data;
}
function changeView(view) {
  state.view=view;
  for(const name of ['compose','history','accounts']) $(name+'-view').hidden=name!==view;
  document.querySelectorAll('.nav-button').forEach(n=>n.classList.toggle('active',n.dataset.view===view));
  $('breadcrumb-view').textContent={compose:'Tạo bài mới',history:'Bài đăng',accounts:'Kênh kết nối'}[view];
  if(view==='history') refreshPosts().catch(e=>notice(e.message,true));
}
document.querySelectorAll('[data-view]').forEach(n=>n.addEventListener('click',()=>changeView(n.dataset.view)));
function preview() {
  $('title-count').textContent=`${$('title').value.length} / 100`;
  $('preview-title').textContent=$('title').value||'Tiêu đề bài đăng';
  $('preview-description').textContent=$('description').value||'Nội dung mô tả sẽ hiển thị tại đây.';
  const checked=[...document.querySelectorAll('#channel-picker input:checked')].map(n=>state.accounts.find(a=>a.id===n.value)?.name);
  $('preview-channel').textContent=checked.join(' · ')||'Chọn một kênh để bắt đầu';
}
function renderAccounts() {
  $('channel-picker').replaceChildren(); $('connected-list').replaceChildren();
  $('no-accounts').hidden=state.accounts.length>0; $('account-count').textContent=`${state.accounts.length} kênh`;
  for(const account of state.accounts) {
    const option=el('label','channel-option'); const checkbox=el('input'); checkbox.type='checkbox';checkbox.value=account.id;checkbox.addEventListener('change',preview);
    const copy=el('span','',account.name);copy.append(el('small','',platformName(account.provider))); option.append(checkbox,icon(account.provider),copy);$('channel-picker').append(option);
    const row=el('div','account-row');const detail=el('div');detail.append(el('strong','',account.name),el('small','',`${platformName(account.provider)} · ${account.external_id}`));
    const disconnect=el('button','text-button','Ngắt kết nối');disconnect.type='button';disconnect.onclick=async()=>{
      if(!confirm(`Ngắt kết nối ${account.name}? Bài đang chờ của kênh này sẽ bị dừng.`))return;
      disconnect.disabled=true;try{await api(`/api/accounts/${account.id}/disconnect`,{method:'POST'});await load();notice('Đã xóa token của kênh khỏi công cụ.');}catch(e){notice(e.message,true);disconnect.disabled=false;}
    };row.append(icon(account.provider),detail,disconnect);$('connected-list').append(row);
  }
  if(!state.accounts.length) $('connected-list').append(el('p','empty-hint','Chưa kết nối tài khoản. Cấu hình OAuth rồi dùng nút Kết nối ở trên.'));
  $('provider-list').replaceChildren();
  for(const provider of ['youtube','facebook']) {
    const card=el('article','card provider-card'),body=el('div');body.append(el('h2','',platformName(provider)),el('p','',provider==='youtube'?'Video và Shorts. Chọn đúng kênh khi cấp quyền Google.':'Bài chữ và video trên các Trang bạn quản lý.'));
    const ready=state.config.providers?.[provider];const button=el('button','secondary',ready?'Kết nối tài khoản ↗':'Chưa cấu hình OAuth');button.disabled=!ready;button.onclick=async()=>{button.disabled=true;try{const r=await api(`/api/oauth/${provider}/start`,{method:'POST'});location.assign(r.url);}catch(e){notice(e.message,true);button.disabled=false;}};
    body.append(button);if(!ready)body.append(el('p','field-help','Nhập thông tin ứng dụng trong .env trên VPS rồi khởi động lại.'));card.append(icon(provider),body);$('provider-list').append(card);
  }
  $('environment-info').replaceChildren();
  for(const [k,v] of [['Database',state.config.database],['Tiến trình đăng',state.config.worker?'Đang bật':'Đang tắt'],['Lưu video',`Trên VPS · dọn sau ${state.config.retention_days} ngày nếu không còn chờ xử lý`]]){const row=el('div','environment-line');row.append(el('span','',k),el('strong','',v));$('environment-info').append(row);}
  $('upload-limit').textContent=`MP4 · tối đa ${state.config.max_upload_mb} MB`;
  preview();
}
function renderPosts() {
  const rows=state.posts; $('nav-count').textContent=rows.length;
  $('stat-total').textContent=rows.length; $('stat-queued').textContent=rows.filter(p=>['queued','posting'].includes(p.status)).length;
  $('stat-submitted').textContent=rows.filter(p=>p.status==='submitted').length;$('stat-errors').textContent=rows.filter(p=>['failed','unknown'].includes(p.status)).length;
  const filter=$('status-filter').value;const selected=rows.filter(p=>filter==='all'||p.status===filter);$('post-list').replaceChildren();
  if(!selected.length){const blank=el('div','empty-state');blank.append(el('strong','',rows.length?'Không có bài ở trạng thái này':'Nội dung đầu tiên bắt đầu ở đây'),el('p','',rows.length?'Chọn trạng thái khác để xem bài đăng.':'Tạo bài mới, chọn kênh và lưu nháp hoặc đưa vào hàng đợi.'));$('post-list').append(blank);}
  for(const post of selected){
    const card=el('article','card post-card'),body=el('div','post-body');body.append(el('h2','',post.title),el('p','',`${post.account_name} · ${new Date(post.created_at*1000).toLocaleString('vi-VN')}`));
    if(post.status==='queued')body.append(el('p','',`Giờ gửi: ${new Date(post.scheduled_at*1000).toLocaleString('vi-VN')}`));
    if(post.error)body.append(el('p','post-error',post.error));
    const actions=el('div','post-actions');
    if(post.remote_url){const link=el('a','',`Mở trên ${platformName(post.provider)} ↗`);link.href=post.remote_url;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);}
    for(const [action,text] of [['queue',post.status==='failed'?'Thử lại':'Đưa vào hàng đợi'],['cancel','Hủy']]){
      if(!(action==='queue'?['draft','failed']:['draft','queued']).includes(post.status))continue;
      const b=el('button','text-button',text);b.onclick=async()=>{if(action==='queue'&&!confirm('Gửi bài này lên nền tảng?'))return;b.disabled=true;try{await api(`/api/posts/${post.id}/${action}`,{method:'POST'});await refreshPosts();}catch(e){notice(e.message,true);b.disabled=false;}};actions.append(b);
    }
    if(post.status==='unknown')body.append(el('p','field-help','Chưa rõ kết quả: kiểm tra tài khoản trước khi tạo bài mới. Công cụ không tự đăng lại.'));
    body.append(actions);card.append(icon(post.provider),body,el('span',`status ${post.status}`,labels[post.status]||post.status));$('post-list').append(card);
  }
}
async function refreshPosts(){state.posts=await api('/api/posts');renderPosts();}
async function load(){[state.config,state.accounts]=await Promise.all([api('/api/config'),api('/api/accounts')]);renderAccounts();await refreshPosts();}
async function enter(){await load();$('login-screen').hidden=true;$('workspace').hidden=false;const connection=new URLSearchParams(location.search).get('connection');if(connection){notice(connection==='success'?'Đã kết nối tài khoản.':'Đã hủy cấp quyền.');history.replaceState({},'',location.pathname);}}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;$('login-error').textContent='';try{const r=await api('/api/login',{method:'POST',body:JSON.stringify({password:$('password').value})});state.csrf=r.csrf;$('password').value='';await enter();}catch(err){$('login-error').textContent=err.message;}finally{b.disabled=false;}});
$('logout').onclick=async()=>{try{await api('/api/logout',{method:'POST'});loggedOut();}catch(e){notice(e.message,true);}};
$('title').oninput=preview;$('description').oninput=preview;$('status-filter').onchange=renderPosts;$('refresh-posts').onclick=()=>refreshPosts().catch(e=>notice(e.message,true));
async function upload(file){
  if(!file||state.uploading)return;
  state.uploading=true;state.media=null;$('upload-info').hidden=false;$('upload-info').textContent='Đang tải và kiểm tra video…';$('video').disabled=true;
  try{if(!file.name.toLowerCase().endsWith('.mp4'))throw new Error('Chọn file MP4.');if(file.size>state.config.max_upload_mb*1024*1024)throw new Error('Video vượt giới hạn dung lượng.');
    const data=new FormData();data.append('file',file);state.media=await api('/api/media',{method:'POST',body:data});
    $('upload-info').textContent=`${state.media.filename} · ${(state.media.size/1024/1024).toFixed(1)} MB · ${Math.round(state.media.duration)} giây · ${state.media.width} × ${state.media.height}`;
    if(state.blob)URL.revokeObjectURL(state.blob);state.blob=URL.createObjectURL(file);$('video-preview').src=state.blob;$('video-preview').hidden=false;$('preview-placeholder').hidden=true;
  }catch(e){$('upload-info').textContent=e.message;notice(e.message,true);$('video-preview').hidden=true;$('preview-placeholder').hidden=false;}
  finally{state.uploading=false;$('video').disabled=false;}
}
$('video').onchange=e=>upload(e.target.files[0]);
for(const type of ['dragenter','dragover'])$('dropzone').addEventListener(type,e=>{e.preventDefault();$('dropzone').classList.add('dragging');});
for(const type of ['dragleave','drop'])$('dropzone').addEventListener(type,e=>{e.preventDefault();$('dropzone').classList.remove('dragging');if(type==='drop')upload(e.dataTransfer.files[0]);});
async function submit(action){
  if(state.busy)return;if(state.uploading){notice('Chờ video tải xong.',true);return;}if(!$('post-form').reportValidity())return;
  const ids=[...document.querySelectorAll('#channel-picker input:checked')].map(n=>n.value);if(!ids.length){notice('Chọn ít nhất một kênh đăng.',true);return;}
  if(action==='queue'&&!confirm(`Gửi nội dung tới ${ids.length} kênh đã chọn? Quyền riêng tư YouTube: ${$('privacy').selectedOptions[0].textContent}.`))return;
  state.busy=true;$('queue-button').disabled=true;$('draft-button').disabled=true;
  try{await api('/api/posts',{method:'POST',body:JSON.stringify({batch_key:state.batch,account_ids:ids,title:$('title').value,description:$('description').value,
    tags:$('tags').value.split(',').map(t=>t.trim()).filter(Boolean),media_id:state.media?.id||null,privacy:$('privacy').value,made_for_kids:$('kids').checked,shorts:$('shorts').checked,action,
    scheduled_at:$('schedule').value?new Date($('schedule').value).toISOString():null})});
    state.batch=crypto.randomUUID();state.media=null;$('post-form').reset();$('upload-info').hidden=true;$('video-preview').pause();$('video-preview').removeAttribute('src');$('video-preview').hidden=true;$('preview-placeholder').hidden=false;if(state.blob){URL.revokeObjectURL(state.blob);state.blob=null;}preview();changeView('history');notice(action==='draft'?'Đã lưu bản nháp.':'Đã đưa bài vào hàng đợi. Theo dõi kết quả bên dưới.');await refreshPosts();
  }catch(e){notice(e.message,true);}finally{state.busy=false;$('queue-button').disabled=false;$('draft-button').disabled=false;}
}
$('post-form').onsubmit=e=>{e.preventDefault();submit('queue');};$('draft-button').onclick=()=>submit('draft');
$('timezone-label').textContent=`Theo giờ máy của bạn: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Lưu và xử lý theo UTC.`;
setInterval(()=>{if(state.csrf&&!document.hidden)refreshPosts().catch(e=>notice(e.message,true));},12000);
(async()=>{try{const r=await api('/api/session');state.csrf=r.csrf;await enter();}catch(e){loggedOut();if(!e.message.includes('Đăng nhập')&&!e.message.includes('hết hạn'))$('login-error').textContent=e.message;}})();
