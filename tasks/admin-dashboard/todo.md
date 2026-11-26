# Task List: Web Admin Dashboard (MVC Architecture: FastAPI + Jinja2 + Bootstrap 5)

## Phase 1: Cấu Hình FastAPI, Khung MVC & Cơ Chế Xác Thực

### Task 1: Cấu Hình Dependencies, Settings & Xác Thực `AdminAuth`
**Description:** Bổ sung các thư viện cần thiết (`sqladmin>=0.20.0`, `fastapi>=0.110.0`, `uvicorn>=0.28.0`, `itsdangerous>=2.1.0`) vào `requirements.txt`. Cập nhật `src/core/config.py` để nạp các tham số `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_SECRET_KEY`, `ADMIN_PORT`. Xây dựng class `AdminAuth(AuthenticationBackend)` và các helper `require_admin`, `is_authenticated` trong `src/admin/auth.py` để xử lý đăng nhập, cấp signed session cookie và bảo vệ tất cả route `/admin`.

**Acceptance criteria:**
- [x] `requirements.txt` có đầy đủ các package cho FastAPI và SQLAdmin.
- [x] `Settings` trong `src/core/config.py` đọc đúng các biến `admin_username`, `admin_password`, `admin_secret_key`, `admin_port` (có giá trị fallback an toàn).
- [x] `AdminAuth` xác thực đúng username/password, từ chối khi nhập sai, và bảo vệ các route `/admin/*`.
- [x] Hỗ trợ đăng xuất (`/admin/logout`) và xóa session cookie an toàn.

**Verification:**
- [x] Tests pass: `docker compose exec -T admin pytest tests/test_admin_auth.py -v` (4/4 passed).

---

### Task 2: Khởi Tạo FastAPI App & MVC Base Templates
**Description:** Tạo file `src/admin/app.py` khởi tạo ứng dụng `FastAPI`, gắn SessionMiddleware, Mount Static files, và xây dựng khung chuẩn `src/admin/templates/base.html`, `login.html`, `src/admin/static/css/admin.css`, `src/admin/static/js/admin.js`.

**Acceptance criteria:**
- [x] FastAPI instance khởi động không có lỗi và kết nối thành công tới PostgreSQL `async_engine`.
- [x] Giao diện đăng nhập hiện đại tại `/admin/login`, chuyển hướng tự động khi chưa đăng nhập.
- [x] Endpoint `/healthz` và `/api/stats` trả về trạng thái healthy và metrics thời gian thực.

**Verification:**
- [x] Tests pass: `docker compose exec -T admin pytest tests/test_admin_app.py -v` (5/5 passed).

---

## Checkpoint 1: Xác Thực & Khung Admin Hoạt Động (PASSED)
- [x] Đăng nhập thành công với tài khoản quản trị viên.
- [x] Giao diện Đăng nhập và Khung Base Sidebar Dark Theme tải hoàn chỉnh.
- [x] Toàn bộ unit tests của Task 1 và Task 2 đều đạt `PASSED`.

---

## Phase 2: Xây Dựng Các MVC Controllers & Views Quản Trị Tri Thức

### Task 3: Controller & Views Từ Vựng (`VocabController`, `vocab/list.html`, `vocab/edit.html`)
**Description:** Xây dựng `src/admin/controllers/vocab_controller.py` cung cấp khả năng tìm kiếm, phân trang, lọc theo cấp độ CEFR và trạng thái (`verified`, `pending`, `quarantined`). Bổ sung batch actions: Phê duyệt (Approve), Xóa/Từ chối (Reject), và form biên tập song ngữ cùng 4 đáp án trắc nghiệm.

**Acceptance criteria:**
- [x] Hiển thị đầy đủ danh sách từ vựng kèm nhãn CEFR, số lần tra cứu, huy hiệu vector 768-dim.
- [x] Tìm kiếm từ vựng theo từ khóa hoặc nghĩa tiếng Việt nhanh chóng.
- [x] Nút action batch cho phép chọn nhiều từ và bấm "Duyệt Tất Cả Đã Chọn" để chuyển trạng thái sang `verified`.

