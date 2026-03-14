#!/usr/bin/env python3
"""
HL7 Anomaly Detection - Enhanced with Continuous Simulation
Render.com Ready Version with Start/Stop Controls
"""

import os
import json
import time
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import random
import string

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__, 
            static_folder='../static',
            template_folder='../templates')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['DATA_FILE'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'messages.json')
app.config['ANOMALY_FILE'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'anomalies.json')

# Initialize SocketIO for real-time updates
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Ensure data directory exists
os.makedirs(os.path.dirname(app.config['DATA_FILE']), exist_ok=True)

# Global variables for simulation control
simulation_active = False
simulation_thread = None
messages = []
anomalies = []

# HL7 Message Templates
HL7_TEMPLATES = {
    'ADT^A01': {
        'description': 'Admit/Visit Notification',
        'segments': [
            'MSH|^~\\&|SENDING_APP|SENDING_FAC|RECV_APP|RECV_FAC|{timestamp}||ADT^A01|{message_id}|P|2.5',
            'EVN|A01|{timestamp}|||{user_id}',
            'PID|1||{patient_id}^^^HOSP^MR||{last_name}^{first_name}^^^^||{dob}|{gender}|||{address}^^^XX^12345||{phone}|||{race}||{account_id}',
            'PV1|1|I|{ward}^{room}^{bed}^{facility}||||{attending_doctor}^^{last_name}^^{first_name}||||||||||{visit_id}'
        ]
    },
    'ADT^A02': {
        'description': 'Transfer a Patient',
        'segments': [
            'MSH|^~\\&|SENDING_APP|SENDING_FAC|RECV_APP|RECV_FAC|{timestamp}||ADT^A02|{message_id}|P|2.5',
            'EVN|A02|{timestamp}|||{user_id}',
            'PID|1||{patient_id}^^^HOSP^MR||{last_name}^{first_name}^^^^||{dob}|{gender}',
            'PV1|1|I|{ward}^{room}^{bed}^{facility}||||{attending_doctor}^^{last_name}^^{first_name}||||||||||{visit_id}'
        ]
    },
    'ADT^A03': {
        'description': 'Discharge a Patient',
        'segments': [
            'MSH|^~\\&|SENDING_APP|SENDING_FAC|RECV_APP|RECV_FAC|{timestamp}||ADT^A03|{message_id}|P|2.5',
            'EVN|A03|{timestamp}|||{user_id}',
            'PID|1||{patient_id}^^^HOSP^MR||{last_name}^{first_name}^^^^||{dob}|{gender}',
            'PV1|1|I|{ward}^{room}^{bed}^{facility}||||{attending_doctor}^^{last_name}^^{first_name}||||||||||{visit_id}||{discharge_date}'
        ]
    },
    'ORM^O01': {
        'description': 'Order Message',
        'segments': [
            'MSH|^~\\&|SENDING_APP|SENDING_FAC|RECV_APP|RECV_FAC|{timestamp}||ORM^O01|{message_id}|P|2.5',
            'PID|1||{patient_id}^^^HOSP^MR||{last_name}^{first_name}^^^^||{dob}|{gender}',
            'PV1|1|O||||||{ordering_doctor}^^{last_name}^^{first_name}',
            'ORC|NW|{order_id}|||{order_status}||{timestamp}|||{ordering_doctor}||{patient_id}',
            'OBR|1|{order_id}||{test_code}^{test_name}|||{timestamp}|||||||||{ordering_doctor}'
        ]
    },
    'ORU^R01': {
        'description': 'Observation Result',
        'segments': [
            'MSH|^~\\&|SENDING_APP|SENDING_FAC|RECV_APP|RECV_FAC|{timestamp}||ORU^R01|{message_id}|P|2.5',
            'PID|1||{patient_id}^^^HOSP^MR||{last_name}^{first_name}^^^^||{dob}|{gender}',
            'OBR|1|{order_id}||{test_code}^{test_name}|||{timestamp}|||||||||{ordering_doctor}',
            'OBX|1|NM|{test_code}^^{test_name}||{result}|{units}|{ref_range}|||F|||{timestamp}'
        ]
    }
}

