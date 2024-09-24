from flask import Flask, render_template, request, send_file, session, flash, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
import os
import uuid
import json
import logging
from logging.handlers import RotatingFileHandler
from redactor import analyze_document, redact_document, restore_document, get_preview, generate_token_for_term, search_document
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# Ensure upload directory exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Set up logging
if not os.path.exists('logs'):
    os.mkdir('logs')
file_handler = RotatingFileHandler('logs/redaction_tool.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Redaction tool startup')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/', methods=['GET', 'POST'])
def index():
    session.clear()
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            try:
                filename = secure_filename(file.filename)
                file_id = str(uuid.uuid4())
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_{filename}")
                file.save(filepath)
                app.logger.info(f'File uploaded: {filename}')

                # Analyze document and suggest redactions
                suggested_redactions = analyze_document(filepath)

                # Organize suggested redactions by type for display
                organized_redactions = {}
                for key, value in suggested_redactions.items():
                    ent_type = value['type']
                    if ent_type not in organized_redactions:
                        organized_redactions[ent_type] = []
                    organized_redactions[ent_type].append((key, value))

                # Save suggested redactions to a file
                redactions_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_redactions.json")
                with open(redactions_filepath, 'w') as f:
                    json.dump(suggested_redactions, f)

                session['file_id'] = file_id
                session['filepath'] = filepath
                session['current_step'] = 1

                return redirect(url_for('review_options'))
            except Exception as e:
                app.logger.error(f'Error during file upload: {str(e)}')
                flash(f"An error occurred: {str(e)}")
                return redirect(request.url)
        else:
            flash('Allowed file type is .docx')
            return redirect(request.url)
    return render_template('index.html')

@app.route('/review_options', methods=['GET', 'POST'])
def review_options():
    file_id = session.get('file_id')
    if not file_id:
        return redirect(url_for('index'))

    redactions_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_redactions.json")
    if not os.path.exists(redactions_filepath):
        flash('No redactions found. Please upload a file first.')
        return redirect(url_for('index'))

    with open(redactions_filepath, 'r') as f:
        suggested_redactions = json.load(f)

    # Organize redactions by type for display
    organized_redactions = {}
    for key, value in suggested_redactions.items():
        ent_type = value['type']
        if ent_type not in organized_redactions:
            organized_redactions[ent_type] = []
        # Add a dictionary for each item to extract individual properties cleanly in the template
        organized_redactions[ent_type].append({
            'original': key,
            'context': value['context'],
            'token': value['token'],
            'confidence': value.get('confidence', 1.0),  # Default confidence if not present
            'action': value.get('action', 'REDACTED')    # Default action
        })

    if request.method == 'POST':
        approved_redactions = {}
        for key, value in request.form.items():
            if key.startswith('redact_'):
                original = key[7:]  # Remove 'redact_' prefix
                action = value
                custom_value = request.form.get(f'custom_{original}', '')
                if original in suggested_redactions:
                    approved_redactions[original] = suggested_redactions[original]
                    approved_redactions[original]['action'] = action
                    if action == 'CUSTOM':
                        approved_redactions[original]['custom_value'] = custom_value
                else:
                    app.logger.warning(f"Redaction key not found in suggestions: {original}")

        # Save approved redactions to a file
        approved_redactions_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_approved_redactions.json")
        with open(approved_redactions_filepath, 'w') as f:
            json.dump(approved_redactions, f)

        session['current_step'] = 2
        return redirect(url_for('preview_redactions'))

    return render_template('review_options.html', suggested_redactions=organized_redactions, current_step=session.get('current_step', 1))

@app.route('/preview_redactions', methods=['GET', 'POST'])
def preview_redactions():
    file_id = session.get('file_id')
    if not file_id:
        return redirect(url_for('index'))

    filepath = session.get('filepath')
    approved_redactions_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_approved_redactions.json")

    if not os.path.exists(approved_redactions_filepath):
        flash('No approved redactions found. Please review redactions first.')
        return redirect(url_for('review_options'))

    with open(approved_redactions_filepath, 'r') as f:
        approved_redactions = json.load(f)

    if request.method == 'POST':
        # Handle additional redactions added in the preview page
        for term, action, custom_value in zip(
            request.form.getlist('term[]'),
            request.form.getlist('redaction_type[]'),
            request.form.getlist('custom_replacement[]')
        ):
            if term.strip():
                approved_redactions[term] = {
                    'type': 'CUSTOM',
                    'token': generate_token_for_term(term),
                    'action': action,
                    'custom_value': custom_value if action == 'CUSTOM' else ''
                }

        # Save updated approved redactions
        with open(approved_redactions_filepath, 'w') as f:
            json.dump(approved_redactions, f)

    # Generate the preview
    preview = get_preview(filepath, approved_redactions)

    return render_template('preview_redactions.html', preview=preview, approved_redactions=approved_redactions, current_step=session.get('current_step', 2))

