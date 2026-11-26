# Clover_BotAI: Knowledge Distillation Telegram AI Bot & Web Admin Hub

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%20%7C%203.13-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/Telegram-Bot%20API%20v22-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram API" />
  <img src="https://img.shields.io/badge/LangChain-Orchestration-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white" alt="LangChain" />
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Redis-Upstash%20Cloud-DC382D?style=for-the-badge&logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/FastAPI-MVC%20Admin-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Docker-Enterprise%20Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker" />
</p>

---

## 📖 1. Giới Thiệu Dự Án (Project Overview)

**Clover_BotAI** là trợ lý học tiếng Anh và luyện thi thông minh qua Telegram, kết hợp với trang quản trị dữ liệu **Web Admin Dashboard**. Dự án được xây dựng theo chiến lược **Knowledge Distillation (Chưng cất tri thức đa tầng)** và kiến trúc **Stateless Cloud-Native**:

* **Học viên (Telegram Client)**: Trò chuyện giao tiếp tự nhiên với AI, giải bài tập tiếng Anh, nhận lịch ôn tập từ vựng ngắt quãng theo thuật toán **SuperMemo-2 (SM-2)** với câu đố trắc nghiệm định kỳ.
* **AI Teacher (Gemini Flash Cloud)**: Đóng vai trò chuyên gia ngôn ngữ, tự động phân tích ngữ cảnh chat, bóc tách từ vựng & ngữ pháp chuẩn khung CEFR (A1-C2), tính toán vector nhúng 768 chiều (`nomic-embed-text`) và nạp vào **PostgreSQL pgvector**.
* **AI Student (Ollama Local / Hugging Face QLoRA)**: Học dần từ dữ liệu vàng (Golden Dataset) đã làm sạch, cho phép hệ thống chạy độc lập 100% offline trên máy cá nhân mà không tốn chi phí API.
* **Trang Web Quản Trị (Admin Hub)**: Xây dựng theo mô hình **MVC (FastAPI + Jinja2 + Bootstrap 5)** cung cấp giao diện trực quan tại cổng `8000` để kiểm duyệt từ vựng, ngữ pháp, xem bong bóng hội thoại ShareGPT, quản lý học viên và xuất dataset huấn luyện 1-click.

---

## 🏗️ 2. Kiến Trúc Hệ Thống (Architecture)

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CLOVER_BOTAI ARCHITECTURE                       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
 📱 TELEGRAM USER                                      💻 ADMIN OPERATOR
   • Chat giao tiếp song ngữ                             • Quản trị từ vựng / ngữ pháp
   • Ôn tập trắc nghiệm SM-2                             • Giám sát KPI & Healthcheck
   • Gửi ảnh / tài liệu PDF                              • Xuất Dataset train QLoRA
        │                                                       │
        ▼ (Telegram Long-polling)                               ▼ (Port 8000 HTTP)
┌───────────────────────────────────┐               ┌───────────────────────────────────┐
│     SERVICE: ai_telegram_bot      │               │     SERVICE: ai_telegram_admin    │
│  (python-telegram-bot + LangChain)│               │  (FastAPI + Jinja2 + Bootstrap 5) │
└─────────────────┬─────────────────┘               └─────────────────┬─────────────────┘
                  │                                                   │
                  └─────────────────────────┬─────────────────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
       ┌───────────────────────────┐                 ┌───────────────────────────┐
       │   POSTGRESQL + PGVECTOR   │                 │     REDIS MEMORY LAYER    │
       │   (Supabase Cloud / Local)│                 │   (Upstash Cloud / Local) │
       ├───────────────────────────┤                 ├───────────────────────────┤
       │ • vocab_ground_truth      │                 │ • Sliding Window Chat (10)│
       │ • grammar_ground_truth    │                 │ • Mutex Distributed Lock  │
       │ • chat_logs (ShareGPT)    │                 │ • LLM Response Cache      │
       │ • quiz_logs & schedules   │                 │ • Rate Limiting           │
       └─────────────┬─────────────┘                 └───────────────────────────┘
                     │
                     ▼
       ┌───────────────────────────────────────────────────────────┐
       │             3-STAGE AI PROGRESSION PIPELINE               │
       ├───────────────────────────────────────────────────────────┤
       │ 1. Teacher  : Gemini 2.5/3.6 Flash (Structured Pydantic)  │
       │ 2. Fallback : Host Ollama (qwen2.5:3b + nomic-embed-text) │
       │ 3. Distill  : Unsloth QLoRA -> GGUF / vLLM Student        │
       └───────────────────────────────────────────────────────────┘
