import os
from flask import Flask
from flask_mail import Mail, Message
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

mail = Mail(app)

with app.app_context():
    try:
        print(f"Server: {app.config['MAIL_SERVER']}")
        print(f"Port: {app.config['MAIL_PORT']}")
        print(f"User: {app.config['MAIL_USERNAME']}")
        print(f"Sender: {app.config['MAIL_DEFAULT_SENDER']}")
        
        recipient = input("Enter recipient email to test: ")
        msg = Message("Test Email from Cricza", recipients=[recipient])
        msg.body = "This is a test email to verify SMTP configuration."
        mail.send(msg)
        print("Success: Email sent!")
    except Exception as e:
        print(f"Error: {str(e)}")
