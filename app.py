import os
import re
import datetime
import uuid
import json
import random
import razorpay
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_mail import Mail, Message
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

# Base Directory Setup
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env')) # Load environment variables early

from models import db, User, Turf, Booking, TurfOffDate, WithdrawalRequest, RateLimit, IdempotencyRecord
from functools import wraps
from flask import abort

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'cricza-development-secret-key-2024')
app.config['SECRET_KEY'] = app.secret_key

@app.errorhandler(429)
def handle_429(e):
    if request.path.startswith('/api/'):
        return jsonify({
            'success': False,
            'message': 'Too many requests. Please try again later.'
        }), 429
    return render_template('ratelimit.html', retry_after=None), 429
# Database Configuration
# Priorities: 1. Environment Variable (Neon/Postgres), 2. Local SQLite v11
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'cricza_v11.db'))
# Fixed: PostgreSQL requires the 'postgresql://' prefix, but some providers like Heroku/Neon might provide 'postgres://'
if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgres://"):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Environment already loaded above

# OAuth Setup
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# Email Configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
app.config['REMEMBER_COOKIE_DURATION'] = datetime.timedelta(days=30)
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

mail = Mail(app)

def send_email(subject, recipient, template, **kwargs):
    """Sends an asynchronous HTML email with the Cricza logo embedded and logs errors to a file."""
    try:
        msg = Message(subject, recipients=[recipient])
        msg.html = render_template(template, **kwargs)
        
        # Embed Logo
        logo_path = os.path.join(app.static_folder, 'image', 'logo.png')
        if os.path.exists(logo_path):
            with app.open_resource(logo_path) as fp:
                msg.attach("logo.png", "image/png", fp.read(), headers={'Content-ID': '<logo>'})
        
        mail.send(msg)
        return True
    except Exception as e:
        error_msg = f"[{datetime.datetime.now()}] Failed to send email to {recipient}: {str(e)}\n"
        print(error_msg)
        with open("email_error.log", "a") as f:
            f.write(error_msg)
        return False

# Razorpay Setup (Cricza Account Helper)
def get_admin_razorpay_creds():
    """Fetches the latest admin credentials from the environment."""
    key_id = os.getenv('RAZORPAY_KEY_ID', '').strip()
    key_secret = os.getenv('RAZORPAY_KEY_SECRET', '').strip()
    return key_id, key_secret

def is_valid_email(email):
    """Validates email format using a standard regex pattern."""
    if not email:
        return False
    # Standard email regex: user@domain.extension
    regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(regex, email) is not None

def rate_limit(limit, period_seconds):
    """Decorator to limit requests per IP/User for a specific endpoint."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            key = f"{request.remote_addr}:{request.path}"
            if current_user.is_authenticated:
                key = f"user_{current_user.id}:{request.path}"
            
            now = datetime.datetime.utcnow()
            record = RateLimit.query.filter_by(key=key).first()
            
            if not record:
                record = RateLimit(key=key, hits=1, period_start=now, last_hit=now)
                db.session.add(record)
            else:
                if now > record.period_start + datetime.timedelta(seconds=period_seconds):
                    record.hits = 1
                    record.period_start = now
                else:
                    record.hits += 1
                record.last_hit = now
            
            db.session.commit()
            
            if record.hits > limit:
                retry_after = int((record.period_start + datetime.timedelta(seconds=period_seconds) - now).total_seconds())
                if request.path.startswith('/api/'):
                    return jsonify({
                        'success': False, 
                        'message': 'Too many requests. Please try again later.',
                        'retry_after': retry_after
                    }), 429
                return render_template('ratelimit.html', retry_after=retry_after), 429
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def idempotent():
    """Decorator to prevent duplicate processing of the same request using an idempotency key."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            key = request.headers.get('X-Idempotency-Key')
            if not key and request.is_json:
                key = request.json.get('idempotency_key')
            
            if not key:
                return f(*args, **kwargs)
            
            record = IdempotencyRecord.query.filter_by(idempotency_key=key).first()
            if record:
                return jsonify(json.loads(record.response_body)), record.status_code
            
            response = f(*args, **kwargs)
            
            resp_obj, status_code = response if isinstance(response, tuple) else (response, 200)
            
            try:
                # Clean response body for storage
                body = resp_obj.get_json() if hasattr(resp_obj, 'get_json') else resp_obj
                new_record = IdempotencyRecord(
                    idempotency_key=key,
                    user_id=current_user.id if current_user.is_authenticated else None,
                    endpoint=request.path,
                    response_body=json.dumps(body),
                    status_code=status_code
                )
                db.session.add(new_record)
                db.session.commit()
            except:
                db.session.rollback()
                record = IdempotencyRecord.query.filter_by(idempotency_key=key).first()
                if record:
                    return jsonify(json.loads(record.response_body)), record.status_code
            
            return response
        return decorated_function
    return decorator

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    pagination = Turf.query.filter_by(is_suspended=False).paginate(page=page, per_page=9, error_out=False)
    turfs = pagination.items
    return render_template('index.html', turfs=turfs, pagination=pagination)

@app.route('/about')
def about():
    return render_template('index.html')

@app.route('/partner')
def partner():
    return render_template('partner.html')

@app.route('/contact')
def contact():
    return render_template('index.html')

