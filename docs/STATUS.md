# Trạng thái và đích triển khai

Goal: gửi một link TikTok vào Telegram → tự tải video, lấy caption/hashtag → đăng YouTube → báo kết quả. Backend riêng, không phụ thuộc Upload-Post.

## Đã kiểm chứng trong mã nguồn
- PR #2 và #3 đã merge; API riêng, queue PostgreSQL và workflow n8n đã có.
- Bot nhận URL trực tiếp hoặc /publish; chỉ người dùng/chat được cho phép.
- Caption/hashtag lấy từ metadata tải về; có giá trị dự phòng nếu thiếu.
- Upload thử dùng quyền riêng tư private; submitted chỉ có nghĩa API đã nhận video.

## Chưa kiểm chứng production
- VPS đã được báo cáo chạy bản caff6db ở loopback 8090; chưa xác nhận cập nhật bản tích hợp.
- Chưa có URL HTTPS Publisher được cung cấp.
- Chưa xác nhận Google OAuth và kênh đích.
- Chưa import/kích hoạt hai workflow n8n thật.
- Chưa thử video TikTok có quyền sử dụng → YouTube Studio → Telegram.

## Thứ tự hoàn tất
1. Cập nhật repo trên VPS, giữ .env và volume; triển khai lại riêng Publisher.
2. Dùng Docker network chung để n8n/Caddy truy cập publisher:8000; chặn /internal/* ở public proxy.
3. Cấu hình domain HTTPS và BASE_URL, kết nối Google OAuth.
4. Điền account UUID, service credential, Telegram credential và allowlist trong n8n.
5. Kiểm thử một video private và đường lỗi; kiểm tra YouTube Studio, thông báo và chống trùng.
6. Chỉ chuyển sang đăng công khai sau khi xác nhận luồng private thành công.

Không coi test giả lập hoặc container healthy là kiểm thử đăng bài thực tế.