```

---

## 🛠️ 3. Bảng Công Nghệ Sử Dụng (Tech Stack)

| Phân hệ | Công nghệ | Chi tiết sử dụng |
| :--- | :--- | :--- |
| **Backend Core** | Python 3.11+ / 3.13 | Bất đồng bộ `asyncio`, type hints, SOLID principles |
| **Telegram Bot** | `python-telegram-bot` v22.x | Asynchronous handlers, Inline Keyboard, JobQueue |
| **AI Orchestration** | `LangChain`, `Pydantic v2` | Factory pattern (`LLMFactory`), Structured Outputs, Hybrid RAG |
| **Vector Database** | `PostgreSQL 16/17` + `pgvector` | Hỗ trợ tìm kiếm tương đồng vector Cosine, `pg_trgm` FTS |
| **Database Cloud** | `Supabase` | Managed PostgreSQL Cloud có sẵn extension vector |
| **Cache & Lock** | `Redis 7` / `Upstash Redis` | Sliding-window memory, Distributed Lock chống spam bằng Lua script |
| **Web Admin Hub** | `FastAPI`, `Jinja2`, `Bootstrap 5` | Kiến trúc MVC, Signed Session Cookie Auth, Responsive Dark Theme |
| **Migration** | `Alembic` | Tự động nâng cấp schema bất đồng bộ (`asyncpg`) |
| **Thuật toán** | `SuperMemo-2 (SM-2)` | Tối ưu chu kỳ nhắc từ vựng theo đường cong quên lãng Ebbinghaus |
| **Containerization** | `Docker` & `Docker Compose` | Đóng gói môi trường đồng nhất chạy đa hệ điều hành |

---

## 🚀 4. Hướng Dẫn Vận Hành & Khởi Chạy (Getting Started)

### 4.1. Chuẩn Bị Biến Môi Trường (`.env`)

Sao chép file cấu hình mẫu `.env.example` thành `.env`:

```bash
cp .env.example .env
```

Điền các thông tin quan trọng vào `.env`:

```env
# --- Telegram Bot ---
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
ADMIN_USER_IDS=your_telegram_user_id

# --- AI Backend (gemini | ollama | huggingface) ---
AI_BACKEND=ollama
GEMINI_API_KEY=your_gemini_api_key
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
EMBEDDING_PROVIDER=ollama
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# --- Database (Supabase Cloud hoặc Local Postgres) ---
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@db.YOUR_PROJECT.supabase.co:5432/postgres

# --- Redis (Upstash Cloud hoặc Local Redis) ---
REDIS_URL=rediss://default:YOUR_KEY@YOUR_ENDPOINT.upstash.io:6379?ssl_cert_reqs=none

# --- Web Admin Hub ---
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password
ADMIN_SECRET_KEY=change_this_secret_key_to_at_least_32_characters
ADMIN_PORT=8000
```

---

### 4.2. Cách 1: Chạy Trực Tiếp Bằng Python Virtualenv (Khuyên Dùng khi dùng Cloud DB)

Khi bạn đã kết nối **Supabase** và **Upstash Redis**, ứng dụng hoàn toàn không cần chạy Postgres hay Redis cục bộ:

```bash
# 1. Kích hoạt môi trường ảo
# Trên Windows PowerShell:
.\.venv\Scripts\activate
# Trên Linux/macOS:
source .venv/bin/activate

# 2. Cài đặt thư viện (nếu chưa cài)
pip install -r requirements.txt

# 3. Đồng bộ cấu trúc bảng lên Database
alembic upgrade head

# 4. Nạp dữ liệu hạt giống (10 từ vựng + 10 công thức ngữ pháp mẫu)
python -m src.cli.seed_vocab --file data/seeds/sample_vocab.json
python -m src.cli.seed_grammar --file data/seeds/sample_grammar.json

# 5. Khởi chạy Bot Telegram (Terminal 1)
python main.py

# 6. Khởi chạy Web Admin Dashboard (Terminal 2)
uvicorn src.admin.app:app --host 0.0.0.0 --port 8000 --reload
```

Sau khi chạy:
* Bot Telegram sẽ online và lắng nghe tin nhắn ngay lập tức.
* Mở trình duyệt vào trang Admin: `http://localhost:8000/admin`.

---

### 4.3. Cách 2: Chạy Hoàn Toàn Trong Docker (All-in-One Container Stack)

Nếu muốn chạy toàn bộ Postgres, Redis và Ollama ngay trên Docker cục bộ:

```bash
# Khởi chạy toàn bộ hệ thống ở chế độ nền
docker compose up -d

# Xem log hoạt động của Bot
docker compose logs -f bot

# Kiểm tra trạng thái các container
docker compose ps
```

---

### 4.4. Cách 3: Deploy Lên Nền Tảng Cloud PaaS (Koyeb / Railway / Render)