**Verification:**
- [x] Tests pass: `docker compose exec -T admin pytest tests/test_mvc_admin.py -k test_vocab_crud_and_moderation_flow -v`.

---

### Task 4: Controller & Views Ngữ Pháp (`GrammarController`, `grammar/list.html`, `grammar/edit.html`)
**Description:** Xây dựng `src/admin/controllers/grammar_controller.py` và views hiển thị công thức code font, xem và sửa cấu trúc JSON ví dụ, cách dùng tiếng Việt và các lỗi thường gặp.

**Acceptance criteria:**
- [x] Danh sách công thức ngữ pháp kèm huy hiệu CEFR và trạng thái embedding 768-dim.
- [x] Form chỉnh sửa cho phép định dạng JSON các cặp câu ví dụ song ngữ an toàn.

**Verification:**
- [x] Tests pass: `docker compose exec -T admin pytest tests/test_mvc_admin.py -k test_grammar_list_and_detail -v`.

---

## Checkpoint 2: Quản Trị CRUD & Kiểm Duyệt Hoạt Động Trơn Tru (PASSED)
- [x] Quản trị viên có thể xem, tìm kiếm, sửa, xóa và duyệt hàng loạt từ vựng/ngữ pháp.
- [x] Theo dõi được toàn bộ nhật ký trò chuyện và lịch học của từng người dùng qua MVC views.

---

## Phase 3: Dashboard Sống Động, Hàng Đợi OCR Moderation & Xuất Dataset QLoRA

### Task 5: Dashboard Sống Động (`DashboardController`, `dashboard.html`)
**Description:** Khắc phục triệt để lỗi trang trắng ban đầu của SQLAdmin bằng Dashboard tổng quan: 4 thẻ KPI thời gian thực, bảng kiểm tra kết nối hạ tầng (Postgres pgvector, Redis Cache, Host Ollama `qwen2.5:3b`), và xem trước các từ mới chờ phê duyệt.

**Acceptance criteria:**
- [x] Trang chủ `/admin` tải trực tiếp giao diện Dashboard trực quan.
- [x] Hiển thị tình trạng sống/chết của PostgreSQL, Redis và Host Ollama.
- [x] Nút "Xuất QLoRA Dataset" 1-click kích hoạt xuất file `train.jsonl` và `eval.jsonl`.

---

### Task 6: Hàng Đợi Kiểm Duyệt OCR (`ModerationController`, `moderation/queue.html`)
**Description:** Màn hình `/admin/moderation` chuyên biệt cho các từ vựng bóc tách từ OCR Tài liệu (Phase 4) hoặc Teacher AI. Giao diện dạng card trực quan với ngữ cảnh câu tiếng Anh, bản dịch tiếng Việt, nguồn thu thập và 2 nút: [✅ Phê Duyệt] và [❌ Từ Chối].

**Acceptance criteria:**
- [x] Hiển thị rõ ràng nguồn thu thập (`document_ocr`, `teacher_fallback`).
- [x] Hỗ trợ phê duyệt từng mục hoặc phê duyệt toàn bộ (Batch Approve).

---

### Task 7: Lịch Sử Hội Thoại ChatML & SM-2 Learners (`chat_controller`, `learners_controller`)
**Description:** Xem chi tiết hội thoại người dùng dưới dạng bong bóng chat (User vs Assistant), đánh dấu dữ liệu vàng (`status='verified'`), và quản lý bật/tắt lịch nhắc học SM-2.

**Acceptance criteria:**
- [x] Giao diện bong bóng hội thoại ShareGPT / ChatML.
- [x] Bật/tắt trạng thái `is_active` của từng học viên.

---

## Checkpoint 3: Toàn Bộ Test Suite Đạt 100% PASS
- [x] 55/55 unit & integration tests đạt `PASSED` (`docker compose exec -T admin pytest tests/ -v`).
- [x] Cổng 8000 vận hành ổn định trên `http://localhost:8000/admin`.
- [x] Sẵn sàng 100% để bước sang Phase 4: Bóc Tách OCR Tài Liệu.
