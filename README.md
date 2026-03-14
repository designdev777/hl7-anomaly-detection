# HL7 Anomaly Detection System - Live Simulation Edition

Real-time HL7 message anomaly detection with continuous simulation, start/stop controls, and full message viewing.

## ✨ Features

- **Continuous Message Simulation**: Generates realistic HL7 messages every 1-5 seconds
- **Anomaly Detection**: 10+ anomaly patterns with severity levels (critical, high, medium, low)
- **Start/Stop Controls**: Pause and resume simulation at any time
- **Full HL7 Message Viewing**: See complete HL7 messages with syntax highlighting
- **Real-time Updates**: WebSocket connections for live data streaming
- **Multiple Message Types**: ADT^A01, ADT^A02, ADT^A03, ORM^O01, ORU^R01
- **Anomaly Resolution**: Mark anomalies as resolved
- **Responsive Dashboard**: Works on desktop and mobile
- **Render.com Ready**: One-click deploy to free tier

## 🚀 Live Demo

[https://hl7-anomaly-detection.onrender.com](https://hl7-anomaly-detection.onrender.com)

## 📋 Anomaly Types

| Type | Severity | Description |
|------|----------|-------------|
| missing_field | High | Missing required PID segment field |
| invalid_format | High | Invalid date format in EVN segment |
| sequence_error | Medium | Out of sequence message |
| duplicate | Low | Duplicate message ID detected |
| patient_mismatch | High | Patient ID mismatch between segments |
| missing_segment | High | Required EVN segment missing |
| invalid_hl7_structure | Critical | Invalid HL7 message structure |
| wrong_message_type | Medium | Message type doesn't match content |
| future_timestamp | Low | Message timestamp is in the future |
| invalid_encoding | Medium | Invalid encoding characters |

## 🚀 One-Click Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

## 🛠️ Local Development

```bash
# Clone repository
git clone https://github.com/yourusername/hl7-anomaly-detection.git
cd hl7-anomaly-detection

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run locally
python app/main.py

# Visit http://localhost:5000