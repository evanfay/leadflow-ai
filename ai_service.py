import anthropic
from crypto_utils import decrypt


def get_client(user):
    key = decrypt(user.anthropic_api_key_encrypted) if user.anthropic_api_key_encrypted else ''
    if not key:
        raise ValueError('No Anthropic API key configured for this account.')
    return anthropic.Anthropic(api_key=key)


def generate_sequence_email(lead, template, campaign) -> tuple:
    """Generate an email for a sequence step. Returns (subject, body). Hard limit: 90 words."""
    client = get_client(campaign.user)

    signal_context = ''
    if lead.signal_1:
        signal_context += f'\nSignal 1: {lead.signal_1}'
    if lead.signal_2:
        signal_context += f'\nSignal 2: {lead.signal_2}'
    if lead.signal_3:
        signal_context += f'\nSignal 3: {lead.signal_3}'

    first_name = campaign.user.display_name.split()[0] if campaign.user.display_name else 'Evan'

    prompt = f"""You are writing a cold outreach email. Follow the template style exactly.

LEAD INFO:
- Name: {lead.first_name} {lead.last_name}
- Company: {lead.company}
- Title: {lead.title or 'Unknown'}
- Website: {lead.website or 'Unknown'}{signal_context}

TEMPLATE STYLE ({template.touch_type.upper()}):
Subject template: {template.subject}
Body template:
{template.body}

STRICT RULES:
1. Maximum 90 words in the body (hard limit — count carefully)
2. No flattery, no "I hope this finds you well"
3. No hyphens or "utilize"
4. First sentence must reference a specific operational problem or signal
5. Personalize using the lead's actual company and signals
6. Be conversational and direct
7. Sign off with just: {first_name}

Output format (exactly):
SUBJECT: [subject line]
BODY:
[email body]"""

    response = client.messages.create(
        model='claude-sonnet-4-6',
        max_tokens=400,
        messages=[{'role': 'user', 'content': prompt}]
    )

    text = response.content[0].text
    lines = text.strip().split('\n')
    subject = ''
    body_lines = []
    in_body = False

    for line in lines:
        if line.startswith('SUBJECT:'):
            subject = line.replace('SUBJECT:', '').strip()
        elif line.startswith('BODY:'):
            in_body = True
        elif in_body:
            body_lines.append(line)

    body = '\n'.join(body_lines).strip()
    return subject, body


def classify_reply(reply_text, user) -> str:
    """Classify a reply into: positive, not_now, wrong_person, unsubscribe, out_of_office"""
    try:
        client = get_client(user)
        response = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=20,
            messages=[{
                'role': 'user',
                'content': f'''Classify this email reply into exactly one category:
- positive (interested, wants to talk, asks questions)
- not_now (not right time, try later, busy)
- wrong_person (not the decision maker, forward to someone else)
- unsubscribe (stop emailing, remove me, unsubscribe)
- out_of_office (auto-reply, OOO, vacation)

Reply: {reply_text[:500]}

Respond with ONLY the category name.'''
            }]
        )
        return response.content[0].text.strip().lower()
    except Exception:
        return 'positive'


def generate_reply_suggestion(reply_text, category, lead, user) -> str:
    """Generate a suggested response to a reply."""
    try:
        client = get_client(user)
        templates = {
            'positive': 'Express enthusiasm, suggest a 15-minute call, offer specific times',
            'not_now': 'Acknowledge timing, be gracious, keep the door open',
            'wrong_person': 'Thank them, ask who the right person would be',
            'out_of_office': 'Brief note acknowledging their OOO, say you will follow up when they return',
        }
        guidance = templates.get(category, 'Be helpful and professional')

        first_name = user.display_name.split()[0] if user.display_name else 'Evan'

        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=300,
            messages=[{
                'role': 'user',
                'content': f'''Draft a reply to this email.
Their reply: {reply_text[:400]}
Lead: {lead.first_name} {lead.last_name} at {lead.company}
Guidance: {guidance}
Keep it under 60 words. Conversational. From: {user.display_name}
Sign off: {first_name}'''
            }]
        )
        return response.content[0].text.strip()
    except Exception:
        return ''
