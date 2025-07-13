from flask import Flask, request, render_template_string, redirect, url_for, flash, send_from_directory, session
import os
from werkzeug.utils import secure_filename
import requests
from PIL import Image
import pytesseract
import base64
import json
import mimetypes
from dotenv import load_dotenv
load_dotenv()
import logging
from utils import allowed_file, run_llava_inference, run_text_llm_inference, run_ocr, convert_tiff_to_png, get_mime_type
from collections import defaultdict
import fakeredis
import uuid

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'tiff', 'tif'}

OLLAMA_API_URL = 'http://localhost:11434/api/generate'

MULTIMODAL_MODELS = ['llava:latest', 'gemma3:27b-vision', 'llama3-vision:latest', 'llama3.2-vision:11b', 'qwen2.5vl:7b']  # Removed llama4-vision, added qwen2.5vl:7b

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent'
GEMINI_FLASH_API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
GEMINI_PRO_API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent'

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = 'supersecretkey'  # For flash messages

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Set up logging
logging.basicConfig(level=logging.INFO)

# Use fakeredis for in-memory Redis-like cache
redis_cache = fakeredis.FakeStrictRedis()

def get_session_id():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    try:
        if request.method == 'POST':
            if 'file' not in request.files:
                flash('No file part')
                return redirect(request.url)
            file = request.files['file']
            if file.filename == '':
                flash('No selected file')
                return redirect(request.url)
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                return render_template_string('''
                    <!doctype html>
                    <title>Choose Parsing Method</title>
                    <h1>File {{ filename }} uploaded!</h1>
                    <form action="/parse/llava" method="post">
                      <input type="hidden" name="filename" value="{{ filename }}">
                      <button type="submit">Parse with LLaVA</button>
                    </form>
                    <form action="/parse/ocr_gemma3" method="post">
                      <input type="hidden" name="filename" value="{{ filename }}">
                      <button type="submit">OCR + Gemma3</button>
                    </form>
                    <form action="/parse/ocr_llama3" method="post">
                      <input type="hidden" name="filename" value="{{ filename }}">
                      <button type="submit">OCR + Llama3</button>
                    </form>
                    <a href="/">Back to upload</a>
                ''', filename=filename)
            else:
                flash('Invalid file type. Only PNG and TIFF are allowed.')
                return redirect(request.url)
        files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if allowed_file(f)]
        return render_template_string('''
            <!doctype html>
            <title>Upload TIFF/PNG File</title>
            <h1>Upload a TIFF or PNG file</h1>
            {% with messages = get_flashed_messages() %}
              {% if messages %}
                <ul>
                {% for message in messages %}
                  <li>{{ message }}</li>
                {% endfor %}
                </ul>
              {% endif %}
            {% endwith %}
            <form method=post enctype=multipart/form-data>
              <input type=file name=file>
              <input type=submit value=Upload>
            </form>
            <hr>
            <h2>Files in Uploads Folder</h2>
            <ul>
            {% for file in files %}
              <li><a href="/uploads/{{ file }}" target="_blank">{{ file }}</a></li>
            {% else %}
              <li>No files uploaded yet.</li>
            {% endfor %}
            </ul>
            <a href="/documents">Go to Document Processing &rarr;</a>
        ''', files=files)
    except Exception as e:
        logging.error(f"Error in upload_file: {e}")
        flash('An unexpected error occurred during file upload.')
        return redirect(request.url)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/documents', methods=['GET', 'POST'])
