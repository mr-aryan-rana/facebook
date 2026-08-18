"""SMTP send primitive for facebook/ campaigns. Mirrors app/mailer/core.py's
error handling (auth failures logged loudly since every subsequent send
fails the same way; rejected recipients treated as expected/non-error;
Gmail throttling responses distinguished from plain connection failures)."""

import os
import smtplib
from email.message import EmailMessage

from env_loader import load_env

load_env()


def send_email(to_address: str, subject: str, body: str) -> tuple[bool, str]:
    from_address = os.environ.get("GMAIL_USER", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(from_address, app_password)
            server.send_message(msg)
        return True, "sent"
    except smtplib.SMTPAuthenticationError as e:
        print(f"mailer: SMTP authentication failed (check GMAIL_APP_PASSWORD): {e}")
        return False, f"auth failed: {e}"
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as e:
        return False, f"recipient rejected: {e}"
    except smtplib.SMTPResponseException as e:
        print(f"mailer: SMTP server rejected the message (code {e.smtp_code}): {e.smtp_error}")
        return False, f"smtp error {e.smtp_code}: {e.smtp_error}"
    except (smtplib.SMTPException, OSError) as e:
        print(f"mailer: send failed (transient): {e}")
        return False, str(e)
