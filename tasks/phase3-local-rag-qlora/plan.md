# Kế Hoạch Thực Hiện: Phase 3 — DB-First AI Agent + Local Ollama + Hybrid RAG + QLoRA
**Phiên bản:** v2.1 — Tích hợp Postgres FTS, Ngưỡng Reranker, Context-Injected Tool, và Bộ lọc Fine-tuning nghiêm ngặt.
**Nguyên tắc thực thi:** Kiểm chứng trực tiếp trên **PostgreSQL thật** và **Host Ollama thật (`http://host.docker.internal:11434`)** — không dùng mock.

--------------------------------------------------------------------------------

### Step-by-Step Roadmap

#### Bước 1: Hardening Code Review & Kết Nối Host Ollama
* Sửa 3 điểm Required từ Code Review:
    1. Thống nhất `chat_logs.turns_json` về chuẩn **ChatML** (`{"role": "user"|"assistant"|"system", "content": "..."}`).
    2. Lọc `telegram_user_id IS NOT NULL` trong `VocabService.get_due_vocab_items`.
    3. Gỡ retry chồng chéo giữa tenacity và SDK, nâng Redis lock TTL lên 60s cho local LLM.
* Dọn dẹp dead code: Xóa `VocabService.save_vocab_item` cũ, ép mọi đường nạp từ phải qua `VocabIngestionService` có embedding 768 chiều.
* Cập nhật `docker-compose.yml` (`extra_hosts: ["host.docker.internal:host-gateway"]`) để container bot kết nối ổn định tới Host Ollama.

#### Bước 2: Schema Mới, Postgres Full-Text Search & Local Embedding
* Tạo Alembic migration 002:
    * Thêm 5 Data Governance columns (`source`, `status`, `usage_count`, `report_count`, `embedding_model`) vào `vocab_ground_truth`.
    * Backfill dữ liệu seed cũ thành `source='global_seed'`, `status='verified'`.
    * Cài đặt PostgreSQL FTS: Thêm chỉ mục GIN cho `to_tsvector('english', ...)` và extension `pg_trgm` cho cả `vocab_ground_truth` và `grammar_ground_truth`.
    * Tạo bảng `grammar_ground_truth` (Vector 768 chiều + HNSW index + 5 Governance columns).
    * Tạo bảng `user_study_schedules`.
* Cấu hình `EMBEDDING_PROVIDER=ollama` (`nomic-embed-text`) với `NomicEmbeddingsWrapper` (tự động gắn `search_document:` khi insert và `search_query:` khi query).
* Viết và chạy `src/cli/reembed_vocab.py` nhúng lại toàn bộ từ vựng hiện có trong DB sang chuẩn vector Nomic 768 chiều.
* Tạo Grammar Seed (`data/seeds/sample_grammar.json`) và nạp vào DB bằng `seed_grammar.py`.

#### Bước 3: Postgres Native Hybrid RAG & 3-Tier Agent Router
##### 3a. KnowledgeRetriever (Postgres FTS + pgvector Dense + Reranker)
Xây dựng `src/services/ai/rag_retriever.py`:
1. **Query Rewriting:** Dùng Local LLM (hoặc Gemini Flash) nhận diện tiếng Việt, dịch sang câu truy vấn tiếng Anh chuẩn và trích xuất 2–4 từ khóa độc lập.
2. **Postgres Native Hybrid Search:**
   * Sparse: Chạy truy vấn FTS SQL (`ts_rank` + `tsvector`).
   * Dense: Chạy pgvector Cosine Distance (`<=>`).
   * Hợp nhất bằng RRF trong Python lấy Top `RAG_CANDIDATE_K = 15`.
3. **Cross-Encoder Reranker + Threshold Gate:**
   * Dùng `ms-marco-MiniLM-L-6-v2` hoặc `bge-reranker-base` chấm điểm Top-15.
   * Lấy Top-3. Nếu `top1_score < RAG_RERANKER_THRESHOLD (0.35)` → Phân loại là **MISS**; ngược lại là **HIT**.

