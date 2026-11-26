# Kiến Trúc MVC Toàn Diện: Web Admin Hub (FastAPI + Jinja2 + Bootstrap 5)
**Mục tiêu:** Thay thế generic admin auto-generated bằng kiến trúc chuẩn **MVC (Model - View - Controller)** thuần túy. Kiểm soát 100% giao diện, cung cấp Dashboard thống kê trực quan, Hàng đợi kiểm duyệt (Moderation Queue) chuyên biệt cho OCR & Teacher, và công cụ quản trị dữ liệu chưng cất QLoRA.

--------------------------------------------------------------------------------

## 1. Phân Tích Vì Sao Chuyển Sang Mô Hình MVC Thuần Túy

| Tiêu chí | SQLAdmin (Black-box auto-generated) | MVC Thuần Túy (FastAPI + Jinja2 + Bootstrap 5) |
| :--- | :--- | :--- |
| **Trang chủ (`/admin`)** | ❌ **Trắng tinh, không có nội dung** (phải tự click sidebar mới thấy bảng thô). | ✅ **Dashboard thời gian thực:** Thống kê tổng từ vựng, thẻ cảnh báo hàng đợi chờ duyệt, tiến độ học viên, tình trạng Ollama/Postgres. |
| **Kiểm duyệt OCR / Teacher** | ❌ Bảng thô, khó xem nội dung song ngữ và câu trắc nghiệm. | ✅ **Moderation Queue Cards:** Thẻ kiểm duyệt trực quan, hiển thị rõ nguồn gốc (`source`), nghĩa, ví dụ, nút **Duyệt 1-Click** hoặc **Từ chối**. |
| **Giao diện & Tùy biến** | ❌ Bị gò bó theo layout cứng nhắc của thư viện bên thứ 3. | ✅ **Tự do 100%:** Thiết kế bảng, badge màu sắc theo CEFR (A1..C2), form chỉnh sửa, bubble chat lịch sử hỏi đáp. |
| **Bảo trì & Mở rộng** | ❌ Dễ xung đột phiên bản khi nâng cấp SQLAlchemy / Starlette. | ✅ **Code minh bạch:** Kiến trúc Controller - View rõ ràng, chuẩn Pythonic, dev mới nắm bắt trong 5 phút. |

--------------------------------------------------------------------------------

## 2. Sơ Đồ Kiến Trúc MVC

```
┌────────────────────────────────────────────────────────────────────────┐
│                          CONTROLLER (FastAPI Routes)                   │
│  src/admin/controllers/                                                │
│  ├── dashboard.py   ──> Lấy số liệu thống kê, healthcheck Ollama/DB    │
│  ├── vocab.py       ──> CRUD Từ vựng, Search, Filter CEFR/Status       │
│  ├── grammar.py     ──> CRUD Ngữ pháp, Công thức, Ví dụ JSON           │
│  ├── moderation.py  ──> Hàng đợi kiểm duyệt OCR & Teacher (1-Click)    │
│  ├── chat_logs.py   ──> Xem hội thoại ChatML, Tải train.jsonl          │
│  └── auth.py        ──> Đăng nhập, Đăng xuất, Session Middleware       │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │                                 │
                   ▼                                 ▼
┌─────────────────────────────────────┐  ┌───────────────────────────────┐
│          MODEL (Database)           │  │       VIEW (Jinja2 HTML)      │
│  src/db/models.py                   │  │  src/admin/templates/         │
│  ├── VocabGroundTruth (pgvector)    │  │  ├── base.html (Layout + Nav) │
│  ├── GrammarGroundTruth (pgvector)  │  │  ├── dashboard.html (Stats)   │
│  ├── ChatLogs (ShareGPT JSONB)      │  │  ├── vocab/ (list, edit)      │
│  ├── UserStudySchedule (SM-2)       │  │  ├── moderation/ (queue cards)│
│  └── QuizLogs (Logs kết quả)        │  │  └── chat_logs/ (detail chat) │
└─────────────────────────────────────┘  └───────────────────────────────┘
```

--------------------------------------------------------------------------------

## 3. Cấu Trúc Thư Mục Chi Tiết

```text
src/admin/
├── __init__.py
├── app.py                      # FastAPI App chính + Mount static + Include Routers
├── auth.py                     # Quản lý Session Cookie & Helper yêu cầu đăng nhập
├── controllers/
│   ├── __init__.py
│   ├── auth_controller.py      # GET/POST /admin/login, GET /admin/logout
│   ├── dashboard_controller.py # GET /admin (Dashboard tổng quan, KPI cards)
│   ├── vocab_controller.py     # GET /admin/vocab, POST /admin/vocab/{id}/edit, approve, delete
│   ├── grammar_controller.py   # GET /admin/grammar, POST edit, approve
│   ├── moderation_controller.py# GET /admin/moderation, POST batch-approve/reject
│   └── chat_controller.py      # GET /admin/chat, POST /admin/export-dataset
├── templates/
│   ├── base.html               # Khung chuẩn: Sidebar navigation, Topbar user, Alert toasts
│   ├── login.html              # Form đăng nhập sạch sẽ, chuyên nghiệp
│   ├── dashboard.html          # 4 thẻ thống kê lớn, bảng hàng đợi gần nhất, trạng thái Ollama
│   ├── vocab/
│   │   ├── list.html           # Bảng từ vựng: Search box, Dropdown lọc CEFR/Status, Pagination
│   │   └── edit.html           # Form sửa từ vựng, phiên âm IPA, 4 options quiz
│   ├── grammar/
│   │   ├── list.html           # Bảng công thức ngữ pháp, badge CEFR
│   │   └── edit.html           # Form sửa công thức, cách dùng tiếng Việt
│   ├── moderation/
│   │   └── queue.html          # Danh sách thẻ duyệt nhanh cho bản ghi OCR & Teacher
│   └── chat_logs/
│       ├── list.html           # Lịch sử hỏi đáp, lọc theo Backend (Ollama/Gemini)
│       └── detail.html         # Khung chat dạng bong bóng (User vs Assistant)
└── static/
    ├── css/admin.css           # Tùy chỉnh màu sắc, badge CEFR, hover effects
    └── js/admin.js             # Xử lý chọn nhiều checkbox, xác nhận modal duyệt
```

