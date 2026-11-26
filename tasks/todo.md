# Task List: Knowledge Distillation Telegram AI Bot (Docker-First & 3-Stage AI)

## Phase 1: Docker-First Foundation & Gemini Teacher Collection

### Task 1: Project Setup, Portable Config & Dependency Pinning
**Description:** Khởi tạo cấu trúc repository chuẩn team-ready với Python 3.11+, pin phiên bản các thư viện trong `requirements.txt` (`python-telegram-bot`, `langchain`, `langchain-google-genai`, `langchain-ollama`, `langchain-huggingface`, `langchain-postgres`, `redis`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic-settings`, `pgvector`). Thiết lập `src/core/config.py` và `.env.example` có hỗ trợ biến `${DATA_DIR}` để mỗi máy tự chọn nơi lưu data (VD: `E:/AI-Telegram/data` trên máy bạn hoặc `./data` mặc định).

**Acceptance criteria:**
- [x] `requirements.txt` pin đầy đủ version ổn định để mọi máy build Docker giống nhau 100%.
- [x] `src/core/config.py` đọc đầy đủ biến: Telegram Token, Gemini Key, Ollama URL, Hugging Face Model ID, Postgres URL, Redis URL, `AI_BACKEND`.
- [x] `.env.example` và `.gitignore` được cấu hình chuẩn (không commit `.env` và thư mục `data/`).

**Verification:**
- [x] Chạy `python -c "import telegram, langchain, redis, sqlalchemy, asyncpg, pydantic_settings; print('OK')"` hoặc build thử Docker image không có lỗi syntax.

**Dependencies:** None
**Files likely touched:**
- `requirements.txt`
- `.env.example`
- `.gitignore`
- `src/core/config.py`
- `src/core/__init__.py`

**Estimated scope:** Small (2-3 files)

---

### Task 2: Portable Docker Infrastructure (Multi-stage Dockerfile, Compose Profiles & GPU Override)
**Description:** Xây dựng hệ thống Docker hoàn chỉnh để chạy đồng nhất trên nhiều máy (Windows, macOS, Linux):
1. Multi-stage `Dockerfile` (Python 3.11-slim, non-root user, tối ưu cache layer).
2. `docker-compose.yml` chứa các services: `postgres` (`pgvector/pgvector:pg16` + healthcheck), `redis` (`redis:7-alpine` + healthcheck), `migrator` (chạy `alembic upgrade head`), `bot` (chính ứng dụng Python), và `ollama` (gắn profile `local-llm`).
3. `docker-compose.gpu.yml` (override file riêng cấp phát NVIDIA GPU cho `ollama` / `trainer` mà không làm lỗi máy teammate không có GPU).

**Acceptance criteria:**
- [x] Volume mapping dùng biến di động `${DATA_DIR:-./data}/postgres`, `${DATA_DIR:-./data}/redis`, `${DATA_DIR:-./data}/ollama`.
- [x] Healthcheck cho Postgres và Redis đảm bảo thứ tự khởi động an toàn.
- [x] Có `.dockerignore` loại bỏ `.git`, `data/`, `__pycache__`, `.env`.

**Verification:**
- [x] Chạy `docker compose up -d` thành công; kiểm tra `docker compose ps` thấy `postgres` và `redis` đạt trạng thái `healthy`.
- [x] Kiểm tra dữ liệu được lưu đúng vào thư mục cấu hình bởi `${DATA_DIR}`.

**Dependencies:** Task 1
**Files likely touched:**
- `Dockerfile`
- `.dockerignore`
- `docker-compose.yml`
- `docker-compose.gpu.yml`

**Estimated scope:** Medium (3-4 files)

---

### Task 3: Database Models (SQLAlchemy 2.0 Async), pgvector & Auto-Migration
**Description:** Thiết lập engine kết nối bất đồng bộ tới PostgreSQL với `asyncpg`, kích hoạt extension `pgvector`, định nghĩa các model SQLAlchemy 2.0 (`VocabGroundTruth`, `ChatLogs`, `QuizLogs`) và cấu hình container `migrator` tự động chạy `alembic upgrade head` mỗi khi khởi động stack.

**Acceptance criteria:**
- [x] Model `VocabGroundTruth` có cột `embedding` (Vector), `ChatLogs` có `turns_json` (JSONB chuẩn ShareGPT), `QuizLogs` lưu lịch sử ôn tập SM-2.
- [x] Migration đầu tiên tự động chạy `CREATE EXTENSION IF NOT EXISTS vector`.
- [x] Service `migrator` trong `docker-compose.yml` thực thi thành công và thoát với exit code 0.

**Verification:**
- [x] Chạy `docker compose up -d` / `migrator` thành công; query vào Postgres xác nhận 4 bảng (`vocab_ground_truth`, `chat_logs`, `quiz_logs`, `alembic_version`) và extension `vector` đã tồn tại.

**Dependencies:** Task 2
**Files likely touched:**
- `src/db/session.py`
- `src/db/models.py`
- `alembic.ini`
- `migrations/env.py`
- `migrations/versions/001_initial_schema.py`

**Estimated scope:** Medium (3-5 files)

---

### Task 4: Redis Service (Session Memory, Rate Limiting & LLM Cache)
**Description:** Xây dựng module giao tiếp Redis bất đồng bộ (`redis.asyncio`) kết nối tới container `redis` trong Docker network:
1. **Sliding Window Chat Memory:** Lưu 5-10 lượt chat gần nhất của user với TTL 24h.
2. **Distributed Mutex Lock:** Ngăn user spam tin nhắn hoặc bấm nút liên tục trong lúc LLM đang xử lý.
3. **LLM Query Cache:** Cache phản hồi cho các câu hỏi/từ vựng giống nhau.

**Acceptance criteria:**
- [x] Class `RedisService` cung cấp đầy đủ hàm quản lý memory, distributed lock (`acquire_user_lock` / `release_user_lock`), và query cache.

**Verification:**
- [x] Chạy `pytest tests/test_redis_service.py` xác minh toàn bộ tests pass (sử dụng fake async Redis stub; chờ test với container Redis thực khi Docker chạy).

**Dependencies:** Task 2
**Files likely touched:**
- `src/services/redis_service.py`
- `tests/test_redis_service.py`

**Estimated scope:** Small (2 files)

---

### Task 5: LangChain LLM Factory & Gemini Teacher Engine
**Description:** Xây dựng mô hình Factory (`LLMFactory`) cho phép khởi tạo động các model theo cấu hình `AI_BACKEND` (`gemini` -> `ChatGoogleGenerativeAI`, `ollama` -> `ChatOllama` trỏ tới container `http://ollama:11434`, `huggingface` -> `vLLM/ChatHuggingFace`). Xây dựng Teacher Engine dùng Gemini với `.with_structured_output(PydanticSchema)` để sinh từ vựng chuẩn cấu trúc và xử lý hội thoại đa lượt.

**Acceptance criteria:**
- [x] `LLMFactory.get_chat_model()` trả về instance chuẩn `BaseChatModel` của LangChain tương ứng với từng tầng.
- [x] Hàm `generate_vocab_item(topic: str)` trả về đúng Pydantic model `VocabSchema`.
- [x] Hàm `chat_with_context(...)` tích hợp lịch sử hội thoại từ Redis.

**Verification:**
- [x] Chạy `pytest tests/test_llm_factory.py` kiểm tra khởi tạo được cả Gemini, Ollama, Hugging Face và output pass Pydantic validation 100% (mocked LLM response).

**Dependencies:** Task 1, Task 4
**Files likely touched:**
- `src/services/ai/llm_factory.py`
- `src/services/ai/chat_service.py`
- `src/schemas/vocab.py`
- `tests/test_llm_factory.py`

**Estimated scope:** Medium (3-4 files)

---

### Task 6: Containerized Telegram Bot Core & Interactive Handlers
**Description:** Khởi tạo Telegram Bot (`python-telegram-bot` v21+ async) chạy trong container `bot` (hỗ trợ mount source code dev mode để dễ debug), xây dựng các command handlers (`/start`, `/learn`, `/model`, `/stats`), xử lý hội thoại tự nhiên, bật typing indicator, áp dụng Redis lock chống spam và ghi log hội thoại vào bảng `chat_logs` (PostgreSQL).

**Acceptance criteria:**
- [x] Tin nhắn văn bản đi qua Redis lock, gọi LangChain Engine (Gemini Teacher), cập nhật Redis memory và lưu xuống PostgreSQL.
- [x] Lệnh `/model` cho phép kiểm tra hoặc chuyển đổi nhanh giữa `gemini`, `ollama` và `huggingface`.
- [x] Container `bot` tự động khởi động sau khi `migrator` và `redis` sẵn sàng (cấu hình trong `docker-compose.yml`).

**Verification:**
- [x] Unit test `tests/test_bot_handlers.py` kiểm tra wiring và `/model`, `/clear` commands pass.
- [ ] Chạy `docker compose up -d`, gửi tin nhắn từ Telegram: Bot phản hồi mượt mà, Redis lưu turn mới, PostgreSQL có bản ghi `chat_logs`. *(Chờ Docker & Telegram token thực tế)*

**Dependencies:** Task 3, Task 4, Task 5
**Files likely touched:**
- `src/bot/app.py`
- `src/bot/handlers/command_handlers.py`
- `src/bot/handlers/message_handlers.py`
- `main.py`

**Estimated scope:** Medium (3-4 files)

---

### Task 7: Spaced Repetition JobQueue & Inline Keyboard Quiz
**Description:** Sử dụng `JobQueue` của `python-telegram-bot` để quét định kỳ các từ vựng đến hạn ôn tập trong `vocab_ground_truth` và gửi câu hỏi trắc nghiệm qua `InlineKeyboardMarkup`. Bắt sự kiện bấm nút qua `CallbackQueryHandler` và lưu kết quả vào `quiz_logs`.

**Acceptance criteria:**
- [x] JobQueue quét và gửi quiz 4 đáp án không gây nghẽn bot.
- [x] Bấm nút phản hồi ngay kết quả Đúng/Sai kèm giải thích và ghi log vào `quiz_logs`.

**Verification:**
- [x] Unit test `tests/test_bot_handlers.py` xác nhận format quiz và callback buttons hoạt động đúng.
- [ ] Trigger thử 1 job ôn tập thực tế qua Telegram: Quiz xuất hiện, bấm đáp án cập nhật tin nhắn tức thì và lưu DB thành công.

**Dependencies:** Task 6
**Files likely touched:**
- `src/bot/jobs/vocab_jobs.py`
- `src/bot/handlers/callback_handlers.py`
- `src/services/vocab_service.py`

**Estimated scope:** Small (2-3 files)

---

## Checkpoint 1: Docker-First Foundation & Team Portability Verified
- [x] Chạy `docker compose up -d` là Bot + Postgres + Redis tự động migrate và khởi động hoàn chỉnh (`ai_telegram_bot` status Up, `Redis connectivity check: OK`).
- [ ] Dữ liệu trên máy cá nhân được cấu hình lưu vào ổ `E:\` qua `${DATA_DIR}`, kiểm thử chat thực tế qua Telegram App với tài khoản người dùng.

---

## Phase 2: Data Maturation, Sanitization & Ollama Open-Source Bridge

### Task 8: SuperMemo-2 (SM-2) Spaced Repetition Engine
**Description:** Hiện thực hóa thuật toán SuperMemo-2 (SM-2) để tính toán `repetition_count`, `ease_factor`, `interval_days` và tự động cập nhật `next_review_at` dựa trên kết quả làm quiz.

**Acceptance criteria:**
- [ ] Thuật toán SM-2 viết dạng pure function độc lập, dễ kiểm thử.
- [ ] Tự động cập nhật lịch ôn tập sau mỗi lần người dùng trả lời trắc nghiệm.

**Verification:**
- [ ] Chạy `docker compose run --rm bot pytest tests/test_sm2.py` pass 100%.

**Dependencies:** Task 7
**Files likely touched:**
- `src/algorithms/sm2.py`
- `src/services/vocab_service.py`
- `tests/test_sm2.py`

**Estimated scope:** Small (2 files)

---

### Task 9: Sanitization Pipeline & "AI Persona" Filter
**Description:** Xây dựng bộ lọc tự động cho `chat_logs`: phát hiện và đánh dấu `rejected` các phản hồi chứa câu máy móc ("As an AI language model...", "Tôi là mô hình ngôn ngữ...") hoặc lỗi format; chỉ đánh dấu `verified_golden` cho dữ liệu sạch.

**Acceptance criteria:**
- [ ] Bộ Regex/Heuristic bao quát từ khóa AI boilerplate cả tiếng Anh lẫn tiếng Việt.
- [ ] Chạy bất đồng bộ theo batch hoặc background job không ảnh hưởng tốc độ chat.

**Verification:**
- [ ] Chạy `docker compose run --rm bot pytest tests/test_sanitizer.py` với 20 mẫu synthetic đạt độ chính xác 100%.

**Dependencies:** Task 3, Task 6
**Files likely touched:**
- `src/services/sanitizer_service.py`
- `tests/test_sanitizer.py`

**Estimated scope:** Small (2 files)

---

### Task 10: System Prompt Refinement & Few-Shot Distillation Optimization
**Description:** Tinh chỉnh System Prompt và các ví dụ Few-Shot trong LangChain PromptTemplate để Gemini trả lời với phong cách "Bạn học đồng hành" (tự nhiên, súc tích, thân thiện), giúp dữ liệu đạt chất lượng cao nhất trước khi chưng cất.

**Acceptance criteria:**
- [ ] Prompt templates tách riêng trong `src/prompts/teacher_prompts.py`.
- [ ] Tích hợp Few-Shot examples cho giải thích từ vựng và trò chuyện tự nhiên.

**Verification:**
- [ ] Kiểm thử sinh 20 hội thoại ngẫu nhiên: tỷ lệ vượt qua Sanitizer ngay từ lần đầu > 95%.

**Dependencies:** Task 5, Task 9
**Files likely touched:**
- `src/prompts/teacher_prompts.py`
- `src/services/ai/chat_service.py`

**Estimated scope:** Small (2 files)

---

### Task 11: Ollama Container Integration (Local Fallback & Baseline Benchmark)
**Description:** Kích hoạt profile `local-llm` trong Docker Compose để chạy container **Ollama** (`qwen2.5:7b` hoặc `llama3.1:8b`, hỗ trợ cả CPU cho laptop thường và GPU qua `docker-compose.gpu.yml`). Thiết lập cơ chế tự động Fallback sang Ollama khi Gemini API gặp rate limit/mất mạng, đồng thời đo điểm chuẩn (Baseline) trước khi fine-tune.

**Acceptance criteria:**
- [ ] Pull và chạy thành công model `qwen2.5:7b` (hoặc `llama3.1:8b`) bên trong container `ollama`.
- [ ] Giao tiếp qua mạng nội bộ Docker (`http://ollama:11434`) trơn tru không cần mở port ra ngoài internet.
- [ ] Lưu lại bảng điểm benchmark (độ trễ, độ tự nhiên) của Ollama trước khi fine-tune.

**Verification:**
- [ ] Chạy `docker compose --profile local-llm up -d`, chuyển bot sang `/model ollama` trên Telegram và trò chuyện thử 10 lượt liên tiếp mượt mà.

**Dependencies:** Task 2, Task 5, Task 6
**Files likely touched:**
- `src/services/ai/llm_factory.py`
- `src/services/ai/fallback_chain.py`
- `tests/test_ollama_bridge.py`

**Estimated scope:** Small (2-3 files)

---

### Task 12: Dataset Tracker CLI & Health Monitor
**Description:** Viết công cụ dòng lệnh (CLI) sử dụng thư viện `rich` thống kê số lượng mẫu `verified_golden`, tỷ lệ reject, phân bố token và tiến độ tích lũy dữ liệu, chạy trực tiếp qua `docker compose exec bot python -m src.cli.stats`.

**Acceptance criteria:**
- [ ] Lệnh CLI hiển thị báo cáo trực quan từ PostgreSQL.

**Verification:**
- [ ] Chạy lệnh trong container xác minh số liệu khớp với DB thực tế.

**Dependencies:** Task 9
**Files likely touched:**
- `src/cli/stats.py`

**Estimated scope:** Small (1 file)

---

## Checkpoint 2: Golden Dataset Threshold & Ollama Bridge Verified
- [ ] Dữ liệu `verified_golden` đạt ngưỡng mục tiêu (ví dụ $\ge 10.000$ mẫu sạch).
- [ ] Tầng trung gian **Ollama container** vận hành trơn tru trên mọi máy hỗ trợ Docker, đóng vai trò fallback an toàn và tạo Baseline benchmark rõ ràng.

---

## Phase 3: Hugging Face Fine-Tuning & Complete Self-Hosting

### Task 13: Dataset Exporter (PostgreSQL to ShareGPT/Alpaca JSONL)
**Description:** Trích xuất dữ liệu có `status = 'verified_golden'` từ PostgreSQL ra 2 file `train.jsonl` (90%) và `val.jsonl` (10%) lưu trong thư mục `${DATA_DIR}/datasets` đúng định dạng huấn luyện của Hugging Face TRL / Unsloth.

**Acceptance criteria:**
- [ ] Lọc sạch dữ liệu và định dạng chuẩn ShareGPT / Alpaca JSONL.

**Verification:**
- [ ] Chạy `docker compose run --rm bot pytest tests/test_dataset_format.py` kiểm tra 100% các dòng JSONL hợp lệ.

**Dependencies:** Task 12
**Files likely touched:**
- `src/cli/export_dataset.py`
- `tests/test_dataset_format.py`

**Estimated scope:** Small (2 files)

---

### Task 14: Containerized Training Environment (Unsloth + Hugging Face QLoRA)
**Description:** Tạo `Dockerfile.train` (dựa trên base image NVIDIA CUDA + PyTorch + Unsloth + Hugging Face `transformers`, `peft`, `trl`, `huggingface_hub`) gắn profile `gpu-train` trong `docker-compose.gpu.yml`. Cho phép bất kỳ thành viên nào có GPU (trên Windows WSL2 hay Linux server) chạy 1 lệnh train QLoRA 4-bit trên Golden Dataset mà không phải cài CUDA thủ công lên máy host.

**Acceptance criteria:**
- [ ] `Dockerfile.train` đóng gói đủ môi trường Unsloth & Hugging Face.
- [ ] Script `training/train_unsloth.py` huấn luyện thành công trên GPU mà không bị tràn VRAM (OOM), lưu weights vào `${DATA_DIR}/models/hf_distilled_student/`.

**Verification:**
- [ ] Chạy `docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile gpu-train run --rm trainer` hoàn tất training run và xuất được model weights.

**Dependencies:** Task 13
**Files likely touched:**
- `Dockerfile.train`
- `training/train_unsloth.py`
- `training/config.yaml`
- `docker-compose.gpu.yml`

**Estimated scope:** Medium (3-4 files)

---

### Task 15: Model Evaluation & Export (Hugging Face Hub / GGUF for Ollama)
**Description:** Đánh giá mô hình Hugging Face vừa fine-tune so với Baseline của Ollama gốc (Task 11) và Gemini Teacher. Hỗ trợ đóng gói kép:
- Lưu dạng **Hugging Face Safetensors/AWQ** (để đẩy lên Hugging Face Hub nội bộ của team hoặc chạy qua `vLLM`).
- Export sang định dạng **GGUF (`Q4_K_M`)** kèm `Modelfile` để nạp trực tiếp vào container **Ollama** (`ollama create ai-telegram-student -f Modelfile`), giúp mọi thành viên trong team kéo về chạy ngay dù không dùng vLLM.

**Acceptance criteria:**
- [ ] Báo cáo so sánh chất lượng giữa: Gemini vs Ollama Gốc vs Student Fine-tuned.
- [ ] File GGUF nạp thành công vào container Ollama.

**Verification:**
- [ ] Chạy thử nghiệm hội thoại với model mới sinh ra qua container Ollama hoặc vLLM, xác nhận văn phong tự nhiên chuẩn như Gemini.

**Dependencies:** Task 14
**Files likely touched:**
- `training/evaluate.py`
- `training/export_model.py`
- `training/Modelfile`

**Estimated scope:** Medium (3 files)

---

### Task 16: Local Hugging Face / Ollama Serving & PGVector Hybrid RAG
**Description:** Tích hợp mô hình Hugging Face đã chưng cất (chạy qua container `vLLM` hoặc container `Ollama` với custom GGUF) vào `LLMFactory`. Kết hợp module **Hybrid RAG** sử dụng `langchain-postgres` (`PGVector`) truy vấn bảng `vocab_ground_truth` để cung cấp ngữ cảnh từ vựng chính xác, triệt tiêu ảo giác.

**Acceptance criteria:**
- [ ] Biến `AI_BACKEND=huggingface` (hoặc `ollama` với custom model) hoạt động hoàn chỉnh với Telegram bot.
- [ ] Module RAG truy xuất đúng top-k từ vựng liên quan từ PostgreSQL `pgvector` và nhồi vào prompt.

**Verification:**
- [ ] Chạy `docker compose run --rm bot pytest tests/test_local_rag.py`: bot trả lời đúng định nghĩa và ví dụ lấy từ database mà không cần internet.

**Dependencies:** Task 15
**Files likely touched:**
- `src/services/ai/llm_factory.py`
- `src/services/ai/rag_service.py`
- `tests/test_local_rag.py`

**Estimated scope:** Medium (3 files)

---

### Task 17: Production Compose Profile, Team Onboarding Docs & API Decoupling
**Description:** Hoàn thiện `docker-compose.yml` cho môi trường Production (ngắt hoàn toàn Gemini API key, mặc định dùng `AI_BACKEND=huggingface` hoặc `ollama`, cấu hình restart policy `unless-stopped`, log rotation). Viết `README.md` chuẩn hướng dẫn team cách clone, cấu hình `.env`, chạy trên máy Windows/Mac/Linux (CPU lẫn GPU).

**Acceptance criteria:**
- [ ] Bất kỳ máy nào cài Docker đều khởi chạy được toàn bộ hệ thống bằng một lệnh `docker compose up -d`.
- [ ] Chi phí vận hành AI = 0đ, tự chủ 100% mô hình và dữ liệu.

**Verification:**
- [ ] Test quy trình Clean Onboarding: xóa sạch container (giữ nguyên volume hoặc test DB mới), chạy theo đúng hướng dẫn trong `README.md` và xác nhận mọi tính năng hoạt động 100%.

**Dependencies:** Task 16
**Files likely touched:**
- `docker-compose.yml`
- `.env.production.example`
- `README.md`

**Estimated scope:** Small to Medium (3 files)

---

## Checkpoint 3: Multi-Machine Portable Self-Hosting Completed
- [ ] Đã hoàn tất chặng đường từ Gemini Teacher ➔ Open Source Ollama Bridge ➔ Fine-tuned Hugging Face Model.
- [ ] Toàn bộ stack được đóng gói 100% trong Docker (từ Bot, Migrator, DB, Redis đến Training & Inference), đảm bảo đồng bộ tuyệt đối khi team cùng phát triển trên nhiều máy khác nhau.
