# khuoqtd Publisher

Công cụ xuất bản riêng chạy trên VPS, kết nối API chính thức của **YouTube** và **Facebook Pages**. Không dùng Upload-Post, cookie hoặc antidetect browser để đăng nội dung. n8n có thể điều phối luồng Telegram riêng, nhưng việc đăng YouTube vẫn do Publisher gọi API chính thức.

Định hướng luồng Telegram → TikTok → YouTube → Telegram: [docs/TELEGRAM_N8N_TARGET.md](docs/TELEGRAM_N8N_TARGET.md). Đây là bản thiết kế tích hợp, **chưa được triển khai thành workflow chạy thật**.

Hướng dẫn production theo thư mục `/root/Khuong/khuoqtd-publisher`: [deploy/PRODUCTION.md](deploy/PRODUCTION.md). Có script kiểm tra/khởi động riêng, không dừng dịch vụ VPS khác. Supabase API key không thay thế chuỗi kết nối PostgreSQL; SQL khởi tạo nằm tại [deploy/supabase-bootstrap.sql](deploy/supabase-bootstrap.sql).

## Deploy bản trải nghiệm trên Vercel

Import repo GitHub này trong Vercel, chọn Framework **Other**. Cấu hình đã nằm trong `vercel.json`: Build Command `python3 tools/build_preview.py`, Output Directory `public`, Install Command để trống. Bản trải nghiệm không cần biến môi trường hoặc kết nối Supabase.

Đặt tên project theo thương hiệu **khuoqtd**, ví dụ `khuoqtd-publisher`.

### Giới hạn của bản trải nghiệm

`vercel.json` chỉ build bản giao diện dùng tại trình duyệt bằng `python3 tools/build_preview.py`. Bản này dùng hai **kênh mẫu**, cho nhập nội dung, đọc video tại máy và lưu/xuất bản nháp. Không tải video lên server, không nhận token, không đăng thật và không chạy hẹn giờ. Bản nháp chỉ nằm trong trình duyệt hiện tại, không đồng bộ Supabase. Đăng thật vẫn dùng backend Docker trên VPS bên dưới. Không deploy backend hiện tại nguyên trạng lên Vercel Functions.


## Có gì trong bản đầu

- Giao diện tiếng Việt: Tạo bài, Bài đăng, Kênh kết nối; dùng được trên điện thoại.
- Một tài khoản quản trị, phiên đăng nhập 8 giờ, CSRF và giới hạn lần đăng nhập.
- OAuth Google + Meta, token mã hóa trên máy chủ. YouTube có refresh token.
- Facebook: đăng bài chữ hoặc video lên Page. YouTube: đăng video, kiểm tra định dạng Shorts, chọn riêng tư/công khai và đối tượng trẻ em.
- Chọn nhiều kênh; mỗi kênh là một tác vụ riêng, có trạng thái riêng.
- Lưu nháp, đăng ngay, hẹn giờ theo múi giờ máy người dùng.
- Hàng đợi database; khóa nhận bài; chống gửi lặp cùng yêu cầu. Không tự retry thao tác đăng.
- Video MP4 lưu trên VPS, không đẩy vào Supabase Storage. Database chỉ lưu metadata và token mã hóa.
- Dọn video sau 7 ngày nếu không còn bài nháp/chờ/không rõ kết quả cần video đó.

**Đây là bản dùng riêng cho một quản trị viên, chưa phải SaaS nhiều người dùng.** Chưa có TikTok, LinkedIn, tải video từ URL, bình luận, tạo nội dung AI hoặc analytics.

## Cài trên VPS bằng Docker

Yêu cầu: Linux, Docker Engine + Compose plugin, domain/subdomain trỏ đến VPS. Không cần mua thêm database. Có thể dùng Supabase Free đang có.

1. Giải nén và chuyển vào thư mục `social-publisher`.
2. Tạo cấu hình và mật khẩu quản trị (không dùng lại mật khẩu mạng xã hội):

