'use strict';
// Browser-only preview. No credentials, social API requests or fake publishing.
window.KhuoqtdPreview = (() => {
  const key='khuoqtd-publisher-preview-v1';
  const examples=[{id:'demo-youtube',provider:'youtube',external_id:'demo-only',name:'Kênh YouTube mẫu · DEMO'},
    {id:'demo-facebook',provider:'facebook',external_id:'demo-only',name:'Facebook Page mẫu · DEMO'}];
  function read(){try{const value=JSON.parse(localStorage.getItem(key)||'{}');return {posts:Array.isArray(value.posts)?value.posts:[],media:value.media||{},hidden:value.hidden||[]};}catch{return {posts:[],media:{},hidden:[]};}}
  function write(data){try{localStorage.setItem(key,JSON.stringify(data));}catch{throw new Error('Trình duyệt không cho lưu bản nháp. Kiểm tra quyền lưu trữ hoặc dung lượng.');}}
  async function probe(file){
    if(!(file instanceof File)||!file.name.toLowerCase().endsWith('.mp4'))throw new Error('Chọn video MP4.');
    if(file.size>250*1024*1024)throw new Error('Chọn video dưới 250 MB cho bản xem thử.');
    const url=URL.createObjectURL(file),video=document.createElement('video');video.preload='metadata';
    try{return await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Không đọc được thông tin video.')),15000);
      video.onloadedmetadata=()=>{clearTimeout(timer);if(!Number.isFinite(video.duration)||video.duration<=0){reject(new Error('Video không hợp lệ.'));return;}resolve({id:crypto.randomUUID(),filename:file.name,size:file.size,duration:video.duration,width:video.videoWidth,height:video.videoHeight,created_at:Date.now()/1000});};
      video.onerror=()=>{clearTimeout(timer);reject(new Error('Trình duyệt không đọc được MP4 này.'));};video.src=url;});}
    finally{URL.revokeObjectURL(url);video.removeAttribute('src');video.load();}
  }
  return {async request(path,options={}){
    const data=read();
    if(path==='/api/session')return {csrf:'browser-preview'};
    if(path==='/api/config')return {providers:{youtube:false,facebook:false},max_upload_mb:250,retention_days:7,worker:false,database:'Trình duyệt của bạn · bản demo',base_url:location.origin};
    if(path==='/api/accounts')return examples.filter(a=>!data.hidden.includes(a.id));
    if(path==='/api/posts'&&(!options.method||options.method==='GET'))return data.posts;
    if(path==='/api/media'){
      const item=await probe(options.body.get('file'));data.media[item.id]=item;write(data);return item;
    }
    if(path==='/api/posts'&&options.method==='POST'){
      const p=JSON.parse(options.body);
      if(p.action!=='draft')throw new Error('Bản demo không đăng bài hoặc chạy hẹn giờ. Chọn Lưu bản nháp để thử luồng soạn bài.');
      const existing=data.posts.filter(x=>x.batch_key===p.batch_key);if(existing.length)return {ids:existing.map(x=>x.id),deduplicated:true};
      if(!p.title.trim())throw new Error('Nhập tiêu đề.');
      const file=p.media_id?data.media[p.media_id]:null;
      const dest=p.account_ids.map(id=>examples.find(a=>a.id===id&&!data.hidden.includes(id)));
      if(dest.some(x=>!x))throw new Error('Kênh mẫu không hợp lệ.');
      if(dest.some(a=>a.provider==='youtube')&&!file)throw new Error('Chọn video cho kênh YouTube mẫu.');
      if(dest.some(a=>a.provider==='youtube')&&p.shorts&&(file.duration>180||file.width>file.height))throw new Error('Chế độ Shorts cần video vuông/dọc, tối đa 180 giây.');
      if(data.posts.length+dest.length>100)throw new Error('Bản demo giữ tối đa 100 bản nháp. Xuất bản nháp cần giữ rồi xóa dữ liệu demo để thử tiếp.');
      const now=Date.now()/1000;
      const rows=dest.map(a=>({...p,id:crypto.randomUUID(),account_id:a.id,account_name:a.name,provider:a.provider,status:'draft',tags:JSON.stringify(p.tags),created_at:now,updated_at:now,scheduled_at:p.scheduled_at?Date.parse(p.scheduled_at)/1000:now,remote_id:null,remote_url:null,error:null}));
      data.posts.unshift(...rows);write(data);return {ids:rows.map(r=>r.id),deduplicated:false};
    }
    const change=path.match(/^\/api\/posts\/([^/]+)\/(queue|cancel)$/);
    if(change){if(change[2]==='queue')throw new Error('Chỉ xem thử. Chưa có máy chủ đăng bài hoặc tài khoản thật.');const item=data.posts.find(x=>x.id===change[1]);if(!item||item.status!=='draft')throw new Error('Bản nháp không còn khả dụng.');item.status='cancelled';write(data);return {ok:true};}
    throw new Error('Tính năng này cần backend trên VPS và tài khoản được cấp quyền OAuth.');
  }, exportDrafts(){return read().posts;}, reset(){localStorage.removeItem(key);}};
})();
