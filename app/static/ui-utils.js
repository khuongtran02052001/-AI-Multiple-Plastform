/* Shared UI behavior; contains no credentials or publishing calls. */
(function (root) {
  'use strict';
  const dateKey = d => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  function analytics(posts, days, platform, now = new Date()) {
    const start = new Date(now); start.setHours(0, 0, 0, 0); start.setDate(start.getDate() - days + 1);
    const rows = posts.filter(p => (platform === 'all' || p.provider === platform) &&
      p.created_at * 1000 >= start.getTime() && p.created_at * 1000 <= now.getTime());
    const labels = [], submitted = [], other = [];
    for (let i = 0; i < days; i++) {
      const d = new Date(start); d.setDate(d.getDate() + i);
      const daily = rows.filter(p => dateKey(new Date(p.created_at * 1000)) === dateKey(d));
      labels.push(d.toLocaleDateString('vi-VN', {month:'numeric', day:'numeric'}));
      submitted.push(daily.filter(p => p.status === 'submitted').length);
      other.push(daily.filter(p => ['queued','posting','failed','unknown'].includes(p.status)).length);
    }
    return {rows, labels, submitted, other};
  }
  function upload(file, csrf, onProgress, onUnauthorized) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/media'); xhr.setRequestHeader('X-CSRF-Token', csrf);
      xhr.timeout = 15 * 60 * 1000;
      xhr.upload.onprogress = e => onProgress(e.lengthComputable ? Math.min(100, Math.floor(e.loaded / e.total * 100)) : null);
      xhr.upload.onload = () => onProgress(null);
      xhr.onerror = () => reject(new Error('Mất kết nối khi tải video. Kiểm tra mạng rồi chọn lại file.'));
      xhr.ontimeout = () => reject(new Error('Tải video quá thời gian chờ. Chọn lại file để thử lại.'));
      xhr.onabort = () => reject(new Error('Đã hủy tải video.'));
      xhr.onload = () => {
        let data;
        try { data = JSON.parse(xhr.responseText); }
        catch (_) { reject(new Error(`Máy chủ trả phản hồi không hợp lệ (HTTP ${xhr.status}).`)); return; }
        if (xhr.status === 401) onUnauthorized();
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(new Error(typeof data.detail === 'string' ? data.detail : `Không tải được video (HTTP ${xhr.status}).`)); return;
        }
        resolve(data);
      };
      const body = new FormData(); body.append('file', file); xhr.send(body);
    });
  }
  const ui = {analytics, upload};
  if (typeof module !== 'undefined' && module.exports) module.exports = ui;
  else root.OmniUI = ui;
})(typeof globalThis !== 'undefined' ? globalThis : this);
