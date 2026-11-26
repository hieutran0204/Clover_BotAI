/**
 * name: admin.js
 * description: Client-side interactive handlers for AI-Telegram Admin Dashboard.
 */

document.addEventListener("DOMContentLoaded", () => {
  // 1. Select all checkboxes for batch operations
  const selectAll = document.getElementById("selectAll");
  if (selectAll) {
    const itemCheckboxes = document.querySelectorAll(".item-checkbox");
    selectAll.addEventListener("change", (e) => {
      itemCheckboxes.forEach((cb) => {
        cb.checked = e.target.checked;
      });
      updateBatchToolbar();
    });

    itemCheckboxes.forEach((cb) => {
      cb.addEventListener("change", updateBatchToolbar);
    });
  }

  function updateBatchToolbar() {
    const selectedCount = document.querySelectorAll(".item-checkbox:checked").length;
    const batchToolbar = document.getElementById("batchToolbar");
    const selectedCountEl = document.getElementById("selectedCount");
    if (batchToolbar) {
      if (selectedCount > 0) {
        batchToolbar.classList.remove("d-none");
        if (selectedCountEl) selectedCountEl.textContent = selectedCount;
      } else {
        batchToolbar.classList.add("d-none");
      }
    }
  }

  // 2. Export dataset button trigger with loader
  const exportBtn = document.getElementById("btnExportDataset");
  if (exportBtn) {
    exportBtn.addEventListener("click", async () => {
      const originalHtml = exportBtn.innerHTML;
      exportBtn.disabled = true;
      exportBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Đang trích xuất...`;
      try {
        const resp = await fetch("/api/export-dataset", { method: "POST" });
        const data = await resp.json();
        if (resp.ok && data.status === "success") {
          alert(`Đã xuất dữ liệu thành công!\nTrain: ${data.train_samples} mẫu\nEval: ${data.eval_samples} mẫu\nĐang bắt đầu tải train.jsonl...`);
          window.location.href = "/api/download-dataset/train.jsonl";
        } else {
          alert("Lỗi khi xuất dataset: " + (data.detail || data.message || "Unknown error"));
        }
      } catch (err) {
        alert("Lỗi kết nối tới máy chủ: " + err.message);
      } finally {
        exportBtn.disabled = false;
        exportBtn.innerHTML = originalHtml;
      }
    });
  }
});

