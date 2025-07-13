from flask import Flask, request, render_template_string, redirect, url_for, flash, send_from_directory
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

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Helper to run LLaVA (image-to-text) via Ollama
def run_llava_inference(image_path):
    with open(image_path, 'rb') as img_file:
        image_bytes = img_file.read()
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    data = {
        'model': 'llava:latest',
        'prompt': 'Describe the contents of this image.',
        'image': image_b64
    }
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
        return result or 'No response from LLaVA.'
    return f"Error: {response.text}"

# Helper to run text inference via Ollama
def run_text_llm_inference(text, model):
    data = {
        'model': model,
        'prompt': f'Analyze the following extracted text from an image and summarize or answer questions as appropriate.\n\n{text}'
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
            return result or 'No response from LLM.'
        return f"Error: {response.text}"
    except Exception as e:
        return f"Error during LLM inference: {str(e)}"

# Helper to run OCR
def run_ocr(image_path):
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image)
    return text.strip()

# Helper to convert TIFF to PNG
def convert_tiff_to_png(tiff_path):
    png_path = tiff_path.rsplit('.', 1)[0] + '_converted.png'
    with Image.open(tiff_path) as img:
        img.save(png_path, 'PNG')
    return png_path

@app.route('/', methods=['GET', 'POST'])
def upload_file():
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
            # After upload, show options to process
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
    # List files in uploads folder
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
    if request.method == 'POST':
        selected_files = request.form.getlist('files')
        selected_combos = request.form.getlist('combos')
        for filename in selected_files:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            for combo in selected_combos:
                if combo == 'ocr':
                    ocr_text = run_ocr(filepath)
                    results.append((filename, 'OCR Only', ocr_text))
                elif combo == 'llava':
                    llava_result = run_llava_inference(filepath)
                    results.append((filename, 'LLaVA Only', llava_result))
                elif combo == 'ocr_gemma3':
                    ocr_text = run_ocr(filepath)
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
                    gemma3_result = run_text_llm_inference(prompt, 'gemma3:27b')
                    results.append((filename, 'OCR + Gemma3', gemma3_result))
                elif combo == 'ocr_llama3':
                    ocr_text = run_ocr(filepath)
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
                    llama3_result = run_text_llm_inference(prompt, 'llama3:8b')
                    results.append((filename, 'OCR + Llama3', llama3_result))
                elif combo == 'img_gemma3':
                    model_name = 'gemma3:27b'  # Update if you have a multimodal variant
                    if model_name not in MULTIMODAL_MODELS:
                        results.append((filename, 'Gemma3 (Image)', 'Gemma3 does not support direct image input. Please use a multimodal model like LLaVA.'))
                        continue
                    with open(filepath, 'rb') as img_file:
                        image_bytes = img_file.read()
                        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                    data = {
                        'model': model_name,
                        'prompt': 'Describe the contents of this image and extract relevant fields as a markdown table.',
                        'image': image_b64
                    }
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
                        results.append((filename, 'Gemma3 (Image)', result or 'No response from Gemma3.'))
                    else:
                        results.append((filename, 'Gemma3 (Image)', f"Error: {response.text}"))
                elif combo == 'img_llama3':
                    model_name = 'llama3.2-vision:11b'  # Use the multimodal Llama3 vision model
                    if model_name not in MULTIMODAL_MODELS:
                        results.append((filename, 'Llama3 (Image)', 'Llama3 does not support direct image input. Please use a multimodal model like LLaVA.'))
                        continue
                    with open(filepath, 'rb') as img_file:
                        image_bytes = img_file.read()
                        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                    data = {
                        'model': model_name,
                        'prompt': 'Describe the contents of this image and extract relevant fields as a markdown table.',
                        'image': image_b64
                    }
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
                        results.append((filename, 'Llama3 (Image)', result or 'No response from Llama3.'))
                    else:
                        results.append((filename, 'Llama3 (Image)', f"Error: {response.text}"))
                elif combo == 'img_qwen2':
                    model_name = 'qwen2.5vl:7b'
                    if model_name not in MULTIMODAL_MODELS:
                        results.append((filename, 'Qwen2.5VL (Image)', 'Qwen2.5VL does not support direct image input.'))
                        continue
                    with open(filepath, 'rb') as img_file:
                        image_bytes = img_file.read()
                        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                    data = {
                        'model': model_name,
                        'prompt': 'Describe the contents of this image and extract relevant fields as a markdown table.',
                        'image': image_b64
                    }
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
                        results.append((filename, 'Qwen2.5VL (Image)', result or 'No response from Qwen2.5VL.'))
                    else:
                        results.append((filename, 'Qwen2.5VL (Image)', f"Error: {response.text}"))
                elif combo == 'ocr_llama4':
                    ocr_text = run_ocr(filepath)
                    if not ocr_text:
                        results.append((filename, 'OCR + Llama4', 'No text found in image.'))
                        continue
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
                        results.append((filename, 'OCR + Llama4', result or 'No response from Llama4.'))
                    else:
                        results.append((filename, 'OCR + Llama4', f"Error: {response.text}"))
                elif combo == 'img_llama4':
                    model_name = 'llama4:latest'
                    with open(filepath, 'rb') as img_file:
                        image_bytes = img_file.read()
                        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                    data = {
                        'model': model_name,
                        'prompt': 'Extract all fields and tables from this document as markdown.',
                        'images': [image_b64]
                    }
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
                        results.append((filename, 'Llama 4 (Image)', result or 'No response from Llama 4.'))
                    else:
                        results.append((filename, 'Llama 4 (Image)', f"Error: {response.text}"))
                elif combo in ('img_gemini_flash', 'img_gemini_pro'):
                    if not GEMINI_API_KEY:
                        results.append((filename, combinations[[c[0] for c in combinations].index(combo)][1], 'Gemini API key not set.'))
                        continue
                    # If TIFF, convert to PNG for Gemini
                    ext = os.path.splitext(filepath)[1].lower()
                    temp_png_path = None
                    if ext in ['.tiff', '.tif']:
                        temp_png_path = convert_tiff_to_png(filepath)
                        image_path_for_gemini = temp_png_path
                    else:
                        image_path_for_gemini = filepath
                    with open(image_path_for_gemini, 'rb') as img_file:
                        image_bytes = img_file.read()
                        image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                    mime_type, _ = mimetypes.guess_type(image_path_for_gemini)
                    if not mime_type:
                        mime_type = 'image/png'  # fallback
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
                        results.append((filename, label, gemini_result))
                    else:
                        results.append((filename, label, f"Error: {response.text}"))
                    # Clean up temp PNG if created
                    if temp_png_path and os.path.exists(temp_png_path):
                        os.remove(temp_png_path)
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
        {% for filename, combo, result in results %}
            <h2>{{ filename }} - {{ combo }}</h2>
            <pre style="background: #f8f8f8; padding: 1em; border-radius: 5px;">{{ result }}</pre>
        {% endfor %}
        <a href="/">Back to upload</a>
    ''', files=files, combinations=combinations, results=results, selected_files=selected_files, selected_combos=selected_combos)

@app.route('/parse/llava', methods=['POST'])
def parse_llava():
    filename = request.form['filename']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    result = run_llava_inference(filepath)
    return render_template_string('''
        <h2>LLaVA Inference Result</h2>
        <pre>{{ result }}</pre>
        <a href="/">Back to upload</a>
    ''', result=result)

@app.route('/parse/ocr_gemma3', methods=['POST'])
def parse_ocr_gemma3():
    filename = request.form['filename']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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

@app.route('/parse/ocr_llama3', methods=['POST'])
def parse_ocr_llama3():
    filename = request.form['filename']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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

if __name__ == '__main__':
    app.run(debug=True) 