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

Cổng host mặc định cho VPS dùng chung là `127.0.0.1:8090`, được điều chỉnh bằng `PUBLISHER_PORT=8090` trong `.env`. Cổng **bên trong container** vẫn là 8000. `bash deploy/vps.sh start` có thể cập nhật container của chính project mà không tự dừng n8n/pett-chatbot. Docker sẽ báo lỗi nếu cổng host thực sự xung đột.

**Quan trọng:** `n8n-caddy-1` là một container. Container đó không thể truy cập ứng dụng qua `127.0.0.1:8090` của host; địa chỉ `172.18.0.1:8090` cũng không phải lối vào đáng tin cậy khi cổng chỉ bind ở loopback host.

Cách giữ nguyên cổng 80/443 và proxy hiện có là nối Caddy vào **cùng mạng Docker** với Publisher:

1. Kiểm tra bằng `docker network ls --filter label=com.docker.compose.project=khuoqtd-publisher` và `docker inspect n8n-caddy-1` để xác định chính xác mạng và container.
2. Kết nối Caddy vào network của Publisher bằng `docker network connect <PUBLISHER_NETWORK> n8n-caddy-1` (chỉ khi chưa kết nối).
3. Trên host mới, thêm **riêng** block Caddy cho domain của Publisher với upstream `reverse_proxy publisher:8000`; không sửa các host đang hoạt động.
4. Kiểm tra và reload Caddy bằng cấu hình/mount thực tế. Xác minh HTTPS và `/healthz`.
5. **Bắt buộc cấu hình mạng kết nối chung trong Compose của Caddy/n8n để tồn tại sau khi container được tạo lại.** Lệnh `docker network connect` đơn lẻ là thay đổi runtime, không phải giải pháp bền vững.

Không deploy lại bằng `--https` khi cổng 80/443 đã do Caddy hiện tại sử dụng. Không áp dụng IP gateway hoặc tên network giả định nếu chưa kiểm tra trên VPS.

## Xoay mật khẩu quản trị đã lộ

Mật khẩu quản trị đã xuất hiện trong nội dung chat/báo cáo phải được xem là đã lộ. **Không dùng lại.** Trên VPS, sau khi đã sao lưu an toàn `.env`, chạy công cụ tương tác sau; công cụ không in mật khẩu, giữ nguyên `ENCRYPTION_KEY` và URL database:

```bash
cd /root/Khuong/khuoqtd-publisher
docker build -t khuoqtd-publisher .
docker run --rm -it -v "$PWD:/work" -w /work khuoqtd-publisher \
  python -m app.setup rotate-admin
docker compose -p khuoqtd-publisher up -d --force-recreate publisher
```

Sau đó thu hồi các phiên quản trị hiện có bằng cách xóa các dòng trong bảng `public.sp_sessions` **chỉ trên đúng Supabase project production** (ví dụ qua SQL Editor: `TRUNCATE TABLE public.sp_sessions;`). Việc đổi hash **không tự thu hồi cookie phiên** đã phát hành. Không quay vòng `ENCRYPTION_KEY` vì sẽ làm token OAuth hiện có không giải mã được.

## 4. Kết nối và thử thật

Nhập OAuth Google/Meta trong `.env`; callback tương ứng là `/oauth/youtube/callback` và `/oauth/facebook/callback` trên BASE_URL. Khởi động lại riêng container publisher sau khi đổi env, đăng nhập web rồi cấp quyền kênh/Page. Dùng YouTube riêng tư cho lần thử đầu; kiểm tra ID trả về và nội dung trên nền tảng. Không có OAuth credentials thì chưa kiểm thử đăng thật được.

## Trạng thái kiểm tra ngày 11/11/2026

- HTTP Data API Supabase trả 200 với khóa do chủ sở hữu cung cấp. Chưa thấy bảng hoặc RPC được công bố trong OpenAPI của project.
- Kết nối quản trị Supabase của phiên này bị từ chối quyền vào project mới; chưa chạy SQL hay đổi schema từ phiên này.
- SSH từ môi trường thực thi báo `Network is unreachable`; chưa đăng nhập VPS, chưa tạo thư mục trên VPS, chưa khởi chạy container hay cấu hình HTTPS.
- Các lệnh và SQL ở trên là bộ triển khai đã chuẩn bị, không phải bằng chứng đã triển khai thành công.