##### 3b. StudyAgentService (3-Tier Router)
Xây dựng `src/services/ai/agent_service.py`:
* **Tier 1 (DB HIT trực tiếp):** Top-1 score cao vượt trội → Trả thẳng từ DB kèm tag `[📦 DB Ground Truth]`.
* **Tier 2 (Local Agent + RAG):** Context DB đủ → Local Ollama (`qwen2.5:3b`) tổng hợp giải thích kèm tag `[🧠 Local Agent • Ollama + RAG]`.
* **Tier 3 (External Teacher Fallback):**
  * Reranker báo MISS → Gọi Gemini lấy `MissingKnowledgeBatch`.
  * Dedup 2 tầng (Pattern Hash + Semantic Cosine $\ge 0.92$).
  * LLM-as-Judge lọc lỗi thô → Ghi vào DB với `status='pending'`.
  * Trả lời user kèm tag `[🌐 Teacher Fallback ➔ Đã nạp DB]`.

#### Bước 4: Telegram Commands, Context-Injected Tools & Admin CLI
* Đăng ký CommandHandler:
  * `/vocab` (alias `/vocal`): Quản lý lịch SM-2, tra từ vựng.
  * `/grammar` (alias `/gramma`): Tra công thức ngữ pháp.
  * `/quiz`: Phát câu hỏi SM-2 tức thì.
  * `/report`: Gắn cờ bản ghi sai → đổi sang `quarantined`, tăng `report_count`.
* **Tool Calling Security:** Inject `telegram_user_id` từ Telegram context vào tool backend; không cho phép LLM truyền tham số này.
* Thêm Job Scheduler trong JobQueue: Quét `user_study_schedules` hàng ngày để tự động cấp từ mới từ Global Seed vào lịch học cá nhân.
* Tạo `src/cli/admin_review.py`: Hiển thị danh sách bản ghi `quarantined` và `pending` để admin bấm Accept / Reject / Edit.

#### Bước 5: Đánh Giá Benchmark & QLoRA Fine-Tuning
* Tạo `datasets/eval_benchmark.json` gồm 50 câu Positive + 15 câu Negative (should-miss).
* Đo `Hit Rate@3 >= 80%` và `False-Hit Rate < 5%`.
* Tạo `src/cli/export_dataset.py`: **Chỉ export các bản ghi có `status='verified'`** sang `train.jsonl` (90%) và `eval.jsonl` (10%).
* Viết script train `src/training/train_qlora.py` tối ưu 4-bit NF4 trên RTX 3050 4GB VRAM cho `Qwen2.5-3B-Instruct`, chuyển đổi GGUF Q4_K_M và nạp vào Ollama thành model `english-tutor:v1`.

--------------------------------------------------------------------------------

### Rủi Ro & Giải Pháp Kỹ Thuật
| Rủi ro | Hậu quả nếu bỏ qua | Giải pháp ngăn chặn |
| :--- | :--- | :--- |
| **Reranker không có ngưỡng** | Câu hỏi không liên quan vẫn lấy Top-3 rác để trả lời | Đặt cứng `RAG_RERANKER_THRESHOLD = 0.35`, dưới ngưỡng bắt buộc rơi xuống Tier 3 |
| **User hỏi Tiếng Việt làm lệch Vector** | Nomic v1 và Reranker tiếng Anh hiểu sai ngữ nghĩa | Bước Query Rewriting luôn dịch sang câu tiếng Anh chuẩn trước khi search |
| **BM25 in-memory bị lệch dữ liệu** | Bản ghi mới nạp vào DB không tìm thấy bằng từ khóa | Dùng trực tiếp PostgreSQL Full-Text Search (tsvector + GIN index) |
| **Model 3B điền sai user_id trong tool** | Ghi đè lịch học của tài khoản khác | Inject `telegram_user_id` từ Telegram context, ẩn khỏi schema của model |
| **Data Poisoning lọt vào tập train** | Mô hình Student học vẹt kiến thức sai của Teacher | Tập train chỉ lấy `status='verified'`, loại bỏ hoàn toàn việc auto-train bản ghi pending |