```bash
docker build -t khuoqtd-publisher .
docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD:/work" -w /work khuoqtd-publisher python -m app.setup
```

3. Mở `.env`, điền:

```dotenv
BASE_URL=https://publisher.tenmiencuaban.vn
APP_DOMAIN=publisher.tenmiencuaban.vn
ACME_EMAIL=email-cuaban@example.com
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

Lấy chính xác **Session pooler** từ Supabase Dashboard → **Connect** → **Session pooler**. Sao chép host/user có sẵn; không tự đoán region. Thay `postgresql://` đầu chuỗi thành `postgresql+psycopg://`. Mật khẩu có ký tự đặc biệt phải URL-encode. Kết nối qua SSL; có thể tăng lên `verify-full` cùng CA certificate của dự án. Không sử dụng anon key hoặc service_role key làm mật khẩu database.

4. Khởi động:

```bash
docker compose --profile https up -d --build
```

Ứng dụng tự tạo các bảng `sp_*`. Không sửa bảng khác. Caddy tự xin HTTPS khi DNS và cổng 80/443 đã đúng.

**Nếu VPS đã có Nginx/Caddy/Traefik dùng cổng 80/443:** chạy `docker compose up -d --build` (không profile `https`). Reverse proxy đang có chuyển domain tới `127.0.0.1:8000`; giữ Host, cho upload tối đa 252 MB và timeout ít nhất 180 giây. Không chạy hai reverse proxy cùng chiếm cổng. BASE_URL vẫn phải là URL HTTPS công khai.

## Kết nối YouTube

