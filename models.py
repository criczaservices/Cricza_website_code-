from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=True) # Nullable for OAuth users
    google_id = db.Column(db.String(100), unique=True, nullable=True)
    profile_pic = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(20), nullable=False, default='Customer')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Subscription fields (Owner only)
    subscription_plan = db.Column(db.String(50), nullable=True)
    subscription_price = db.Column(db.Float, nullable=True)
    subscription_start = db.Column(db.DateTime, nullable=True)
    subscription_end = db.Column(db.DateTime, nullable=True)

    wallet_balance = db.Column(db.Float, default=0.0)
    razorpay_key_id = db.Column(db.String(100), nullable=True)
    razorpay_key_secret = db.Column(db.String(100), nullable=True)
    
    # Password Reset Fields
    reset_otp = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)

    bookings = db.relationship('Booking', backref='customer', lazy=True, cascade="all, delete-orphan")
    turfs = db.relationship('Turf', backref='owner', lazy=True, cascade="all, delete-orphan")
    withdrawals = db.relationship('WithdrawalRequest', backref='owner', lazy=True, cascade="all, delete-orphan")

    @property
    def subscription_days_left(self):
        if self.subscription_end:
            delta = self.subscription_end - datetime.utcnow()
            return max(0, delta.days)
        return 0

    @property
    def subscription_active(self):
        if self.subscription_end:
            return datetime.utcnow() < self.subscription_end
        return False

class Turf(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(200), nullable=False)
    pincode = db.Column(db.String(10), nullable=True)
    price_per_hour = db.Column(db.Float, nullable=False)
    photo_url = db.Column(db.Text, nullable=True)
    open_time = db.Column(db.Integer, nullable=False, default=6)
    close_time = db.Column(db.Integer, nullable=False, default=23)
    is_suspended = db.Column(db.Boolean, nullable=False, default=False)

    bookings = db.relationship('Booking', backref='turf', lazy=True, cascade="all, delete-orphan")
    off_dates = db.relationship('TurfOffDate', backref='turf', lazy=True, cascade="all, delete-orphan")
    coupon = db.relationship('Coupon', backref='turf', uselist=False, cascade="all, delete-orphan")

    @property
    def active_coupon(self):
        """Returns the coupon if it is valid by date and usage limit."""
        if self.coupon:
            from datetime import datetime
            now_str = datetime.utcnow().strftime('%Y-%m-%d')
            if self.coupon.valid_until >= now_str and self.coupon.used_count < self.coupon.usage_limit:
                return self.coupon
        return None

class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    turf_id = db.Column(db.Integer, db.ForeignKey('turf.id'), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    discount_amount = db.Column(db.Float, nullable=False)
    usage_limit = db.Column(db.Integer, nullable=False, default=10)
    used_count = db.Column(db.Integer, nullable=False, default=0)
    valid_until = db.Column(db.String(20), nullable=False) # YYYY-MM-DD

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    turf_id = db.Column(db.Integer, db.ForeignKey('turf.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False) 
    time_slot = db.Column(db.String(500), nullable=False) 
    cost = db.Column(db.Float, nullable=False)
    razorpay_order_id = db.Column(db.String(100), nullable=True)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)
    payment_status = db.Column(db.String(20), default='Pending') # Pending, Success, Failed
    payment_to = db.Column(db.String(20), nullable=True) # Admin, Owner
    offline_customer_name = db.Column(db.String(100), nullable=True)
    offline_customer_email = db.Column(db.String(120), nullable=True)
    offline_customer_phone = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    coupon_code = db.Column(db.String(20), nullable=True)

class TurfOffDate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    turf_id = db.Column(db.Integer, db.ForeignKey('turf.id'), nullable=False)
    off_date = db.Column(db.String(20), nullable=False)  # YYYY-MM-DD

class WithdrawalRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Pending')  # Pending / Paid
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)

class RateLimit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), index=True) # IP or User ID + Endpoint
    hits = db.Column(db.Integer, default=0)
    last_hit = db.Column(db.DateTime, default=datetime.utcnow)
    period_start = db.Column(db.DateTime, default=datetime.utcnow)

class IdempotencyRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    idempotency_key = db.Column(db.String(255), unique=True, index=True)
    user_id = db.Column(db.Integer, nullable=True)
    endpoint = db.Column(db.String(255))
    response_body = db.Column(db.Text)
    status_code = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
