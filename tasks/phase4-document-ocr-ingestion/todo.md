# Task List: Phase 4 — Module Bóc Tách OCR Tài Liệu & Nhận Diện Đa Phương Thức Thông Minh

## Phase 1: Nền Tảng Trích Xuất Văn Bản & Hybrid OCR Engine

### Task 1: Unified Document Parser (`DocumentParserService`)
**Description:** Xây dựng service phân tích văn bản tài liệu thống nhất bằng `PyMuPDF` (`fitz`), thay thế thư viện cũ `pypdf`. Service có khả năng xử lý cả Digital PDF (trích xuất văn bản số tức thì, giữ cấu trúc đoạn văn, loại bỏ số trang và header lặp lại) lẫn Scanned PDF (tự động nhận diện trang không có văn bản và render trang đó thành ảnh PNG bitmap để phục vụ OCR).

**Acceptance criteria:**
- [ ] Trích xuất văn bản số từ các trang Digital PDF với tốc độ dưới 100ms/trang.
- [ ] Nhận diện chính xác trang Scanned PDF (`len(text.strip()) < 50`) và trả về danh sách ảnh bitmap tương ứng.
- [ ] Giới hạn xử lý tối đa `max_pdf_pages` (mặc định 15 trang) để bảo vệ tài nguyên hệ thống và tránh tràn RAM.
- [ ] Tách đoạn và gộp văn bản thành các chunks có kích thước bounded ($\le 4000$ ký tự) không bị đứt câu.

**Verification:**
- [ ] Tests pass: `docker compose exec -T bot pytest tests/test_document_parser.py -v`
- [ ] Build succeeds: `docker compose exec -T bot python -c "import fitz; from src.services.document_parser import DocumentParserService; print('PyMuPDF OK')"`
- [ ] Manual check: Đọc thử 1 file PDF text-native và 1 file PDF scan mẫu, in ra số chunks và số trang scan phát hiện được.

**Dependencies:** None
**Files likely touched:**
- `requirements.txt`
- `src/services/document_parser.py`
- `tests/test_document_parser.py`

**Estimated scope:** Medium (3 files)

---

### Task 2: Hybrid OCR Engine (`OCREngineService`)
**Description:** Xây dựng module nhận diện ký tự quang học đa tầng kết hợp giữa Local Fast OCR (`rapidocr_onnxruntime`) và Cloud Multimodal Vision (`Gemini Flash`). Local OCR chạy hoàn toàn offline trên CPU/GPU của máy, đảm bảo 0 chi phí và không phụ thuộc internet; nếu chất lượng nhận diện văn bản dưới ngưỡng hoặc ảnh quá mờ, engine tự động fallback sang Gemini Vision.

**Acceptance criteria:**
- [ ] Tích hợp `rapidocr_onnxruntime` nhận diện văn bản tiếng Anh và tiếng Việt từ mảng byte ảnh JPEG/PNG.
- [ ] Hỗ trợ cấu hình `OCR_PROVIDER` trong `.env` (`hybrid`, `local`, `gemini`).
- [ ] Cơ chế Fallback thông minh: Nếu Local OCR trả về rỗng hoặc dưới 10 từ khi có cấu hình `hybrid`, tự động gọi Gemini Vision để trích xuất.
- [ ] Chuẩn hóa output trả về định dạng văn bản thô kèm danh sách các khối chữ (text blocks).

**Verification:**
- [ ] Tests pass: `docker compose exec -T bot pytest tests/test_ocr_engine.py -v`
- [ ] Build succeeds: `docker compose exec -T bot python -c "from src.services.ai.ocr_engine import OCREngineService; print('OCR Engine OK')"`
- [ ] Manual check: Chạy OCR trên 1 ảnh chụp bài tập tiếng Anh mẫu, xác nhận nhận diện đúng trên 90% từ vựng.

**Dependencies:** Task 1
**Files likely touched:**
- `requirements.txt`
- `src/core/config.py`
- `.env.example`
- `src/services/ai/ocr_engine.py`
- `tests/test_ocr_engine.py`

**Estimated scope:** Medium (4 files)

---

## Checkpoint 1: Nền Tảng Trích Xuất Văn Bản Thô Đã Hoàn Thành
- [ ] Đọc và phân tách trơn tru cả Digital PDF, Scanned PDF và Ảnh chụp.
- [ ] Local OCR hoạt động ổn định trong môi trường Docker, không tốn quota API.
- [ ] Toàn bộ unit tests của Task 1 và Task 2 đều đạt trạng thái `PASSED`.

