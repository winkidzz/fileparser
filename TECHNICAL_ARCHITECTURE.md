# Technical Architecture: FileParser Demo

## Overview
FileParser is a Flask-based web application for uploading, parsing, and comparing scanned documents (TIFF/PNG) using multiple LLMs and OCR. It is designed for demo and prototyping use, with a focus on modularity, extensibility, and in-memory server-side caching.

---

## High-Level Architecture Diagram

```
+-------------------+         +-------------------+         +-------------------+
|                   |         |                   |         |                   |
|   Web Browser     +-------->+   Flask App       +-------->+   LLM/OCR/Cache   |
|                   |  HTTP   |  (app.py)         |  Logic  |  (utils.py, Redis)|
+-------------------+         +-------------------+         +-------------------+
```

---

## Main Components

### 1. **Frontend (Web UI)**
- Built with Flask's `render_template_string` and HTML forms.
- Allows users to upload files, select LLM/OCR processing options, and compare results.
- Renders document, LLM requests, and parsed responses in a user-friendly layout.

### 2. **Flask Backend (app.py)**
- Handles all HTTP routes:
  - `/` for upload
  - `/documents` for processing and comparison
  - `/uploads/<filename>` for serving uploaded files
- Orchestrates file handling, LLM/OCR invocation, and caching.
- Uses robust error handling and logging.

### 3. **Helper Logic (utils.py)**
- Contains modular functions for:
  - File validation
  - OCR (Tesseract)
  - LLM inference (Ollama, Gemini, etc.)
  - TIFF-to-PNG conversion
  - MIME type detection
- All helpers are robust, with error handling and logging.

### 4. **Server-Side Caching (fakeredis)**
- Uses `fakeredis` to emulate a Redis server in memory (no external service needed).
- Caches LLM/OCR results per user session using a generated UUID.
- Ensures that repeated requests and comparisons are fast and isolated per user.
- No data is persisted after server restart (demo/prototype only).

### 5. **Session Management**
- Flask's built-in session is used to store a unique `session_id` (UUID) for each user.
- All cache keys are namespaced by this session ID for per-user isolation.

---

## Data Flow

1. **Upload:**
   - User uploads a TIFF/PNG file via the web UI.
   - File is saved to the `uploads/` directory.

2. **Processing:**
   - User selects one or more LLM/OCR options and submits the form.
   - For each file/option:
     - If TIFF, it is converted to PNG for models that require it.
     - OCR and/or LLMs are invoked as needed.
     - The request and parsed response are cached in fakeredis under a session-specific key.

3. **Display:**
   - The UI displays:
     - The document image (once)
     - The request sent to each LLM
     - The parsed response from each LLM
   - If multiple LLMs are selected, a comparison section allows side-by-side viewing of any two parsed responses.

4. **Comparison:**
   - User selects two LLM results from dropdowns.
   - The app retrieves the parsed responses from the cache and displays them side-by-side.

---

## Extensibility
- **Add new LLMs:** Implement new helpers in `utils.py` and add options to the `combinations` list in `app.py`.
- **Swap cache backend:** Replace `fakeredis` with real Redis or another Flask-Caching backend for production.
- **UI enhancements:** Replace `render_template_string` with Jinja templates or a frontend framework for more complex UIs.
- **Authentication:** Add Flask-Login or similar for user auth if needed.

---

## Security & Limitations
- Not for production: uses Flask dev server, in-memory cache, and no authentication.
- All data is lost on server restart.
- No rate limiting or input sanitization for production use.

---

## Dependencies
- Flask
- Pillow
- pytesseract
- requests
- fakeredis
- python-dotenv

---

## Summary
FileParser is a modular, extensible demo for document parsing and LLM comparison, with robust server-side caching and a clear separation of concerns between UI, backend, helpers, and cache. 