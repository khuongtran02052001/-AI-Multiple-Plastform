# Kiểm chứng bản bàn giao — 11/11/2026

## Đã kiểm tra

- `python -m pytest -q`: **19 passed** (có 1 cảnh báo deprecation của thư viện test Starlette/httpx).
- `python -m compileall -q app`: qua kiểm tra cú pháp Python.
- `node --check app/static/app.js`: qua kiểm tra cú pháp JavaScript.
- `pip check`: không có dependency bị thiếu/xung đột.
- Trình duyệt: mở được trang đăng nhập và workspace QA cục bộ; chuyển Tạo bài / Bài đăng / Kênh kết nối; nhập tiêu đề/mô tả cập nhật preview; chặn lưu bài khi chưa chọn kênh; hiển thị đúng trạng thái chưa cấu hình OAuth.

## Các nhóm kiểm thử backend

Đăng nhập và đăng xuất; giới hạn đăng nhập; CSRF và Origin; idempotency; hai worker tranh cùng bài; thành công/từ chối/timeout/crash; phục hồi job quá hạn sang unknown; OAuth state ràng buộc phiên và chỉ dùng một lần; mã hóa token và không lộ qua API; ngắt kết nối dừng bài chờ; kiểm tra lịch có múi giờ; kiểm tra MP4 bằng ffprobe và kích thước Shorts; HTTP contract upload YouTube dùng phản hồi giả lập; Facebook bắt buộc Page token và che token trong lỗi; refresh token YouTube; dọn media vẫn giữ bài chờ/unknown.

## Chưa xác minh trong môi trường thật

- Backend chưa triển khai lên VPS. Repo có cấu hình Vercel cho bản xem thử giao diện, chưa có deployment Vercel được xác nhận. Thương hiệu của mã nguồn là khuoqtd.

- Chưa kết nối hoặc sửa database Supabase thật. Chỉ kiểm tra với SQLite. RLS/revoke PostgreSQL có trong bộ khởi tạo, cần kiểm tra lại sau khi chọn đúng project và chạy trên Supabase.
- Chưa build/chạy Docker image hoặc Caddy trong môi trường này vì không có Docker daemon.
- Chưa có OAuth client riêng, chưa kiểm thử callback Google/Meta thật, chưa đăng bài công khai hoặc gửi video thật lên nền tảng.
- Đã kiểm tra bản demo trên trình duyệt: tạo nháp Facebook mẫu và giữ được nháp sau khi tải lại. Trang deploy riêng tư yêu cầu đăng nhập ChatGPT; kiểm thử thao tác dùng cùng build ở preview cục bộ.

Các kiểm thử dùng API giả lập xác nhận logic và cấu trúc yêu cầu; không chứng minh quyền API của một tài khoản thật hoặc trạng thái kiểm duyệt video. Không tuyên bố đảm bảo exactly-once hoặc bảo mật được kiểm toán độc lập.
