import csv
import io
import json
import re
from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from . import campaigns_bp
from extensions import db
from models import (Campaign, Sequence, Lead, EnrolledLead, SendLog, ReplyLog,
                    TaskQueue, CampaignStatus, EnrolledStatus, ContentMode, TaskStatus,
                    Template, DoNotContact, SendStatus)


@campaigns_bp.route('/')
@login_required
def list_campaigns():
    campaigns = Campaign.query.filter_by(user_id=current_user.id).order_by(
        Campaign.created_at.desc()
    ).all()
    return render_template('campaigns/list.html', campaigns=campaigns)


@campaigns_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_campaign():
    sequences = Sequence.query.filter(
        (Sequence.user_id == current_user.id) | (Sequence.is_builtin == True)
    ).order_by(Sequence.name).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        sequence_id = request.form.get('sequence_id')
        content_mode = request.form.get('content_mode', ContentMode.REVIEW)
        draft_timeout = int(request.form.get('draft_timeout_hours', 24))
        ab_method = request.form.get('ab_rotation_method', 'round_robin')
        notes = request.form.get('notes', '')

        if not name:
            flash('Campaign name is required.', 'danger')
            return render_template('campaigns/create.html', sequences=sequences)

        campaign = Campaign(
            user_id=current_user.id,
            name=name,
            sequence_id=int(sequence_id) if sequence_id else None,
            content_mode=content_mode,
            draft_timeout_hours=draft_timeout,
            ab_rotation_method=ab_method,
            status=CampaignStatus.ACTIVE,
            notes=notes,
        )
        db.session.add(campaign)
        db.session.commit()
        flash(f'Campaign "{name}" created!', 'success')
        return redirect(url_for('campaigns.detail', campaign_id=campaign.id))

    return render_template('campaigns/create.html', sequences=sequences)


