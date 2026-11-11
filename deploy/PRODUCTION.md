# Triển khai khuoqtd Publisher

Thư mục cố định: **`/root/Khuong/khuoqtd-publisher`**. Không đặt mã hay khóa vào thư mục n8n.

## 1. Chuẩn bị trên VPS

Chạy trên máy có quyền SSH vào VPS:

```bash
ssh root@YOUR_VPS_IP
```

Trong phiên SSH:

```bash
install -d -m 700 /root/Khuong
git clone https://github.com/khuongtran02052001/-AI-Multiple-Plastform.git /root/Khuong/khuoqtd-publisher
cd /root/Khuong/khuoqtd-publisher
bash deploy/vps.sh prepare
```

Nếu thư mục đã có dữ liệu, không xóa hoặc clone đè; kiểm tra repo hiện có trước. Script yêu cầu Docker Engine + Compose đã cài. Nó tạo mật khẩu quản trị và khóa mã hóa thông qua `app.setup`; không chứa sẵn mật khẩu.

## 2. Supabase production

Sử dụng project production mà chủ sở hữu đã chỉ định; lấy đúng thông tin từ Dashboard của project đó.

- URL và publishable/secret API key dùng cho HTTP Data API, **không phải** thông tin đăng nhập PostgreSQL.
- Backend hiện dùng SQLAlchemy/psycopg. Lấy **Connect → Session pooler**, nhập mật khẩu database trực tiếp trong `.env` trên VPS.
- Đầu chuỗi dùng `postgresql+psycopg://`, giữ chính xác host/user do Dashboard cung cấp và thêm `sslmode=require` (hoặc `verify-full` cùng CA).
- Không đưa database password, API secret, SSH password hay `.env` vào GitHub.
- App tự tạo bảng `sp_*` khi khởi động với quyền database phù hợp. Có thể tạo trước bằng [supabase-bootstrap.sql](supabase-bootstrap.sql) trong SQL Editor của đúng project. File này bật RLS và thu hồi quyền truy cập trực tiếp của trình duyệt; không cần chạy cả hai cách.
- API key hoạt động không đồng nghĩa kết nối quản trị hiện tại được quyền chạy SQL trên project. Nếu dùng kết nối Supabase của ChatGPT, cần cấp quyền project này trong đúng tổ chức/tài khoản.

## 3. HTTPS và cấu hình ứng dụng

Sửa `.env` trực tiếp trên VPS:

```dotenv
BASE_URL=https://publisher.YOUR_DOMAIN
APP_DOMAIN=publisher.YOUR_DOMAIN
ACME_EMAIL=YOUR_EMAIL
DATABASE_URL=postgresql+psycopg://USER:ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

Chưa có domain được lựa chọn trong cấu hình bàn giao. Không dùng domain của dịch vụ khác khi chưa được phép cấu hình DNS/proxy cho công cụ này.

Kiểm tra:

```bash
bash deploy/vps.sh check
```

Nếu 80/443 chưa có dịch vụ và domain đã trỏ đúng VPS:

```bash
bash deploy/vps.sh start --https
```

Nếu n8n hoặc proxy khác đã dùng 80/443, chỉ khởi động backend:

```bash
bash deploy/vps.sh start
```

Sau đó thêm riêng host của công cụ vào reverse proxy hiện có, trỏ tới `127.0.0.1:8000`; không dừng hoặc thay cấu hình host n8n. Script từ chối cổng đã bị chiếm để tránh làm gián đoạn dịch vụ khác.

## 4. Kết nối và thử thật

Nhập OAuth Google/Meta trong `.env`; callback tương ứng là `/oauth/youtube/callback` và `/oauth/facebook/callback` trên BASE_URL. Khởi động lại riêng container publisher sau khi đổi env, đăng nhập web rồi cấp quyền kênh/Page. Dùng YouTube riêng tư cho lần thử đầu; kiểm tra ID trả về và nội dung trên nền tảng. Không có OAuth credentials thì chưa kiểm thử đăng thật được.

## Trạng thái kiểm tra ngày 11/11/2026

- HTTP Data API Supabase trả 200 với khóa do chủ sở hữu cung cấp. Chưa thấy bảng hoặc RPC được công bố trong OpenAPI của project.
- Kết nối quản trị Supabase của phiên này bị từ chối quyền vào project mới; chưa chạy SQL hay đổi schema từ phiên này.
- SSH từ môi trường thực thi báo `Network is unreachable`; chưa đăng nhập VPS, chưa tạo thư mục trên VPS, chưa khởi chạy container hay cấu hình HTTPS.
- Các lệnh và SQL ở trên là bộ triển khai đã chuẩn bị, không phải bằng chứng đã triển khai thành công.