# Anomaly Patterns
ANOMALY_PATTERNS = [
    {
        'type': 'missing_field',
        'severity': 'high',
        'description': 'Missing required PID segment field',
        'apply': lambda msg: msg.replace('||||', '|||~|')  # Remove a field
    },
    {
        'type': 'invalid_format',
        'severity': 'high',
        'description': 'Invalid date format in EVN segment',
        'apply': lambda msg: msg.replace(msg.split('|')[6] if len(msg.split('|')) > 6 else '', '2025010')
    },
    {
        'type': 'sequence_error',
        'severity': 'medium',
        'description': 'Out of sequence message',
        'apply': lambda msg: msg.replace('A01', 'A99')
    },
    {
        'type': 'duplicate',
        'severity': 'low',
        'description': 'Duplicate message ID detected',
        'apply': lambda msg: msg  # Will be marked as duplicate in tracking
    },
    {
        'type': 'patient_mismatch',
        'severity': 'high',
        'description': 'Patient ID mismatch between PID and PV1 segments',
        'apply': lambda msg: msg.replace('PID|1||', 'PID|1||P99999|')  # Change patient ID
    },
    {
        'type': 'missing_segment',
        'severity': 'high',
        'description': 'Required EVN segment missing',
        'apply': lambda msg: '\n'.join([line for line in msg.split('\n') if not line.startswith('EVN')])
    },
    {
        'type': 'invalid_hl7_structure',
        'severity': 'critical',
        'description': 'Invalid HL7 message structure',
        'apply': lambda msg: msg.replace('|', '')[:100]  # Remove all separators
    },
    {
        'type': 'wrong_message_type',
        'severity': 'medium',
        'description': 'Message type doesn\'t match content',
        'apply': lambda msg: msg.replace('ADT', 'ORM')
    },
    {
        'type': 'future_timestamp',
        'severity': 'low',
        'description': 'Message timestamp is in the future',
        'apply': lambda msg: msg.replace(msg.split('|')[6] if len(msg.split('|')) > 6 else '', 
                                         (datetime.now() + timedelta(days=1)).strftime('%Y%m%d%H%M%S'))
    },
    {
        'type': 'invalid_encoding',
        'severity': 'medium',
        'description': 'Invalid encoding characters',
        'apply': lambda msg: msg.replace('^~\\&', '^~\\&amp;')
    }
]

def generate_patient_data():
    """Generate random patient data"""
    first_names = ['John', 'Jane', 'Michael', 'Sarah', 'David', 'Emma', 'James', 'Lisa', 'Robert', 'Maria']
    last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez', 'Martinez']
    streets = ['Main St', 'Oak Ave', 'Maple Rd', 'Washington Blvd', 'Park Dr', 'Cedar Ln', 'Elm St', 'Pine Ave']
    cities = ['Springfield', 'Riverside', 'Centerville', 'Franklin', 'Greenville', 'Bristol', 'Clinton', 'Georgetown']
    
    return {
        'first_name': random.choice(first_names),
        'last_name': random.choice(last_names),
        'dob': f"{random.randint(1940, 2020)}{str(random.randint(1, 12)).zfill(2)}{str(random.randint(1, 28)).zfill(2)}",
        'gender': random.choice(['M', 'F', 'U']),
        'address': f"{random.randint(100, 9999)} {random.choice(streets)}",
        'city': random.choice(cities),
        'state': random.choice(['CA', 'NY', 'TX', 'FL', 'IL', 'PA', 'OH', 'GA']),
        'zip': str(random.randint(10000, 99999)),
        'phone': f"{random.randint(200, 999)}{random.randint(100, 999)}{random.randint(1000, 9999)}",
        'race': random.choice(['W', 'B', 'A', 'H', 'O']),
        'account_id': f"A{random.randint(10000, 99999)}"
    }