@campaigns_bp.route('/<int:campaign_id>')
@login_required
def detail(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    # Enrolled leads with various statuses
    enrolled = EnrolledLead.query.filter_by(campaign_id=campaign_id).all()
    status_filter = request.args.get('status', '')
    if status_filter:
        enrolled = [e for e in enrolled if e.status == status_filter]

    # Pending drafts (review queue)
    drafts = SendLog.query.join(
        EnrolledLead, SendLog.enrolled_lead_id == EnrolledLead.id
    ).filter(
        EnrolledLead.campaign_id == campaign_id,
        SendLog.status == 'draft'
    ).order_by(SendLog.id.desc()).all()

    # Tasks for this campaign
    tasks = TaskQueue.query.join(
        EnrolledLead, TaskQueue.enrolled_lead_id == EnrolledLead.id
    ).filter(
        EnrolledLead.campaign_id == campaign_id,
        TaskQueue.status == TaskStatus.PENDING
    ).order_by(TaskQueue.due_date).all()

    # Replies for this campaign
    replies = ReplyLog.query.join(
        EnrolledLead, ReplyLog.enrolled_lead_id == EnrolledLead.id
    ).filter(
        EnrolledLead.campaign_id == campaign_id
    ).order_by(ReplyLog.received_at.desc()).all()

    # Stats
    total_sent = SendLog.query.join(
        EnrolledLead, SendLog.enrolled_lead_id == EnrolledLead.id
    ).filter(
        EnrolledLead.campaign_id == campaign_id,
        SendLog.status == 'sent'
    ).count()

    tab = request.args.get('tab', 'overview')

    from models import Sequence
    sequences = Sequence.query.filter(
        (Sequence.user_id == current_user.id) | (Sequence.is_builtin == True)
    ).order_by(Sequence.name).all()

    return render_template(
        'campaigns/detail.html',
        campaign=campaign,
        enrolled=enrolled,
        drafts=drafts,
        tasks=tasks,
        replies=replies,
        total_sent=total_sent,
        tab=tab,
        status_filter=status_filter,
        sequences=sequences,
    )


@campaigns_bp.route('/<int:campaign_id>/pause', methods=['POST'])
@login_required
def pause_campaign(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()
    campaign.status = CampaignStatus.PAUSED
    db.session.commit()
    flash(f'Campaign "{campaign.name}" paused.', 'info')
    return redirect(url_for('campaigns.detail', campaign_id=campaign_id))


@campaigns_bp.route('/<int:campaign_id>/resume', methods=['POST'])
@login_required
def resume_campaign(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()
    campaign.status = CampaignStatus.ACTIVE
    db.session.commit()
    flash(f'Campaign "{campaign.name}" resumed.', 'success')
    return redirect(url_for('campaigns.detail', campaign_id=campaign_id))


@campaigns_bp.route('/<int:campaign_id>/settings', methods=['POST'])
@login_required
def update_settings(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    sequence_id_raw = request.form.get('sequence_id', '').strip()
    campaign.sequence_id = int(sequence_id_raw) if sequence_id_raw.isdigit() else None

    content_mode = request.form.get('content_mode', 'review')
    if content_mode not in ('auto', 'review', 'manual'):
        content_mode = 'review'
    campaign.content_mode = content_mode

    db.session.commit()

    seq_name = campaign.sequence.name if campaign.sequence else 'none'
    flash(f'Campaign updated — sequence: {seq_name}, mode: {content_mode}.', 'success')
    return redirect(url_for('campaigns.detail', campaign_id=campaign_id))


@campaigns_bp.route('/<int:campaign_id>/enroll', methods=['POST'])
@login_required
def enroll_leads(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    lead_ids = request.form.getlist('lead_ids')
    if not lead_ids:
        # Try JSON body
        data = request.get_json(silent=True) or {}
        lead_ids = data.get('lead_ids', [])

    if not lead_ids:
        flash('No leads selected for enrollment.', 'warning')
        return redirect(url_for('campaigns.detail', campaign_id=campaign_id))

    enrolled_count = 0
    skipped_count = 0
    for lead_id in lead_ids:
        lead = Lead.query.filter_by(id=int(lead_id), user_id=current_user.id).first()
        if not lead:
            continue
        # Check if already enrolled in this campaign
        existing = EnrolledLead.query.filter_by(
            campaign_id=campaign_id, lead_id=lead.id
        ).first()
        if existing:
            skipped_count += 1
            continue

        el = EnrolledLead(
            campaign_id=campaign_id,
            lead_id=lead.id,
            enrolled_at=datetime.utcnow(),
            status=EnrolledStatus.ACTIVE,
        )
        db.session.add(el)
        enrolled_count += 1

    db.session.commit()
    flash(f'Enrolled {enrolled_count} leads. {skipped_count} already in campaign.', 'success')
    return redirect(url_for('campaigns.detail', campaign_id=campaign_id))


@campaigns_bp.route('/<int:campaign_id>/drafts/<int:draft_id>/approve', methods=['POST'])
@login_required
def approve_draft(campaign_id, draft_id):
    draft = SendLog.query.get_or_404(draft_id)
    # Verify ownership
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    from email_service import send_email
    from models import EmailAccount, EnrolledLead

    el = EnrolledLead.query.get(draft.enrolled_lead_id)
    lead = el.lead

    accounts = EmailAccount.query.filter_by(user_id=current_user.id, active=True).all()
    if not accounts:
        flash('No email account configured. Add one in Settings.', 'danger')
        return redirect(url_for('campaigns.detail', campaign_id=campaign_id, tab='review'))

    sent_count = SendLog.query.filter_by(enrolled_lead_id=el.id, status='sent').count()
    account = accounts[sent_count % len(accounts)]

    success, error = send_email(account, lead.email, draft.subject,
                                 draft.body_snippet, current_user)
    if success:
        draft.status = 'sent'
        draft.sent_at = datetime.utcnow()
        draft.from_account_id = account.id
        db.session.commit()
        flash('Email sent successfully.', 'success')
    else:
        flash(f'Send failed: {error}', 'danger')

    return redirect(url_for('campaigns.detail', campaign_id=campaign_id, tab='review'))


@campaigns_bp.route('/<int:campaign_id>/drafts/<int:draft_id>/edit', methods=['POST'])
@login_required
def edit_draft(campaign_id, draft_id):
    draft = SendLog.query.get_or_404(draft_id)
    Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    new_subject = request.form.get('subject', draft.subject)
    new_body = request.form.get('body', draft.body_snippet)

    draft.subject = new_subject
    draft.body_snippet = new_body[:2000]
    db.session.commit()

    flash('Draft updated.', 'success')
    return redirect(url_for('campaigns.detail', campaign_id=campaign_id, tab='review'))


@campaigns_bp.route('/<int:campaign_id>/drafts/<int:draft_id>/skip', methods=['POST'])
@login_required
def skip_draft(campaign_id, draft_id):
    draft = SendLog.query.get_or_404(draft_id)
    Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()
    draft.status = 'skipped'
    db.session.commit()
    flash('Draft skipped.', 'info')
    return redirect(url_for('campaigns.detail', campaign_id=campaign_id, tab='review'))


@campaigns_bp.route('/<int:campaign_id>/stats')
@login_required
def campaign_stats(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    total_enrolled = campaign.enrolled_leads.count()
    active = campaign.enrolled_leads.filter_by(status=EnrolledStatus.ACTIVE).count()
    paused = campaign.enrolled_leads.filter_by(status=EnrolledStatus.PAUSED).count()
    complete = campaign.enrolled_leads.filter_by(status=EnrolledStatus.COMPLETE).count()
    unsubscribed = campaign.enrolled_leads.filter_by(status=EnrolledStatus.UNSUBSCRIBED).count()

    total_sent = SendLog.query.join(
        EnrolledLead, SendLog.enrolled_lead_id == EnrolledLead.id
    ).filter(
        EnrolledLead.campaign_id == campaign_id,
        SendLog.status == 'sent'
    ).count()

    total_replies = ReplyLog.query.join(
        EnrolledLead, ReplyLog.enrolled_lead_id == EnrolledLead.id
    ).filter(
        EnrolledLead.campaign_id == campaign_id
    ).count()

    reply_rate = round((total_replies / total_sent * 100), 1) if total_sent > 0 else 0

    # Variant breakdown
    from sqlalchemy import func
    variant_stats = db.session.query(
        SendLog.variant_label,
        func.count(SendLog.id).label('sent')
    ).join(
        EnrolledLead, SendLog.enrolled_lead_id == EnrolledLead.id
    ).filter(
        EnrolledLead.campaign_id == campaign_id,
        SendLog.status == 'sent'
    ).group_by(SendLog.variant_label).all()

    return jsonify({
        'total_enrolled': total_enrolled,
        'active': active,
        'paused': paused,
        'complete': complete,
        'unsubscribed': unsubscribed,
        'total_sent': total_sent,
        'total_replies': total_replies,
        'reply_rate': reply_rate,
        'variant_stats': [{'label': v.variant_label, 'sent': v.sent} for v in variant_stats],
    })


@campaigns_bp.route('/<int:campaign_id>/export')
@login_required
def export_csv(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    enrolled = EnrolledLead.query.filter_by(campaign_id=campaign_id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['First Name', 'Last Name', 'Email', 'Company', 'Title',
                     'Status', 'Enrolled At', 'Step'])

    for el in enrolled:
        lead = el.lead
        writer.writerow([
            lead.first_name, lead.last_name, lead.email, lead.company,
            lead.title, el.status,
            el.enrolled_at.strftime('%Y-%m-%d') if el.enrolled_at else '',
            el.current_step,
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=campaign_{campaign_id}.csv'}
    )


# ── Campaign AI Prompt Builder ────────────────────────────────────────────────

def _humanize_touch(slot):
    labels = {
        'opener':       'Opener — First Email',
        'observation':  'Opening Touch — Signal Observation',
        'hypothesis':   'Follow-up #2 — Hypothesis',
        'proof':        'Follow-up #3 — Proof / Case Study',
        'soft_close':   'Soft Close',
        'breakup':      'Breakup / Final Touch',
        'not_now':      'Not Now Reply',
        'link_clicked': 'Link Clicked Follow-up',
        'reply_received': 'Reply Received Response',
        'out_of_office':  'Out of Office Follow-up',
    }
    return labels.get(slot, slot.replace('_', ' ').title())


def _find_due_leads(campaign, days_out, limit):
    """
    Return up to `limit` enrolled leads whose next pending email step is due
    within today + days_out days and has no existing SendLog for that step.
    Each result dict includes all data needed to build the prompt and import.
    """
    from scheduler_jobs import _step_jitter

    if not campaign.sequence_id:
        return []

    today = date.today()
    cutoff = today + timedelta(days=days_out)

    email_steps = sorted(
        [s for s in campaign.sequence.steps.all() if s.channel == 'Email'],
        key=lambda s: s.day_offset
    )

    active_els = (EnrolledLead.query
                  .filter_by(campaign_id=campaign.id, status=EnrolledStatus.ACTIVE)
                  .order_by(EnrolledLead.enrolled_at)
                  .all())

    results = []
    for el in active_els:
        if len(results) >= limit:
            break

        lead = el.lead
        if lead.do_not_contact:
            continue
        dnc = DoNotContact.query.filter_by(
            user_id=campaign.user_id, email_address=lead.email
        ).first()
        if dnc:
            continue

        enrolled_date = el.enrolled_at.date() if el.enrolled_at else today

        for step in email_steps:
            jitter = _step_jitter(el.id, step.id)
            due_date = enrolled_date + timedelta(days=step.day_offset + jitter)

            if due_date > cutoff:
                continue  # not due yet within the window

            existing = SendLog.query.filter_by(
                enrolled_lead_id=el.id, step_id=step.id
            ).first()
            if existing:
                continue  # already has a log (sent/draft/queued)

            # Resolve template
            st = step.step_templates.filter_by(is_active=True).first()
            tmpl = st.template if st else Template.query.filter_by(
                touch_type=step.template_slot, is_builtin=True
            ).first()

            results.append({
                'enrolled_lead_id': el.id,
                'step_id':          step.id,
                'template_id':      tmpl.id if tmpl else None,
                'email':            lead.email,
                'lead':             lead,
                'touch_label':      _humanize_touch(step.template_slot),
                'template_subject': tmpl.subject if tmpl else '',
                'template_body':    tmpl.body    if tmpl else '',
                'due_date':         due_date,
            })
            break  # one pending step per lead

    return results


def _build_combined_prompt(results):
    """Build one prompt covering all leads, each labeled with their touch type."""
    lead_blocks = []
    for i, r in enumerate(results, 1):
        lead = r['lead']
        lines = [
            f'[Lead {i}]',
            f'EMAIL TYPE: {r["touch_label"]}',
        ]
        if r['template_body']:
            # Inline the template condensed so the AI knows the style/structure
            condensed = r['template_body'].replace('\n\n', ' | ').replace('\n', ' ')[:300]
            lines.append(f'STYLE GUIDE: {condensed}')
        lines.append(f'Email: {lead.email}')
        if lead.first_name:  lines.append(f'First Name: {lead.first_name}')
        if lead.last_name:   lines.append(f'Last Name: {lead.last_name}')
        if lead.company:     lines.append(f'Company: {lead.company}')
        if lead.title:       lines.append(f'Title: {lead.title}')
        if lead.website:     lines.append(f'Website: {lead.website}')
        if lead.signal_1:    lines.append(f'Signal 1: {lead.signal_1}')
        if lead.signal_2:    lines.append(f'Signal 2: {lead.signal_2}')
        lead_blocks.append('\n'.join(lines))

    prompt = f"""You are a B2B sales copywriter. Write one personalized email for EACH lead below.
Each lead specifies their EMAIL TYPE — write exactly that type of email for that person.

RULES:
- Under 100 words per email
- Plain text only — no bullet points, no HTML, no markdown
- Conversational and human — not salesy or corporate
- Personalize using the lead's name, company, title, and any signals
- Use the STYLE GUIDE as a structural reference — do not copy it verbatim
- Do not invent facts you don't have

OUTPUT FORMAT — use this exactly for every lead, no exceptions:

---LEAD:{{email address}}---
SUBJECT: {{subject line}}
BODY:
{{email body}}
---END---

Write all {len(results)} emails now. Start immediately with the first ---LEAD:--- block.

{'=' * 60}

""" + '\n\n'.join(lead_blocks)

    return prompt


@campaigns_bp.route('/<int:campaign_id>/write-with-ai', methods=['GET'])
@login_required
def write_with_ai(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    days_out = request.args.get('days_out', '')
    try:
        limit = max(1, min(200, int(request.args.get('limit', 30))))
    except (ValueError, TypeError):
        limit = 30

    results = []
    lead_step_map = {}   # email -> {enrolled_lead_id, step_id, template_id}

    if days_out:
        try:
            days_out_int = max(0, int(days_out))
        except (ValueError, TypeError):
            days_out_int = 1
        results = _find_due_leads(campaign, days_out_int, limit)
        lead_step_map = {
            r['email']: {
                'enrolled_lead_id': r['enrolled_lead_id'],
                'step_id':          r['step_id'],
                'template_id':      r['template_id'],
            }
            for r in results
        }

    return render_template(
        'campaigns/write_with_ai.html',
        campaign=campaign,
        results=results,
        days_out=days_out,
        limit=limit,
        lead_step_map_json=json.dumps(lead_step_map),
        prompt=_build_combined_prompt(results) if results else '',
    )


@campaigns_bp.route('/<int:campaign_id>/write-with-ai/import', methods=['POST'])
@login_required
def write_with_ai_import(campaign_id):
    campaign = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first_or_404()

    raw_output   = request.form.get('ai_output', '').strip()
    action       = request.form.get('action', 'draft')
    lead_step_raw = request.form.get('lead_step_map', '{}')

    if not raw_output:
        flash('Paste the AI output before importing.', 'warning')
        return redirect(url_for('campaigns.write_with_ai', campaign_id=campaign_id))

    try:
        lead_step_map = json.loads(lead_step_raw)
    except (ValueError, TypeError):
        lead_step_map = {}

    pattern = r'---LEAD:\s*(.*?)\s*---\s*SUBJECT:\s*(.*?)\s*BODY:\s*(.*?)\s*---END---'
    matches = re.findall(pattern, raw_output, re.DOTALL | re.IGNORECASE)

    if not matches:
        flash('Could not parse the AI output — make sure it includes all ---LEAD:--- and ---END--- markers.', 'danger')
        return redirect(url_for('campaigns.write_with_ai', campaign_id=campaign_id))

    saved = sent_ok = skipped = 0
    errors = []

    for email_addr, subject, body in matches:
        email_addr = email_addr.strip().lower()
        subject    = subject.strip()
        body       = body.strip()

        if not email_addr or not subject or not body:
            skipped += 1
            continue

        mapping = lead_step_map.get(email_addr) or lead_step_map.get(email_addr.lower())
        if not mapping:
            skipped += 1
            errors.append(f'{email_addr}: not in the generated lead list')
            continue

        el = EnrolledLead.query.filter_by(
            id=mapping['enrolled_lead_id'],
            campaign_id=campaign_id
        ).first()
        if not el or el.lead.user_id != current_user.id:
            skipped += 1
            errors.append(f'{email_addr}: enrollment not found')
            continue

        step_id    = mapping.get('step_id')
        template_id = mapping.get('template_id')

        # Prevent double-save if already has a log for this step
        if step_id and SendLog.query.filter_by(enrolled_lead_id=el.id, step_id=step_id).first():
            skipped += 1
            errors.append(f'{email_addr}: already has an email for this step')
            continue

        if action == 'send':
            from email_service import send_email
            from models import EmailAccount
            accounts = EmailAccount.query.filter_by(user_id=current_user.id, active=True).all()
            account  = accounts[sent_ok % len(accounts)] if accounts else None
            if not account:
                skipped += 1
                errors.append(f'{email_addr}: no active email account')
                continue
            success, error = send_email(account, el.lead.email, subject, body, current_user)
            log = SendLog(
                enrolled_lead_id=el.id,
                step_id=step_id,
                template_id=template_id,
                variant_label='AI-Prompt',
                subject=subject,
                body_snippet=body[:4000],
                status=SendStatus.SENT if success else SendStatus.FAILED,
                sent_at=datetime.utcnow() if success else None,
                from_account_id=account.id if success else None,
            )
            db.session.add(log)
            if success:
                sent_ok += 1
            else:
                skipped += 1
                errors.append(f'{email_addr}: send failed — {error}')
        else:
            log = SendLog(
                enrolled_lead_id=el.id,
                step_id=step_id,
                template_id=template_id,
                variant_label='AI-Prompt',
                subject=subject,
                body_snippet=body[:4000],
                status=SendStatus.DRAFT,
            )
            db.session.add(log)
            saved += 1

    db.session.commit()

    if action == 'send':
        flash(f'Sent {sent_ok} email{"s" if sent_ok != 1 else ""}. {skipped} skipped.', 'success')
    else:
        flash(f'{saved} draft{"s" if saved != 1 else ""} added to Review Queue. {skipped} skipped.', 'success')

    if errors:
        flash('Skipped: ' + '; '.join(errors[:5]) + (f' (+{len(errors)-5} more)' if len(errors) > 5 else ''), 'warning')

    return redirect(url_for('campaigns.detail', campaign_id=campaign_id, tab='review'))
