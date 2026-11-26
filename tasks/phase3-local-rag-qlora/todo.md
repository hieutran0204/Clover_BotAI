# Task Breakdown: Phase 3 — DB-First AI Agent, /vocab & /grammar, Local RAG & QLoRA
**Phiên bản:** v2.1 — Cập nhật Postgres FTS, Reranker Threshold, Context-Injected Security, và Bộ lọc Fine-Tuning chuẩn.
**Luật kiểm chứng:** Mọi task tích hợp đều phải kiểm tra trên **PostgreSQL thật** và **Host Ollama thật (`http://host.docker.internal:11434`)**.

--------------------------------------------------------------------------------

### Stage 1: Hardening Code Review & Kết Nối Host Ollama
#### Task 1: Sửa lỗi Required & Dọn Dead Code
* [x] Thống nhất `AIChatService._to_sharegpt_turns` xuất chuẩn ChatML (`role` / `content`).
* [x] Sửa `VocabService.get_due_vocab_items` lọc `VocabGroundTruth.telegram_user_id.is_not(None)`.
* [x] Gỡ retry nhân đôi giữa tenacity và SDK; nâng Redis lock TTL lên 60s cho local LLM.
* [x] Xóa hàm cũ `VocabService.save_vocab_item` (chỉ dùng `VocabIngestionService`).
* [x] Cập nhật `docker-compose.yml` (`extra_hosts: ["host.docker.internal:host-gateway"]`), xác minh container ping được Host Ollama.

--------------------------------------------------------------------------------

### Stage 2: Schema Mới, Postgres Full-Text Search & Local Embedding
#### Task 2: Migration 002 — Governance Fields, Postgres FTS & Bảng Mới
* [x] Tạo `migrations/versions/002_phase3_schema.py`:
    * Cập nhật `vocab_ground_truth`: Thêm `source`, `status`, `usage_count`, `report_count`, `embedding_model`.
    * Backfill: `UPDATE vocab_ground_truth SET source='global_seed', status='verified' WHERE source IS NULL`.
    * Thêm PostgreSQL FTS: Tạo index GIN trên `to_tsvector('english', word || ' ' || COALESCE(definition_vi, ''))` và bật extension `pg_trgm`.
    * Thêm HNSW cosine index cho cột `embedding Vector(768)`.
    * Tạo bảng `grammar_ground_truth` (đầy đủ các trường ngữ pháp + FTS GIN index + Vector(768) HNSW + 5 governance columns).
    * Tạo bảng `user_study_schedules`.
* [x] Cập nhật ORM models trong `src/db/models.py` và Pydantic schemas trong `src/schemas/grammar.py`.
* [x] Tạo `data/seeds/sample_grammar.json` (10–15 công thức ngữ pháp mẫu) và script `src/cli/seed_grammar.py`.

#### Task 3: Chuyển Sang nomic-embed-text & Re-embed DB
* [x] Tạo class `NomicEmbeddingsWrapper` trong `src/services/ai/embedding_service.py` (tự động gắn prefix `search_document:` và `search_query:`).
* [x] Cập nhật `.env`: `EMBEDDING_PROVIDER=ollama`, `OLLAMA_EMBEDDING_MODEL=nomic-embed-text`, `RAG_CANDIDATE_K=15`, `RAG_TOP_K=3`, `RAG_RERANKER_THRESHOLD=0.35`.
* [x] Tạo và chạy `src/cli/reembed_vocab.py` để nhúng lại toàn bộ từ vựng trong DB; kiểm tra xác nhận `embedding_model = 'nomic-embed-text'`.

--------------------------------------------------------------------------------

### Stage 3: Postgres Native Hybrid RAG & 3-Tier AI Agent
#### Task 4: KnowledgeRetriever — Query Rewriting, Postgres FTS + pgvector & Reranker
* [x] Thêm `sentence-transformers>=3.0.0` vào `requirements.txt`.
* [x] Tạo `src/services/ai/rag_retriever.py` (KnowledgeRetriever):
    * **Query Rewriting:** Nhận diện câu hỏi tiếng Việt/câu phức → sinh `english_query` chuẩn + danh sách 2–4 keywords.
    * **Postgres Native Sparse:** Chạy Full-Text Search bằng SQL với `ts_rank`.
    * **pgvector Dense:** Chạy cosine similarity với prefix `search_query:`.
    * **Custom RRF:** Hợp nhất kết quả FTS và Dense trong Python lấy Top-15 candidates.
    * **Cross-Encoder Reranker:** Dùng `ms-marco-MiniLM-L-6-v2` chấm điểm Top-15 → Lấy Top-3.
    * **Threshold Check:** Trả cờ `is_hit = (top1_score >= RAG_RERANKER_THRESHOLD)`.