def generate_hl7_message(msg_type=None, include_anomaly=False):
    """Generate a single HL7 message"""
    if msg_type is None:
        msg_type = random.choice(list(HL7_TEMPLATES.keys()))
    
    template = HL7_TEMPLATES[msg_type]
    patient = generate_patient_data()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    message_id = f"MSG{random.randint(100000, 999999)}"
    patient_id = f"P{random.randint(10000, 99999)}"
    visit_id = f"V{random.randint(100000, 999999)}"
    order_id = f"ORD{random.randint(100000, 999999)}"
    
    # Generate segments
    segments = []
    for segment_template in template['segments']:
        segment = segment_template.format(
            timestamp=timestamp,
            message_id=message_id,
            patient_id=patient_id,
            last_name=patient['last_name'].upper(),
            first_name=patient['first_name'].upper(),
            dob=patient['dob'],
            gender=patient['gender'],
            address=f"{patient['address']}^{patient['city']}^{patient['state']}",
            phone=patient['phone'],
            race=patient['race'],
            account_id=patient['account_id'],
            ward=random.choice(['ER', 'ICU', 'CCU', 'MED', 'SUR', 'PED']),
            room=str(random.randint(100, 999)),
            bed=random.choice(['A', 'B', 'C']),
            facility='MAIN',
            attending_doctor=f"D{random.randint(1000, 9999)}",
            user_id=f"U{random.randint(1000, 9999)}",
            visit_id=visit_id,
            order_id=order_id,
            order_status=random.choice(['NW', 'IP', 'SC', 'CM']),
            test_code=random.choice(['CBC', 'BMP', 'LIPID', 'TSH', 'A1C']),
            test_name=random.choice(['Complete Blood Count', 'Basic Metabolic Panel', 'Lipid Panel', 'Thyroid', 'Hemoglobin A1C']),
            result=str(random.randint(1, 1000) / 10),
            units=random.choice(['mg/dL', 'g/dL', 'mEq/L', 'IU/L', '%']),
            ref_range=f"{random.randint(1, 50)}-{random.randint(50, 200)}",
            ordering_doctor=f"D{random.randint(1000, 9999)}",
            discharge_date=(datetime.now() + timedelta(days=random.randint(1, 10))).strftime('%Y%m%d%H%M%S')
        )
        segments.append(segment)
    
    message = '\r'.join(segments)  # HL7 uses \r as segment separator
    
    # Apply anomaly if requested
    anomaly_type = None
    anomaly_desc = None
    anomaly_severity = None
    
    if include_anomaly and random.random() < 0.3:  # 30% chance of anomaly
        anomaly = random.choice(ANOMALY_PATTERNS)
        original_message = message
        message = anomaly['apply'](message)
        
        # Only count as anomaly if the message was actually modified
        if message != original_message or anomaly['type'] == 'duplicate':
            anomaly_type = anomaly['type']
            anomaly_desc = anomaly['description']
            anomaly_severity = anomaly['severity']
    
    return {
        'id': message_id,
        'timestamp': datetime.now().isoformat(),
        'patient_id': patient_id,
        'patient_name': f"{patient['first_name']} {patient['last_name']}",
        'message_type': msg_type,
        'message_type_desc': template['description'],
        'full_message': message,
        'segments': len(segments),
        'has_anomaly': anomaly_type is not None,
        'anomaly_type': anomaly_type,
        'anomaly_description': anomaly_desc,
        'anomaly_severity': anomaly_severity
    }

def simulation_worker():
    """Background worker for continuous message generation"""
    global messages, anomalies, simulation_active
    
    logger.info("Simulation worker started")
    message_count = 0
    
    while simulation_active:
        try:
            # Generate message with random anomaly chance
            include_anomaly = random.random() < 0.25  # 25% anomaly rate
            msg = generate_hl7_message(include_anomaly=include_anomaly)
            
            # Add to messages list
            messages.append(msg)
            
            # Keep only last 1000 messages
            if len(messages) > 1000:
                messages = messages[-1000:]
            
            # If anomaly, add to anomalies list
            if msg['has_anomaly']:
                anomaly_record = {
                    'id': f"ANOM{len(anomalies)+1}",
                    'message_id': msg['id'],
                    'patient_id': msg['patient_id'],
                    'patient_name': msg['patient_name'],
                    'anomaly_type': msg['anomaly_type'],
                    'severity': msg['anomaly_severity'],
                    'description': msg['anomaly_description'],
                    'full_message': msg['full_message'],
                    'detected_at': msg['timestamp'],
                    'message_type': msg['message_type'],
                    'resolved': False
                }
                anomalies.append(anomaly_record)
                
                # Keep only last 500 anomalies
                if len(anomalies) > 500:
                    anomalies = anomalies[-500:]
            
            # Save to file periodically
            if message_count % 10 == 0:
                save_data()
            
            # Emit real-time update via SocketIO
            socketio.emit('new_message', {
                'message': msg,
                'stats': get_stats_data()
            })
            
            message_count += 1
            
            # Wait before next message (1-5 seconds)
            time.sleep(random.uniform(1, 5))
            
        except Exception as e:
            logger.error(f"Error in simulation worker: {e}")
            time.sleep(5)
    
    logger.info("Simulation worker stopped")

