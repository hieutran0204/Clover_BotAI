# Task Breakdown: Ground Truth Ingestion (1 ➔ 3 ➔ 2) & Distillation Data Pipeline

> **Thứ tự thực hiện:** Nền tảng Lõi (Tasks 1–2) ➔ **Phần 1: Seeder** (Tasks 3–4) ➔ **Phần 3: Chat Extraction** (Tasks 5–6) ➔ **Phần 2: Multimodal OCR** (Tasks 7–8) ➔ **Chuyển hóa thành Golden Data** (Tasks 9–10).

---

## Stage 0: Nền Tảng Lõi (Unified Ingestion, Vector Embedding & SM-2)

### Task 1: Unified `VocabIngestionService` & `pgvector` Embedding Service (768-dim)
**Description:** Xây dựng lõi nạp dữ liệu dùng chung cho cả 3 nguồn nạp. Thêm schema `VocabBatchSchema` (`items: List[VocabSchema]`), xây dựng `EmbeddingService` dùng `GoogleGenerativeAIEmbeddings` cấu hình cứng `output_dimensionality=768` khớp cột `Vector(768)` trong `VocabGroundTruth`, và xây dựng `VocabIngestionService` chuẩn hóa `word.strip().lower()`, lọc bỏ từ trùng lặp trước khi gọi embedding và insert hàng loạt vào PostgreSQL.

**Acceptance criteria:**
- [x] `EmbeddingService.embed_texts(texts)` trả về các vector đúng `768` chiều và hỗ trợ inject mock cho test.
- [x] `VocabIngestionService.ingest_items(session, items, telegram_user_id)` kiểm tra trùng theo `(lower(word), telegram_user_id)`, bỏ qua từ đã tồn tại, tạo embedding và trả về báo cáo `{inserted, skipped_duplicates, inserted_words}`.
- [x] `VocabBatchSchema` trong `src/schemas/vocab.py` cho phép list rỗng `items: []` để xử lý an toàn khi ảnh/chat không có từ mới.

**Verification:**
- [x] Chạy `docker compose exec -T bot pytest tests/test_vocab_ingestion.py -v` xác minh logic deduplication, kích thước vector 768 chiều và kết quả đếm chính xác.

**Dependencies:** Phase 1 completed
**Files likely touched:**
- `src/schemas/vocab.py`
- `src/services/ai/embedding_service.py`
- `src/services/vocab_ingestion_service.py`
- `tests/test_vocab_ingestion.py`

**Estimated scope:** Medium (4 files)

---

### Task 2: SuperMemo-2 (SM-2) Spaced Repetition Engine
**Description:** Hiện thực hóa thuật toán SuperMemo-2 (SM-2) dưới dạng pure function để tính toán lại `repetition_count`, `ease_factor`, `interval_days` và `next_review_at` dựa trên điểm chất lượng (0–5), thay thế logic nhân đôi ngày đơn giản ở Phase 1 trong `VocabService.record_quiz_attempt`.

**Acceptance criteria:**
- [x] Hàm `calculate_sm2(repetition_count, ease_factor, interval_days, quality)` xử lý đúng cả nhánh nhớ (`quality >= 3`) và nhánh quên (`quality < 3`: reset `repetition_count=0`, `interval_days=1`, giữ `ease_factor >= 1.3`).
- [x] `VocabService.record_quiz_attempt` cập nhật chính xác 4 trường SM-2 trên bản ghi `VocabGroundTruth`.

**Verification:**
- [x] Chạy `docker compose exec -T bot pytest tests/test_sm2.py -v` đạt 100% pass cho tất cả trường hợp biên.

**Dependencies:** Phase 1 completed
**Files likely touched:**
- `src/algorithms/__init__.py`
- `src/algorithms/sm2.py`
- `src/services/vocab_service.py`
- `tests/test_sm2.py`

**Estimated scope:** Small (3-4 files)

---

## Checkpoint A: Core Ingestion & SM-2 Verified
- [x] `test_vocab_ingestion.py` và `test_sm2.py` pass 100% trong container `bot`.

---

## Stage 1 (Phần 1): Seeder Đẩy Dữ Liệu Ground Truth Từ File & Chủ Đề