def list_documents():
    files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if allowed_file(f)]
    combinations = [
        ('ocr', 'OCR Only'),
        ('llava', 'LLaVA Only'),
        ('ocr_gemma3', 'OCR + Gemma3'),
        ('ocr_llama3', 'OCR + Llama3'),
        ('img_gemma3', 'Gemma3 (Image)'),
        ('img_llama3', 'Llama3 (Image)'),
        ('img_qwen2', 'Qwen2.5VL (Image)'),
        ('ocr_llama4', 'OCR + Llama4'),
        ('img_llama4', 'Llama 4 (Image)'),
        ('img_gemini_flash', 'Gemini 2.5 Flash (Image)'),
        ('img_gemini_pro', 'Gemini 2.5 Pro (Image)'),
    ]
    results = []
    selected_files = []
    selected_combos = []
    llm_requests = {}
    llm_responses = {}
    compare_keys = []
    if request.method == 'POST':
        # Detect if this is a compare POST (dropdowns present)
        is_compare = 'left_select' in request.form or 'right_select' in request.form
        if is_compare:
            files_field = request.form.get('files')
            combos_field = request.form.get('combos')
            selected_files = [f.strip() for f in files_field.split(',') if f.strip()] if files_field else []
            selected_combos = [c.strip() for c in combos_field.split(',') if c.strip()] if combos_field else []
        else:
            selected_files = request.form.getlist('files')
            selected_combos = request.form.getlist('combos')
        user_session_id = get_session_id()
        for filename in selected_files:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            for combo in selected_combos:
                cache_key = f"{user_session_id}:{filename}::{combo}"
                cached = redis_cache.get(cache_key)
                if cached:
                    cached_obj = json.loads(cached)
                    req, resp = cached_obj['request'], cached_obj['response']
                else:
                    req, resp = '', ''
                    if combo == 'ocr':
                        req = f"OCR on {filename}"
                        resp = run_ocr(filepath)
                    elif combo == 'llava':
                        req = f"LLaVA inference on {filename}"
                        resp = run_llava_inference(filepath, OLLAMA_API_URL)
                    elif combo == 'ocr_gemma3':
                        ocr_text = run_ocr(filepath)
                        req = (
                            "You are an expert at reading scanned medical lab forms. "
                            "Given the following OCR-extracted text from a scanned form, extract the following fields as accurately as possible: "
                            "Patient ID, Lab ID, Patient Name, Date, Test Name, Result, Reference Range, Doctor Name. "
                            "For each field, if the value is not found, leave it blank. "
                            "Do not swap field names and values, and do not guess. "
                            "Present the results as a markdown table with columns: Field, Value. "
                            "If you find extra fields, add them as additional rows. "
                            "Here is the OCR text:\n"
                            f"{ocr_text}"
                        )
                        resp = run_text_llm_inference(req, 'gemma3:27b')
                    elif combo == 'ocr_llama3':
                        ocr_text = run_ocr(filepath)
                        req = (
                            "You are an expert at reading scanned medical lab forms. "
                            "Given the following OCR-extracted text from a scanned form, extract the following fields as accurately as possible: "
                            "Patient ID, Lab ID, Patient Name, Date, Test Name, Result, Reference Range, Doctor Name. "
                            "For each field, if the value is not found, leave it blank. "
                            "Do not swap field names and values, and do not guess. "
                            "Present the results as a markdown table with columns: Field, Value. "
                            "If you find extra fields, add them as additional rows. "
                            "Here is the OCR text:\n"
                            f"{ocr_text}"
                        )
                        resp = run_text_llm_inference(req, 'llama3:8b')
                    elif combo == 'img_gemma3':
                        model_name = 'gemma3:27b'  # Update if you have a multimodal variant
                        if model_name not in MULTIMODAL_MODELS:
                            resp = 'Gemma3 does not support direct image input. Please use a multimodal model like LLaVA.'
                        else:
                            try:
                                image_b64 = run_llava_inference(filepath, OLLAMA_API_URL)
                                resp = image_b64
                            except Exception as e:
                                resp = f"Error: {e}"
                    elif combo == 'img_llama3':
                        model_name = 'llama3.2-vision:11b'  # Use the multimodal Llama3 vision model
                        if model_name not in MULTIMODAL_MODELS:
                            resp = 'Llama3 does not support direct image input. Please use a multimodal model like LLaVA.'
                        else:
                            try:
                                image_b64 = run_llava_inference(filepath, OLLAMA_API_URL)
                                resp = image_b64
                            except Exception as e:
                                resp = f"Error: {e}"
                    elif combo == 'img_qwen2':
                        model_name = 'qwen2.5vl:7b'
                        if model_name not in MULTIMODAL_MODELS:
                            resp = 'Qwen2.5VL does not support direct image input.'
                        else:
                            try:
                                image_b64 = run_llava_inference(filepath, OLLAMA_API_URL)
                                resp = image_b64
                            except Exception as e:
                                resp = f"Error: {e}"
                    elif combo == 'ocr_llama4':
                        ocr_text = run_ocr(filepath)
                        if not ocr_text:
                            resp = 'No text found in image.'
                        else:
                            prompt = (
                                "You are an expert at reading scanned forms. "
                                "Given the following OCR-extracted text from a scanned form, extract all relevant fields and values, "
                                "and present them as a markdown table. If the form has sections, use them as table headers. "
                                "If the data is not tabular, present it in a clear, structured way.\n\n"
                                f"{ocr_text}"
                            )
                            data = {
                                'model': 'llama4:latest',
                                'prompt': prompt
                            }
                            try:
                                response = requests.post(OLLAMA_API_URL, json=data, stream=True)
                                if response.ok:
                                    result = ''
                                    for line in response.iter_lines():
                                        if line:
                                            try:
                                                part = line.decode('utf-8')
                                                json_part = json.loads(part)
                                                result += json_part.get('response', '')
                                            except Exception:
                                                continue
                                    resp = result or 'No response from Llama4.'
                                else:
                                    resp = f"Error: {response.text}"
                            except Exception as e:
                                resp = f"Error during LLM inference: {str(e)}"
                    elif combo == 'img_llama4':
                        model_name = 'llama4:latest'
                        if model_name not in MULTIMODAL_MODELS:
                            resp = 'Llama4 does not support direct image input. Please use a multimodal model like LLaVA.'
                        else:
                            try:
                                image_b64 = run_llava_inference(filepath, OLLAMA_API_URL)
                                resp = image_b64
                            except Exception as e:
                                resp = f"Error: {e}"
                    elif combo in ('img_gemini_flash', 'img_gemini_pro'):
                        if not GEMINI_API_KEY:
                            resp = 'Gemini API key not set.'
                        else:
                            # If TIFF, convert to PNG for Gemini
                            ext = os.path.splitext(filepath)[1].lower()
                            temp_png_path = None
                            if ext in ['.tiff', '.tif']:
                                temp_png_path = convert_tiff_to_png(filepath)
                                image_path_for_gemini = temp_png_path
                            else:
                                image_path_for_gemini = filepath
                            try:
                                mime_type = get_mime_type(image_path_for_gemini)
                                with open(image_path_for_gemini, 'rb') as img_file:
                                    image_bytes = img_file.read()
                                    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                                headers = {'Content-Type': 'application/json'}
                                params = {'key': GEMINI_API_KEY}
                                data = {
                                    'contents': [
                                        {
                                            'parts': [
                                                {'text': 'Extract all fields and tables from this document as markdown.'},
                                                {'inlineData': {'mimeType': mime_type, 'data': image_b64}}
                                            ]
                                        }
                                    ]
                                }
                                api_url = GEMINI_FLASH_API_URL if combo == 'img_gemini_flash' else GEMINI_PRO_API_URL
                                response = requests.post(api_url, headers=headers, params=params, json=data)
                                label = combinations[[c[0] for c in combinations].index(combo)][1]
                                if response.ok:
                                    try:
                                        gemini_result = response.json()['candidates'][0]['content']['parts'][0]['text']
                                    except Exception:
                                        gemini_result = response.text
                                    resp = gemini_result
                                else:
                                    resp = f"Error: {response.text}"
                                # Clean up temp PNG if created
                                if temp_png_path and os.path.exists(temp_png_path):
                                    os.remove(temp_png_path)
                            except Exception as e:
                                resp = f"Error: {e}"
                    else:
                        req = f"{combo} on {filename}"
                        resp = "Not implemented."
                    redis_cache.set(cache_key, json.dumps({'request': req, 'response': resp, 'filename': filename, 'combo': combo}))
                llm_requests[cache_key] = req
                llm_responses[cache_key] = resp
                results.append({'filename': filename, 'combo': combo, 'request': req, 'response': resp})
        compare_keys = [f"{user_session_id}:{r['filename']}::{r['combo']}" for r in results]
    # Get dropdowns: collect all cache_keys for this POST
    left_sel = request.form.get('left_select')
    right_sel = request.form.get('right_select')
    # If not found in llm_responses (e.g., on compare POST), try to get from redis_cache
    if left_sel and not llm_responses.get(left_sel):
        cached = redis_cache.get(left_sel)
        left_resp = json.loads(cached)['response'] if cached else ''
    else:
        left_resp = llm_responses.get(left_sel, '')
    if right_sel and not llm_responses.get(right_sel):
        cached = redis_cache.get(right_sel)
        right_resp = json.loads(cached)['response'] if cached else ''
    else:
        right_resp = llm_responses.get(right_sel, '')
    return render_template_string('''
        <h1>Uploaded Documents</h1>
        <form method="post">
            <label>Select files:</label><br>
            <select name="files" multiple size="5" style="width: 300px;">
                {% for file in files %}
                <option value="{{ file }}" {% if file in selected_files %}selected{% endif %}>{{ file }}</option>
                {% endfor %}
            </select><br><br>
            <label>Select combinations:</label><br>
            {% for combo, label in combinations %}
                <input type="checkbox" name="combos" value="{{ combo }}" {% if combo in selected_combos %}checked{% endif %}> {{ label }}<br>
            {% endfor %}
            <br>
            <input type="submit" value="Process">
        </form>
        <hr>
        {% if results|length > 0 %}
            <h2>Document</h2>
            <img src="/uploads/{{ results[0].filename }}" alt="Document Image" style="max-width: 100%; border: 1px solid #ccc;"/>
            <hr>
        {% endif %}
        {% for r in results %}
            <h2>{{ r.filename }} - {{ r.combo }}</h2>
            <div style="display: flex; gap: 2em;">
                <div style="flex: 1;">
                    <h3>Request Sent to LLM</h3>
                    <pre style="background: #f0f0f0; padding: 1em; border-radius: 5px; white-space: pre-wrap;">{{ r.request }}</pre>
                    <h3>Parsed Response from LLM</h3>
                    <pre style="background: #f8f8f8; padding: 1em; border-radius: 5px; white-space: pre-wrap;">{{ r.response|safe }}</pre>
                </div>
            </div>
            <hr>
        {% endfor %}
        {% if results|length > 1 %}
        <h2>Compare LLM Parsed Responses</h2>
        <form method="post">
            <input type="hidden" name="files" value="{{ selected_files|join(',') }}">
            <input type="hidden" name="combos" value="{{ selected_combos|join(',') }}">
            <label>Left:</label>
            <select name="left_select">
                {% for k in compare_keys %}
                <option value="{{ k }}" {% if k == left_sel %}selected{% endif %}>{{ k }}</option>
                {% endfor %}
            </select>
            <label>Right:</label>
            <select name="right_select">
                {% for k in compare_keys %}
                <option value="{{ k }}" {% if k == right_sel %}selected{% endif %}>{{ k }}</option>
                {% endfor %}
            </select>
            <input type="submit" value="Compare">
        </form>
        <div style="display: flex; gap: 2em;">
            <div style="flex: 1;">
                <h3>Left Parsed Response</h3>
                <pre style="background: #f8f8f8; padding: 1em; border-radius: 5px; white-space: pre-wrap;">{{ left_resp|safe }}</pre>
            </div>
            <div style="flex: 1;">
                <h3>Right Parsed Response</h3>
                <pre style="background: #f8f8f8; padding: 1em; border-radius: 5px; white-space: pre-wrap;">{{ right_resp|safe }}</pre>
            </div>
        </div>
        {% endif %}
        <a href="/">Back to upload</a>
    ''', files=files, combinations=combinations, results=results, selected_files=selected_files, selected_combos=selected_combos, compare_keys=compare_keys, left_sel=left_sel, right_sel=right_sel, left_resp=left_resp, right_resp=right_resp)

