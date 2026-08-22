(() => {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const browseBtn = document.getElementById("browseBtn");
  const dzIdle = document.getElementById("dzIdle");
  const dzFile = document.getElementById("dzFile");
  const fileNameEl = document.getElementById("fileName");
  const fileIconEl = document.getElementById("fileIcon");
  const fileClearBtn = document.getElementById("fileClear");
  const lenOpts = Array.from(document.querySelectorAll(".len-opt"));
  const runBtn = document.getElementById("runBtn");
  const runLabel = runBtn.querySelector(".run-label");
  const scanbar = document.getElementById("scanbar");
  const errorMsg = document.getElementById("errorMsg");

  const resultsSection = document.getElementById("results");
  const resFilename = document.getElementById("resFilename");
  const resMethod = document.getElementById("resMethod");
  const resStats = document.getElementById("resStats");
  const resSummary = document.getElementById("resSummary");
  const resKeyPoints = document.getElementById("resKeyPoints");
  const resSuggestions = document.getElementById("resSuggestions");
  const resRawText = document.getElementById("resRawText");
  const resetBtn = document.getElementById("resetBtn");

  const MAX_BYTES = 15 * 1024 * 1024;
  const ACCEPTED_EXT = ["pdf", "png", "jpg", "jpeg", "bmp", "tiff", "tif", "webp"];

  let selectedFile = null;
  let selectedLength = "medium";
  let isProcessing = false;

  function extOf(name) {
    const parts = name.split(".");
    return parts.length > 1 ? parts.pop().toLowerCase() : "";
  }

  function showError(msg) {
    errorMsg.textContent = msg;
    errorMsg.hidden = false;
  }

  function clearError() {
    errorMsg.hidden = true;
    errorMsg.textContent = "";
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function selectFile(file) {
    clearError();
    const ext = extOf(file.name);

    if (!ACCEPTED_EXT.includes(ext)) {
      showError(`Unsupported file type ".${ext}". Please upload a PDF or an image (PNG, JPG, BMP, TIFF).`);
      return;
    }
    if (file.size > MAX_BYTES) {
      showError(`File is too large (${formatBytes(file.size)}). Maximum size is 15 MB.`);
      return;
    }

    selectedFile = file;
    fileNameEl.textContent = `${file.name} · ${formatBytes(file.size)}`;
    fileIconEl.textContent = ext === "pdf" ? "▤" : "◧";
    dzIdle.hidden = true;
    dzFile.hidden = false;
  }

  function resetDropzone() {
    selectedFile = null;
    fileInput.value = "";
    dzIdle.hidden = false;
    dzFile.hidden = true;
    clearError();
  }

  // --- drag & drop ---
  ["dragenter", "dragover"].forEach(evt => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!isProcessing) dropzone.classList.add("is-dragover");
    });
  });
  ["dragleave", "drop"].forEach(evt => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove("is-dragover");
    });
  });
  dropzone.addEventListener("drop", (e) => {
    if (isProcessing) return;
    const files = e.dataTransfer.files;
    if (files && files.length > 0) selectFile(files[0]);
  });

  // --- file picker ---
  browseBtn.addEventListener("click", () => fileInput.click());
  dzIdle.addEventListener("click", (e) => {
    if (e.target === browseBtn) return;
    fileInput.click();
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length > 0) {
      selectFile(fileInput.files[0]);
    }
  });

  fileClearBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    resetDropzone();
  });

  // --- length picker ---
  lenOpts.forEach(btn => {
    btn.addEventListener("click", () => {
      lenOpts.forEach(b => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      selectedLength = btn.dataset.len;
    });
  });

  // --- run ---
  runBtn.addEventListener("click", async () => {
    if (!selectedFile || isProcessing) return;
    clearError();
    setProcessing(true);

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("length", selectedLength);

    try {
      const resp = await fetch("/api/process", { method: "POST", body: formData });
      const data = await resp.json();

      if (!resp.ok) {
        showError(data.error || "Something went wrong while processing the document.");
        return;
      }
      renderResults(data);
    } catch (err) {
      showError("Could not reach the server. Please check your connection and try again.");
    } finally {
      setProcessing(false);
    }
  });

  function setProcessing(state) {
    isProcessing = state;
    runBtn.disabled = state;
    runLabel.textContent = state ? "Scanning…" : "Summarize";
    scanbar.classList.toggle("is-active", state);
    dropzone.classList.toggle("is-processing", state);
  }

  function renderResults(data) {
    resFilename.textContent = data.filename;
    resMethod.textContent = data.extraction_method === "ocr" ? "OCR extracted" : "PDF parsed";
    resStats.textContent = `${data.stats.word_count.toLocaleString()} words → ${data.stats.summary_word_count.toLocaleString()} word summary (${data.length})`;

    resSummary.textContent = data.summary;

    resKeyPoints.innerHTML = "";
    data.key_points.forEach(point => {
      const li = document.createElement("li");
      li.textContent = point;
      resKeyPoints.appendChild(li);
    });

    resSuggestions.innerHTML = "";
    data.suggestions.forEach(s => {
      const li = document.createElement("li");
      li.textContent = s;
      resSuggestions.appendChild(li);
    });

    resRawText.textContent = data.extracted_text;

    resultsSection.hidden = false;
    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  resetBtn.addEventListener("click", () => {
    resultsSection.hidden = true;
    resetDropzone();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
})();
