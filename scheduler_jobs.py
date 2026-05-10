from datetime import datetime, timedelta, date


# Warmup send caps by tier and week number
# After the last defined week, the account's own daily_limit takes over
WARMUP_CAPS = {
    'slow':       {1: 5,  2: 10, 3: 20, 4: 35, 5: 50},   # 5 weeks — safest, new domains
    'medium':     {1: 10, 2: 25, 3: 40, 4: 60},            # 4 weeks — standard Gmail
    'aggressive': {1: 20, 2: 40, 3: 60},                   # 3 weeks — established domain
}

# Spam trigger words that hurt deliverability
SPAM_WORDS = [
    'free', 'guarantee', 'no risk', 'act now', 'limited time', 'click here',
    'unsubscribe', 'opt out', 'bulk', 'mass email', 'make money', 'earn money',
    'winner', 'congratulations', 'prize', 'urgent', 'important notice',
    'dear friend', 'this is not spam', 'no obligation', '100%', 'cash',
    'buy now', 'order now', 'special promotion', 'marketing', 'advertisement',
]


def register_jobs(scheduler, app):
    scheduler.add_job(
        func=send_due_emails,
        trigger='interval',
        minutes=15,
        args=[app],
        id='send_due_emails',
        replace_existing=True
    )
    scheduler.add_job(
        func=poll_gmail_replies,
        trigger='interval',
        minutes=30,
        args=[app],
        id='poll_gmail_replies',
        replace_existing=True
    )
    scheduler.add_job(
        func=poll_imap_replies,
        trigger='interval',
        minutes=10,
        args=[app],
        id='poll_imap_replies',
        replace_existing=True
    )
    scheduler.add_job(
        func=check_resume_dates,
        trigger='interval',
        hours=1,
        args=[app],
        id='check_resume_dates',
        replace_existing=True
    )
    # Advance warmup week every Monday
    scheduler.add_job(
        func=advance_warmup_weeks,
        trigger='cron',
        day_of_week='mon',
        hour=0,
        minute=5,
        args=[app],
        id='advance_warmup_weeks',
        replace_existing=True
    )


def _get_daily_cap(account):
    """
    Return today's effective send cap for this account.
    - If warmup is ON: use the tier schedule for the current week.
      Once the tier's schedule is exhausted, fall through to daily_limit.
    - If warmup is OFF: use daily_limit directly.
      daily_limit == 0 means no cap (unlimited).
    """
    if account.warmup_enabled:
        tier = account.warmup_tier or 'medium'
        schedule = WARMUP_CAPS.get(tier, WARMUP_CAPS['medium'])
        week = max(1, account.warmup_week)
        # Look up this week's cap; if past the schedule, use daily_limit
        cap = schedule.get(week)
        if cap is not None:
            return cap
        # Warmup complete — fall through to account's full daily_limit
    if account.daily_limit == 0:
        return float('inf')   # no cap
    return account.daily_limit


def _account_can_send(account):
    """Return True if this account has not hit its daily cap."""
    from models import SendLog, SendStatus
    today = date.today()
    sent_today = SendLog.query.filter(
        SendLog.from_account_id == account.id,
        SendLog.status == SendStatus.SENT,
        SendLog.sent_at >= datetime.combine(today, datetime.min.time())
    ).count()
    cap = _get_daily_cap(account)
    return sent_today < cap


# Daily send ratio: (follow_ups_per_cycle, new_touches_per_cycle).
# (3, 2) = 60 % follow-ups / 40 % new first-touch openers.
# Examples:
#   (1, 1) → 50/50    (2, 1) → 67/33    (3, 2) → 60/40    (3, 1) → 75/25
SEND_RATIO = (3, 2)   # 60 % follow-ups, 40 % new touches


def _step_jitter(enrolled_lead_id, step_id):
    """
    Deterministic ±1-day jitter for a given lead+step pair.
    Using a hash means the same pair always gets the same offset, so a step
    that is 'due' at 8 am stays due at 8:15 am and doesn't randomly flip.
    """
    return (hash((enrolled_lead_id, step_id)) % 3) - 1   # always -1, 0, or +1


