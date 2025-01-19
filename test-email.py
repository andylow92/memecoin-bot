import smtplib
from email.mime.text import MIMEText
import os
# Email credentials

sender_email = os.getenv("SENDER_EMAIL")
password = os.getenv("SENDER_PASSWORD")
receiver_email = os.getenv("RECEIVER_EMAIL")



# Email content
subject = "Test Email from Crypto Bot"
body = "This is a second test "
msg = MIMEText(body)
msg["Subject"] = subject
msg["From"] = sender_email
msg["To"] = receiver_email

# Send email
try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender_email, password)
        server.send_message(msg)
    print("Test email sent successfully!")
except Exception as e:
    print(f"Error sending email: {e}")
