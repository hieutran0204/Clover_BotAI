# Tổng Quan Hệ Thống & Đánh Giá Code (Phase 1 ➔ Phase 2 Ground Truth Pipeline)

> **Phạm vi rà soát:** Toàn bộ codebase `AI-Telegram` tính đến thời điểm hiện tại (Hạ tầng Phase 1 + Unified Ingestion, SM-2, File/Topic Seeder, Passive Chat Extraction, Multimodal OCR, Sanitizer/Distillation & Stats CLI).  
> **Trạng thái Runtime & Test hiện tại:** Stack Docker (`ai_telegram_bot`, `ai_telegram_postgres`, `ai_telegram_redis`) đang hoạt động với `GEMINI_MODEL=gemini-3.6-flash`; **33/33 unit tests** pass (`3.14s` trong container `bot`).

---

## Phần A: Tổng Quan Những Gì Đã Xây Dựng

### 1. Hạ Tầng & Kiến Trúc Nền (Phase 1)
- **Container & Database:** [docker-compose.yml](file:///e:/AI-Telegram/docker-compose.yml), [Dockerfile](file:///e:/AI-Telegram/Dockerfile), [001_initial_schema.py](file:///e:/AI-Telegram/migrations/versions/001_initial_schema.py).
  - PostgreSQL 16 + extension `pgvector` (bảng `vocab_ground_truth` với cột `Vector(768)`, `chat_logs` lưu `JSONB`, `quiz_logs` theo dõi lịch sử trả lời).
  - Redis 7 làm Sliding Window Chat Memory, cache backend LLM (`/model`), và Distributed User Lock chống user spam song song (`acquire_user_lock` / `release_user_lock` dùng Lua script an toàn).
- **3-Stage LLM Orchestration:** [llm_factory.py](file:///e:/AI-Telegram/src/services/ai/llm_factory.py), [chat_service.py](file:///e:/AI-Telegram/src/services/ai/chat_service.py).
  - Hỗ trợ chuyển nóng runtime qua `/model` giữa `gemini` (Stage 1 Teacher), `ollama` (Stage 2 Local Bridge), và `huggingface` / vLLM (Stage 3 Student).
- **Telegram Bot Core & Scheduler:** [app.py](file:///e:/AI-Telegram/src/bot/app.py), [command_handlers.py](file:///e:/AI-Telegram/src/bot/handlers/command_handlers.py), [callback_handlers.py](file:///e:/AI-Telegram/src/bot/handlers/callback_handlers.py), [vocab_jobs.py](file:///e:/AI-Telegram/src/bot/jobs/vocab_jobs.py).
  - Đã đăng ký 10 handlers (6 lệnh `/start`, `/help`, `/learn`, `/model`, `/stats`, `/clear`, 1 callback quiz inline `quiz:<uuid>:<idx>`, 3 message handlers: `PHOTO`, `Document.PDF`, `TEXT`) + JobQueue `check_due_vocab_job` lặp mỗi 5 phút.

### 2. Stage 0 — Lõi Nạp Chung & Thuật Toán SM-2
- [`EmbeddingService`](file:///e:/AI-Telegram/src/services/ai/embedding_service.py): Gọi `models/gemini-embedding-001` với `output_dimensionality=768` khớp schema `pgvector`.
- [`VocabIngestionService`](file:///e:/AI-Telegram/src/services/vocab_ingestion_service.py): Chuẩn hóa `word.strip().lower()`, lọc trùng trong batch và trong PostgreSQL theo `(lower(word), telegram_user_id)` **trước** khi gọi API embedding, giúp tiết kiệm quota và tránh duplicate.
- [`calculate_sm2`](file:///e:/AI-Telegram/src/algorithms/sm2.py) tích hợp vào [`VocabService.record_quiz_attempt`](file:///e:/AI-Telegram/src/services/vocab_service.py): Tính chuẩn `repetition_count`, `ease_factor` (floor `1.3`), `interval_days`, `next_review_at` dựa trên kết quả đúng/sai.

### 3. Kênh Nạp Ground Truth (Theo Đúng Thứ Tự 1 ➔ 3 ➔ 2)
1. **Phần 1 — Seeder từ File & Chủ Đề:** [sample_vocab.json](file:///e:/AI-Telegram/data/seeds/sample_vocab.json), [seed_vocab.py](file:///e:/AI-Telegram/src/cli/seed_vocab.py).
   - Hỗ trợ `.json` và `.csv` (cả bản ghi đầy đủ lẫn danh sách từ thô cần Gemini enrich theo batch 10 từ/lần).
   - Hỗ trợ `--topics` kèm `exclude_words` lấy từ DB để sinh bộ từ mới không trùng.
2. **Phần 3 — Passive Extraction từ Hội Thoại Chat:** [vocab_extractor.py](file:///e:/AI-Telegram/src/services/ai/vocab_extractor.py), [message_handlers.py](file:///e:/AI-Telegram/src/bot/handlers/message_handlers.py).
   - Lọc nhanh tin nhắn xã giao (`"hi"`, `"ok"`, `"cảm ơn"`...) để không gọi LLM thừa.
   - Sau khi gửi câu trả lời chat chính cho user, chạy ngầm `asyncio.create_task` cô lập bằng `try/except` và chỉ báo cho user khi `inserted > 0`.
3. **Phần 2 — Multimodal OCR (Ảnh & PDF):** [vision_extractor.py](file:///e:/AI-Telegram/src/services/ai/vision_extractor.py), [media_handlers.py](file:///e:/AI-Telegram/src/bot/handlers/media_handlers.py).
   - Ảnh: Encode base64 data URL gửi `Gemini Vision` với `.with_structured_output(VocabBatchSchema)`.
   - PDF: Dùng `pypdf` đọc in-memory, giới hạn tối đa 15 trang/file, gom nhóm 3 trang/chunk, chặn PDF scan rỗng text trước khi gọi LLM, giới hạn file Telegram 20MB và luôn release Redis lock trong `finally`.

### 4. Stage 4 — Chuyển Hóa Golden Dataset & Giám Sát
- [`SanitizerService`](file:///e:/AI-Telegram/src/services/sanitizer_service.py) & [sanitize_logs.py](file:///e:/AI-Telegram/src/cli/sanitize_logs.py): Chặn câu AI boilerplate song ngữ Anh–Việt, câu fallback lỗi, câu quá ngắn (`< 20` ký tự) và code block bị cắt cụt (lẻ số lượng ```` ``` ````).
- [generate_distill_data.py](file:///e:/AI-Telegram/src/cli/generate_distill_data.py) & [teacher_prompts.py](file:///e:/AI-Telegram/src/prompts/teacher_prompts.py): Chuyển đổi `vocab_ground_truth` thành hội thoại ShareGPT trong `chat_logs` (chạy offline template chuẩn hóa hoặc `--use-llm`), bắt buộc đi qua [`SanitizerService`](file:///e:/AI-Telegram/src/services/sanitizer_service.py) trước khi gắn `status = 'verified_golden'`.
- [stats.py](file:///e:/AI-Telegram/src/cli/stats.py): Dashboard Rich CLI thống kê tổng từ vựng, độ phủ vector 768 chiều, phân bố CEFR, số từ đến hạn SM-2, trạng thái `chat_logs` và cảnh báo tự động khi thiếu embedding hoặc tỷ lệ reject > 10%.

---

## Phần B: Đánh Giá Code 5 Trục (Five-Axis Code Review)

### Mức độ ưu tiên cần xử lý (`Critical` & `Required`)

#### 1. **Required (Correctness / Scheduling Bug): `get_due_vocab_items` có thể bỏ sót từ của User vì bị các từ Global Seed chiếm hết `limit=5`**
- **Vị trí:** [`VocabService.get_due_vocab_items`](file:///e:/AI-Telegram/src/services/vocab_service.py#L57-L78) và [`check_due_vocab_job`](file:///e:/AI-Telegram/src/bot/jobs/vocab_jobs.py#L78-L83).
- **Vấn đề:** Hiện tại `get_due_vocab_items(session, limit=5)` lấy 5 bản ghi bất kỳ có `next_review_at <= now` theo thứ tự tăng dần **mà không lọc `telegram_user_id IS NOT NULL`**. Trong DB đang có 10 từ Global Seed (`telegram_user_id = None`) vừa đến hạn SM-2. Khi scheduler chạy, 5 từ `None` cũ nhất luôn chiếm trọn 5 slot trả về, và vòng lặp `if not vocab.telegram_user_id: continue` bỏ qua cả 5 — khiến các từ riêng của user có thể **không bao giờ được gửi quiz**!
- **Hướng sửa (Structural Remedy):** Thêm `.where(VocabGroundTruth.telegram_user_id.is_not(None))` trực tiếp vào câu query trong `VocabService.get_due_vocab_items` (hoặc thêm tham số `user_scoped_only: bool = True`).

#### 2. **Required (Architecture / Schema Drift): Định dạng `turns_json` trong `chat_logs` chưa thống nhất trước khi đưa vào `SanitizerService`**
- **Vị trí:** [`AIChatService._to_sharegpt_turns`](file:///e:/AI-Telegram/src/services/ai/chat_service.py#L84-L105) vs [`build_sharegpt_turns`](file:///e:/AI-Telegram/src/prompts/teacher_prompts.py) vs [`SanitizerService.evaluate_turn`](file:///e:/AI-Telegram/src/services/sanitizer_service.py).
- **Vấn đề:**
  - Chat thật ghi `turns_json` theo cặp key ShareGPT kinh điển: `{"from": "human"|"gpt", "value": "..."}`.
  - `generate_distill_data.py` ghi theo key ChatML: `{"role": "system"|"user"|"assistant", "content": "..."}`.
  - Khi chạy `sanitize_logs.py`, `SanitizerService` chuẩn hóa mọi record sang `role/content`, tạo ra trạng thái hỗn hợp (`raw` dùng `from/value`, còn `verified_golden` dùng `role/content`).
- **Hướng sửa (Structural Remedy):** Chọn 1 schema chuẩn duy nhất (khuyên dùng ChatML `{"role": "system"|"user"|"assistant", "content": ...}` vì tương thích trực tiếp với `transformers` / `trl` / Unsloth `apply_chat_template` ở Phase 3) ngay từ `_to_sharegpt_turns` và xóa sự khác biệt hai chuẩn.

#### 3. **Required (Correctness / Concurrency): Nhân bội retry giữa `tenacity` và LangChain SDK làm vượt TTL khóa Redis**
- **Vị trí:** [`AIChatService`](file:///e:/AI-Telegram/src/services/ai/chat_service.py#L131-L240), [`LLMFactory.get_chat_model`](file:///e:/AI-Telegram/src/services/ai/llm_factory.py#L43-L49), [`RedisService.acquire_user_lock`](file:///e:/AI-Telegram/src/services/redis_service.py).
- **Vấn đề:** `LLMFactory` đặt `timeout=30.0, max_retries=1` (tối đa ~60s), trong khi 4 method của `AIChatService` bọc thêm `@retry(stop=stop_after_attempt(3))` ➔ tổng cộng tối đa **6 lần thử (~180 giây)**, vượt xa khóa Redis `ttl_seconds=30` của user. Nếu upstream chậm, khóa hết hạn giữa chừng cho phép tin nhắn thứ hai chạy song song cùng user.
- **Hướng sửa (Structural Remedy):** Chỉ giữ retry ở **một tầng duy nhất** (khuyên giữ `tenacity` hoặc SDK `max_retries=1`), và bọc lời gọi AI tương tác trong `handle_text_message` bằng `asyncio.wait_for(..., timeout=28.0)` để khớp với lock 30s.

---

### Điểm cần cải thiện / gợi ý (`Optional` & `Consider`)

- **Optional — Bug UX nhỏ ở `/learn`:** [`learn_command`](file:///e:/AI-Telegram/src/bot/handlers/command_handlers.py#L83-L89) đã chuyển sang gọi `ingestion.ingest_items(...)`, nhưng không kiểm tra `report.skipped_duplicates > 0`. Nếu Gemini sinh trúng từ user đã học, bot vẫn báo `"Từ này đã được lưu..."`. Có thể hiển thị thông báo phân biệt từ mới vs từ đã có trong kho.
- **Optional — Thiếu Rate Limit cho Media OCR:** [`handle_photo_message`](file:///e:/AI-Telegram/src/bot/handlers/media_handlers.py) và [`handle_pdf_document`](file:///e:/AI-Telegram/src/bot/handlers/media_handlers.py) đã chặn size `20MB` và khóa Redis đồng thời, nhưng chưa có giới hạn số lượt OCR/ngày mỗi user (cần thiết nếu mở bot cho nhiều người dùng để bảo vệ quota Gemini Vision).
- **Consider — Hỗ trợ nạp embedding bổ sung (Backfill) cho dữ liệu cũ:** `stats.py` đang phát hiện đúng 1 bản ghi `/learn` từ Phase 1 chưa có vector (`Missing Embedding: 1`). Nên có thêm flag nhỏ hoặc script backfill chạy qua [`EmbeddingService`](file:///e:/AI-Telegram/src/services/ai/embedding_service.py) để lấp đầy mọi bản ghi NULL nếu sau này bật tìm kiếm ngữ nghĩa RAG.
- **Security Summary (Đạt mức tốt cho môi trường dev/local):**
  - Toàn bộ query PostgreSQL đều parameterized qua SQLAlchemy.
  - Toàn bộ message Telegram `parse_mode="HTML"` đều đi qua `html.escape(...)` chống injection thẻ HTML.
  - `.env` (chứa `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, DB credentials) đã được loại trừ khỏi git và Docker build context thông qua [.gitignore](file:///e:/AI-Telegram/.gitignore) và [.dockerignore](file:///e:/AI-Telegram/.dockerignore).

---

### Vệ Sinh Mã Nguồn (`Dead Code Hygiene`)

- **Cần xác nhận trước khi dọn:** [`VocabService.save_vocab_item`](file:///e:/AI-Telegram/src/services/vocab_service.py#L22-L55) hiện không còn luồng chính nào gọi (vì `seed_vocab`, `learn_command`, `message_handlers`, `media_handlers` đều đi qua [`VocabIngestionService.ingest_items`](file:///e:/AI-Telegram/src/services/vocab_ingestion_service.py) để có chống trùng và vector 768 chiều). Nó chỉ còn nằm ở nhánh fallback `else` trong [`command_handlers.py`](file:///e:/AI-Telegram/src/bot/handlers/command_handlers.py#L88-L89). Khi chắc chắn `vocab_ingestion` luôn được inject trong `bot_data`, có thể cân nhắc bỏ nhánh fallback + hàm cũ này để tránh vô tình tạo bản ghi thiếu embedding.

---

## Phần C: Bức Tranh Kiểm Chứng (Verification Status)

| Hạng mục | Cách kiểm tra đã thực hiện | Kết quả |
|---|---|---|
| Bộ unit test toàn hệ thống | `docker compose exec -T bot pytest -o cache_dir=/tmp/pytest_cache -v` | **33 passed in 3.14s** (đa số test Phase 2 mock LLM & DB session) |
| Live Embedding (`768-dim`) + File Seeder | `python -m src.cli.seed_vocab --file data/seeds/sample_vocab.json` | Lần 1: `inserted=10`; Lần 2: `skipped_duplicates=10`. DB xác nhận đủ `vector_dims = 768` |
| Live Chat Engine (`gemini-3.6-flash`) | Test trực tiếp `AIChatService.chat_with_context` từ container `bot` | Phản hồi đúng sau khi chuyển từ `gemini-3.8-flash` (đang lỗi `504`) sang `gemini-3.6-flash` |
| Live Distillation & Dashboard | `python -m src.cli.generate_distill_data` + `python -m src.cli.stats` | `11` từ `➔ 11 verified_golden` trong `chat_logs`; bảng `stats` khớp SQL |
| Live `--topics` CLI (`seed_vocab.py`) | Chạy với `gemini-3.8-flash` lúc trước | Bị treo/timeout do `gemini-3.8-flash` trả `504` (chưa chạy lại với `gemini-3.6-flash`) |
| Test thủ công trực tiếp trên app Telegram | Chat hỏi từ mới, gửi ảnh chụp, gửi PDF, trả lời quiz SM-2 | **Chờ user test trực tiếp trên Telegram** |