def _interleave_leads(active_leads, followup_ids):
    """
    Split active leads into follow-up and new-touch buckets, then interleave
    them according to SEND_RATIO so both always get daily capacity.

    At SEND_RATIO=(3,2) and cap=50: ~30 follow-ups + ~20 new openers per day.
    When one bucket empties, remaining capacity goes to the other — no waste.
    """
    followups  = [el for el in active_leads if el.id in followup_ids]
    new_touches = [el for el in active_leads if el.id not in followup_ids]

    # Within each bucket: oldest enrollment first (most overdue / FIFO)
    followups.sort(key=lambda el: el.enrolled_at or datetime.min)
    new_touches.sort(key=lambda el: el.enrolled_at or datetime.min)

    fu_per_cycle, new_per_cycle = SEND_RATIO
    interleaved = []
    fi = ni = 0
    while fi < len(followups) or ni < len(new_touches):
        for _ in range(fu_per_cycle):
            if fi < len(followups):
                interleaved.append(followups[fi]); fi += 1
        for _ in range(new_per_cycle):
            if ni < len(new_touches):
                interleaved.append(new_touches[ni]); ni += 1

    return interleaved


def send_due_emails(app):
    """Check enrolled leads for due email steps and send them.

    Capacity split: leads are interleaved at FOLLOWUP_TO_NEW_RATIO so that
    both follow-ups AND new first-touch emails get sent every day, regardless
    of how large the existing pipeline grows. When one bucket empties, any
    remaining capacity goes to the other bucket.
    """
    with app.app_context():
        from models import db, EnrolledLead, DoNotContact, EmailAccount, SendLog
        from models import EnrolledStatus, SendStatus

        now = datetime.utcnow()
        # Only send on weekdays, during business hours (8am–11am or 1pm–4pm UTC)
        if now.weekday() >= 5:
            return
        hour = now.hour
        if not ((8 <= hour < 11) or (13 <= hour < 16)):
            return

        active_leads = EnrolledLead.query.filter_by(status=EnrolledStatus.ACTIVE).all()

        # ── Identify which enrolled leads have already received ≥1 sent email ──
        # One query; avoids N+1 per lead.
        followup_ids = set(
            row[0] for row in
            db.session.query(SendLog.enrolled_lead_id)
            .filter(SendLog.status == SendStatus.SENT)
            .distinct()
            .all()
        )

        # ── Interleave follow-ups and new touches at the configured ratio ──────
        active_leads = _interleave_leads(active_leads, followup_ids)

        # ── Early-exit helpers ─────────────────────────────────────────────────
        accounts = EmailAccount.query.filter(EmailAccount.active == True).all()

        def _all_capped(user_id):
            user_accounts = [a for a in accounts if a.user_id == user_id]
            return bool(user_accounts) and all(not _account_can_send(a) for a in user_accounts)

        user_capped_cache = {}

        for el in active_leads:
            try:
                campaign = el.campaign
                if not campaign or not campaign.sequence_id:
                    continue
                if campaign.status != 'active':
                    continue

                uid = campaign.user_id
                # Check cap cache; refresh once per user per scheduler run
                if uid not in user_capped_cache:
                    user_capped_cache[uid] = _all_capped(uid)
                if user_capped_cache[uid]:
                    # All this user's accounts are at cap — skip remaining leads for them
                    continue

                sequence = campaign.sequence
                steps = sorted(sequence.steps.all(), key=lambda s: s.day_offset)
                enrolled_date = el.enrolled_at.date()
                today = date.today()

                for step in steps:
                    jitter = _step_jitter(el.id, step.id)
                    due_date = enrolled_date + timedelta(days=step.day_offset + jitter)

                    if today >= due_date and step.channel == 'Email' and step.is_auto:
                        existing_log = SendLog.query.filter_by(
                            enrolled_lead_id=el.id,
                            step_id=step.id
                        ).first()
                        if existing_log:
                            # Pre-loaded draft ready to auto-send
                            if existing_log.status == 'queued' and existing_log.body_snippet:
                                _send_queued_draft(existing_log, el, step, campaign)
                                # Invalidate cap cache for this user after a send
                                user_capped_cache.pop(uid, None)
                            continue

                        lead = el.lead
                        dnc = DoNotContact.query.filter_by(
                            user_id=campaign.user_id,
                            email_address=lead.email
                        ).first()
                        if dnc or lead.do_not_contact:
                            el.status = EnrolledStatus.DO_NOT_CONTACT
                            db.session.commit()
                            break

                        _queue_email_step(el, step, campaign)
                        # Invalidate cap cache after a send attempt
                        user_capped_cache.pop(uid, None)
                        break
            except Exception as e:
                print(f'[Scheduler] Error processing enrolled lead {el.id}: {e}')


