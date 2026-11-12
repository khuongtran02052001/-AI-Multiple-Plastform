"""Build a strictly browser-local trial; never imports backend or secrets."""
from pathlib import Path
import shutil

root=Path(__file__).resolve().parents[1]
target=root/'public'
(target/'static').mkdir(parents=True,exist_ok=True)
html=(root/'app/static/index.html').read_text()
html=html.replace('<script src="/static/app.js" defer></script>',
    '<script src="/static/local-api.js" defer></script><script src="/static/app.js" defer></script><script src="/static/preview-ui.js" defer></script>')
html=html.replace('<title>khuoqtd Publisher — Không gian xuất bản</title>','<title>khuoqtd Publisher — Bản trải nghiệm</title>')
(target/'index.html').write_text(html)
js=(root/'app/static/app.js').read_text()
js=js.replace('async function api(path, options={}) {','async function api(path, options={}) {\n  return window.KhuoqtdPreview.request(path, options);\n  /* Production HTTP implementation omitted from the trial. */\n}\nasync function unusedProductionApi(path, options={}) {',1)
js=js.replace('`Trên VPS · dọn sau ${state.config.retention_days} ngày nếu không còn chờ xử lý`',"'Video chỉ được xem tại máy bạn; không tải lên máy chủ'")
js=js.replace("'Chưa cấu hình OAuth'","'Cần cấu hình trên VPS'")
js=js.replace("'Đang tải và kiểm tra video…'","'Đang đọc video tại máy bạn…'")
js=js.replace("'Đã lưu bản nháp.'","'Đã lưu bản nháp trong trình duyệt này.'")
js=js.replace("$('queue-button').disabled=false", "$('queue-button').disabled=true")
(target/'static/app.js').write_text(js)
css=(root/'app/static/style.css').read_text()+'''\n.demo-bar{background:#eaf0df;border:1px solid #d1ddbf;border-radius:10px;padding:14px 18px;margin-bottom:25px;display:flex;align-items:center;justify-content:space-between;gap:20px}.demo-bar strong{display:block;font-size:10px;letter-spacing:1.4px;color:#456b35}.demo-bar span{display:block;font-size:11px;color:#65765a;margin-top:4px}.demo-actions{display:flex;gap:18px;flex-shrink:0}.demo-actions button{font-size:11px}#schedule{opacity:.5}@media(max-width:850px){.demo-bar{align-items:flex-start;flex-direction:column;gap:10px}.demo-actions{gap:20px}}\n'''
(target/'static/style.css').write_text(css)
for name in ('local-api.js','preview-ui.js'):shutil.copyfile(root/'preview'/name,target/'static'/name)
shutil.copyfile(target/'index.html',target/'workspace.html')
shutil.copyfile(root/'preview'/'autopost.html',target/'index.html')
print('Built browser-local preview in public/. No backend, secrets or social publishing included.')
