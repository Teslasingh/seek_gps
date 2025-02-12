import os
import re
import random
import logging
from datetime import datetime
from functools import wraps
import pytz

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    Response,
    Blueprint,
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from werkzeug.security import generate_password_hash, check_password_hash

# ------------------------------------------------------------------------------
# Application Configuration & Logging
# ------------------------------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = '458266'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email configuration – Replace these with your SMTP server details!
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587  # or 465 for SSL
app.config['MAIL_USE_TLS'] = True  # or MAIL_USE_SSL = True
app.config['MAIL_USERNAME'] = 'seekbuslocator@gmail.com'
app.config['MAIL_PASSWORD'] = 'ulsscrjmpknjdxza'
app.config['MAIL_DEFAULT_SENDER'] = 'seekbuslocator@gmail.com'

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

def get_ist_time():
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Database Models
# ------------------------------------------------------------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    confirmed = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class DeviceData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=get_ist_time)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    speed = db.Column(db.Float)
    satellite = db.Column(db.Integer)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ------------------------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------------------------
def send_email(to, subject, html):
    try:
        msg = Message(subject, recipients=[to], html=html)
        mail.send(msg)
        logger.info(f"Email sent to {to}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

def validate_password(password):
    # Password must be at least 8 characters and include one digit and one special character.
    if len(password) < 8:
        return False
    if not re.search(r'\d', password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True

# ------------------------------------------------------------------------------
# Email Authentication Routes
# ------------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))
        if not validate_password(password):
            flash('Password must be at least 8 characters long and contain at least one number and one special character.', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email address already exists.', 'danger')
            return redirect(url_for('register'))

        # Generate a 6-digit OTP and store in session.
        otp = str(random.randint(100000, 999999))
        session['otp'] = otp
        session['email'] = email
        session['password'] = password

        subject = "Your OTP for Registration"
        html = render_template('otp_email.html', otp=otp)
        send_email(email, subject, html)

        flash('An OTP has been sent to your email. Please check your inbox.', 'info')
        return redirect(url_for('verify_otp'))
    return render_template('register.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if request.method == 'POST':
        user_otp = request.form['otp']
        if 'otp' in session and user_otp == session['otp']:
            new_user = User(email=session['email'])
            new_user.set_password(session['password'])
            new_user.confirmed = True
            db.session.add(new_user)
            db.session.commit()
            session.pop('otp', None)
            session.pop('email', None)
            session.pop('password', None)
            flash('Registration successful! You can now log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid OTP. Please try again.', 'danger')
    return render_template('verify_otp.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            if not user.confirmed:
                flash('Please confirm your email address first.', 'warning')
                return redirect(url_for('login'))
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('gps.monitor'))
        else:
            flash('Invalid email or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = serializer.dumps(email, salt='password-reset')
            reset_url = url_for('reset_password', token=token, _external=True)
            html = render_template('reset_email.html', reset_url=reset_url)
            subject = "Password Reset Requested"
            send_email(email, subject, html)
            flash('A password reset email has been sent.', 'info')
        else:
            flash('Email address not found.', 'danger')
        return redirect(url_for('login'))
    return render_template('forgot.html')

@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset', max_age=3600)
    except SignatureExpired:
        flash('The password reset link has expired.', 'danger')
        return redirect(url_for('forgot_password'))
    except BadSignature:
        flash('Invalid password reset token.', 'danger')
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        user = User.query.filter_by(email=email).first_or_404()
        new_password = request.form['password']
        confirm_password = request.form['confirm_password']
        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('reset_password', token=token))
        if not validate_password(new_password):
            flash('Password must be at least 8 characters long and contain at least one number and one special character.', 'danger')
            return redirect(url_for('reset_password', token=token))
        user.set_password(new_password)
        db.session.commit()
        flash('Your password has been updated!', 'success')
        return redirect(url_for('login'))
    return render_template('reset.html', token=token)

# ------------------------------------------------------------------------------
# GPS Blueprint: User Interface & Device API Endpoints
# ------------------------------------------------------------------------------
gps_bp = Blueprint('gps', __name__, url_prefix='/gps')

# Hardcoded credentials for the device API.
VALID_USERNAME = "admin"
VALID_PASSWORD = "458266"

def api_auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not (auth.username == VALID_USERNAME and auth.password == VALID_PASSWORD):
            return Response(
                'Could not verify your access level for that URL.\n'
                'You have to login with proper credentials',
                401,
                {'WWW-Authenticate': 'Basic realm="GPS Service"'},
            )
        return f(*args, **kwargs)
    return decorated

# Endpoint for devices to send GPS data.
@gps_bp.route('/api/data', methods=['POST'])
@api_auth_required
def save_gps_data():
    data = request.get_json()
    if not data:
        logger.error('Missing JSON data')
        return jsonify({'error': 'Missing JSON data'}), 400

    device_id = data.get('device_id')
    lat = data.get('lat')
    lng = data.get('lng')
    speed = data.get('speed', None)
    satellite = data.get('satellite', None)

    if not device_id or lat is None or lng is None:
        logger.error('Missing required fields')
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        lat = float(lat)
        lng = float(lng)
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            logger.error('Invalid latitude or longitude')
            return jsonify({'error': 'Invalid latitude or longitude'}), 400
        if speed is not None:
            speed = float(speed)
        if satellite is not None:
            satellite = int(satellite)
    except ValueError as e:
        logger.error(f'Invalid data type for numeric fields: {e}')
        return jsonify({'error': 'Invalid data type for numeric fields'}), 400

    try:
        record = DeviceData(device_id=device_id, lat=lat, lng=lng, speed=speed, satellite=satellite)
        db.session.add(record)
        db.session.commit()
        logger.info(f"GPS data saved for device {device_id}: {lat}, {lng}")
        return jsonify({'message': f"Data saved successfully for device {device_id}"}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to save GPS data: {e}")
        return jsonify({'error': 'Failed to save GPS data'}), 500

# User Interface Endpoints

# This monitor page should include UI code (e.g., JavaScript) that fetches GPS data
# using the correct URL format: `/gps/data/<device_id>`
@gps_bp.route('/', methods=['GET'])
@login_required
def monitor():
    return render_template('gps_monitor.html')

@gps_bp.route('/data/<device_id>', methods=['GET'])
@login_required
def get_gps_data_ui(device_id):
    record = DeviceData.query.filter_by(device_id=device_id).order_by(DeviceData.timestamp.desc()).first()
    if record:
        return jsonify({
            'timestamp': record.timestamp.isoformat(),
            'device_id': record.device_id,
            'lat': record.lat,
            'lng': record.lng,
            'speed': record.speed,
            'satellite': record.satellite
        }), 200
    else:
        return jsonify({'error': f"No data found for device {device_id}"}), 404

# Register the GPS blueprint.
app.register_blueprint(gps_bp)

# ------------------------------------------------------------------------------
# Main: Create Database Tables and Run the Application
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, ssl_context=('localhost.pem', 'localhost-key.pem'), debug=True)