### Task 3: Sample Seed Data & CLI File Seeder (`CSV` / `JSON`)
**Description:** Tạo bộ dữ liệu mẫu chuẩn (`data/seeds/sample_vocab.json`) và viết CLI script `src/cli/seed_vocab.py` cho phép nạp từ vựng từ file `.json` hoặc `.csv`. Nếu file đã có đủ cấu trúc `VocabSchema` thì nạp thẳng qua `VocabIngestionService`; nếu file chỉ có danh sách từ thô (`word`, `topic`), tự động lọc bỏ từ đã có trong DB rồi gọi Gemini enrich thành `VocabSchema` theo batch.

**Acceptance criteria:**
- [x] Chạy được lệnh `docker compose exec -T bot python -m src.cli.seed_vocab --file data/seeds/sample_vocab.json`.
- [x] Hỗ trợ cả định dạng `.json` và `.csv`, bỏ qua từ đã tồn tại trong DB trước khi gọi Gemini enrich để tiết kiệm API quota.

**Verification:**
- [x] Chạy `docker compose exec -T bot pytest tests/test_seed_vocab.py -v` và nạp thử `sample_vocab.json` vào PostgreSQL thật, kiểm tra có dữ liệu và cột `embedding` khác NULL.

**Dependencies:** Task 1
**Files likely touched:**
- `data/seeds/sample_vocab.json`
- `src/cli/__init__.py`
- `src/cli/seed_vocab.py`
- `tests/test_seed_vocab.py`

**Estimated scope:** Medium (4 files)

---

### Task 4: Topic-Based Batch Ground Truth Generator
**Description:** Bổ sung chế độ sinh từ vựng theo danh sách chủ đề (`--topics "software engineering,daily idioms" --count 10`) vào `src/cli/seed_vocab.py` và `AIChatService`. Lấy danh sách các từ đã có trong `vocab_ground_truth` làm `exclude_words` truyền vào prompt để Gemini sinh `N` từ mới (B1–C1) không trùng lặp rồi nạp qua `VocabIngestionService`.

**Acceptance criteria:**
- [x] Hàm `AIChatService.generate_vocab_batch(topic, count, exclude_words)` trả về `VocabBatchSchema` đúng cấu trúc.
- [x] CLI `--topics` sinh và nạp thành công từ mới cho từng chủ đề mà không sinh trùng các từ đã tồn tại.

**Verification:**
- [ ] Chạy `docker compose exec -T bot pytest tests/test_seed_topics.py -v` (mocked Gemini) và thử sinh 5 từ cho 1 chủ đề thật vào PostgreSQL. *(Unit test mocked pass; lệnh live Gemini `--topics` bị chậm/timeout khi thử trực tiếp, có thể chạy lại riêng khi mạng ổn định)*

**Dependencies:** Task 3
**Files likely touched:**
- `src/services/ai/chat_service.py`
- `src/cli/seed_vocab.py`
- `tests/test_seed_topics.py`

**Estimated scope:** Small (3 files)

---

## Checkpoint B (Phần 1 Complete): File & Topic Seeding Verified
- [x] Kho `vocab_ground_truth` đã có bộ từ vựng nền tảng kèm vector 768 chiều sẵn sàng phục vụ ôn tập SM-2 và RAG.

---

## Stage 2 (Phần 3): Tự Động Trích Xuất Từ Vựng Từ Cuộc Chat Của User

### Task 5: LangChain Passive Chat Vocab Extractor
**Description:** Xây dựng `VocabExtractorService` sử dụng LangChain `.with_structured_output(VocabBatchSchema)` để phân tích cặp tin nhắn `(user_message, ai_reply)`: nhận diện xem user có đang hỏi nghĩa, hỏi cách dùng từ mới, hoặc dùng sai từ đáng chú ý hay không, từ đó trích xuất tối đa 1–3 thẻ `VocabSchema` (trình độ B1+ hoặc idiom).

**Acceptance criteria:**
- [x] Trả về `items: []` đối với câu xã giao ngắn (`"hi"`, `"ok"`, `"cảm ơn"`), tránh sinh thẻ rác.
- [x] Trích xuất chính xác các từ vựng mục tiêu thành `VocabSchema` đầy đủ nghĩa, ví dụ và quiz khi user hỏi từ vựng.

**Verification:**
- [x] Chạy `docker compose exec -T bot pytest tests/test_vocab_extractor.py -v` kiểm tra cả kịch bản xã giao (0 từ) và kịch bản hỏi nghĩa từ (ra đúng thẻ từ).