#### Task 5: StudyAgentService — 3-Tier Router, Dedup & LLM-as-Judge
* [x] Tạo `src/services/ai/agent_service.py`:
    * **Tier 1 (DB HIT trực tiếp):** Top-1 Reranker score cao vượt trội → Trả thẳng từ DB, tag `[📦 DB Ground Truth]`.
    * **Tier 2 (Local Agent + RAG):** Khi `is_hit == True` → Local Ollama (`qwen2.5:3b`) tổng hợp câu trả lời, tag `[🧠 Local Agent • Ollama + RAG]`.
    * **Tier 3 (Teacher Fallback):** Khi `is_hit == False` → Gọi Gemini `MissingKnowledgeBatch`.
        * Dedup Tầng 1: Check `pattern_key` tồn tại.
        * Dedup Tầng 2: Check cosine similarity $\ge 0.92$.
        * LLM-as-Judge Critic Prompt kiểm tra thô.
        * Lưu vào PostgreSQL với `status='pending'` (hoặc `pending_high_confidence`).
        * Tag `[🌐 Teacher Fallback ➔ Đã nạp DB]`.
* [x] Kiểm tra thực tế trên DB: Hỏi cùng 1 từ/công thức 2 lần liên tiếp → Lần 2 bắt buộc hit Tier 1 hoặc Tier 2, **log xác nhận 0 call ra Gemini**.

--------------------------------------------------------------------------------

### Stage 4: Telegram Handlers, Bảo Mật Tool & Admin CLI
#### Task 6: Đăng Ký Lệnh Mới & Context-Injected Tool Calling
* [x] Cập nhật `src/bot/handlers/command_handlers.py`:
    * `/vocab` (alias `/vocal`): Xem lịch ôn SM-2, tra từ vựng DB-First.
    * `/grammar` (alias `/gramma`): Tra công thức ngữ pháp DB-First.
    * `/quiz`: Phát câu trắc nghiệm SM-2 ngay lập tức.
    * `/report`: Gắn cờ bản ghi sai → auto `status='quarantined'`, tăng `report_count`.
* [x] **Bảo mật Tool Calling:** Sửa schema các tool — bỏ tham số `user_id`, inject `telegram_user_id` từ `Update.effective_user.id` phía backend handler.
* [x] Tạo `src/bot/jobs/vocab_jobs.py`: Đọc `user_study_schedules` hàng ngày để tự động cấp từ mới từ Global Seed vào lịch học của user.
* [x] Đăng ký lệnh với Telegram menu qua `bot.set_my_commands` trong `_post_init`.

#### Task 7: Admin Review CLI
* [x] Tạo `src/cli/admin_review.py`:
    * `--list quarantined` / `--list pending`: Liệt kê các bản ghi cần kiểm duyệt.
    * `--accept <id>`: Đổi status sang `'verified'`.
    * `--reject <id>`: Đổi status sang `'rejected'`.
    * `--edit <id> --field <col> --value <val>`: Chỉnh sửa nội dung rồi chuyển `'verified'`.

--------------------------------------------------------------------------------

### Stage 5: Đánh Giá Benchmark & QLoRA Fine-Tuning
#### Task 8: Benchmark 65 Câu (Hit Rate@3 & False-Hit Rate)
* [x] Tạo `datasets/eval_benchmark.json` gồm 50 câu Positive + 15 câu Negative (should-miss).
* [x] Tạo `src/cli/eval_rag.py`:
    * Đo `Hit Rate@3` (Mục tiêu $\ge 80\%$).
    * Đo `False-Hit Rate` (Mục tiêu $< 5\%$).
    * Nếu False-Hit Rate cao → tăng `RAG_RERANKER_THRESHOLD` lên (ví dụ từ 0.35 lên 0.45).

#### Task 9: Export Dataset Chuẩn & QLoRA Fine-Tuning
* [x] Tạo `src/cli/export_dataset.py`:
    * **Bộ lọc nghiêm ngặt:** Chỉ trích xuất các bản ghi có `status = 'verified'` (loại bỏ hoàn toàn bản ghi `pending`).
    * Xuất `datasets/train.jsonl` (90%) và `datasets/eval.jsonl` (10%).
* [x] Tạo `src/training/train_qlora.py` tối ưu 4-bit NF4 trên RTX 3050 4GB VRAM cho `Qwen2.5-3B-Instruct`.
* [x] Tạo `src/training/eval_student.py` so sánh model gốc và model sau train.
* [x] Tạo script đóng gói GGUF Q4_K_M và nạp vào Ollama (`ollama create english-tutor:v1`).
