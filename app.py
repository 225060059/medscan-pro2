import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from flask_bcrypt import Bcrypt # Encryption tool
from twilio.rest import Client  # SMS tool
import datetime
import smtplib
import tempfile
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from fpdf import FPDF

app = Flask(__name__)
CORS(app)
bcrypt = Bcrypt(app) # Initialize encryption

# ==========================================
# 🔑 CONFIGURATION (EDIT THESE!)
# ==========================================
# EMAIL SETTINGS
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "ritetive@gmail.com"
SENDER_PASSWORD = "wihs ljqt lpag ngll"

# SMS SETTINGS (Get these from Twilio.com)
TWILIO_SID = "YOUR_TWILIO_SID"
TWILIO_TOKEN = "YOUR_TWILIO_AUTH_TOKEN"
TWILIO_PHONE = "+1234567890"

# ==========================================
# 💽 DATABASE
# ==========================================
try:
    # Local Database Connection
    # Connect to Cloud DB if available, otherwise use Local DB
mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/medscan_pro')
client = MongoClient(mongo_uri)
    db = client['medscan_pro']
    patients_col = db['patients']
    logs_col = db['logs']
    users_col = db['users'] # Collection for Doctors
    print("✅ Connected to MongoDB successfully.")
except Exception as e:
    print(f"❌ DB Error: {e}")

# --- LOGGING ---
def log_action(action, details):
    try:
        logs_col.insert_one({
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "details": details
        })
        # Keep log clean (max 50 entries)
        if logs_col.count_documents({}) > 50:
            logs_col.delete_one({"_id": logs_col.find().sort("timestamp", 1).limit(1)[0]["_id"]})
    except Exception as e:
        print(f"Log Error: {e}")

# --- SETUP DEFAULT ADMIN ---
def init_db():
    try:
        if users_col.count_documents({}) == 0:
            hashed_pw = bcrypt.generate_password_hash("1234").decode('utf-8')
            users_col.insert_one({"username": "admin", "password": hashed_pw, "role": "Chief MD"})
            print("👤 Admin user created (User: admin, Pass: 1234)")
    except Exception as e:
        print(f"Init DB Error: {e}")

init_db()

# ==========================================
# 🔐 AUTH ROUTES
# ==========================================

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = users_col.find_one({"username": data['username']})
    
    if user and bcrypt.check_password_hash(user['password'], data['password']):
        log_action("LOGIN", f"User {data['username']} logged in")
        return jsonify({"message": "Login Success", "role": user['role']})
    
    return jsonify({"error": "Invalid Credentials"}), 401

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    hashed_pw = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    users_col.insert_one({"username": data['username'], "password": hashed_pw, "role": "Doctor"})
    return jsonify({"message": "Doctor added"})

# ==========================================
# 📱 SMS ROUTE
# ==========================================
@app.route('/sms/<patient_id>', methods=['POST'])
def send_sms(patient_id):
    data = request.json
    phone = data.get('phone')
    
    patient = patients_col.find_one({"id": patient_id})
    if not patient: return jsonify({"error": "Not found"}), 404

    message_body = f"MedScan Update: Dear {patient['name']}, your report for {patient['diag']} is ready. Please check your email."

    try:
        if TWILIO_SID == "YOUR_TWILIO_SID":
            print(f"⚠️ SIMULATION SMS to {phone}: {message_body}")
            log_action("SMS", f"Simulated SMS sent to {phone}")
            return jsonify({"message": "Simulation SMS Sent (Configure Twilio for real SMS)"})
        
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        message = client.messages.create(body=message_body, from_=TWILIO_PHONE, to=phone)
        log_action("SMS", f"SMS sent to {phone}")
        return jsonify({"message": "SMS Sent Successfully"})
        
    except Exception as e:
        print(f"SMS Error: {e}")
        return jsonify({"error": str(e)}), 500

