# FileParser: Multimodal Document Processing Flask App

## Overview
FileParser is a Flask-based web application for uploading and processing scanned documents (TIFF/PNG). It supports OCR, LLM-based extraction, and direct image-to-text with state-of-the-art models, including Gemini Pro/Flash, LLaVA, Gemma3, Llama3, and Qwen2.5VL. The app is designed for extensibility and robust handling of medical lab forms and similar documents.

## Features
- **File Upload:** Upload TIFF and PNG files via a web interface.
- **TIFF to PNG Conversion:** Automatically converts TIFF files to PNG for models/APIs that require it (e.g., Gemini).
- **OCR Extraction:** Uses Tesseract OCR to extract text from images.
- **Multimodal LLMs:** Supports image-to-text and text-to-structured-data using:
  - Gemini 2.5 Pro & Flash (Google)
  - LLaVA (Ollama)
  - Gemma3, Llama3, Qwen2.5VL (Ollama)
- **Flexible Processing:** Choose from multiple processing pipelines (OCR only, OCR+LLM, direct image-to-LLM, etc.).
- **API Key Management:** Uses `.env` file for secure Gemini API key management.

## Architecture
```
User Uploads File (TIFF/PNG)
        |
        v
[Flask Web App]
        |
        +---> [TIFF?] --yes--> [Convert to PNG] --+
        |                                         |
        +----------------no-----------------------+
        |
        v
[Processing Options]
    | OCR Only
    | OCR + LLM (Gemma3, Llama3, Llama4)
    | Direct Image-to-LLM (LLaVA, Gemini, Qwen2.5VL)
        |
        v
[Results Rendered in Web UI]
```

- **app.py**: Main Flask app, routes, and logic
- **uploads/**: Uploaded files
- **requirements.txt**: Python dependencies
- **.env**: Environment variables (e.g., GEMINI_API_KEY)

## Setup
1. **Clone the repo:**
   ```sh
   git clone https://github.com/winkidzz/fileparser.git
   cd fileparser
   ```
2. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```
3. **Set up environment variables:**
   - Create a `.env` file in the project root:
     ```
     GEMINI_API_KEY=your_actual_api_key_here
     ```
4. **Run the app:**
   ```sh
   python3 app.py
   ```
5. **Access the app:**
   - Open [http://localhost:5000](http://localhost:5000) in your browser.

## Usage
- Upload a TIFF or PNG file.
- Choose a processing method (OCR, LLM, Gemini, etc.).
- View and copy the extracted/structured results.

## Extending
- Add new models or processing routes in `app.py`.
- Update `requirements.txt` for new dependencies.

## Security & Notes
- Do not use the Flask dev server in production.
- Keep your `.env` file secure and never commit secrets.
- For best results, use high-quality scans.

## License
MIT License 