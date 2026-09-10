# -*- coding: utf-8 -*-
"""Envoi d'emails de notification via le relais SMTP mutualisé (smtplib, stdlib).
Best-effort : renvoie le nombre de destinataires servis, 0 si non configuré/erreur."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from . import config

log = logging.getLogger("dtz-rag.mailer")


def send(to_list, subject, text):
    to_list = [t for t in (to_list or []) if isinstance(t, str) and "@" in t][:50]
    if not config.SMTP_HOST or not config.SMTP_FROM or not to_list:
        return 0
    msg = EmailMessage()
    msg["From"] = f"{config.SMTP_FROM_DISPLAY} <{config.SMTP_FROM}>"
    msg["To"] = ", ".join(to_list)
    if config.SMTP_REPLY_TO:
        msg["Reply-To"] = config.SMTP_REPLY_TO
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.ehlo()
            if config.SMTP_STARTTLS:
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg, from_addr=config.SMTP_ENVELOPE_FROM,
                           to_addrs=to_list)
        log.info("notification envoyée à %d destinataire(s) : %s", len(to_list), subject)
        return len(to_list)
    except Exception as e:
        log.warning("envoi email échec : %s", e)
        return 0