# ==========================================
# 🏥 PATIENT ROUTES
# ==========================================
@app.route('/patients', methods=['GET', 'POST'])
def handle_patients():
    if request.method == 'GET':
        return jsonify(list(patients_col.find({}, {'_id': 0})))
    
    data = request.json
    count = patients_col.count_documents({})
    new_rec = {
        "id": f"P-{1001 + count}",
        "name": data['name'], 
        "diag": data['diag'],
        "email": data.get('email', ''), # Capture email if sent
        "date": datetime.datetime.now().strftime("%Y-%m-%d")
    }
    patients_col.insert_one(new_rec)
    new_rec.pop('_id', None)
    log_action("CREATE", f"Added {data['name']}")
    return jsonify({"message": "Saved", "patient": new_rec})

@app.route('/patients/<pid>', methods=['DELETE'])
def delete_patient(pid):
    patients_col.delete_one({"id": pid})
    log_action("DELETE", f"Deleted {pid}")
    return jsonify({"message": "Deleted"})

@app.route('/predict', methods=['POST'])
def predict():
    # This just logs the result for now. The frontend handles the image.
    log_action("AI SCAN", f"Detected {request.json.get('message')}")
    return jsonify({"reply": "Logged"})

@app.route('/logs', methods=['GET'])
def get_logs():
    return jsonify(list(logs_col.find({}, {'_id': 0}).sort("timestamp", -1)))

# ==========================================
# 📧 EMAIL & PDF ROUTE (FULL CODE)
# ==========================================
@app.route('/email/<pid>', methods=['POST'])
def send_email(pid):
    data = request.json
    recipient_email = data.get('email')

    print(f"1. Starting Email Process for Patient {pid} to {recipient_email}")

    # 1. Get Patient Data
    patient = patients_col.find_one({"id": pid})
    if not patient:
        print("❌ Patient not found in DB")
        return jsonify({"error": "Patient not found"}), 404

    try:
        # 2. Generate PDF
        print("2. Generating PDF...")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        
        pdf.cell(200, 10, txt="MedScan Pro - Diagnostic Report", ln=1, align='C')
        pdf.cell(200, 10, txt="------------------------------------------------", ln=1, align='C')
        pdf.cell(200, 10, txt=f"Patient ID: {patient['id']}", ln=1)
        pdf.cell(200, 10, txt=f"Patient Name: {patient['name']}", ln=1)
        pdf.cell(200, 10, txt=f"Diagnosis: {patient['diag']}", ln=1)
        pdf.cell(200, 10, txt=f"Date: {patient['date']}", ln=1)
        
        pdf.cell(200, 10, txt="------------------------------------------------", ln=1, align='C')
        pdf.multi_cell(0, 10, txt="This is an automated report generated by the MedScan Pro AI System. Please consult a dermatologist for confirmation.")

        # Save to temporary file
        temp_dir = tempfile.gettempdir()
        pdf_path = os.path.join(temp_dir, f"Report_{pid}.pdf")
        pdf.output(pdf_path)
        print(f"✅ PDF saved at {pdf_path}")

        # 3. Setup Email
        print("3. Connecting to Gmail...")
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = recipient_email
        msg['Subject'] = f"Medical Report: {patient['name']}"
        
        body = f"Dear Patient,\n\nPlease find attached your diagnostic report for {patient['diag']}.\n\nBest regards,\nMedScan Pro Team"
        msg.attach(MIMEText(body, 'plain'))

        # 4. Attach PDF
        with open(pdf_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename=Report_{pid}.pdf")
        msg.attach(part)

        # 5. Send via Gmail
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        text = msg.as_string()
        server.sendmail(SENDER_EMAIL, recipient_email, text)
        server.quit()

        print("✅ Email sent successfully!")
        log_action("EMAIL", f"Report sent to {recipient_email}")
        return jsonify({"message": "Email Sent Successfully!"})

    except Exception as e:
        print(f"❌ ERROR SENDING EMAIL: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)