def _queue_email_step(enrolled_lead, step, campaign):
    """Generate and optionally send an email for this sequence step."""
    from models import db, SendLog, TaskQueue, Template
    from ai_service import generate_sequence_email

    lead = enrolled_lead.lead

    step_templates = [st for st in step.step_templates.all() if st.is_active]
    if not step_templates:
        # Fall back to a builtin template matching the touch type
        builtin = Template.query.filter_by(touch_type=step.template_slot, is_builtin=True).first()
        if not builtin:
            return

        class _VirtualST:
            template = builtin
            variant_label = 'A'
        step_templates = [_VirtualST()]

    sent_count = SendLog.query.filter_by(enrolled_lead_id=enrolled_lead.id).count()
    variant = step_templates[sent_count % len(step_templates)]
    template = variant.template

    if campaign.content_mode == 'auto':
        try:
            subject, body = generate_sequence_email(lead, template, campaign)
            _send_email_step(enrolled_lead, step, template, variant.variant_label, subject, body, campaign)
        except Exception as e:
            print(f'[Scheduler] Email generation error for lead {lead.id}: {e}')

    elif campaign.content_mode == 'review':
        try:
            subject, body = generate_sequence_email(lead, template, campaign)
        except Exception:
            subject = template.subject.replace('{{first_name}}', lead.first_name or '').replace('{{company}}', lead.company or '')
            body = template.body
        draft = SendLog(
            enrolled_lead_id=enrolled_lead.id,
            step_id=step.id,
            template_id=template.id,
            variant_label=variant.variant_label,
            subject=subject,
            body_snippet=body[:2000],
            status='draft'
        )
        db.session.add(draft)
        db.session.commit()

    elif campaign.content_mode == 'manual':
        # Create a task to remind user to write and send manually
        task = TaskQueue(
            user_id=campaign.user_id,
            enrolled_lead_id=enrolled_lead.id,
            step_id=step.id,
            task_type='write_email',
            due_date=datetime.utcnow().date(),
            status='pending',
            notes=(
                f'Write & send email for {lead.first_name} {lead.last_name} '
                f'at {lead.company} — Touch: {_humanize_touch(step.template_slot)}'
            )
        )
        db.session.add(task)
        db.session.commit()

    elif campaign.content_mode == 'compose':
        # Create a blank draft — user will paste their own content
        draft = SendLog(
            enrolled_lead_id=enrolled_lead.id,
            step_id=step.id,
            template_id=template.id,
            variant_label=variant.variant_label,
            subject='',
            body_snippet='',
            status='compose'  # signals "waiting for user content"
        )
        db.session.add(draft)
        db.session.commit()


def _humanize_touch(slot):
    labels = {
        'opener': 'Opener — First Email',
        'observation': 'Opening — Signal Observation',
        'hypothesis': 'Follow-up — Hypothesis',
        'proof': 'Follow-up — Proof / Case Study',
        'soft_close': 'Soft Close',
        'breakup': 'Breakup / Final Touch',
        'linkedin_connect': 'LinkedIn Connection',
        'linkedin_dm': 'LinkedIn DM',
        'voicemail': 'Voicemail',
        'live_call': 'Live Call',
    }
    return labels.get(slot, slot.replace('_', ' ').title())


def _pick_account(enrolled_lead, campaign):
    """
    Pick the sending account for this enrolled lead.
    If a pinned account (from_account_id) is set and still active + under cap, use it.
    Otherwise fall back to round-robin across all active accounts.
    """
    from models import SendLog, EmailAccount

    # Pinned account takes priority
    if enrolled_lead.from_account_id:
        pinned = EmailAccount.query.filter_by(
            id=enrolled_lead.from_account_id, active=True
        ).first()
        if pinned and _account_can_send(pinned):
            return pinned
        if pinned and not _account_can_send(pinned):
            print(f'[Scheduler] Pinned account {pinned.email_address} at daily cap — skipping send for lead {enrolled_lead.lead_id}')
            return None

    # Round-robin fallback
    accounts = EmailAccount.query.filter_by(user_id=campaign.user_id, active=True).all()
    if not accounts:
        return None
    sent_count = SendLog.query.filter_by(enrolled_lead_id=enrolled_lead.id).count()
    for i in range(len(accounts)):
        candidate = accounts[(sent_count + i) % len(accounts)]
        if _account_can_send(candidate):
            return candidate
    return None


