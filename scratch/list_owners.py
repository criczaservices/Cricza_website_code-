from app import app, db
from models import User

with app.app_context():
    owners = User.query.filter_by(role='Owner').all()
    for owner in owners:
        print(f"ID: {owner.id}, Name: {owner.name}, Email: {owner.email}, Active: {owner.subscription_active}")
