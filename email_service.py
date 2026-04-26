import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from crypto_utils import decrypt


def send_email(account, to_email: str, subject: str, body: str, user) -> tuple:
    """Send an email via the given account. Returns (success, error_message)."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f'{user.display_name} <{account.email_address}>'
        msg['To'] = to_email
        msg['X-Mailer'] = 'Outlook 16.0'

        full_body = body
        if user.signature:
            full_body += f'\n\n--\n{user.signature}'

        msg.attach(MIMEText(full_body, 'plain'))

        if account.auth_method == 'smtp':
            password = decrypt(account.smtp_password_encrypted)
            host = account.smtp_host or 'smtp.gmail.com'
            port = account.smtp_port or 465
            if port == 465:
                with smtplib.SMTP_SSL(host, port) as smtp:
                    smtp.login(account.email_address, password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, port) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.login(account.email_address, password)
                    smtp.send_message(msg)
        elif account.auth_method == 'oauth':
            from gmail_service import send_via_oauth
            send_via_oauth(account, to_email, subject, full_body)
        else:
            return False, f'Unknown auth method: {account.auth_method}'

        return True, ''
    except Exception as e:
        return False, str(e)
