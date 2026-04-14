import json
import base64
from email.mime.text import MIMEText
from crypto_utils import decrypt


def get_gmail_service(account):
    """Build Gmail API service from stored OAuth token."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_data = json.loads(decrypt(account.oauth_token_encrypted))
    creds = Credentials(
        token=token_data.get('token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=token_data.get('client_id'),
        client_secret=token_data.get('client_secret'),
    )
    return build('gmail', 'v1', credentials=creds)


def send_via_oauth(account, to_email, subject, body):
    service = get_gmail_service(account)
    msg = MIMEText(body)
    msg['to'] = to_email
    msg['subject'] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId='me', body={'raw': raw}).execute()


def check_for_replies(account):
    """Check Gmail inbox for replies to our sent emails. Returns list of reply dicts."""
    try:
        service = get_gmail_service(account)
        results = service.users().messages().list(
            userId='me',
            q='in:inbox is:unread',
            maxResults=50
        ).execute()

        replies = []
        messages = results.get('messages', [])
        for msg_ref in messages:
            msg = service.users().messages().get(
                userId='me', id=msg_ref['id'], format='full'
            ).execute()

            headers = {h['name']: h['value'] for h in msg['payload']['headers']}

            # Only process if it's a reply (has In-Reply-To or References header)
            if 'In-Reply-To' not in headers and 'References' not in headers:
                continue

            body_text = _extract_body(msg['payload'])
            from_email = headers.get('From', '')
            if '<' in from_email:
                from_email = from_email.split('<')[1].rstrip('>')

            replies.append({
                'message_id': msg['id'],
                'from_email': from_email,
                'subject': headers.get('Subject', ''),
                'body': body_text,
                'in_reply_to': headers.get('In-Reply-To', '')
            })

        return replies
    except Exception as e:
        print(f'Gmail poll error: {e}')
        return []


def _extract_body(payload):
    """Extract text body from Gmail message payload."""
    if payload.get('mimeType') == 'text/plain':
        data = payload.get('body', {}).get('data', '')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
        return ''

    for part in payload.get('parts', []):
        body = _extract_body(part)
        if body:
            return body
    return ''