@app.route('/api/contact', methods=['POST'])
@rate_limit(3, 60)
def handle_contact():
    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    subject = data.get('subject', '').strip()
    message = data.get('message', '').strip()

    if not all([name, email, subject, message]):
        return jsonify({'success': False, 'message': 'All fields are required.'}), 400

    if not is_valid_email(email):
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400

    # 1. Send Confirmation Email to Customer
    send_email(
        subject="We Received Your Message - Cricza",
        recipient=email,
        template="emails/contact_confirmation.html",
        user_name=name,
        subject_text=subject
    )

    # 2. Send Inquiry Email to Cricza Support
    send_email(
        subject=f"New Inquiry: {subject}",
        recipient="criczaservices@gmail.com",
        template="emails/contact_inquiry.html",
        user_name=name,
        user_email=email,
        inquiry_subject=subject,
        message=message
    )

    return jsonify({'success': True, 'message': 'Thank you! Your message has been sent successfully.'})

@app.route('/policies')
def policies():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
@rate_limit(5, 60)
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            if user.role == 'Admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'Owner':
                return redirect(url_for('owner_dashboard'))
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password.')
    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
@rate_limit(2, 60)
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Generate 6-digit OTP
            otp = str(random.randint(100000, 999999))
            user.reset_otp = otp
            user.otp_expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=10)
            db.session.commit()
            
            # Send Email
            send_email(
                subject="Password Reset OTP - Cricza",
                recipient=user.email,
                template="emails/otp_email.html",
                otp=otp
            )
            
            session['reset_email'] = email
            flash('A 6-digit OTP has been sent to your email.')
            return redirect(url_for('verify_otp'))
        else:
            flash('Email address not found.')
            
    return render_template('forgot_password.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'reset_email' not in session:
        return redirect(url_for('forgot_password'))
        
    if request.method == 'POST':
        otp = request.form.get('otp')
        email = session.get('reset_email')
        user = User.query.filter_by(email=email).first()
        
        if user and user.reset_otp == otp:
            if datetime.datetime.utcnow() < user.otp_expiry:
                session['otp_verified'] = True
                return redirect(url_for('reset_password'))
            else:
                flash('OTP has expired. Please request a new one.')
                return redirect(url_for('forgot_password'))
        else:
            flash('Invalid OTP code. Please try again.')
            
    return render_template('verify_otp.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if not session.get('otp_verified') or 'reset_email' not in session:
        return redirect(url_for('forgot_password'))
        
    if request.method == 'POST':
        password = request.form.get('password')
        confirm = request.form.get('confirm_password')
        
        if password != confirm:
            flash('Passwords do not match.')
            return render_template('reset_password.html')
            
        email = session.get('reset_email')
        user = User.query.filter_by(email=email).first()
        
        if user:
            user.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
            user.reset_otp = None
            user.otp_expiry = None
            db.session.commit()
            
            session.pop('reset_email', None)
            session.pop('otp_verified', None)
            
            flash('Password updated successfully! You can now log in.')
            return redirect(url_for('login'))
            
    return render_template('reset_password.html')

@app.route('/register', methods=['GET', 'POST'])
@rate_limit(3, 60)
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        
        if not is_valid_email(email):
            flash('Please enter a valid email address (e.g., user@gmail.com).')
            return redirect(url_for('register'))
            
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already exists.')
            return redirect(url_for('register'))
            
        new_user = User(
            name=name, 
            email=email, 
            phone=request.form.get('phone'),
            password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
            role='Customer'
        )
        db.session.add(new_user)
        db.session.commit()
        
        # Send Welcome Email
        send_email(
            subject="Welcome to Cricza!",
            recipient=new_user.email,
            template="emails/welcome.html",
            user_name=new_user.name,
            explore_url=url_for('index', _external=True)
        )
        
        login_user(new_user, remember=True)
        return redirect(url_for('index'))
            
    return render_template('register.html')

@app.route('/register/partner', methods=['GET', 'POST'])
@rate_limit(3, 60)
def register_partner():
    plan = request.args.get('plan', 'Free Trial')
    price = request.args.get('price', '0')
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        
        if not is_valid_email(email):
            flash('Please enter a valid email address (e.g., owner@outlook.com).')
            return redirect(url_for('register_partner', plan=plan, price=price))
            
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already registered.')
            return redirect(url_for('register_partner', plan=plan, price=price))
            
        now = datetime.datetime.utcnow()
        # Creating an owner with subscription
        # Trial is 31 days just to be safe for a full month
        duration = 31 if plan == 'Free Trial' else 30
        
        new_owner = User(
            name=name, 
            email=email, 
            phone=request.form.get('phone'),
            password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
            role='Owner',
            subscription_plan=plan,
            subscription_price=float(price),
            subscription_start=now,
            subscription_end=now if float(price) > 0 else now + datetime.timedelta(days=duration)
        )
        db.session.add(new_owner)
        db.session.commit()
        
        login_user(new_owner, remember=True)
        
        if float(price) > 0:
            # For paid plans, we let the template trigger the Razorpay modal
            return render_template('register_owner.html', plan=plan, price=price, registration_success=True)
        
        # Send Subscription Email (Free Trial)
        send_email(
            subject="Welcome Partner - Cricza",
            recipient=current_user.email,
            template="emails/subscription_confirmation.html",
            user_name=current_user.name,
            plan_name=plan,
            end_date=current_user.subscription_end.strftime('%Y-%m-%d'),
            dashboard_url=url_for('owner_dashboard', _external=True)
        )
        
        flash(f'Registration Successful! You are now on the {plan}.')
        return redirect(url_for('owner_dashboard'))
        
    return render_template('register_owner.html', plan=plan, price=price)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/login/google')
def google_login():
    redirect_uri = url_for('google_authorize', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/login/google/authorize')
def google_authorize():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    
    if not user_info:
        # Fallback if id_token doesn't have userinfo for some reason
        resp = google.get('https://www.googleapis.com/oauth2/v3/userinfo')
        user_info = resp.json()
    
    # User info looks like: {'sub': '...', 'name': '...', 'given_name': '...', 'family_name': '...', 'picture': '...', 'email': '...', 'email_verified': True, 'locale': 'en'}
    google_id = user_info.get('sub')
    email = user_info.get('email')
    name = user_info.get('name')
    picture = user_info.get('picture')

    # 1. Try to find user by google_id
    user = User.query.filter_by(google_id=google_id).first()
    
    if not user:
        # 2. If not found, try to find user by email
        user = User.query.filter_by(email=email).first()
        if user:
            # Link google_id to existing account
            user.google_id = google_id
        else:
            # 3. Create new user
            user = User(
                name=name,
                email=email,
                google_id=google_id,
                role='Customer' # Default role
            )
            db.session.add(user)
            db.session.commit() # Commit to ensure user has ID if needed, though send_email doesn't use it yet
            
            # Send Welcome Email
            send_email(
                subject="Welcome to Cricza!",
                recipient=user.email,
                template="emails/welcome.html",
                user_name=user.name,
                explore_url=url_for('index', _external=True)
            )
    
    # 4. Always update name and profile picture from Google as requested
    user.name = name
    user.profile_pic = picture
    db.session.commit()

    login_user(user, remember=True)
    flash(f"Welcome back, {user.name}!")
    return redirect(url_for('index'))

@app.route('/booking')
@login_required
def my_bookings():
    # Strictly show only Success or Manual bookings to the user
    bookings = Booking.query.filter(
        Booking.customer_id == current_user.id,
        (
            (Booking.payment_status == 'Success') |
            (Booking.razorpay_order_id == 'MANUAL')
        )
    ).order_by(Booking.created_at.desc()).all()
    b_delta = datetime.timedelta(hours=5, minutes=30)
    return render_template('booking.html', bookings=bookings, b_delta=b_delta)

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

# =============================================
#   ADMIN ROUTES
# =============================================

@app.route('/dashboard/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'Admin':
        return redirect(url_for('index'))
    turfs = Turf.query.all()
    owners = User.query.filter_by(role='Owner').all()
    customers = User.query.filter_by(role='Customer').all()
    pending_withdrawals = WithdrawalRequest.query.filter_by(status='Pending').all()
    paid_withdrawals = WithdrawalRequest.query.filter_by(status='Paid').order_by(WithdrawalRequest.paid_at.desc()).all()
    return render_template('dashboard_admin.html', turfs=turfs, owners=owners, customers=customers, 
                           pending_withdrawals=pending_withdrawals, paid_withdrawals=paid_withdrawals)

@app.route('/api/admin/turf/<int:turf_id>/toggle', methods=['POST'])
@login_required
def admin_toggle_turf(turf_id):
    if current_user.role != 'Admin':
         flash('Unauthorized access.')
         return redirect(url_for('index'))
    turf = db.session.get(Turf, turf_id)
    if turf:
        turf.is_suspended = not turf.is_suspended
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/api/admin/turf/<int:turf_id>/delete', methods=['POST'])
@login_required
def admin_delete_turf(turf_id):
    if current_user.role != 'Admin':
         flash('Unauthorized access.')
         return redirect(url_for('index'))
    turf = db.session.get(Turf, turf_id)
    if turf:
        db.session.delete(turf)
        db.session.commit()
        flash('Turf successfully deleted.')
    return redirect(url_for('admin_dashboard'))

@app.route('/api/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if current_user.role != 'Admin':
         flash('Unauthorized access.')
         return redirect(url_for('index'))
    user = db.session.get(User, user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash('User profile successfully deleted.')
    return redirect(url_for('admin_dashboard'))

@app.route('/api/admin/user/<int:user_id>/cancel-subscription', methods=['POST'])
@login_required
def admin_cancel_subscription(user_id):
    if current_user.role != 'Admin':
         flash('Unauthorized access.')
         return redirect(url_for('index'))
    
    user = db.session.get(User, user_id)
    if user and user.role == 'Owner':
        # Expire subscription immediately
        user.subscription_end = datetime.datetime.utcnow()
        
        # Also suspend all their turfs
        for turf in user.turfs:
            turf.is_suspended = True
            
        db.session.commit()
        flash(f'Subscription for {user.name} has been cancelled and their turfs suspended.')
    return redirect(url_for('admin_dashboard'))

@app.route('/api/admin/withdrawal/<int:wd_id>/pay', methods=['POST'])
@login_required
def admin_pay_withdrawal(wd_id):
    if current_user.role != 'Admin':
         flash('Unauthorized access.')
         return redirect(url_for('index'))
    wd = db.session.get(WithdrawalRequest, wd_id)
    if wd and wd.status == 'Pending':
        wd.status = 'Paid'
        wd.paid_at = datetime.datetime.utcnow()
        db.session.commit()
        flash(f'Withdrawal marked as Paid for {wd.owner.name}.')
    return redirect(url_for('admin_dashboard'))

# =============================================
#   OWNER ROUTES
# =============================================

@app.route('/dashboard/owner')
@login_required
def owner_dashboard():
    if current_user.role != 'Owner':
        return redirect(url_for('index'))
    turfs = Turf.query.filter_by(owner_id=current_user.id).all()
    
    recent_bookings = []
    for turf in turfs:
        for booking in turf.bookings:
            # Only show Success or Manual bookings
            if booking.payment_status == 'Success' or booking.customer_id == current_user.id:
                recent_bookings.append({
                    'order_id': booking.razorpay_payment_id or booking.razorpay_order_id or 'MANUAL',
                    'turf_name': turf.name,
                    'customer_name': booking.offline_customer_name if booking.offline_customer_name else ("Manual Booking (Offline)" if booking.customer_id == current_user.id else (booking.customer.name if booking.customer else 'Unknown')),
                    'customer_email': booking.offline_customer_email or (booking.customer.email if booking.customer else 'N/A'),
                    'customer_phone': booking.offline_customer_phone or (booking.customer.phone if booking.customer else 'N/A'),
                    'is_manual': booking.customer_id == current_user.id,
                    'date': booking.date,
                    'time_slot': booking.time_slot,
                    'cost': booking.cost,
                    'created_at': (booking.created_at + datetime.timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p')
                })
    
    recent_bookings.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Withdrawal history
    withdrawals = WithdrawalRequest.query.filter_by(owner_id=current_user.id).order_by(WithdrawalRequest.created_at.desc()).all()
    
    # Flag if any turf is suspended by Admin
    any_suspended = any(t.is_suspended for t in turfs)
    b_delta = datetime.timedelta(hours=5, minutes=30)
    
    return render_template('dashboard_owner.html', 
                           turfs=turfs, 
                           wallet_balance=current_user.wallet_balance, 
                           recent_bookings=recent_bookings,
                           withdrawals=withdrawals,
                           any_suspended=any_suspended,
                           b_delta=b_delta)

@app.route('/api/turf/add', methods=['POST'])
@login_required
def add_turf():
    if current_user.role != 'Owner':
        return redirect(url_for('index'))
        
    name = request.form.get('name')
    description = request.form.get('description')
    location = request.form.get('location')
    pincode = request.form.get('pincode')
    price = float(request.form.get('price_per_hour', 0))
    photo_url = request.form.get('photo_url')
    open_time = int(request.form.get('open_time', 6))
    close_time = int(request.form.get('close_time', 23))
    
    new_turf = Turf(
        owner_id=current_user.id,
        name=name,
        description=description,
        location=location,
        pincode=pincode,
        price_per_hour=price,
        photo_url=photo_url,
        open_time=open_time,
        close_time=close_time
    )
    db.session.add(new_turf)
    db.session.commit()
    
    flash('Turf successfully hosted and public!')
    return redirect(url_for('owner_dashboard'))

@app.route('/api/turf/<int:turf_id>/edit', methods=['POST'])
@login_required
def edit_turf(turf_id):
    if current_user.role != 'Owner':
        return redirect(url_for('index'))
    turf = db.session.get(Turf, turf_id)
    if not turf or turf.owner_id != current_user.id:
        flash('Turf not found or unauthorized.')
        return redirect(url_for('owner_dashboard'))
    
    turf.name = request.form.get('name', turf.name)
    turf.description = request.form.get('description', turf.description)
    turf.location = request.form.get('location', turf.location)
    turf.pincode = request.form.get('pincode', turf.pincode)
    turf.price_per_hour = float(request.form.get('price_per_hour', turf.price_per_hour))
    turf.photo_url = request.form.get('photo_url', turf.photo_url)
    turf.open_time = int(request.form.get('open_time', turf.open_time))
    turf.close_time = int(request.form.get('close_time', turf.close_time))
    
    db.session.commit()
    flash(f'Turf "{turf.name}" updated successfully!')
    return redirect(url_for('owner_dashboard'))

@app.route('/api/turf/<int:turf_id>/off-date', methods=['POST'])
@login_required
def add_off_date(turf_id):
    if current_user.role != 'Owner':
        return redirect(url_for('index'))
    turf = db.session.get(Turf, turf_id)
    if not turf or turf.owner_id != current_user.id:
        flash('Turf not found or unauthorized.')
        return redirect(url_for('owner_dashboard'))
    
    off_date = request.form.get('off_date')
    if off_date:
        # Check if already exists
        existing = TurfOffDate.query.filter_by(turf_id=turf_id, off_date=off_date).first()
        if not existing:
            new_off = TurfOffDate(turf_id=turf_id, off_date=off_date)
            db.session.add(new_off)
            db.session.commit()
            flash(f'Off-date {off_date} added for {turf.name}.')
        else:
            flash(f'{off_date} is already marked as off.')
    return redirect(url_for('owner_dashboard'))

@app.route('/api/turf/<int:turf_id>/off-date/remove', methods=['POST'])
@login_required
def remove_off_date(turf_id):
    if current_user.role != 'Owner':
        return redirect(url_for('index'))
    turf = db.session.get(Turf, turf_id)
    if not turf or turf.owner_id != current_user.id:
        flash('Turf not found or unauthorized.')
        return redirect(url_for('owner_dashboard'))
    
    off_date = request.form.get('off_date')
    entry = TurfOffDate.query.filter_by(turf_id=turf_id, off_date=off_date).first()
    if entry:
        db.session.delete(entry)
        db.session.commit()
        flash(f'Off-date {off_date} removed for {turf.name}.')
    return redirect(url_for('owner_dashboard'))

@app.route('/api/turf/<int:turf_id>/coupon/add', methods=['POST'])
@login_required
def add_coupon(turf_id):
    if current_user.role != 'Owner':
        return redirect(url_for('index'))
    turf = db.session.get(Turf, turf_id)
    if not turf or turf.owner_id != current_user.id:
        flash('Turf not found or unauthorized.')
        return redirect(url_for('owner_dashboard'))
    
    code = request.form.get('code').strip().upper()
    discount = float(request.form.get('discount', 0))
    limit = int(request.form.get('limit', 10))
    expiry = request.form.get('expiry')
    
    if not code or not expiry:
        flash('Invalid coupon details.')
        return redirect(url_for('owner_dashboard'))

    # Delete existing if any
    from models import Coupon
    existing = Coupon.query.filter_by(turf_id=turf_id).first()
    if existing:
        db.session.delete(existing)
    
    # Check if code is unique globally
    if Coupon.query.filter_by(code=code).first():
        flash('Coupon code already exists in our system. Please choose a unique code.')
        return redirect(url_for('owner_dashboard'))

    new_coupon = Coupon(
        turf_id=turf_id,
        code=code,
        discount_amount=discount,
        usage_limit=limit,
        valid_until=expiry
    )
    db.session.add(new_coupon)
    db.session.commit()
    flash(f'Coupon "{code}" added for {turf.name}!')
    return redirect(url_for('owner_dashboard'))

@app.route('/api/turf/<int:turf_id>/coupon/remove', methods=['POST'])
@login_required
def remove_coupon(turf_id):
    if current_user.role != 'Owner':
        return redirect(url_for('index'))
    turf = db.session.get(Turf, turf_id)
    if not turf or turf.owner_id != current_user.id:
        flash('Turf not found or unauthorized.')
        return redirect(url_for('owner_dashboard'))
    
    from models import Coupon
    coupon = Coupon.query.filter_by(turf_id=turf_id).first()
    if coupon:
        db.session.delete(coupon)
        db.session.commit()
        flash('Coupon removed.')
    return redirect(url_for('owner_dashboard'))

@app.route('/api/owner/withdraw', methods=['POST'])
@login_required
def request_withdrawal():
    if current_user.role != 'Owner':
        return redirect(url_for('index'))
    
    # Calculate current balance
    total_revenue = 0
    turfs = Turf.query.filter_by(owner_id=current_user.id).all()
    for turf in turfs:
        for booking in turf.bookings:
            total_revenue += booking.cost
    
    paid = sum(w.amount for w in current_user.withdrawals if w.status == 'Paid')
    pending = sum(w.amount for w in current_user.withdrawals if w.status == 'Pending')
    available = total_revenue - paid - pending
    
    if available <= 0:
        flash('No available balance to withdraw.')
        return redirect(url_for('owner_dashboard'))
    
    wd = WithdrawalRequest(
        owner_id=current_user.id,
        amount=round(available, 2),
        status='Pending'
    )
    db.session.add(wd)
    db.session.commit()
    flash(f'Withdrawal request of ${round(available, 2)} submitted!')
    return redirect(url_for('owner_dashboard'))

@app.route('/api/owner/update-keys', methods=['POST'])
@login_required
def update_owner_keys():
    if current_user.role != 'Owner':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    key_id = request.form.get('key_id', '').strip()
    key_secret = request.form.get('key_secret', '').strip()
    
    if not key_id or not key_secret:
        flash('Both Key ID and Key Secret are required.')
        return redirect(url_for('owner_dashboard'))
    
    current_user.razorpay_key_id = key_id
    current_user.razorpay_key_secret = key_secret
    db.session.commit()
    
    flash('Razorpay credentials updated successfully!')
    return redirect(url_for('owner_dashboard'))

@app.route('/api/owner/delete-keys', methods=['POST'])
@login_required
def delete_owner_keys():
    if current_user.role != 'Owner':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    current_user.razorpay_key_id = None
    current_user.razorpay_key_secret = None
    db.session.commit()
    
    flash('Razorpay credentials deleted successfully!')
    return redirect(url_for('owner_dashboard'))

# =============================================
#   BOOKING API ROUTES
# =============================================

@app.route('/api/turf/<int:turf_id>/booked_slots')
def get_booked_slots(turf_id):
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'booked_slots': [], 'is_off_date': False})
    
    # Check off-date
    is_off = TurfOffDate.query.filter_by(turf_id=turf_id, off_date=date_str).first()
    if is_off:
        return jsonify({'booked_slots': [], 'is_off_date': True})
    
    now = datetime.datetime.utcnow()
    bookings = Booking.query.filter(
        Booking.turf_id == turf_id,
        Booking.date == date_str,
        (
            (Booking.payment_status == 'Success') |
            (Booking.razorpay_order_id == 'MANUAL') |
            (
                (Booking.payment_status == 'Pending') &
                (Booking.created_at > now - datetime.timedelta(minutes=7))
            )
        )
    ).all()
    slots = []
    for b in bookings:
        slots.extend([s.strip() for s in b.time_slot.split(',')])

    # Past Slot Logic (IST Time)
    ist_now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    today_str = ist_now.strftime('%Y-%m-%d')
    if date_str == today_str:
        current_hour = ist_now.hour
        turf = db.session.get(Turf, turf_id)
        if turf:
            for hour in range(turf.open_time, turf.close_time):
                if hour <= current_hour:
                    slot_str = f"{hour}:00 - {hour+1}:00"
                    if slot_str not in slots:
                        slots.append(slot_str)

    return jsonify({'booked_slots': slots, 'is_off_date': False})

@app.route('/api/validate_coupon', methods=['POST'])
@rate_limit(10, 60)
def validate_coupon():
    data = request.json
    turf_id = data.get('turf_id')
    code = data.get('code', '').strip().upper()
    
    if not turf_id or not code:
        return jsonify({'success': False, 'message': 'Invalid data.'})

    from models import Coupon
    coupon = Coupon.query.filter_by(turf_id=turf_id, code=code).first()
    
    if not coupon:
        return jsonify({'success': False, 'message': 'Invalid coupon code.'})
    
    now_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    if coupon.valid_until < now_str:
        return jsonify({'success': False, 'message': 'This coupon has expired.'})
    
    if coupon.used_count >= coupon.usage_limit:
        return jsonify({'success': False, 'message': 'This coupon has reached its usage limit.'})
    
    return jsonify({
        'success': True, 
        'discount': coupon.discount_amount,
        'message': f'Coupon applied! ( -${coupon.discount_amount} )'
    })

@app.route('/api/payment/create-order', methods=['POST'])
@login_required
@rate_limit(3, 10)
@idempotent()
def create_booking_order():
    try:
        data = request.json
        turf_id = data.get('turf_id')
        time_slot = data.get('time_slot')
        cost = float(data.get('cost'))
        date_str = data.get('date')
        coupon_code = data.get('coupon_code')
        
        turf = db.session.get(Turf, turf_id)
        if not turf:
            return jsonify({'success': False, 'message': 'Turf not found.'}), 404
        
        # Check off-date
        is_off = TurfOffDate.query.filter_by(turf_id=turf.id, off_date=date_str).first()
        if is_off:
            return jsonify({'success': False, 'message': 'This turf is closed on the selected date.'}), 400
        
        # Overlap & Past Slot Check (Including Pending locks for 7 mins)
        requested_slots = [s.strip() for s in time_slot.split(',')]
        
        # Check against system time if booking for today
        ist_now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
        today_str = ist_now.strftime('%Y-%m-%d')
        if date_str == today_str:
            current_hour = ist_now.hour
            for s in requested_slots:
                try:
                    slot_hour = int(s.split(':')[0])
                    if slot_hour <= current_hour:
                        return jsonify({'success': False, 'message': f'Slot {s} has already passed.'}), 400
                except: continue

        now = datetime.datetime.utcnow()
        existing_bookings = Booking.query.filter(
            Booking.turf_id == turf.id,
            Booking.date == date_str,
            (
                (Booking.payment_status == 'Success') |
                (
                    (Booking.payment_status == 'Pending') &
                    (Booking.created_at > now - datetime.timedelta(minutes=7))
                )
            )
        ).all()
        already_booked = []
        for b in existing_bookings:
            already_booked.extend([s.strip() for s in b.time_slot.split(',')])
        
        conflicts = [s for s in requested_slots if s in already_booked]
        if conflicts:
            return jsonify({'success': False, 'message': f'Slots already booked or payment in progress: {", ".join(conflicts)}'}), 409
        
        # Recalculate cost on server to prevent manipulation or double-discount
        num_slots = len(requested_slots)
        base_cost = turf.price_per_hour * num_slots
        
        final_cost = base_cost
        applied_coupon_code = None
        
        if coupon_code:
            from models import Coupon
            coupon = Coupon.query.filter_by(turf_id=turf.id, code=coupon_code.upper()).first()
            if not coupon:
                return jsonify({'success': False, 'message': 'Invalid coupon code.'}), 400
                
            now_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')
            if coupon.valid_until < now_str:
                return jsonify({'success': False, 'message': 'This coupon has expired.'}), 400
                
            if coupon.used_count >= coupon.usage_limit:
                return jsonify({'success': False, 'message': 'This coupon has reached its usage limit.'}), 400
                
            final_cost = max(0, base_cost - coupon.discount_amount)
            applied_coupon_code = coupon.code
        
        # Determine Credentials
        owner = turf.owner
        admin_key_id, admin_key_secret = get_admin_razorpay_creds()
        
        use_admin_creds = True
        key_id = admin_key_id
        owner_has_creds = False

        if owner and owner.razorpay_key_id and owner.razorpay_key_secret:
            use_admin_creds = False
            key_id = owner.razorpay_key_id
            owner_has_creds = True
            temp_client = razorpay.Client(auth=(owner.razorpay_key_id, owner.razorpay_key_secret))
        else:
            temp_client = razorpay.Client(auth=(admin_key_id, admin_key_secret))
        
        # Create Razorpay Order
        # Amount in paise
        razorpay_order = temp_client.order.create({
            'amount': int(final_cost * 100),
            'currency': 'INR',
            'payment_capture': '1'
        })
        
        # Create Pending Booking
        booking = Booking(
            customer_id=current_user.id,
            turf_id=turf.id,
            date=date_str,
            time_slot=time_slot,
            cost=final_cost,
            razorpay_order_id=razorpay_order['id'],
            payment_status='Pending',
            payment_to='Owner' if owner_has_creds else 'Admin',
            coupon_code=applied_coupon_code
        )
        db.session.add(booking)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'order_id': razorpay_order['id'],
            'amount': final_cost * 100,
            'key_id': key_id,
            'booking_id': booking.id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/book_manual', methods=['POST'])
@login_required
@rate_limit(5, 60)
@idempotent()
def book_manual():
    if current_user.role != 'Owner':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    try:
        data = request.json
        turf_id = data.get('turf_id')
        time_slot = data.get('time_slot')
        cost = float(data.get('cost', 0))
        date_str = data.get('date')
        offline_name = data.get('offline_name')
        offline_email = data.get('offline_email')
        offline_phone = data.get('offline_phone')
        coupon_code = data.get('coupon_code')
        
        turf = db.session.get(Turf, turf_id)
        if not turf or turf.owner_id != current_user.id:
             return jsonify({'success': False, 'message': 'Turf not found or unauthorized.'}), 404
             
        # Coupon check for manual booking
        applied_coupon_code = None
        if coupon_code:
            from models import Coupon
            coupon = Coupon.query.filter_by(turf_id=turf.id, code=coupon_code.upper()).first()
            if coupon:
                now_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')
                if coupon.valid_until < now_str:
                    return jsonify({'success': False, 'message': 'This coupon has expired.'}), 400
                if coupon.used_count >= coupon.usage_limit:
                    return jsonify({'success': False, 'message': 'This coupon has reached its usage limit.'}), 400
                
                applied_coupon_code = coupon.code
                coupon.used_count += 1 # Instant success for manual

        # Past Slot Check for manual booking
        requested_slots = [s.strip() for s in time_slot.split(',')]
        ist_now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
        today_str = ist_now.strftime('%Y-%m-%d')
        if date_str == today_str:
            current_hour = ist_now.hour
            for s in requested_slots:
                try:
                    slot_hour = int(s.split(':')[0])
                    if slot_hour <= current_hour:
                        return jsonify({'success': False, 'message': f'Slot {s} has already passed.'}), 400
                except: continue

        # Create Success Booking directly since it's manual offline cash
        booking = Booking(
            customer_id=current_user.id, # Marked as owner's own booking
            turf_id=turf.id,
            date=date_str,
            time_slot=time_slot,
            cost=cost,
            razorpay_order_id='MANUAL',
            payment_status='Success',
            payment_to='Offline',
            offline_customer_name=offline_name,
            offline_customer_email=offline_email,
            offline_customer_phone=offline_phone,
            coupon_code=applied_coupon_code
        )
        db.session.add(booking)
        db.session.commit()
        
        # Send Booking Confirmation Email if email provided
        if offline_email:
            send_email(
                subject="Booking Confirmed - Cricza",
                recipient=offline_email,
                template="emails/booking_confirmation.html",
                user_name=offline_name or 'Valued Customer',
                booking_id=booking.id,
                turf_name=turf.name,
                date=booking.date,
                time_slot=booking.time_slot,
                amount=booking.cost,
                booking_time=(booking.created_at + datetime.timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p'),
                location=turf.location,
                owner_phone=current_user.phone or 'N/A',
                dashboard_url=url_for('index', _external=True)
            )
        
        return jsonify({'success': True, 'message': 'Manual booking recorded successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/booking/<int:booking_id>/cancel', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if booking and booking.customer_id == current_user.id and booking.payment_status == 'Pending':
        booking.payment_status = 'Cancelled'
        db.session.commit()
        return jsonify({'success': True, 'message': 'Slot released.'})
    return jsonify({'success': False, 'message': 'Could not cancel booking.'}), 400

@app.route('/api/payment/verify', methods=['POST'])
@login_required
@rate_limit(5, 60)
@idempotent()
def verify_booking_payment():
    data = request.json
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    booking_id = data.get('booking_id')
    
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({'success': False, 'message': 'Booking not found.'}), 404
    
    turf = booking.turf
    owner = turf.owner
    
    # Get current secret for verification
    admin_key_id, admin_key_secret = get_admin_razorpay_creds()
    
    secret = admin_key_secret
    active_key_id = admin_key_id
    
    if booking.payment_to == 'Owner' and owner and owner.razorpay_key_secret:
        secret = owner.razorpay_key_secret
        active_key_id = owner.razorpay_key_id
        
    try:
        # Verify signature
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        
        # Create a temp client just for verification
        v_client = razorpay.Client(auth=(active_key_id, secret))
        v_client.utility.verify_payment_signature(params_dict)
        
        # Payment verified
        booking.payment_status = 'Success'
        booking.razorpay_payment_id = razorpay_payment_id
        
        # If payment went to Admin, update owner's wallet
        if booking.payment_to == 'Admin' and owner:
            owner.wallet_balance += booking.cost
        
        # Increment coupon usage if applicable
        if booking.coupon_code:
            from models import Coupon
            cp = Coupon.query.filter_by(turf_id=booking.turf_id, code=booking.coupon_code).first()
            if cp:
                cp.used_count += 1
        
        db.session.commit()
        
        # Send Booking Confirmation Email to CUSTOMER
        send_email(
            subject="Booking Confirmed - Cricza",
            recipient=current_user.email,
            template="emails/booking_confirmation.html",
            user_name=current_user.name,
            booking_id=booking.id,
            turf_name=turf.name,
            date=booking.date,
            time_slot=booking.time_slot,
            amount=booking.cost,
            booking_time=(booking.created_at + datetime.timedelta(hours=5, minutes=30)).strftime('%d %b %Y, %I:%M %p'),
            location=turf.location,
            owner_phone=owner.phone if owner else 'N/A',
            dashboard_url=url_for('my_bookings', _external=True)
        )

        # Send Booking Notification Email to OWNER
        if owner and owner.email:
            send_email(
                subject=f"New Booking: {booking.id} - {turf.name}",
                recipient=owner.email,
                template="emails/owner_booking_notification.html",
                customer_name=current_user.name,
                customer_email=current_user.email,
                customer_phone=current_user.phone or 'N/A',
                booking_id=booking.id,
                turf_name=turf.name,
                date=booking.date,
                time_slot=booking.time_slot,
                amount=booking.cost,
                dashboard_url=url_for('owner_dashboard', _external=True)
            )
        
        return jsonify({'success': True, 'message': 'Booking confirmed and payment verified!'})
    except Exception as e:
        booking.payment_status = 'Failed'
        db.session.commit()
        return jsonify({'success': False, 'message': 'Payment verification failed.'}), 400

# =============================================
#   SUBSCRIPTION RENEWAL
# =============================================

@app.route('/api/subscription/create-order', methods=['POST'])
@login_required
def create_subscription_order():
    try:
        data = request.json
        plan = data.get('plan', 'Paid Plan')
        price = float(data.get('price', 500.0))
        
        admin_key_id, admin_key_secret = get_admin_razorpay_creds()
        temp_client = razorpay.Client(auth=(admin_key_id, admin_key_secret))

        # Create Razorpay Order
        razorpay_order = temp_client.order.create({
            'amount': int(price * 100),
            'currency': 'INR',
            'payment_capture': '1'
        })
        
        return jsonify({
            'success': True,
            'order_id': razorpay_order['id'],
            'amount': price * 100,
            'key_id': admin_key_id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/subscription/verify', methods=['POST'])
@login_required
@idempotent()
def verify_subscription_payment():
    data = request.json
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')
    plan = data.get('plan', 'Paid Plan')
    price = float(data.get('price', 500.0))
    
    try:
        admin_key_id, admin_key_secret = get_admin_razorpay_creds()
        temp_client = razorpay.Client(auth=(admin_key_id, admin_key_secret))

        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        
        temp_client.utility.verify_payment_signature(params_dict)
        
        # Update User Subscription
        now = datetime.datetime.utcnow()
        current_user.subscription_plan = plan
        current_user.subscription_price = price
        current_user.subscription_start = now
        current_user.subscription_end = now + datetime.timedelta(days=30)
        current_user.role = 'Owner' # Ensure they are an owner
        
        # Resume turfs
        for turf in current_user.turfs:
            turf.is_suspended = False
            
        db.session.commit()
        
        # Send Subscription Email
        send_email(
            subject="Partner Plan Activated - Cricza",
            recipient=current_user.email,
            template="emails/subscription_confirmation.html",
            user_name=current_user.name,
            plan_name=plan,
            end_date=current_user.subscription_end.strftime('%Y-%m-%d'),
            dashboard_url=url_for('owner_dashboard', _external=True)
        )
        
        return jsonify({'success': True, 'message': 'Subscription active!'})
    except Exception as e:
        return jsonify({'success': False, 'message': 'Payment verification failed.'}), 400

@app.route('/api/owner/renew', methods=['POST'])
@login_required
def renew_subscription():
    # This is now handled by the Razorpay flow, but we can keep it as a legacy redirect if needed
    # or just point it to a page that starts the Razorpay flow.
    return redirect(url_for('partner'))

# =============================================
#   APP STARTUP
# =============================================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Seed Admin
        if not User.query.filter_by(email='admin@123').first():
            admin_user = User(
                name='Super Admin',
                email='admin@123',
                password_hash=generate_password_hash('admin123', method='pbkdf2:sha256'),
                role='Admin'
            )
            db.session.add(admin_user)
            db.session.commit()

        if Turf.query.count() == 0:
            turfs = [
                Turf(name='Downtown Arena', description='Premium 6v6 turf with LED lighting and covered nets.', location='Downtown', price_per_hour=50.0, open_time=8, close_time=22),
                Turf(name='Westside Pitch', description='Spacious field ideal for 8v8. Includes dugout and stands.', location='Westside', price_per_hour=70.0, open_time=6, close_time=23),
                Turf(name='North Stadium', description='International standard 11v11 turf. Night match floodlights available.', location='North', price_per_hour=120.0, open_time=10, close_time=20)
            ]
            db.session.bulk_save_objects(turfs)
            db.session.commit()
            
    app.run(debug=True)
