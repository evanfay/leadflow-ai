import email
import imaplib
from email.header import decode_header as _decode_header_lib

from crypto_utils import decrypt


def check_imap_for_replies(account):
    """Poll IMAP inbox for unread replies. Returns list of reply dicts."""
    try:
        host = account.imap_host
        port = account.imap_port or 993
        password = decrypt(account.imap_password_encrypted)

        with imaplib.IMAP4_SSL(host, port) as mail:
            mail.login(account.email_address, password)
            mail.select('INBOX')

            _, msg_ids = mail.search(None, 'UNSEEN')
            if not msg_ids or not msg_ids[0]:
                return []

            replies = []
            for msg_id in msg_ids[0].split():
                try:
                    _, msg_data = mail.fetch(msg_id, '(RFC822)')
                    if not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)

                    in_reply_to = msg.get('In-Reply-To', '')
                    references = msg.get('References', '')

                    # Only process actual replies, not fresh inbound messages
                    if not in_reply_to and not references:
                        continue

                    from_email = _parse_address(msg.get('From', ''))
                    subject = _decode_header(msg.get('Subject', ''))
                    body = _extract_text(msg)

                    replies.append({
                        'from_email': from_email,
                        'subject': subject,
                        'body': body,
                        'in_reply_to': in_reply_to,
                    })

                    # Mark seen so we don't reprocess
                    mail.store(msg_id, '+FLAGS', '\\Seen')

                except Exception as e:
                    print(f'[IMAP] Message parse error: {e}')

            return replies

    except imaplib.IMAP4.error as e:
        print(f'[IMAP] Auth/connection error for {account.email_address}: {e}')
        return []
    except Exception as e:
        print(f'[IMAP] Unexpected error for {account.email_address}: {e}')
        return []


def _decode_header(value):
    if not value:
        return ''
    parts = _decode_header_lib(value)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or 'utf-8', errors='replace'))
        else:
            out.append(text)
    return ''.join(out)


def _parse_address(from_header):
    if '<' in from_header:
        return from_header.split('<')[1].rstrip('>').strip()
    return from_header.strip()


def _extract_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    return payload.decode(charset, errors='replace')
    else:
        if msg.get_content_type() == 'text/plain':
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                return payload.decode(charset, errors='replace')
    return ''