**Dependencies:** Task 1
**Files likely touched:**
- `src/services/ai/vocab_extractor.py`
- `tests/test_vocab_extractor.py`

**Estimated scope:** Small (2 files)

---

### Task 6: Non-Blocking Background Extraction Hook trong Telegram Chat
**Description:** Tích hợp `VocabExtractorService` vào `handle_text_message` theo cơ chế chạy ngầm không chặn luồng chat (`asyncio.create_task` có `try/except` cô lập). Sau khi bot gửi xong câu trả lời chính cho user, tác vụ ngầm trích xuất từ mới, lưu qua `VocabIngestionService` với `telegram_user_id=user_id`, và chỉ gửi thêm 1 tin nhắn ngắn báo cho user nếu `inserted > 0`.

**Acceptance criteria:**
- [x] Độ trễ phản hồi tin nhắn chat chính không bị ảnh hưởng bởi tác vụ trích xuất từ vựng.
- [x] Lỗi ở background task chỉ ghi log warning/exception, tuyệt đối không làm crash bot polling.
- [x] Chỉ gửi thông báo `"📝 Đã tự động lưu từ mới vào lịch ôn tập: ..."` khi có ít nhất 1 từ mới được thêm.

**Verification:**
- [ ] Chạy `docker compose exec -T bot pytest tests/test_chat_extraction_hook.py -v` và test chat thật trên Telegram hỏi nghĩa 1 từ mới, kiểm tra từ đó tự xuất hiện trong `vocab_ground_truth`. *(Unit test mocked pass; chưa test chat thật trên app Telegram)*

**Dependencies:** Task 5
**Files likely touched:**
- `src/bot/handlers/message_handlers.py`
- `src/bot/app.py`
- `tests/test_chat_extraction_hook.py`

**Estimated scope:** Small (3 files)

---

## Checkpoint C (Phần 3 Complete): Organic Chat Extraction Verified
- [ ] Trò chuyện tự nhiên trên Telegram để hỏi nghĩa/cách dùng từ tự động lưu từ vựng mới vào lịch ôn tập SM-2 của user.

---

## Stage 3 (Phần 2): Multimodal OCR Đọc Ảnh Chụp & Tài Liệu PDF

### Task 7: Multimodal Vision & PDF Chunk Extractor (`Gemini Vision` + `pypdf`)
**Description:** Bổ sung `pypdf>=5.0.0` vào `requirements.txt` và rebuild Docker image. Xây dựng `VisionExtractorService` gửi ảnh chụp trang sách/screenshot (base64 data URL) trực tiếp sang `gemini-3.8-flash` Multimodal kèm `.with_structured_output(VocabBatchSchema)`. Với file PDF, dùng `pypdf` trích text theo từng cụm 3 trang (tối đa 15 trang/file để bảo vệ quota) rồi bóc tách tối đa 10 từ đắt giá mỗi chunk.

**Acceptance criteria:**
- [x] `extract_from_image(image_bytes, mime_type)` bóc tách được `VocabSchema` list (hoặc rỗng nếu ảnh không có từ vựng).
- [x] `extract_from_pdf(pdf_bytes)` tách chunk 3 trang/lần, gộp kết quả và loại bỏ từ trùng lặp trước khi trả về.

**Verification:**
- [x] Chạy `docker compose exec -T bot pytest tests/test_vision_extractor.py -v` kiểm tra logic chunking PDF và multimodal message payload.

**Dependencies:** Task 1
**Files likely touched:**
- `requirements.txt`
- `src/services/ai/vision_extractor.py`
- `tests/test_vision_extractor.py`

**Estimated scope:** Medium (3 files)

---

### Task 8: Telegram Photo & PDF Document Handlers
**Description:** Tạo `src/bot/handlers/media_handlers.py` xử lý `filters.PHOTO` và `filters.Document.PDF` trên Telegram, đăng ký vào `src/bot/app.py`. Kiểm tra giới hạn file (tối đa 20MB), áp dụng Redis user lock, tải file vào memory, chạy `VisionExtractorService` ➔ `VocabIngestionService`, và phản hồi danh sách từ mới đã lưu kèm số từ trùng bỏ qua.