def get_stats_data():
    """Get current statistics"""
    one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
    
    return {
        'total_messages': len(messages),
        'unique_patients': len(set(m['patient_id'] for m in messages)),
        'anomalies_count': len(anomalies),
        'active_patients': len(set(
            m['patient_id'] for m in messages 
            if m['timestamp'] > one_hour_ago
        )),
        'simulation_active': simulation_active
    }

def load_data():
    """Load data from file"""
    global messages, anomalies
    try:
        if os.path.exists(app.config['DATA_FILE']):
            with open(app.config['DATA_FILE'], 'r') as f:
                messages = json.load(f)
        if os.path.exists(app.config['ANOMALY_FILE']):
            with open(app.config['ANOMALY_FILE'], 'r') as f:
                anomalies = json.load(f)
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def save_data():
    """Save data to file"""
    try:
        with open(app.config['DATA_FILE'], 'w') as f:
            json.dump(messages[-500:], f, indent=2)  # Save last 500
        with open(app.config['ANOMALY_FILE'], 'w') as f:
            json.dump(anomalies[-200:], f, indent=2)  # Save last 200
    except Exception as e:
        logger.error(f"Error saving data: {e}")

# Routes
@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/api/stats')
def get_stats():
    """Get statistics for dashboard"""
    try:
        return jsonify(get_stats_data())
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages')
def get_messages():
    """Get recent messages"""
    try:
        limit = int(request.args.get('limit', 50))
        return jsonify(messages[-limit:])
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/anomalies')
def get_anomalies():
    """Get anomalies"""
    try:
        limit = int(request.args.get('limit', 50))
        return jsonify(anomalies[-limit:])
    except Exception as e:
        logger.error(f"Error getting anomalies: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/anomalies/<anomaly_id>/resolve', methods=['POST'])
def resolve_anomaly(anomaly_id):
    """Mark an anomaly as resolved"""
    global anomalies
    for a in anomalies:
        if a['id'] == anomaly_id:
            a['resolved'] = True
            save_data()
            return jsonify({'success': True})
    return jsonify({'error': 'Anomaly not found'}), 404

@app.route('/api/simulation/start', methods=['POST'])
def start_simulation():
    """Start continuous message simulation"""
    global simulation_active, simulation_thread
    
    if not simulation_active:
        simulation_active = True
        simulation_thread = threading.Thread(target=simulation_worker)
        simulation_thread.daemon = True
        simulation_thread.start()
        logger.info("Simulation started")
        return jsonify({'status': 'started', 'active': True})
    return jsonify({'status': 'already_running', 'active': True})

@app.route('/api/simulation/stop', methods=['POST'])
def stop_simulation():
    """Stop continuous message simulation"""
    global simulation_active
    
    if simulation_active:
        simulation_active = False
        logger.info("Simulation stopped")
        return jsonify({'status': 'stopped', 'active': False})
    return jsonify({'status': 'already_stopped', 'active': False})

@app.route('/api/simulation/status')
def simulation_status():
    """Get simulation status"""
    return jsonify({
        'active': simulation_active,
        'message_count': len(messages),
        'anomaly_count': len(anomalies)
    })

@app.route('/api/simulation/generate', methods=['POST'])
def generate_single():
    """Generate a single test message"""
    data = request.json or {}
    msg_type = data.get('message_type')
    force_anomaly = data.get('force_anomaly', False)
    
    msg = generate_hl7_message(msg_type=msg_type, include_anomaly=force_anomaly)
    return jsonify(msg)

@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'simulation_active': simulation_active,
        'messages': len(messages),
        'anomalies': len(anomalies)
    })

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

# Load initial data
load_data()

# Auto-start simulation on app startup
if os.environ.get('AUTO_START_SIMULATION', 'true').lower() == 'true':
    simulation_active = True
    simulation_thread = threading.Thread(target=simulation_worker)
    simulation_thread.daemon = True
    simulation_thread.start()
    logger.info("Simulation auto-started")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)