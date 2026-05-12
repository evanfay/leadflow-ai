from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from . import inbox_bp
from extensions import db
from models import ReplyLog, EnrolledLead, Campaign, Lead, TaskQueue, DoNotContact
from models import EnrolledStatus, TaskStatus
from datetime import datetime


@inbox_bp.route('/')
@inbox_bp.route('')
@login_required
def replies():
    category_filter = request.args.get('category', '')

    base_query = ReplyLog.query.join(
        EnrolledLead, ReplyLog.enrolled_lead_id == EnrolledLead.id
    ).join(
        Campaign, EnrolledLead.campaign_id == Campaign.id
    ).filter(Campaign.user_id == current_user.id)

    if category_filter:
        query = base_query.filter(ReplyLog.reply_category == category_filter)
    else:
        query = base_query

    reply_logs = query.order_by(ReplyLog.received_at.desc()).all()

    # Category counts — only unhandled, so badges clear when handled
    unhandled = base_query.filter(ReplyLog.handled == False).all()
    counts = {}
    for r in unhandled:
        counts[r.reply_category] = counts.get(r.reply_category, 0) + 1

    active_campaigns = Campaign.query.filter_by(
        user_id=current_user.id, status='active'
    ).order_by(Campaign.name).all()

    return render_template('inbox/replies.html', reply_logs=reply_logs,
                           counts=counts, category_filter=category_filter,
                           active_campaigns=active_campaigns)


@inbox_bp.route('/<int:reply_id>/send', methods=['POST'])
@login_required
def send_reply(reply_id):
    reply = ReplyLog.query.get_or_404(reply_id)
    el = EnrolledLead.query.get(reply.enrolled_lead_id)
    campaign = Campaign.query.filter_by(id=el.campaign_id, user_id=current_user.id).first_or_404()

    body = request.form.get('body', reply.suggested_reply)
    subject = request.form.get('subject', 'Re: following up')

    from models import EmailAccount
    from email_service import send_email

    accounts = EmailAccount.query.filter_by(user_id=current_user.id, active=True).all()
    if not accounts:
        flash('No email account configured.', 'danger')
        return redirect(url_for('inbox.replies'))

    lead = el.lead
    success, error = send_email(accounts[0], lead.email, subject, body, current_user)

    if success:
        reply.handled = True
        db.session.commit()
        flash('Reply sent successfully.', 'success')
    else:
        flash(f'Send failed: {error}', 'danger')

    return redirect(url_for('inbox.replies'))


@inbox_bp.route('/<int:reply_id>/handle', methods=['POST'])
@login_required
def handle_reply(reply_id):
    reply = ReplyLog.query.get_or_404(reply_id)
    el = EnrolledLead.query.get(reply.enrolled_lead_id)
    Campaign.query.filter_by(id=el.campaign_id, user_id=current_user.id).first_or_404()

    reply.handled = True
    db.session.commit()

    if request.is_json:
        return jsonify({'ok': True})
    flash('Reply marked as handled.', 'success')
    return redirect(url_for('inbox.replies'))


@inbox_bp.route('/<int:reply_id>/reenroll', methods=['POST'])
@login_required
def reenroll(reply_id):
    reply = ReplyLog.query.get_or_404(reply_id)
    el = EnrolledLead.query.get(reply.enrolled_lead_id)
    Campaign.query.filter_by(id=el.campaign_id, user_id=current_user.id).first_or_404()

    campaign_id = request.form.get('campaign_id')
    if not campaign_id:
        flash('Select a campaign to re-enroll.', 'warning')
        return redirect(url_for('inbox.replies'))

    new_campaign = Campaign.query.filter_by(
        id=int(campaign_id), user_id=current_user.id
    ).first_or_404()

    existing = EnrolledLead.query.filter_by(
        campaign_id=new_campaign.id, lead_id=el.lead_id
    ).first()

    if existing:
        flash('Lead already enrolled in that campaign.', 'warning')
        return redirect(url_for('inbox.replies'))

    new_el = EnrolledLead(
        campaign_id=new_campaign.id,
        lead_id=el.lead_id,
        status=EnrolledStatus.ACTIVE,
        enrolled_at=datetime.utcnow(),
    )
    db.session.add(new_el)
    reply.handled = True
    db.session.commit()

    flash(f'Lead re-enrolled in "{new_campaign.name}".', 'success')
    return redirect(url_for('inbox.replies'))
