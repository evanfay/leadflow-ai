import csv
import io
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from . import campaigns_bp
from extensions import db
from models import (Campaign, Sequence, Lead, EnrolledLead, SendLog, ReplyLog,
                    TaskQueue, CampaignStatus, EnrolledStatus, ContentMode, TaskStatus)


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