@app.route('/parse/llava', methods=['POST'])
def parse_llava():
    filename = request.form['filename']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        result = run_llava_inference(filepath, OLLAMA_API_URL)
        return render_template_string('''
            <h2>LLaVA Inference Result</h2>
            <pre>{{ result }}</pre>
            <a href="/">Back to upload</a>
        ''', result=result)
    except Exception as e:
        logging.error(f"Error in parse_llava: {e}")
        flash('An unexpected error occurred during LLaVA parsing.')
        return redirect(request.url)

@app.route('/parse/ocr_gemma3', methods=['POST'])
def parse_ocr_gemma3():
    filename = request.form['filename']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        ocr_text = run_ocr(filepath)
        if not ocr_text:
            result = 'No text found in image.'
        else:
            prompt = (
                "You are an expert at reading scanned medical lab forms. "
                "Given the following OCR-extracted text from a scanned form, extract the following fields as accurately as possible: "
                "Patient ID, Lab ID, Patient Name, Date, Test Name, Result, Reference Range, Doctor Name. "
                "For each field, if the value is not found, leave it blank. "
                "Do not swap field names and values, and do not guess. "
                "Present the results as a markdown table with columns: Field, Value. "
                "If you find extra fields, add them as additional rows. "
                "Here is the OCR text:\n"
                f"{ocr_text}"
            )
            result = run_text_llm_inference(prompt, 'gemma3:27b')
        # Display the image and the parsed result below
        return render_template_string('''
            <h2>Scanned Image</h2>
            <img src="/uploads/{{ filename }}" alt="Scanned Image" style="max-width: 100%; height: auto; border: 1px solid #ccc; margin-bottom: 20px;"/>
            <h2>OCR Extracted Text</h2>
            <pre style="background: #f0f0f0; padding: 1em; border-radius: 5px;">{{ ocr_text }}</pre>
            <h2>Parsed Document (Table or Structured Data)</h2>
            <pre style="background: #f8f8f8; padding: 1em; border-radius: 5px;">{{ result }}</pre>
            <a href="/">Back to upload</a>
        ''', filename=filename, result=result, ocr_text=ocr_text)
    except Exception as e:
        logging.error(f"Error in parse_ocr_gemma3: {e}")
        flash('An unexpected error occurred during OCR + Gemma3 parsing.')
        return redirect(request.url)

@app.route('/parse/ocr_llama3', methods=['POST'])
def parse_ocr_llama3():
    filename = request.form['filename']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        ocr_text = run_ocr(filepath)
        if not ocr_text:
            result = 'No text found in image.'
        else:
            result = run_text_llm_inference(ocr_text, 'llama3:8b')
        return render_template_string('''
            <h2>OCR + Llama3 Result</h2>
            <pre>{{ result }}</pre>
            <a href="/">Back to upload</a>
        ''', result=result)
    except Exception as e:
        logging.error(f"Error in parse_ocr_llama3: {e}")
        flash('An unexpected error occurred during OCR + Llama3 parsing.')
        return redirect(request.url)

if __name__ == '__main__':
    app.run(debug=True) 