"""Canales de notificación externos.

Mantener las llamadas HTTP aquí evita que los modelos y las vistas conozcan los
detalles del API de Telegram.
"""

import logging

import requests
from django.conf import settings
from django.core.mail import send_mail


logger = logging.getLogger(__name__)
TELEGRAM_CAPTION_LIMIT = 1024


def send_telegram_message(message, photo=None):
    """Envía un mensaje a los chats configurados, sin bloquear el flujo ante fallos."""
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    chat_ids = getattr(settings, 'TELEGRAM_CHAT_IDS', [])
    if not token or not chat_ids:
        return

    caption = message.strip()
    if len(caption) > TELEGRAM_CAPTION_LIMIT:
        caption = f'{caption[:TELEGRAM_CAPTION_LIMIT - 24]}\n...'

    for chat_id in chat_ids:
        try:
            if photo:
                photo.open('rb')
                try:
                    response = requests.post(
                        f'https://api.telegram.org/bot{token}/sendPhoto',
                        data={'chat_id': chat_id, 'caption': caption},
                        files={'photo': photo.file},
                        timeout=15,
                    )
                finally:
                    photo.close()
            else:
                response = requests.post(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    data={'chat_id': chat_id, 'text': caption},
                    timeout=15,
                )
            response.raise_for_status()
        except requests.RequestException:
            logger.exception('No se pudo enviar la notificación de Telegram.')


def send_email_notification(subject, message, recipients):
    """Envía un correo a una colección de direcciones válidas y sin duplicados."""
    recipient_list = list(dict.fromkeys(email for email in recipients if email))
    if not recipient_list:
        return
    try:
        send_mail(
            subject,
            message,
            getattr(settings, 'DEFAULT_FROM_EMAIL', '') or 'registrodatos@grupominerobonanza.com',
            recipient_list,
            fail_silently=True,
        )
    except Exception:
        logger.exception('No se pudo enviar la notificación por correo.')
