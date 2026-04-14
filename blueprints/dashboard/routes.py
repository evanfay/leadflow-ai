from flask import render_template
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from . import dashboard_bp
from models import Campaign, Lead, TaskQueue, ReplyLog, EnrolledLead
from models import CampaignStatus, TaskStatus, EnrolledStatus
from extensions import db


@dashboard_bp.route('/')
@login_required
def index():
    # Stats
    total_leads = Lead.query.filter_by(user_id=current_user.id).count()

    active_campaigns = Campaign.query.filter_by(
        user_id=current_user.id, status=CampaignStatus.ACTIVE
    ).count()

    tasks_pending = TaskQueue.query.filter_by(
        user_id=current_user.id, status=TaskStatus.PENDING
    ).count()

    # Replies this week
    week_ago = datetime.utcnow() - timedelta(days=7)
    replies_this_week = ReplyLog.query.join(
        EnrolledLead, ReplyLog.enrolled_lead_id == EnrolledLead.id
    ).join(
        Campaign, EnrolledLead.campaign_id == Campaign.id
    ).filter(
        Campaign.user_id == current_user.id,
        ReplyLog.received_at >= week_ago
    ).count()

    # Active campaigns list
    campaigns = Campaign.query.filter_by(
        user_id=current_user.id, status=CampaignStatus.ACTIVE
    ).order_by(Campaign.created_at.desc()).limit(5).all()

    # Pending tasks
    pending_tasks = TaskQueue.query.filter_by(
        user_id=current_user.id, status=TaskStatus.PENDING
    ).order_by(TaskQueue.due_date).limit(5).all()

    # Recent replies (unhandled)
    recent_replies = ReplyLog.query.join(
        EnrolledLead, ReplyLog.enrolled_lead_id == EnrolledLead.id
    ).join(
        Campaign, EnrolledLead.campaign_id == Campaign.id
    ).filter(
        Campaign.user_id == current_user.id,
        ReplyLog.handled == False
    ).order_by(ReplyLog.received_at.desc()).limit(5).all()

    return render_template(
        'dashboard.html',
        total_leads=total_leads,
        active_campaigns=active_campaigns,
        tasks_pending=tasks_pending,
        replies_this_week=replies_this_week,
        campaigns=campaigns,
        pending_tasks=pending_tasks,
        recent_replies=recent_replies,
    )