def _send_queued_draft(send_log, enrolled_lead, step, campaign):
    """Send a pre-loaded queued draft immediately."""
    from models import db
    from email_service import send_email

    account = _pick_account(enrolled_lead, campaign)
    if not account:
        print(f'[Scheduler] No available account for queued draft {send_log.id}')
        return

    lead = enrolled_lead.lead
    success, error = send_email(account, lead.email, send_log.subject, send_log.body_snippet, campaign.user)
    send_log.status = 'sent' if success else 'failed'
    send_log.sent_at = datetime.utcnow() if success else None
    send_log.from_account_id = account.id
    db.session.commit()


def _send_email_step(enrolled_lead, step, template, variant_label, subject, body, campaign):
    """Actually send the email via an active account, respecting warmup cap."""
    from models import db, SendLog, EmailAccount
    from email_service import send_email

    account = _pick_account(enrolled_lead, campaign)
    if not account:
        print(f'[Scheduler] No available account for user {campaign.user_id} — skipping send')
        return

    lead = enrolled_lead.lead
    success, error = send_email(account, lead.email, subject, body, campaign.user)
    log = SendLog(
        enrolled_lead_id=enrolled_lead.id,
        step_id=step.id,
        template_id=template.id,
        variant_label=variant_label,
        sent_at=datetime.utcnow() if success else None,
        from_account_id=account.id,
        subject=subject,
        body_snippet=body[:2000],
        status='sent' if success else 'failed'
    )
    db.session.add(log)
    db.session.commit()


def advance_warmup_weeks(app):
    """Bump warmup_week by 1 for all warmup-enabled accounts, every Monday."""
    with app.app_context():
        from models import db, EmailAccount
        accounts = EmailAccount.query.filter_by(warmup_enabled=True).all()
        advanced = 0
        for acct in accounts:
            tier = acct.warmup_tier or 'medium'
            schedule = WARMUP_CAPS.get(tier, WARMUP_CAPS['medium'])
            max_week = max(schedule.keys())
            if acct.warmup_week < max_week:
                acct.warmup_week += 1
                advanced += 1
            # Once past max_week, warmup is complete — optionally disable it
        db.session.commit()
        print(f'[Scheduler] Advanced warmup week for {advanced}/{len(accounts)} account(s)')


def poll_gmail_replies(app):
    """Poll Gmail API for replies to sent emails."""
    with app.app_context():
        from models import EmailAccount, AuthMethod

        oauth_accounts = EmailAccount.query.filter_by(auth_method=AuthMethod.OAUTH, active=True).all()
        for account in oauth_accounts:
            try:
                from gmail_service import check_for_replies
                replies = check_for_replies(account)
                for reply_data in replies:
                    _process_reply(reply_data, account)
            except Exception as e:
                print(f'[Scheduler] Gmail poll error for {account.email_address}: {e}')


def _process_reply(reply_data, account):
    """Process a detected reply — pause sequence, classify, create task."""
    from models import db, EnrolledLead, ReplyLog, TaskQueue, Lead, DoNotContact
    from models import EnrolledStatus
    from ai_service import classify_reply, generate_reply_suggestion

    lead = Lead.query.filter_by(email=reply_data['from_email'], user_id=account.user_id).first()
    if not lead:
        return

    enrolled = EnrolledLead.query.filter_by(lead_id=lead.id, status=EnrolledStatus.ACTIVE).first()
    if not enrolled:
        return

    category = classify_reply(reply_data['body'], account.user)

    enrolled.status = EnrolledStatus.PAUSED
    enrolled.paused_reason = f'Reply received: {category}'

    if category == 'unsubscribe':
        enrolled.status = EnrolledStatus.UNSUBSCRIBED
        dnc = DoNotContact(
            user_id=account.user_id,
            email_address=lead.email,
            reason='Unsubscribe reply',
            added_at=datetime.utcnow()
        )
        db.session.add(dnc)

    suggestion = generate_reply_suggestion(reply_data['body'], category, lead, account.user)

    reply_log = ReplyLog(
        enrolled_lead_id=enrolled.id,
        received_at=datetime.utcnow(),
        reply_category=category,
        snippet=reply_data['body'][:300],
        suggested_reply=suggestion,
        handled=False,
        followup_due_at=datetime.utcnow() + timedelta(days=90) if category == 'not_now' else None
    )
    db.session.add(reply_log)

    task = TaskQueue(
        user_id=account.user_id,
        enrolled_lead_id=enrolled.id,
        task_type='respond_to_reply',
        due_date=date.today(),
        status='pending',
        notes=f'Reply from {lead.first_name} {lead.last_name}: {category}'
    )
    db.session.add(task)
    db.session.commit()