1. Mở [Google Cloud Console](https://console.cloud.google.com/). Tạo/chọn project của công cụ.
2. Bật **YouTube Data API v3**.
3. Cấu hình Google Auth Platform: tên ứng dụng, email, audience và scopes `youtube.upload`, `youtube.readonly`. Nếu Testing, thêm tài khoản Google của bạn vào Test users.
4. Tạo OAuth Client loại **Web application**, Authorized redirect URI chính xác:

```text
https://publisher.tenmiencuaban.vn/oauth/youtube/callback
```

5. Điền `GOOGLE_CLIENT_ID` và `GOOGLE_CLIENT_SECRET` vào `.env`; `docker compose up -d --force-recreate publisher`.
6. Đăng nhập web → **Kênh kết nối** → **YouTube** → chọn đúng kênh và cấp quyền.

Refresh token có thể bị thu hồi/hết hiệu lực. OAuth app đang Testing có thể có hạn token ngắn. Xác minh OAuth và kiểm tra tuân thủ API là thủ tục của Google, không được thay thế bằng mã nguồn này. Shorts do YouTube phân loại; công cụ chỉ kiểm tra kích thước/thời lượng, không bảo đảm kiếm tiền hoặc vượt kiểm tra bản quyền.

## Kết nối Facebook Pages

1. Mở [Meta for Developers](https://developers.facebook.com/apps/). Tạo/chọn ứng dụng có quyền quản lý Trang và cấu hình Facebook Login phù hợp với loại app.
2. Trong cài đặt OAuth, thêm redirect URI:

```text
https://publisher.tenmiencuaban.vn/oauth/facebook/callback
```

3. Điền `META_APP_ID`, `META_APP_SECRET`, `META_API_VERSION` theo phiên bản API app hỗ trợ vào `.env`; khởi động lại service `publisher`.
4. Cấp các quyền `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`. Vào **Kênh kết nối** → **Facebook Page**; cấp quyền các Page muốn quản lý. Các Page được cấp sẽ xuất hiện trong danh sách.

Đăng bằng **Page Access Token**, không dùng User Token để đăng bài. Công cụ lấy Page Token trong OAuth. Tài khoản ngoài vai trò app, quyền nâng cao, loại app và yêu cầu xét duyệt/xác minh phụ thuộc cấu hình Meta hiện hành; code không tự cấp quyền thay Meta. Không đăng lên trang cá nhân Facebook trong bản này.

## Sử dụng

1. Chọn kênh, nhập tiêu đề/mô tả, tải MP4.
2. YouTube mặc định **Riêng tư**. Kiểm tra đối tượng trẻ em và quyền riêng tư trước khi xác nhận.
3. Lưu nháp hoặc đưa vào hàng đợi. Hẹn giờ là thời điểm VPS bắt đầu gửi, không bảo đảm thời điểm video xuất hiện trên nền tảng.
4. Xem kết quả ở **Bài đăng**.

| Trạng thái | Ý nghĩa |
|---|---|
| Bản nháp | Chưa gửi |
| Đang chờ | Đợi lịch hoặc worker |
| Đang gửi | Worker đang thực hiện yêu cầu |
| Đã gửi nền tảng | API trả ID; video có thể đang xử lý/kiểm duyệt, chưa bảo đảm công khai |
| Bị từ chối | API từ chối rõ ràng; có thể sửa quyền/cấu hình rồi thử lại |
| Cần kiểm tra | Mất kết nối/crash/kết quả không rõ; không tự gửi lại |

Không bấm thử lại bằng cách tạo bài mới khi kết quả chưa rõ. Mở tài khoản nền tảng để đối soát trước. Không có giao dịch nguyên tử xuyên database và API mạng xã hội: hệ thống giảm nguy cơ trùng, không tuyên bố “exactly once”.

## Dữ liệu và bảo mật

- Giữ `.env`, `ENCRYPTION_KEY`, mật khẩu database riêng. Không commit hoặc gửi vào chat.
- Backup `.env` và volume `publisher_data`; mất encryption key sẽ không đọc được token đã lưu.
- Toàn bộ bảng `sp_*` bật RLS và thu hồi quyền PUBLIC/anon/authenticated khi chạy PostgreSQL. Trình duyệt không truy cập Supabase trực tiếp. Kết nối backend dùng chủ sở hữu bảng; bản này không dành cho nhiều người dùng độc lập.
- Ngắt kết nối xóa token khỏi công cụ và dừng bài chờ; thu hồi quyền từ phía nền tảng làm ở Google/Meta account settings.
- Chạy **một process Uvicorn** như Dockerfile. Khóa database bảo vệ queue giữa tiến trình, nhưng giới hạn upload/login trong bản này là trong process.
- Video đang upload dùng vùng tạm. Có giới hạn từng file và tổng thư mục video; theo dõi dung lượng VPS, `/tmp`, quota và tình trạng Supabase.
- Chưa có giao diện xóa bài/media thủ công. Media được dọn tự động theo retention; trạng thái unknown giữ file để đối soát.

## Kiểm thử / chạy cục bộ

Yêu cầu Python 3.12+, ffmpeg/ffprobe. SQLite chỉ dành cho chạy thử tại máy, production dùng Supabase.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Sau khi tạo `.env` bằng `python -m app.setup`, dùng Docker như trên hoặc nạp các biến môi trường bằng công cụ triển khai của bạn rồi chạy:

```bash
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --no-proxy-headers
```

Tiện ích QA và database thử không nằm trong gói bàn giao.

## Tình trạng bàn giao

Source, giao diện, OAuth handlers, queue, bộ kiểm thử và cấu hình Docker đã được xây dựng. Chưa truy cập VPS, chưa chọn/chỉnh database Supabase thật, chưa có OAuth credentials riêng của ứng dụng và chưa đăng bài thật. Kiểm thử API nền tảng dùng HTTP giả lập, không thay thế kiểm thử đầu-cuối sau khi kết nối tài khoản.

## Tài liệu đối chiếu

- [Supabase Postgres / session pooler](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Google OAuth web server](https://developers.google.com/identity/protocols/oauth2/web-server)
- [YouTube resumable uploads](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol)
- [YouTube videos.insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert)
- [Meta Pages API](https://developers.facebook.com/docs/pages-api/)
