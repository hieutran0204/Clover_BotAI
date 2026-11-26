# Implementation Plan: Module Bóc Tách OCR Tài Liệu & Nhận Diện Đa Phương Thức (Phase 4)

## Overview
Xây dựng pipeline xử lý tài liệu học tập đa định dạng (ảnh chụp trang sách, ghi chú viết tay, PDF số và PDF scan) với cơ chế Hybrid OCR (Local Fast OCR qua RapidOCR + Cloud Vision qua Gemini Flash). Pipeline giải quyết triệt để lỗi không đọc được PDF scan, bóc tách đồng thời cả **Từ vựng (Vocabulary)** và **Cấu trúc ngữ pháp (Grammar Patterns)**, nhúng vector 768 chiều `nomic-embed-text` nạp vào PostgreSQL, đồng thời cung cấp giao diện cập nhật tiến độ trực tiếp (Live Progress Editing) trên Telegram mà không làm đơ bot.

---

## Architecture Decisions

### Decision 1: Sử dụng PyMuPDF (`fitz`) thay cho `pypdf`
* **Vấn đề:** `pypdf` ném exception khi gặp scanned PDF và trích xuất text số rất chậm, dễ làm đứt gãy layout nhiều cột (multi-column) trong giáo trình tiếng Anh.
* **Giải pháp:** Sử dụng `PyMuPDF` (`fitz`). Thư viện C-core này đọc file cực nhanh, giữ cấu trúc khối văn bản, và hỗ trợ xuất trang scan thành `Pixmap` (ảnh PNG/JPEG) ngay lập tức để chuyển sang bộ OCR.

### Decision 2: Hybrid OCR Engine (Local-First với RapidOCR + Cloud-Fallback với Gemini)
* **Vấn đề:** Phụ thuộc 100% vào Cloud Gemini Vision dẫn tới nguy cơ chạm trần quota Free Tier (20 req/ngày), làm bot bị tê liệt khi người dùng gửi tài liệu dài. Cài đặt Tesseract OCR trong Docker container lại cồng kềnh (yêu cầu cài đặt các gói hệ điều hành và tệp ngôn ngữ nặng).
* **Giải pháp:** Tích hợp `rapidocr_onnxruntime`. Thư viện này chạy trực tiếp trên Python ONNX runtime (CPU/GPU), không yêu cầu cài đặt binary phức tạp vào hệ điều hành, hỗ trợ nhận diện cả tiếng Anh và tiếng Việt với độ chính xác cao và tốc độ ~300ms/trang. Khi gặp ảnh mờ hoặc chữ viết tay phức tạp, hệ thống tự động fallback sang Gemini Flash.

### Decision 3: Dual Knowledge Extraction (Trích xuất kép Từ Vựng & Cấu Trúc Ngữ Pháp)
* **Vấn đề:** Hiện tại `VisionExtractorService` chỉ bóc tách từ vựng đơn lẻ, bỏ qua các cấu trúc ngữ pháp học thuật quan trọng (đảo ngữ, câu chẻ, mệnh đề quan hệ rút gọn, v.v.).
* **Giải pháp:** Thiết kế schema Pydantic `DocumentKnowledgeBatch` gồm `vocab_items: List[VocabSchema]` và `grammar_items: List[GrammarSchema]`. Sử dụng LLM phân tích văn bản để bóc tách song song cả hai dạng tri thức và lưu vào `vocab_ground_truth` lẫn `grammar_ground_truth`.

### Decision 4: Telegram Progressive UX (Live Dynamic Message Editing)
* **Vấn đề:** Xử lý tài liệu 10–15 trang có thể mất 20–45 giây. Nếu giữ kết nối đồng bộ, Telegram webhook/polling sẽ bị nghẽn và người dùng tưởng bot bị treo.
* **Giải pháp:** Xử lý qua tác vụ bất đồng bộ (`asyncio.create_task`) có gắn Redis user lock. Bot phản hồi ngay 1 tin nhắn tiến độ và liên tục cập nhật trạng thái `[1/3] Đang OCR` ➔ `[2/3] Phân tích AI` ➔ `[3/3] Lưu DB & Lên lịch SM-2`.

---

## Task List