def poll_imap_replies(app):
    """Poll IMAP inboxes for replies on all accounts with IMAP configured."""
    with app.app_context():
        from models import EmailAccount

        accounts = EmailAccount.query.filter(
            EmailAccount.active == True,
            EmailAccount.imap_host != None,
            EmailAccount.imap_password_encrypted != None,
        ).all()

        for account in accounts:
            try:
                from imap_service import check_imap_for_replies
                replies = check_imap_for_replies(account)
                for reply_data in replies:
                    _process_reply(reply_data, account)
            except Exception as e:
                print(f'[Scheduler] IMAP poll error for {account.email_address}: {e}')


def check_resume_dates(app):
    """Resume OOO-paused sequences when resume date passes."""
    with app.app_context():
        from models import db, EnrolledLead

        ooo_leads = EnrolledLead.query.filter(
            EnrolledLead.paused_reason.like('%Out of Office%'),
            EnrolledLead.resume_at <= datetime.utcnow(),
            EnrolledLead.status == 'paused'
        ).all()

        for el in ooo_leads:
            el.status = 'active'
            el.resume_at = None
            el.paused_reason = None

        db.session.commit()


def check_template_spam_score(body_text):
    """
    Scan email body for spam trigger words.
    Returns (score 0-100, list of flagged words).
    0 = clean, 100 = very risky.
    """
    text_lower = body_text.lower()
    flagged = [w for w in SPAM_WORDS if w in text_lower]
    score = min(100, len(flagged) * 15)
    return score, flagged


def get_account_health(account):
    """Return a health dict for a single email account."""
    from models import SendLog, SendStatus
    today = date.today()
    sent_today = SendLog.query.filter(
        SendLog.from_account_id == account.id,
        SendLog.status == SendStatus.SENT,
        SendLog.sent_at >= datetime.combine(today, datetime.min.time())
    ).count()

    cap = _get_daily_cap(account)
    unlimited = (cap == float('inf'))
    cap_pct = round((sent_today / cap * 100)) if not unlimited and cap > 0 else 0

    tier = account.warmup_tier or 'medium'
    schedule = WARMUP_CAPS.get(tier, WARMUP_CAPS['medium'])
    max_week = max(schedule.keys())
    warmup_complete = account.warmup_enabled and account.warmup_week > max_week

    # Human-readable tier name
    tier_labels = {'slow': 'Slow (5-week)', 'medium': 'Medium (4-week)', 'aggressive': 'Aggressive (3-week)'}
    tier_label = tier_labels.get(tier, tier.title())

    warnings = []
    if not unlimited:
        if cap_pct >= 100:
            warnings.append('Daily send limit reached — no more sends today')
        elif cap_pct >= 90:
            warnings.append(f'At {cap_pct}% of daily limit — approaching cap')
    if account.warmup_enabled and account.warmup_week == 1 and tier == 'slow' and sent_today > 5:
        warnings.append('Slow warmup week 1: stay under 5 emails/day')
    if account.warmup_enabled and warmup_complete:
        warnings.append('Warmup complete — consider disabling warmup mode')

    if (not unlimited and cap_pct >= 90) or not account.active:
        health_status = 'danger'
    elif (not unlimited and cap_pct >= 70) or warnings:
        health_status = 'warning'
    else:
        health_status = 'ok'

    return {
        'email': account.email_address,
        'sent_today': sent_today,
        'daily_cap': cap if not unlimited else None,
        'unlimited': unlimited,
        'cap_pct': cap_pct,
        'warmup_enabled': account.warmup_enabled,
        'warmup_tier': tier,
        'warmup_tier_label': tier_label,
        'warmup_week': account.warmup_week,
        'warmup_max_week': max_week,
        'warmup_complete': warmup_complete,
        'warmup_cap': schedule.get(account.warmup_week) if account.warmup_enabled and not warmup_complete else None,
        'active': account.active,
        'status': health_status,
        'warnings': warnings,
    }