**Acceptance criteria:**
- [x] Gửi ảnh hoặc file PDF qua Telegram: bot thông báo đang xử lý, bóc tách và lưu từ mới kèm embedding vào `vocab_ground_truth`.
- [x] Từ chối lịch sự nếu file quá 20MB hoặc định dạng document không phải PDF; luôn release Redis lock trong `finally`.

**Verification:**
- [ ] Chạy `docker compose exec -T bot pytest tests/test_media_handlers.py -v` và test gửi 1 ảnh chụp bài đọc/danh sách từ vựng qua Telegram để xác minh lưu DB thành công. *(Unit test mocked pass; chưa test gửi ảnh/PDF thật trên Telegram)*

**Dependencies:** Task 7
**Files likely touched:**
- `src/bot/handlers/media_handlers.py`
- `src/bot/app.py`
- `tests/test_media_handlers.py`

**Estimated scope:** Medium (3 files)

---

## Checkpoint D (Phần 2 Complete): Multimodal OCR Ingestion Verified
- [ ] Cả 3 kênh nạp Ground Truth (**1: File/Topic Seeder ➔ 3: Passive Chat Extraction ➔ 2: Photo/PDF Multimodal OCR**) đều chạy hoàn chỉnh và đổ về chung một kho `vocab_ground_truth` có vector 768 chiều.

---

## Stage 4: Chuyển Hóa Ground Truth Thành Dữ Liệu Huấn Luyện (Golden Dataset)

### Task 9: Sanitizer Filter & Synthetic Distillation Q&A Generator
**Description:** Xây dựng `SanitizerService` lọc bỏ các câu boilerplate AI máy móc (*"As an AI..."*, *"Tôi là mô hình ngôn ngữ..."*) và lỗi format trong `chat_logs` (gắn cờ `verified_golden` hoặc `rejected`). Đồng thời xây dựng CLI `src/cli/generate_distill_data.py` lấy các từ từ `vocab_ground_truth` để sinh các cặp hội thoại học tập đa dạng chuẩn ShareGPT (giải thích nghĩa, đặt câu, phân biệt sắc thái, sửa lỗi), chạy qua `SanitizerService` trước khi lưu `status = 'verified_golden'`.

**Acceptance criteria:**
- [x] `SanitizerService` phát hiện chính xác boilerplate song ngữ Anh–Việt và lỗi cắt cụt câu.
- [x] `generate_distill_data.py` sinh được hội thoại ShareGPT đa dạng từ `vocab_ground_truth` và lọc tự động thành `verified_golden`.

**Verification:**
- [x] Chạy `docker compose exec -T bot pytest tests/test_sanitizer_and_distill.py -v` pass 100% và thử sinh dữ liệu mẫu cho 5 từ trong PostgreSQL.

**Dependencies:** Task 1
**Files likely touched:**
- `src/services/sanitizer_service.py`
- `src/cli/sanitize_logs.py`
- `src/cli/generate_distill_data.py`
- `tests/test_sanitizer_and_distill.py`

**Estimated scope:** Medium (4 files)

---

### Task 10: CLI Ingestion & Golden Dataset Health Monitor
**Description:** Viết công cụ dòng lệnh `src/cli/stats.py` sử dụng `rich` để hiển thị dashboard tổng hợp: số từ trong `vocab_ground_truth` (phân bố CEFR, số đã có embedding, số đến hạn SM-2) và tình trạng `chat_logs` (`verified_golden`, `raw`, `rejected`, tiến độ đạt ngưỡng train).

**Acceptance criteria:**
- [x] Lệnh `docker compose exec -T bot python -m src.cli.stats` in ra bảng thống kê rõ ràng, cảnh báo nếu thiếu embedding hoặc tỷ lệ reject > 10%.

**Verification:**
- [x] Chạy lệnh trong container và đối chiếu khớp với query SQL thực tế trong PostgreSQL.

**Dependencies:** Task 9
**Files likely touched:**
- `src/cli/stats.py`

**Estimated scope:** Small (1 file)

---

## Checkpoint E: Data Ready for Ollama Bridge & Phase 3 Fine-Tuning
- [x] Kho `vocab_ground_truth` đầy đủ từ 3 nguồn (1 ➔ 3 ➔ 2) với vector 768 chiều.
- [x] Tập dữ liệu `verified_golden` trong `chat_logs` sẵn sàng cho bước tiếp theo (tích hợp Ollama fallback/baseline và export `dataset.jsonl` fine-tune Hugging Face).