Do ứng dụng đã là **Stateless**, bạn chỉ cần kết nối repo GitHub này:
1. Tạo Service Web cho **Admin Dashboard**:
   * Command: `uvicorn src.admin.app:app --host 0.0.0.0 --port 8000`
   * Expose Port: `8000`
2. Tạo Service Worker cho **Bot Telegram**:
   * Command: `python main.py`
3. Nhập toàn bộ biến môi trường từ file `.env` vào mục **Environment Variables** trên dashboard của PaaS.

---

## 📊 5. Tính Năng Trang Web Quản Trị (Admin Hub)

Truy cập tại: `http://localhost:8000/admin` (Đăng nhập với tài khoản cấu hình trong `ADMIN_USERNAME` / `ADMIN_PASSWORD`).

* **Trang Tổng Quan (Dashboard)**: Theo dõi số lượng từ vựng, công thức ngữ pháp, lịch sử chat và kiểm tra trạng thái sống/chết (Healthcheck) của PostgreSQL, Redis, Ollama thời gian thực.
* **Kho Từ Vựng (`/admin/vocab`)**: Tìm kiếm, lọc theo cấp độ CEFR, xem câu ví dụ song ngữ, nhãn vector 768-dim và nút phê duyệt hàng loạt (Batch Approve).
* **Kho Ngữ Pháp (`/admin/grammar`)**: Quản trị các cấu trúc ngữ pháp mẫu, câu ví dụ và các bẫy ngữ pháp thường gặp.
* **Hàng Đợi Kiểm Duyệt OCR (`/admin/moderation`)**: Giao diện duyệt nhanh dạng card cho các từ vựng bóc tách từ tài liệu, ảnh bài tập hoặc Teacher AI.
* **Nhật Ký Trò Chuyện (`/admin/chat-logs`)**: Xem chi tiết hội thoại của người dùng dưới định dạng bong bóng ChatML (User vs Assistant) và gắn nhãn Dữ liệu Vàng.
* **Lịch Học Học Viên (`/admin/learners`)**: Giám sát khoảng thời gian ôn tập SM-2 (`repetition`, `interval`, `ease_factor`) của từng học viên.
* **Xuất QLoRA Dataset**: Nút bấm 1-click xuất toàn bộ hội thoại đã xác thực ra 2 file `train.jsonl` và `eval.jsonl` chuẩn ShareGPT/Alpaca.

---

## 🤖 6. Danh Sách Lệnh Telegram Bot

| Lệnh | Mô tả chức năng |
| :--- | :--- |
| `/start` | Đăng ký học viên, giới thiệu cách sử dụng và hiển thị menu trợ giúp |
| `/quiz` | Lấy ngay 1 câu hỏi trắc nghiệm từ vựng cần ôn tập hôm nay (theo thuật toán SM-2) |
| `/stats` | Xem thống kê số từ đã thuộc, điểm streak ôn tập và chu kỳ ghi nhớ cá nhân |
| `/model` | Chuyển đổi mô hình AI (`Gemini Flash` ⇄ `Ollama Qwen 2.5:3b`) |
| `/reset` | Xóa bộ nhớ ngắn hạn của phiên chat hiện tại |
| `/help` | Xem bảng hướng dẫn chi tiết cách học |

---

## 🧪 7. Kiểm Thử Tự Động (Automated Testing)

Toàn bộ dự án đi kèm hệ thống kiểm thử tự động toàn diện:

```bash
# Chạy toàn bộ test suite
pytest -v

# Chạy riêng kiểm thử Admin Dashboard MVC
pytest tests/test_mvc_admin.py -v

# Chạy riêng kiểm thử thuật toán SM-2
pytest tests/test_sm2.py -v

# Chạy riêng kiểm thử Redis Memory & Lock
pytest tests/test_redis_service.py -v
```

---

## 🛡️ 8. Bảo Mật & An Toàn Dữ Liệu

* **Không lưu trữ Secret trong Git**: File `.gitignore` được cấu hình chặt chẽ để loại trừ `.env`, dữ liệu nhạy cảm và cache.
* **Signed Session Cookie**: Trang Admin dùng cơ chế mã hóa cookie có chữ ký số bí mật (`ADMIN_SECRET_KEY`) để chống giả mạo danh tính.
* **Distributed Concurrency Guard**: Redis Mutex Lock ngăn chặn người dùng spam nút hoặc gửi tin nhắn liên tục khi AI đang bận suy luận.

---

## 📄 9. Bản Quyền & Tác Giả

* **Dự án**: Clover_BotAI (Knowledge Distillation Telegram AI Bot & Web Admin Hub)
* **Tác giả**: Tran Minh Hieu ([@hieutran0204](https://github.com/hieutran0204))
* **Giấy phép (License)**: MIT License.