---

## Phase 2: Bóc Tách Tri Thức Kép & Lưu Trữ PostgreSQL

### Task 3: Dual Knowledge Extractor (`DocumentKnowledgeExtractor`)
**Description:** Nâng cấp tầng trích xuất tri thức từ văn bản sau OCR/Parser. Thay vì chỉ bóc tách từ vựng, extractor mới sử dụng LLM (ưu tiên Host Ollama `qwen2.5:3b`, fallback Gemini) với schema `DocumentKnowledgeBatch` để bóc tách song song cả Từ vựng (CEFR B1-C2, phiên âm IPA, giải nghĩa song ngữ, quiz SM-2) và Cấu trúc ngữ pháp (tên công thức, cấp độ CEFR, ý nghĩa tiếng Việt, câu ví dụ mẫu).

**Acceptance criteria:**
- [ ] Định nghĩa Pydantic schema `DocumentKnowledgeBatch` chứa `vocab_items: List[VocabSchema]` và `grammar_items: List[GrammarSchema]`.
- [ ] Prompt chuyên gia bóc tách phân biệt rõ từ vựng học thuật và cấu trúc câu đặc biệt (câu điều kiện đảo ngữ, câu chẻ, mệnh đề quan hệ rút gọn...).
- [ ] Hỗ trợ suy luận có cấu trúc (Structured Outputs) với cả Ollama Local LLM và Gemini API.
- [ ] Xử lý gộp kết quả qua nhiều chunks văn bản mà không bị trùng lặp từ vựng hoặc công thức trong cùng một tài liệu.

**Verification:**
- [ ] Tests pass: `docker compose exec -T bot pytest tests/test_document_knowledge_extractor.py -v`
- [ ] Manual check: Truyền vào 1 đoạn văn tiếng Anh học thuật có chứa cả từ khó và cấu trúc đảo ngữ, xác nhận JSON trả về có đủ cả `vocab_items` và `grammar_items`.

**Dependencies:** Task 2
**Files likely touched:**
- `src/schemas/document.py`
- `src/services/ai/document_extractor.py`
- `tests/test_document_knowledge_extractor.py`

**Estimated scope:** Medium (3 files)

---

### Task 4: Quality Gate, Content Sanitizer & Grammar Ingestion Service
**Description:** Xây dựng bộ lọc làm sạch rác OCR (`DocumentSanitizer`) để loại trừ các từ rác (dưới 2 ký tự, số trang, ISBN, tiêu đề lặp lại). Đồng thời hoàn thiện `GrammarIngestionService` để nạp các cấu trúc ngữ pháp trích xuất từ tài liệu vào bảng `grammar_ground_truth`, tự động tính toán vector 768 chiều `nomic-embed-text` và gán nhãn `source='document_ocr'`, `status='verified'`.

**Acceptance criteria:**
- [ ] `DocumentSanitizer` lọc sạch 100% các chuỗi rác OCR (từ chứa số, ký tự đặc biệt vô nghĩa, từ viết tắt số trang như 'p.12').
- [ ] `GrammarIngestionService` tự động deduplicate công thức theo `pattern_key` và nạp vào bảng `grammar_ground_truth`.
- [ ] Tính toán nhúng vector 768 chiều cho toàn bộ từ vựng và ngữ pháp mới bằng `EmbeddingService`.
- [ ] Lưu trữ đầy đủ metadata provenance (`source='document_ocr'`, `telegram_user_id`).

**Verification:**
- [ ] Tests pass: `docker compose exec -T bot pytest tests/test_dual_ingestion.py -v`
- [ ] Manual check: Kiểm tra truy vấn cơ sở dữ liệu PostgreSQL thật, xác nhận các dòng mới xuất hiện với `embedding IS NOT NULL` và `status = 'verified'`.

**Dependencies:** Task 3
**Files likely touched:**
- `src/services/document_sanitizer.py`
- `src/services/grammar_ingestion_service.py`
- `src/services/vocab_ingestion_service.py`
- `tests/test_dual_ingestion.py`

**Estimated scope:** Medium (4 files)

---

