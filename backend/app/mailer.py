"""Sends sign-up codes by email when SMTP is configured.

Set SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD and SMTP_FROM in backend/.env
(any provider works, e.g. Brevo, Resend or Gmail with an app password). Without SMTP_HOST,
MendMap runs in demo mode: no email is sent and the app shows the code on screen instead.
"""
import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("mendmap.mail")


def configured() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def _send(to: str, subject: str, body: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "MendMap <no-reply@mendmap.local>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=20) as s:
        if port != 25:
            s.starttls()
        if os.getenv("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
        s.send_message(msg)


async def send_code(to: str, code: str) -> None:
    body = (
        f"Your MendMap code is {code}\n\n"
        "Enter it in the app to finish signing in. It expires in 10 minutes.\n"
        "If you didn't ask for this, you can ignore this email."
    )
    html = f"""<div style="font-family:Arial,sans-serif;max-width:420px;margin:auto;padding:24px;color:#0f1b3d">
  <h2 style="margin:0 0 8px;color:#1f4fd8">MendMap</h2>
  <p>Enter this code in the app to finish signing in:</p>
  <p style="font-size:34px;letter-spacing:10px;font-weight:600;margin:18px 0;padding:14px;background:#eaeef7;border-radius:12px;text-align:center">{code}</p>
  <p style="color:#5b6787;font-size:14px">It expires in 10 minutes. If you didn't ask for this, you can ignore this email.</p>
</div>"""
    try:
        await asyncio.to_thread(_send, to, f"{code} is your MendMap code", body, html)
    except Exception as exc:  # never crash the request; the user can ask for a new code
        log.warning("Could not email the sign-in code: %s", exc)
