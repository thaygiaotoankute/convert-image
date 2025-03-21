import os
import re
import json
import base64
import hashlib
import xml.etree.ElementTree as ET
import requests
import logging
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from mistralai import Mistral

app = Flask(__name__)

# Vercel uses temporary file system, change storage directory
if os.environ.get('VERCEL_ENV') == 'production':
    # Use /tmp directory on Vercel
    app.config['UPLOAD_FOLDER'] = '/tmp'
else:
    app.config['UPLOAD_FOLDER'] = 'uploads'
    
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max upload size

# Create upload directory if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configure logging
if os.environ.get('VERCEL_ENV') == 'production':
    app.logger.setLevel(logging.INFO)
else:
    app.logger.setLevel(logging.DEBUG)
    
# Log handler
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
app.logger.addHandler(handler)

# Utility functions from original app
def load_rsa_private_key_from_xml(xml_str):
    """Load RSA private key from XML format"""
    root = ET.fromstring(xml_str)
    def get_int(tag):
        text = root.find(tag).text
        return int.from_bytes(base64.b64decode(text), 'big')
    n = get_int('Modulus')
    e = get_int('Exponent')
    d = get_int('D')
    p = get_int('P')
    q = get_int('Q')
    key = RSA.construct((n, e, d, p, q))
    return key

def decrypt_api_key(encrypted_key_base64, rsa_private_key):
    """Decrypt API key"""
    try:
        cipher = PKCS1_v1_5.new(rsa_private_key)
        encrypted_data = base64.b64decode(encrypted_key_base64)
        decrypted = cipher.decrypt(encrypted_data, None)
        
        if not decrypted:
            raise ValueError("Decryption failed")
        return decrypted.decode('utf-8')
    except Exception as e:
        raise ValueError(f"Error decrypting API key: {str(e)}")

def get_mineru_token():
    """Get API key from GitHub"""
    PRIVATE_KEY_XML = """<RSAKeyValue>
<Modulus>pWVItQwZ7NCPcBhSL4rqJrwh4OQquiPVtqTe4cqxO7o+UjYNzDPfLkfKAvR8k9ED4lq2TU11zEj8p2QZAM7obUlK4/HVexzfZd0qsXlCy5iaWoTQLXbVdzjvkC4mkO5TaX3Mpg/+p4oZjk1iS68tQFmju5cT19dcsPh554ICk8U=</Modulus>
<Exponent>AQAB</Exponent>
<P>0ZWwsKa9Vw9BJAsRaW4eV60i6Z+R6z9LNSgjNn4pYH2meZtGUbmJVowRv7EM5sytouB5EMru7sQbRHEQ7nrwSw==</P>
<Q>ygZQWNkUgfHhHBataXvYLxWgPB5UZTWogN8Mb33LT4rq7I5P1GX3oWtYF2AdmChX8Lq3Ms/A/jBhqYomhYOiLw==</Q>
<DP>qS9VOsTfA3Bk/VuR6rHh/JTfIgiWGnk1lOuZwVuGu0WzJWebFE3Z9+uKSFv8NjPz1w+tq0imKEhWWqGLMXg8kQ==</DP>
<DQ>UCtXQRrMB5EL6tCY+k4aCP1E+/ZxOUSk3Jcm4SuDPcp71WnYBgp8zULCz2vl8pa35yDBSFmnVXevmc7n4H3PIw==</DQ>
<InverseQ>Qm9RjBhxANWyIb8I28vjGz+Yb9CnunWxpHWbfRo1vF+Z38WB7dDgLsulAXMGrUPQTeG6K+ot5moeZ9ZcAc1Hzw==</InverseQ>
<D>F9lU9JY8HsOsCzPWlfhn7xHtqKn95z1HkcCQSuqZR82BMwWMU8efBONhI6/xTrcy4i7GXrsuozhbBiAO4ujy5qPytdFemLuqjwFTyvllkcOy3Kbe0deczxnPPCwmSMVKsYInByJoBP3JYoyVAj4bvY3UqZJtw+2u/OIOhoBe33k=</D>
</RSAKeyValue>"""
    
    try:
        rsa_private_key = load_rsa_private_key_from_xml(PRIVATE_KEY_XML)
        github_url = "https://raw.githubusercontent.com/thayphuctoan/pconvert/refs/heads/main/ocr-pdf"
        response = requests.get(github_url, timeout=10)
        response.raise_for_status()
        
        encrypted_keys = [line.strip() for line in response.text.splitlines() if line.strip()]
        if not encrypted_keys:
            raise ValueError("No encrypted API key found")
        
        token = decrypt_api_key(encrypted_keys[0], rsa_private_key)
        if not token:
            raise ValueError("Decrypted API key is empty")
        return token
    except Exception as e:
        raise Exception(f"Error getting API key: {str(e)}")

