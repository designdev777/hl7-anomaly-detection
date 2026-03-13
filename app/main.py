#!/usr/bin/env python3
"""
HL7 Anomaly Detection - Render.com Ready Version
"""

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__, 
            static_folder='../static',
            template_folder='../templates')
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['DATA_FILE'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'messages.json')
app.config['ANOMALY_FILE'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'anomalies.json')

# Ensure data directory exists
os.makedirs(os.path.dirname(app.config['DATA_FILE']), exist_ok=True)

# Sample data generator for demo
def generate_sample_data():
    """Generate sample data for demonstration"""
    from random import choice, randint
    from datetime import datetime, timedelta
    
    patients = [f"P{str(i).zfill(5)}" for i in range(1, 51)]
    message_types = ['ADT^A01', 'ADT^A02', 'ADT^A03', 'ORM^O01', 'ORU^R01', 'ACK']
    anomaly_types = [
        {'type': 'missing_field', 'severity': 'medium', 'desc': 'Missing required field'},
        {'type': 'invalid_format', 'severity': 'high', 'desc': 'Invalid message format'},
        {'type': 'sequence_error', 'severity': 'medium', 'desc': 'Out of sequence message'},
        {'type': 'duplicate', 'severity': 'low', 'desc': 'Duplicate message detected'},
        {'type': 'patient_mismatch', 'severity': 'high', 'desc': 'Patient ID mismatch'}
    ]
    
    messages = []
    anomalies = []
    
    # Generate messages for last 24 hours
    now = datetime.now()
    for i in range(100):
        timestamp = now - timedelta(hours=randint(0, 24), minutes=randint(0, 59))
        patient = choice(patients)
        msg_type = choice(message_types)
        
        message = {
            'id': f'MSG{str(i+1).zfill(6)}',
            'timestamp': timestamp.isoformat(),
            'patient_id': patient,
            'message_type': msg_type,
            'content': f'MSH|^~\\&|SENDING|FACILITY|RECEIVING|APPLICATION|{timestamp.strftime("%Y%m%d%H%M%S")}||{msg_type}|MSG{str(i+1).zfill(6)}|P|2.5'
        }
        messages.append(message)
        
        # 30% chance of anomaly
        if randint(1, 100) <= 30:
            anomaly = choice(anomaly_types)
            anomaly_record = {
                'id': f'ANOM{str(len(anomalies)+1).zfill(6)}',
                'message_id': message['id'],
                'patient_id': patient,
                'anomaly_type': anomaly['type'],
                'severity': anomaly['severity'],
                'description': anomaly['desc'],
                'detected_at': timestamp.isoformat(),
                'resolved': False
            }
            anomalies.append(anomaly_record)
    
    return messages, anomalies

# Load or generate data
def load_data():
    """Load data from file or generate sample data"""
    messages = []
    anomalies = []
    
    # Try to load from files
    if os.path.exists(app.config['DATA_FILE']):
        try:
            with open(app.config['DATA_FILE'], 'r') as f:
                messages = json.load(f)
        except:
            pass
    
    if os.path.exists(app.config['ANOMALY_FILE']):
        try:
            with open(app.config['ANOMALY_FILE'], 'r') as f:
                anomalies = json.load(f)
        except:
            pass
    
    # If no data, generate sample data
    if not messages or not anomalies:
        messages, anomalies = generate_sample_data()
        save_data(messages, anomalies)
    
    return messages, anomalies

def save_data(messages, anomalies):
    """Save data to files"""
    with open(app.config['DATA_FILE'], 'w') as f:
        json.dump(messages, f, indent=2)
    with open(app.config['ANOMALY_FILE'], 'w') as f:
        json.dump(anomalies, f, indent=2)

# Load initial data
messages, anomalies = load_data()

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    """Get statistics for dashboard"""
    try:
        # Calculate stats
        total_messages = len(messages)
        unique_patients = len(set(m['patient_id'] for m in messages))
        anomalies_count = len(anomalies)
        
        # Active patients in last hour
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        active_patients = len(set(
            m['patient_id'] for m in messages 
            if m['timestamp'] > one_hour_ago
        ))
        
        # Recent anomalies
        recent = sorted(anomalies, key=lambda x: x['detected_at'], reverse=True)[:10]
        
        # Message types breakdown
        msg_types = {}
        for m in messages:
            msg_type = m['message_type'].split('^')[0] if '^' in m['message_type'] else m['message_type']
            msg_types[msg_type] = msg_types.get(msg_type, 0) + 1
        
        msg_type_list = [
            {'message_type': k, 'count': v} 
            for k, v in sorted(msg_types.items(), key=lambda x: x[1], reverse=True)
        ]
        
        # Anomaly types breakdown
        anom_types = {}
        for a in anomalies:
            anom_types[a['anomaly_type']] = anom_types.get(a['anomaly_type'], 0) + 1
        
        anom_type_list = [
            {
                'anomaly_type': k, 
                'count': v,
                'severity': next((a['severity'] for a in anomalies if a['anomaly_type'] == k), 'medium')
            }
            for k, v in sorted(anom_types.items(), key=lambda x: x[1], reverse=True)
        ]
        
        return jsonify({
            'total_messages': total_messages,
            'unique_patients': unique_patients,
            'anomalies_count': anomalies_count,
            'active_patients': active_patients,
            'recent_anomalies': recent,
            'message_types': msg_type_list,
            'anomaly_types': anom_type_list
        })
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/anomalies/<anomaly_id>/resolve', methods=['POST'])
def resolve_anomaly(anomaly_id):
    """Mark an anomaly as resolved"""
    global anomalies
    for a in anomalies:
        if a['id'] == anomaly_id:
            a['resolved'] = True
            save_data(messages, anomalies)
            return jsonify({'success': True})
    return jsonify({'error': 'Anomaly not found'}), 404

@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)