import os
import base64
import requests
from PIL import Image
import pytesseract
import mimetypes
import logging
import json

def allowed_file(filename, allowed_extensions=None):
    if allowed_extensions is None:
        allowed_extensions = {'png', 'tiff', 'tif'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def run_llava_inference(image_path, ollama_api_url):
    try:
        with open(image_path, 'rb') as img_file:
            image_bytes = img_file.read()
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
        data = {
            'model': 'llava:latest',
            'prompt': 'Describe the contents of this image.',
            'image': image_b64
        }
        response = requests.post(ollama_api_url, json=data, stream=True)
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
    except Exception as e:
        logging.error(f"LLaVA inference failed: {e}")
        return f"Error during LLaVA inference: {str(e)}"

def run_text_llm_inference(text, model, ollama_api_url):
    data = {
        'model': model,
        'prompt': f'Analyze the following extracted text from an image and summarize or answer questions as appropriate.\n\n{text}'
    }
    try:
        response = requests.post(ollama_api_url, json=data, stream=True)
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
        logging.error(f"Text LLM inference failed: {e}")
        return f"Error during LLM inference: {str(e)}"

def run_ocr(image_path):
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as e:
        logging.error(f"OCR failed: {e}")
        return ''

def convert_tiff_to_png(tiff_path):
    try:
        png_path = tiff_path.rsplit('.', 1)[0] + '_converted.png'
        with Image.open(tiff_path) as img:
            img.save(png_path, 'PNG')
        return png_path
    except Exception as e:
        logging.error(f"TIFF to PNG conversion failed: {e}")
        return None

def get_mime_type(filepath):
    mime_type, _ = mimetypes.guess_type(filepath)
    return mime_type or 'image/png' 