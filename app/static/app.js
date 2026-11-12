'use strict';
const $ = (id) => document.getElementById(id);
const state = {csrf: '', accounts: [], posts: [], config: {}, media: null, blob: null, batch: crypto.randomUUID(), view: 'compose', busy: false, uploading: false};
const labels = {draft:'Draft',queued:'Queued',posting:'Publishing',submitted:'Delivered',failed:'Failed',unknown:'Review needed',cancelled:'Cancelled'};
const platformName = (p) => ({youtube:'YouTube',facebook:'Facebook Page',tiktok:'TikTok',instagram:'Instagram',linkedin:'LinkedIn',x:'X',pinterest:'Pinterest'}[p]||p);
function el(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; }
function icon(provider) { return el('span', `platform-icon ${provider}`, ({youtube:'▶',facebook:'f',tiktok:'♪',instagram:'◎',linkedin:'in',x:'𝕏',pinterest:'p'}[provider]||'•')); }
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
  if(view==='history'||view==='calendar'||view==='dashboard'||view==='analytics') refreshPosts().catch(e=>notice(e.message,true));
}
document.addEventListener('click',event=>{const trigger=event.target.closest('[data-view]');if(trigger)changeView(trigger.dataset.view);});
function preview() {
  $('title-count').textContent=`${$('title').value.length} / 100`;
  $('preview-title').textContent=$('title').value||'Your post title';
  $('preview-description').textContent=$('description').value||'Your caption and hashtags will appear here.';
  const checked=[...document.querySelectorAll('#channel-picker input:checked')].map(n=>state.accounts.find(a=>a.id===n.value)?.name).filter(Boolean);
  $('preview-channel').textContent=checked.join(' · ')||'Choose a channel to get started';
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
    const card=el('article','card provider-card'),body=el('div'),ready=state.config.providers?.[provider];
    const descriptions={youtube:'Publish videos and Shorts with privacy controls.',facebook:'Publish text and video to the Pages you manage.',tiktok:'Video publishing is not configured in this deployment.',instagram:'Connect an eligible Instagram Business account.',linkedin:'Share updates with your professional audience.',x:'Social publishing is not configured in this deployment.',pinterest:'Share ideas and videos with your boards.'};
    body.append(el('h2','',platformName(provider)),el('p','',descriptions[provider]));
    const button=el('button','secondary',ready?'Connect account ↗':(['youtube','facebook'].includes(provider)?'OAuth setup required':'Coming soon'));button.disabled=!ready;button.onclick=async()=>{button.disabled=true;try{const r=await api(`/api/oauth/${provider}/start`,{method:'POST'});location.assign(r.url);}catch(e){notice(e.message,true);button.disabled=false;}};
    body.append(button);if(!ready&&['youtube','facebook'].includes(provider))body.append(el('p','field-help','Add platform OAuth credentials to your private deployment to enable account linking.'));card.append(icon(provider),body);$('provider-list').append(card);
  }
  $('environment-info').replaceChildren();
  for(const [k,v] of [['Database',state.config.database],['Publishing worker',state.config.worker?'Running':'Stopped'],['Video storage',`On server · removed after ${state.config.retention_days} days when no longer queued`]]){const row=el('div','environment-line');row.append(el('span','',k),el('strong','',v));$('environment-info').append(row);}
  $('upload-limit').textContent=`MP4 · up to ${state.config.max_upload_mb} MB`;
  renderSettings();
  renderDashboard();
  preview();
}
function renderDashboard() {
  const published=state.posts.filter(p=>p.status==='submitted').length;
  const queued=state.posts.filter(p=>['queued','posting'].includes(p.status)).length;
  $('dash-published').textContent=published;
  $('dash-queued').textContent=queued;
  $('analytics-published').textContent=published;
  $('dash-accounts').textContent=state.accounts.length;
  const sampleProcessing=!queued&&/demo/i.test(state.config.database||'');
  $('processing-label').textContent=queued?`${queued} post${queued===1?'':'s'} in the publishing queue`:sampleProcessing?'Sample TikTok ingestion · converting to 9:16':'Waiting for your next post';
  $('processing-percent').textContent=queued?'In queue':sampleProcessing?'65% · Demo':'Ready';
  const progress=$('processing-progress');
  progress.style.width=sampleProcessing?'65%':'0%';
  progress.setAttribute('aria-valuenow',sampleProcessing?'65':'0');
  progress.setAttribute('aria-label',sampleProcessing?'Demo video ingestion progress':'Publishing queue progress');
  $('processing-foot').textContent=queued?'Your publishing worker will process these posts':sampleProcessing?'Illustrative progress only · no live media job is running':'Your channels are standing by';
  const channels=$('dashboard-channels');channels.replaceChildren();
  for(const provider of ['youtube','facebook']) {
    const matched=state.accounts.filter(a=>a.provider===provider);
    const row=el('div','channel-summary');row.append(icon(provider));
    const copy=el('span');copy.append(el('strong','',provider==='youtube'?'YouTube':'Facebook Pages'),el('small','',matched.length?matched.map(a=>a.name).join(', '):'Not connected'));
    row.append(copy,el('span','channel-status',matched.length?'Connected':'—'));channels.append(row);
  }
  const target=$('dashboard-posts');target.replaceChildren();
  const recent=state.posts.slice(0,4);
  if(!recent.length){const blank=el('div','empty-state');blank.append(el('strong','', 'Your publishing story starts here'),el('p','', 'Once you create a post, its progress will show up here.'));const create=el('button','secondary','Create your first post');create.type='button';create.dataset.view='compose';blank.append(create);target.append(blank);}
  for(const post of recent){const row=el('div','dashboard-post-row');row.append(icon(post.provider));const copy=el('div','dashboard-post-copy');copy.append(el('strong','',post.title),el('small','',`${post.account_name} · ${new Date(post.created_at*1000).toLocaleDateString('en-US',{month:'short',day:'numeric'})}`));row.append(copy,el('span',`status ${post.status}`,labels[post.status]||post.status));target.append(row);}
  renderCalendar();
}
function renderCalendar() {
  const target=$('calendar-list');if(!target)return;target.replaceChildren();
  const upcoming=state.posts.filter(p=>['queued','posting','submitted'].includes(p.status)).slice(0,8);
  if(!upcoming.length){const blank=el('div','empty-state');blank.append(el('strong','', 'Your calendar is ready when you are'),el('p','', 'Schedule a post to see it here.'));const create=el('button','secondary','Create a scheduled post');create.type='button';create.dataset.view='compose';blank.append(create);target.append(blank);return;}
  for(const post of upcoming){const row=el('div','calendar-row'),when=new Date((post.scheduled_at||post.created_at)*1000),date=el('span','calendar-date');date.append(el('strong','',String(when.getDate()).padStart(2,'0')),document.createTextNode(when.toLocaleDateString('en-US',{month:'short'})));const copy=el('div');copy.append(el('strong','',post.title),el('small','',`${when.toLocaleString('en-US',{weekday:'short',hour:'numeric',minute:'2-digit'})} · ${post.account_name}`));row.append(date,copy,el('span',`status ${post.status}`,labels[post.status]||post.status));target.append(row);}
}
function renderSettings() {
  const target=$('settings-info');if(!target)return;target.replaceChildren();
  for(const [key,value] of [['Publishing database',state.config.database||'Loading'],['Publishing worker',state.config.worker?'Active':'Inactive'],['Video storage',`Private VPS storage · ${state.config.retention_days} day retention`],['Maximum video size',`${state.config.max_upload_mb||0} MB`]]){const row=el('div','environment-line');row.append(el('span','',key),el('strong','',value));target.append(row);}
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
    if(post.status==='unknown')body.append(el('p','field-help','Delivery status is unclear. Check the account before creating another post; this tool will not retry automatically.'));
    body.append(actions);card.append(icon(post.provider),body,el('span',`status ${post.status}`,labels[post.status]||post.status));$('post-list').append(card);
  }
  renderDashboard();
}
async function refreshPosts(){state.posts=await api('/api/posts');renderPosts();}
async function load(){[state.config,state.accounts]=await Promise.all([api('/api/config'),api('/api/accounts')]);renderAccounts();await refreshPosts();}
async function enter(){await load();$('login-screen').hidden=true;$('workspace').hidden=false;const connection=new URLSearchParams(location.search).get('connection');if(connection){notice(connection==='success'?'Account connected.':'Authorization cancelled.');history.replaceState({},'',location.pathname);}}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;$('login-error').textContent='';try{const r=await api('/api/login',{method:'POST',body:JSON.stringify({password:$('password').value})});state.csrf=r.csrf;$('password').value='';await enter();}catch(err){$('login-error').textContent=err.message;}finally{b.disabled=false;}});
$('logout').onclick=async()=>{try{await api('/api/logout',{method:'POST'});loggedOut();}catch(e){notice(e.message,true);}};
document.querySelectorAll('[data-preview]').forEach(tab=>tab.addEventListener('click',()=>{document.querySelectorAll('[data-preview]').forEach(item=>item.classList.toggle('active',item===tab));const platform=tab.dataset.preview;$('preview-channel').textContent=platform==='youtube'?'YouTube Shorts preview':platform==='tiktok'?'TikTok preview · channel connection unavailable':'Facebook Reels preview';}));
$('ingest-button').addEventListener('click',()=>{const input=$('ingest-url');if(!input.reportValidity()||!input.value)return;notice('Link ingestion is not configured for this deployment. Upload an MP4 directly to continue.',true);});
$('title').oninput=preview;$('description').oninput=preview;$('status-filter').onchange=renderPosts;$('refresh-posts').onclick=()=>refreshPosts().catch(e=>notice(e.message,true));
async function upload(file){
  if(!file||state.uploading)return;
  state.uploading=true;state.media=null;$('upload-info').hidden=false;$('upload-info').textContent='Uploading and checking your video…';$('video').disabled=true;
  try{if(!file.name.toLowerCase().endsWith('.mp4'))throw new Error('Choose an MP4 file.');if(file.size>state.config.max_upload_mb*1024*1024)throw new Error('The video exceeds the size limit.');
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
(async()=>{try{const r=await api('/api/session');state.csrf=r.csrf;await enter();}catch(e){loggedOut();if(!e.message.includes('Đăng nhập')&&!e.message.includes('hết hạn'))$('login-error').textContent=e.message;}})();