def check_activation(hardware_id):
    """Check if hardware ID is activated"""
    try:
        url = "https://raw.githubusercontent.com/thayphuctoan/pconvert/refs/heads/main/ocr-image"
        response = requests.get(url, timeout=(10, 30))
        
        if response.status_code == 200:
            valid_ids = response.text.strip().split('\n')
            if hardware_id in valid_ids:
                return True
        return False
    except Exception as e:
        app.logger.error(f"Error checking activation: {str(e)}")
        return False

def process_ocr_image(file_path):
    """Process OCR for image file"""
    try:
        # Get API key
        api_key = get_mineru_token()
        client = Mistral(api_key=api_key)
        
        # Read image file as base64
        with open(file_path, 'rb') as f:
            base64_image = base64.b64encode(f.read()).decode('utf-8')
            
        # Process OCR
        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "image_url",
                "image_url": f"data:image/jpeg;base64,{base64_image}"
            }
        )
        
        # Process result
        result_text = ""
        if hasattr(ocr_response, 'text'):
            result_text = ocr_response.text
        elif hasattr(ocr_response, 'markdown'):
            result_text = ocr_response.markdown
        elif hasattr(ocr_response, 'pages') and len(ocr_response.pages) > 0:
            for page in ocr_response.pages:
                if hasattr(page, 'text') and page.text:
                    result_text += page.text + "\n\n"
                elif hasattr(page, 'markdown') and page.markdown:
                    result_text += page.markdown + "\n\n"
                    
        # Clean up text
        cleaned_text = result_text
        cleaned_text = re.sub(r'OCRPageObject\(.*?\)', '', cleaned_text)
        cleaned_text = re.sub(r'OCRPageDimensions\(.*?\)', '', cleaned_text)
        
        return {"text": cleaned_text}
        
    except Exception as e:
        app.logger.error(f"Error in OCR process: {str(e)}")
        raise

# Routes
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    # Check hardware ID and activation
    hardware_id = request.form.get('hardware_id')
    if not hardware_id or not check_activation(hardware_id):
        return jsonify({
            'success': False,
            'error': 'Software not activated or invalid Hardware ID.'
        }), 403
    
    # Check file
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    # Check if file is an image
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
    if file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        try:
            # Process OCR
            result = process_ocr_image(file_path)
            
            # Return results
            return jsonify({
                'success': True,
                'filename': filename,
                'text': result['text']
            })
            
        except Exception as e:
            app.logger.error(f"Error processing OCR: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
        finally:
            # Delete temporary file
            if os.path.exists(file_path):
                os.remove(file_path)
                
    return jsonify({'success': False, 'error': 'Unsupported file type, only images are accepted'}), 400

@app.route('/api/hardware-id', methods=['POST'])
def get_hardware_id():
    """API to generate hardware ID from submitted information"""
    data = request.json
    if not data or not all(k in data for k in ('cpu_id', 'bios_serial', 'motherboard_serial')):
        return jsonify({'success': False, 'error': 'Missing hardware information'}), 400
    
    combined_info = f"{data['cpu_id']}|{data['bios_serial']}|{data['motherboard_serial']}"
    hardware_id = hashlib.md5(combined_info.encode()).hexdigest().upper()
    formatted_id = '-'.join([hardware_id[i:i+8] for i in range(0, len(hardware_id), 8)])
    formatted_id = formatted_id + "-Premium"
    
    return jsonify({
        'success': True,
        'hardware_id': formatted_id,
        'activated': check_activation(formatted_id)
    })