### Phase 1: Nền Tảng Trích Xuất Văn Bản & Hybrid OCR Engine
- [ ] **Task 1: Unified Document Parser (`DocumentParserService`)** — Tách văn bản PDF số, phân loại Scanned PDF, và xuất ảnh bitmap trang scan qua PyMuPDF (`fitz`).
- [ ] **Task 2: Hybrid OCR Engine (`OCREngineService`)** — Tích hợp RapidOCR ONNX Local kết hợp Cloud Gemini Multimodal Fallback.
- [ ] **Checkpoint 1: Kiểm Thử Trích Xuất Văn Bản Thô & OCR Độc Lập** — Đảm bảo trích xuất text sạch từ ảnh chụp, PDF số và PDF scan mà không văng lỗi.

### Phase 2: Bóc Tách Tri Thức Kép & Lưu Trữ PostgreSQL
- [ ] **Task 3: Dual Knowledge Extractor (`DocumentKnowledgeExtractor`)** — Trích xuất đồng thời VocabSchema và GrammarSchema từ văn bản tài liệu bằng LLM.
- [ ] **Task 4: Quality Gate, Content Sanitizer & Grammar Ingestion Service** — Làm sạch rác OCR, nạp đồng thời vào `vocab_ground_truth` và `grammar_ground_truth` với vector 768-dim.
- [ ] **Checkpoint 2: Kiểm Thử Bóc Tách & Nạp Dữ Liệu PostgreSQL** — Xác nhận bản ghi xuất hiện chính xác trong cả 2 bảng cơ sở dữ liệu với vector 768 chiều và `status='verified'` / `source='document_ocr'`.

### Phase 3: Tích Hợp Telegram Progressive UX & Quản Trị Dữ Liệu
- [ ] **Task 5: Async Media Handlers & Live Progress Editing trên Telegram** — Cập nhật `handle_photo_message` và `handle_pdf_document` theo dõi tiến độ thời gian thực và cung cấp inline buttons.
- [ ] **Task 6: Mở Rộng Admin Review CLI & Bộ Test Tự Động Toàn Diện** — Thêm bộ lọc `--source ocr` trong `admin_review.py` và viết bộ unit/integration tests cho toàn bộ pipeline OCR.
- [ ] **Checkpoint 3: Hoàn Tất Triển Khai Thực Tế & Kiểm Thử End-to-End** — Chạy thử nghiệm thực tế trên bot Telegram với ảnh trang sách và file PDF scan thật.

---

## Risks and Mitigations

| Rủi ro kỹ thuật | Mức độ | Chiến lược kiểm soát & Giảm thiểu |
| :--- | :---: | :--- |
| **PDF quá dài (50–100 trang) làm cạn kiệt RAM/CPU** | Cao | Giới hạn cứng `max_pdf_pages = 15` trang đầu tiên đối với tài liệu dài, log cảnh báo rõ ràng cho người dùng trong báo cáo. |
| **Ký tự OCR bị méo mó, sinh từ vựng rác hoặc ảo giác** | Trung bình | Bộ lọc `DocumentSanitizer` kiểm tra độ dài từ ($\ge 2$), loại bỏ số/ký tự đặc biệt, đối chiếu kiểm tra định dạng IPA và CEFR trước khi ghi DB. |
| **Telegram Rate Limit khi edit message tiến độ quá nhanh** | Trung bình | Đặt khoảng cách cập nhật tối thiểu giữa các lần edit message $\ge 1.5$ giây, bọc khối `try...except telegram.error.RetryAfter`. |
| **Ảnh chụp quá mờ khiến Local OCR trả về văn bản rỗng** | Thấp | Tự động kích hoạt cơ chế Fallback gọi Gemini Vision Teacher nếu Local OCR trả về dưới 10 từ. |

---

## Open Questions & Alignment
1. **Định dạng file bổ sung:** Hiện tại bot ưu tiên xử lý Ảnh (`.jpg`, `.png`, `.webp`) và `.pdf`. Có cần hỗ trợ thêm tài liệu Word (`.docx`) hay `.txt` thuần túy không?
2. **Quyền riêng tư kho từ vựng từ tài liệu:** Từ vựng trích xuất từ tài liệu của người dùng nên được nạp vào kho cá nhân của user (`telegram_user_id = user_id`) hay tự động đóng góp vào Global Seed nếu là từ vựng phổ thông? (Hiện tại: nạp vào kho cá nhân của user, gán `source='document_ocr'`).