# Add the reverse_redaction route here
@app.route('/reverse_redaction', methods=['POST'])
def reverse_redaction():
    file_id = session.get('file_id')
    if not file_id:
        flash('No file to restore')
        return redirect(url_for('index'))

    redacted_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_redacted.docx")
    redaction_map_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_redaction_map.json")

    if not os.path.exists(redacted_filepath) or not os.path.exists(redaction_map_filepath):
        flash('Redacted file or redaction map not found')
        return redirect(url_for('index'))

    try:
        with open(redaction_map_filepath, 'r') as f:
            redaction_map = json.load(f)

        restored_filepath = restore_document(redacted_filepath, redaction_map)
        app.logger.info(f'File restored: {file_id}')
        return send_file(restored_filepath, as_attachment=True, download_name="restored_document.docx")
    except Exception as e:
        app.logger.error(f'Error during restoration: {str(e)}')
        flash(f"An error occurred during restoration: {str(e)}")
        return redirect(url_for('index'))

# Continue with the existing code in app.py
@app.route('/finalize_redactions', methods=['POST'])
def finalize_redactions():
    file_id = session.get('file_id')
    if not file_id:
        return redirect(url_for('index'))

    filepath = session.get('filepath')
    approved_redactions_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_approved_redactions.json")

    if not os.path.exists(approved_redactions_filepath):
        flash('No approved redactions found. Please review redactions first.')
        return redirect(url_for('review_options'))

    with open(approved_redactions_filepath, 'r') as f:
        approved_redactions = json.load(f)

    # Generate a unique Redaction ID
    redaction_id = str(uuid.uuid4())
    session['redaction_id'] = redaction_id

    redacted_filepath, redaction_map = redact_document(filepath, approved_redactions, redaction_id)

    # Save redaction_map to a file
    redaction_map_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{redaction_id}_redaction_map.json")
    with open(redaction_map_filepath, 'w') as f:
        json.dump(redaction_map, f)

    app.logger.info(f'File redacted: {os.path.basename(filepath)}')

    # Generate summary
    summary = generate_summary(redaction_map)
    session['summary'] = summary
    session['current_step'] = 3

    # Provide Redaction ID to the user
    flash(f"Your Redaction ID is: {redaction_id}. Please keep it safe for restoring the original document.")

    # Return the redacted file for download
    return send_file(redacted_filepath, as_attachment=True, download_name="redacted_document.docx")

@app.route('/redaction_summary')
def redaction_summary():
    if 'summary' not in session:
        return redirect(url_for('index'))

    summary = session['summary']
    return render_template('redaction_summary.html', summary=summary, current_step=session.get('current_step', 3))

@app.route('/restore', methods=['GET', 'POST'])
def restore():
    if request.method == 'POST':
        if 'file' not in request.files or 'redaction_id' not in request.form:
            flash('Please provide both the redacted file and the Redaction ID.')
            return redirect(request.url)
        file = request.files['file']
        redaction_id = request.form.get('redaction_id')
        if file.filename == '':
            flash('No file selected.')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            try:
                filename = secure_filename(file.filename)
                redacted_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"restored_{filename}")
                file.save(redacted_filepath)

                redaction_map_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{redaction_id}_redaction_map.json")
                if not os.path.exists(redaction_map_filepath):
                    flash('Invalid Redaction ID or redaction map not found.')
                    return redirect(request.url)

                with open(redaction_map_filepath, 'r') as f:
                    redaction_map = json.load(f)

                restored_filepath = restore_document(redacted_filepath, redaction_map)
                app.logger.info(f'File restored using Redaction ID: {redaction_id}')

                return send_file(restored_filepath, as_attachment=True, download_name="restored_document.docx")
            except Exception as e:
                app.logger.error(f'Error during restoration: {str(e)}')
                flash(f"An error occurred: {str(e)}")
                return redirect(request.url)
        else:
            flash('Allowed file type is .docx')
            return redirect(request.url)
    return render_template('restore.html')

@app.route('/search', methods=['POST'])
def search():
    filepath = session.get('filepath')
    if not filepath:
        return jsonify({'success': False, 'error': 'No document loaded'})

    query = request.form.get('query')
    if not query:
        return jsonify({'success': False, 'error': 'No search query provided'})

    results = search_document(filepath, query)
    return jsonify({'success': True, 'results': results})

def generate_summary(redaction_map):
    summary = {
        'total_redactions': len(redaction_map),
        'redaction_types': {}
    }
    for token, info in redaction_map.items():
        ent_type = info.get('type', 'CUSTOM')
        if ent_type not in summary['redaction_types']:
            summary['redaction_types'][ent_type] = 0
        summary['redaction_types'][ent_type] += 1
    return summary

if __name__ == '__main__':
    app.run(debug=True)