## Checkpoint 2: Trích Xuất Kép & Nạp Dữ Liệu PostgreSQL Thành Công
- [ ] Đã nạp thành công đồng thời cả từ vựng và ngữ pháp từ tài liệu vào cơ sở dữ liệu thật.
- [ ] Dữ liệu được nhúng vector 768 chiều `nomic-embed-text` chuẩn hóa, không bị ô nhiễm bởi rác OCR.
- [ ] Toàn bộ unit tests của Task 3 và Task 4 đều đạt trạng thái `PASSED`.

---

## Phase 3: Tích Hợp Telegram Progressive UX & Quản Trị Dữ Liệu

### Task 5: Async Media Handlers & Live Progress Editing trên Telegram
**Description:** Nâng cấp các handlers tiếp nhận file ảnh (`handle_photo_message`) và file tài liệu (`handle_pdf_document`) trong `src/bot/handlers/media_handlers.py`. Chuyển sang cơ chế bất đồng bộ non-blocking với Telegram Dynamic Message Editing: gửi tin nhắn ban đầu và cập nhật tiến độ theo từng bước (`[1/3] Đang đọc file` ➔ `[2/3] Bóc tách AI` ➔ `[3/3] Lưu DB & Lên lịch`), kết thúc bằng bảng tóm tắt kèm Inline Buttons tương tác ôn tập.

**Acceptance criteria:**
- [ ] Giữ Redis lock cho user để ngăn chặn việc spam gửi liên tục nhiều file nặng cùng lúc.
- [ ] Cập nhật tin nhắn tiến độ mượt mà, có cơ chế throttle tối thiểu 1.5s giữa các lần edit để không bị dính Telegram Rate Limit.
- [ ] Tin nhắn tổng kết hiển thị rõ số từ vựng mới, số cấu trúc ngữ pháp mới, danh sách xem trước, và các nút bấm Inline Keyboard (`🎯 Ôn tập ngay`, `📖 Xem ngữ pháp`).
- [ ] Bắt lỗi exception an toàn, thông báo lỗi thân thiện cho người dùng nếu file bị hỏng hoặc mật khẩu bảo vệ.

**Verification:**
- [ ] Tests pass: `docker compose exec -T bot pytest tests/test_media_handlers.py -v`
- [ ] Manual check: Gửi 1 file PDF scan qua Telegram bot thật, quan sát tin nhắn tiến độ thay đổi theo thời gian thực và nhận báo cáo hoàn tất.

**Dependencies:** Task 4
**Files likely touched:**
- `src/bot/handlers/media_handlers.py`
- `src/bot/app.py`
- `tests/test_media_handlers.py`

**Estimated scope:** Medium (3 files)

---

### Task 6: Mở Rộng Admin Review CLI & Toàn Bộ Test Suite
**Description:** Nâng cấp công cụ dòng lệnh quản trị `src/cli/admin_review.py` để hỗ trợ lọc và kiểm duyệt riêng các bản ghi có nguồn gốc từ tài liệu OCR (`--source ocr` / `--source document_ocr`). Viết bộ test tích hợp toàn diện End-to-End đảm bảo toàn bộ hệ thống từ nhận file đến RAG search hoạt động trơn tru.

**Acceptance criteria:**
- [ ] CLI `admin_review.py` hỗ trợ cờ `--source` để lọc danh sách kiểm duyệt theo nguồn thu thập (`ocr`, `chat`, `seed`).
- [ ] Toàn bộ 40+ tests tự động trong toàn bộ dự án chạy thành công trong môi trường Docker.
- [ ] Cập nhật tài liệu hướng dẫn sử dụng tính năng gửi tài liệu học trong tin nhắn lệnh `/help`.

**Verification:**
- [ ] Tests pass: `docker compose exec -T bot pytest -v` (toàn bộ test suite xanh 100%)
- [ ] CLI check: `docker compose exec -T bot python -m src.cli.admin_review --list pending --source ocr`

**Dependencies:** Task 5
**Files likely touched:**
- `src/cli/admin_review.py`
- `tests/test_e2e_ocr_pipeline.py`
- `src/bot/handlers/command_handlers.py`

**Estimated scope:** Small to Medium (3 files)

---

## Checkpoint 3: Hoàn Tất Phase 4 & Sẵn Sàng Vận Hành Thực Tế
- [ ] Toàn bộ 6 tasks đều đã được triển khai, kiểm thử và xác nhận bằng log thực tế.
- [ ] Bot Telegram xử lý mượt mà tài liệu ảnh chụp và PDF scan của người dùng.
- [ ] Toàn bộ test suite chạy thành công không có lỗi hồi quy.

