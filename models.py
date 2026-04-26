import json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


# ── Status constants ───────────────────────────────────────────────────────────
class CampaignStatus:
    ACTIVE = 'active'
    PAUSED = 'paused'
    COMPLETE = 'complete'
    ARCHIVED = 'archived'

class EnrolledStatus:
    ACTIVE = 'active'
    PAUSED = 'paused'
    COMPLETE = 'complete'
    UNSUBSCRIBED = 'unsubscribed'
    DO_NOT_CONTACT = 'do_not_contact'
    BOUNCED = 'bounced'

class TaskStatus:
    PENDING = 'pending'
    COMPLETE = 'complete'
    SKIPPED = 'skipped'

class SendStatus:
    DRAFT = 'draft'
    SENT = 'sent'
    FAILED = 'failed'
    SKIPPED = 'skipped'

class AuthMethod:
    SMTP = 'smtp'
    OAUTH = 'oauth'

class ContentMode:
    AUTO = 'auto'
    REVIEW = 'review'
    MANUAL = 'manual'


# ── Models ─────────────────────────────────────────────────────────────────────
class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), default='')
    signature = db.Column(db.Text, default='')
    anthropic_api_key_encrypted = db.Column(db.Text, default='')
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    scraper_email_threshold = db.Column(db.Integer, default=6)

    # Relationships
    leads = db.relationship('Lead', backref='user', lazy='dynamic')
    campaigns = db.relationship('Campaign', backref='user', lazy='dynamic')
    sequences = db.relationship('Sequence', backref='user', lazy='dynamic')
    templates = db.relationship('Template', backref='user', lazy='dynamic')
    email_accounts = db.relationship('EmailAccount', backref='user', lazy='dynamic')
    tasks = db.relationship('TaskQueue', backref='user', lazy='dynamic')
    scraper_leads = db.relationship('ScraperLead', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.id)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def __repr__(self):
        return f'<User {self.email}>'


class Lead(db.Model):
    __tablename__ = 'leads'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), default='')
    last_name = db.Column(db.String(100), default='')
    company = db.Column(db.String(255), default='')
    title = db.Column(db.String(255), default='')
    website = db.Column(db.String(500), default='')
    phone = db.Column(db.String(50), default='')
    linkedin_url = db.Column(db.String(500), default='')
    signal_1 = db.Column(db.Text, default='')
    signal_2 = db.Column(db.Text, default='')
    signal_3 = db.Column(db.Text, default='')
    account_grade = db.Column(db.String(10), default='B')
    notes = db.Column(db.Text, default='')
    do_not_contact = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    source = db.Column(db.String(100), default='manual')
    extra_data = db.Column(db.Text, default=None)

    # Relationships
    enrolled_leads = db.relationship('EnrolledLead', backref='lead', lazy='dynamic')

    def __repr__(self):
        return f'<Lead {self.first_name} {self.last_name} <{self.email}>>'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip() or self.email

    @property
    def custom_fields(self):
        if self.extra_data:
            try:
                return json.loads(self.extra_data)
            except (ValueError, TypeError):
                return {}
        return {}


class Sequence(db.Model):
    __tablename__ = 'sequences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default='')
    is_builtin = db.Column(db.Boolean, default=False)

    steps = db.relationship('SequenceStep', backref='sequence', lazy='dynamic',
                             cascade='all, delete-orphan')
    campaigns = db.relationship('Campaign', backref='sequence', lazy='dynamic')

    def __repr__(self):
        return f'<Sequence {self.name}>'

    @property
    def step_count(self):
        return self.steps.count()

    @property
    def email_count(self):
        return self.steps.filter_by(channel='Email').count()

    @property
    def duration_days(self):
        steps = self.steps.order_by(SequenceStep.day_offset.desc()).first()
        return steps.day_offset if steps else 0


class SequenceStep(db.Model):
    __tablename__ = 'sequence_steps'

    id = db.Column(db.Integer, primary_key=True)
    sequence_id = db.Column(db.Integer, db.ForeignKey('sequences.id'), nullable=False, index=True)
    day_offset = db.Column(db.Integer, nullable=False)
    channel = db.Column(db.String(50), nullable=False)  # Email, LinkedIn, Phone
    template_slot = db.Column(db.String(100), nullable=False)  # touch_type name
    is_auto = db.Column(db.Boolean, default=True)

    step_templates = db.relationship('StepTemplate', backref='step', lazy='dynamic',
                                      cascade='all, delete-orphan')
    send_logs = db.relationship('SendLog', backref='step', lazy='dynamic')
    tasks = db.relationship('TaskQueue', backref='step', lazy='dynamic')

    def __repr__(self):
        return f'<SequenceStep Day {self.day_offset} {self.channel}>'


class Template(db.Model):
    __tablename__ = 'templates'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # None = builtin
    name = db.Column(db.String(255), nullable=False)
    touch_type = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(500), default='')
    body = db.Column(db.Text, default='')
    is_builtin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    step_templates = db.relationship('StepTemplate', backref='template', lazy='dynamic')
    send_logs = db.relationship('SendLog', backref='template', lazy='dynamic')

    def __repr__(self):
        return f'<Template {self.name}>'


class StepTemplate(db.Model):
    __tablename__ = 'step_templates'

    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, db.ForeignKey('sequence_steps.id'), nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey('templates.id'), nullable=False)
    variant_label = db.Column(db.String(10), default='A')
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<StepTemplate Step {self.step_id} Variant {self.variant_label}>'


class Campaign(db.Model):
    __tablename__ = 'campaigns'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    sequence_id = db.Column(db.Integer, db.ForeignKey('sequences.id'), nullable=True)
    content_mode = db.Column(db.String(20), default=ContentMode.REVIEW)
    draft_timeout_hours = db.Column(db.Integer, default=24)
    ab_rotation_method = db.Column(db.String(20), default='round_robin')
    status = db.Column(db.String(20), default=CampaignStatus.ACTIVE)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text, default='')

    enrolled_leads = db.relationship('EnrolledLead', backref='campaign', lazy='dynamic',
                                      cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Campaign {self.name}>'

    @property
    def active_lead_count(self):
        return self.enrolled_leads.filter_by(status=EnrolledStatus.ACTIVE).count()

    @property
    def total_lead_count(self):
        return self.enrolled_leads.count()

    @property
    def reply_count(self):
        from sqlalchemy import func
        count = 0
        for el in self.enrolled_leads:
            count += ReplyLog.query.filter_by(enrolled_lead_id=el.id).count()
        return count


class EnrolledLead(db.Model):
    __tablename__ = 'enrolled_leads'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.id'), nullable=False, index=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('leads.id'), nullable=False, index=True)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)
    current_step = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default=EnrolledStatus.ACTIVE)
    engagement_score = db.Column(db.Integer, default=0)
    paused_reason = db.Column(db.String(500), default='')
    resume_at = db.Column(db.DateTime, nullable=True)
    # Pinned sending account — future touches always come from this address
    from_account_id = db.Column(db.Integer, db.ForeignKey('email_accounts.id'), nullable=True)

    send_logs = db.relationship('SendLog', backref='enrolled_lead', lazy='dynamic',
                                 cascade='all, delete-orphan')
    reply_logs = db.relationship('ReplyLog', backref='enrolled_lead', lazy='dynamic',
                                  cascade='all, delete-orphan')
    tasks = db.relationship('TaskQueue', backref='enrolled_lead', lazy='dynamic')

    def __repr__(self):
        return f'<EnrolledLead campaign={self.campaign_id} lead={self.lead_id}>'

    @property
    def is_active(self):
        return self.status == EnrolledStatus.ACTIVE


class SendLog(db.Model):
    __tablename__ = 'send_log'

    id = db.Column(db.Integer, primary_key=True)
    enrolled_lead_id = db.Column(db.Integer, db.ForeignKey('enrolled_leads.id'), nullable=False, index=True)
    step_id = db.Column(db.Integer, db.ForeignKey('sequence_steps.id'), nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey('templates.id'), nullable=True)
    variant_label = db.Column(db.String(10), default='A')
    sent_at = db.Column(db.DateTime, nullable=True)
    from_account_id = db.Column(db.Integer, db.ForeignKey('email_accounts.id'), nullable=True)
    subject = db.Column(db.String(500), default='')
    body_snippet = db.Column(db.Text, default='')
    status = db.Column(db.String(20), default=SendStatus.DRAFT)

    from_account = db.relationship('EmailAccount', backref='send_logs', lazy='joined')

    def __repr__(self):
        return f'<SendLog {self.status} {self.sent_at}>'


class EmailAccount(db.Model):
    __tablename__ = 'email_accounts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    email_address = db.Column(db.String(255), nullable=False)
    auth_method = db.Column(db.String(10), default=AuthMethod.SMTP)
    smtp_host = db.Column(db.String(255), default='smtp.gmail.com')
    smtp_port = db.Column(db.Integer, default=465)
    smtp_password_encrypted = db.Column(db.Text, default='')
    oauth_token_encrypted = db.Column(db.Text, default='')
    imap_host = db.Column(db.String(255), default=None)
    imap_port = db.Column(db.Integer, default=993)
    imap_password_encrypted = db.Column(db.Text, default=None)
    daily_limit = db.Column(db.Integer, default=30)   # 0 = no cap
    warmup_enabled = db.Column(db.Boolean, default=False)
    warmup_tier = db.Column(db.String(20), default='medium')  # slow | medium | aggressive
    warmup_week = db.Column(db.Integer, default=1)
    active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<EmailAccount {self.email_address}>'

    @property
    def sent_today(self):
        today = datetime.utcnow().date()
        return SendLog.query.filter(
            SendLog.from_account_id == self.id,
            SendLog.status == SendStatus.SENT,
            db.func.date(SendLog.sent_at) == today
        ).count()


class ReplyLog(db.Model):
    __tablename__ = 'reply_log'

    id = db.Column(db.Integer, primary_key=True)
    enrolled_lead_id = db.Column(db.Integer, db.ForeignKey('enrolled_leads.id'), nullable=False, index=True)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    reply_category = db.Column(db.String(50), default='positive')
    snippet = db.Column(db.Text, default='')
    suggested_reply = db.Column(db.Text, default='')
    handled = db.Column(db.Boolean, default=False)
    followup_due_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<ReplyLog {self.reply_category} handled={self.handled}>'


class TaskQueue(db.Model):
    __tablename__ = 'task_queue'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    enrolled_lead_id = db.Column(db.Integer, db.ForeignKey('enrolled_leads.id'), nullable=True)
    step_id = db.Column(db.Integer, db.ForeignKey('sequence_steps.id'), nullable=True)
    task_type = db.Column(db.String(50), nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default=TaskStatus.PENDING)
    notes = db.Column(db.Text, default='')

    def __repr__(self):
        return f'<TaskQueue {self.task_type} {self.status}>'

    @property
    def is_overdue(self):
        if self.due_date and self.status == TaskStatus.PENDING:
            return self.due_date < datetime.utcnow().date()
        return False


class DoNotContact(db.Model):
    __tablename__ = 'do_not_contact'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    email_address = db.Column(db.String(255), nullable=False)
    reason = db.Column(db.String(500), default='')
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<DoNotContact {self.email_address}>'


class ScraperLead(db.Model):
    __tablename__ = 'scraper_leads'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(255), default='')
    address = db.Column(db.String(500), default='')
    phone = db.Column(db.String(50), default='')
    website = db.Column(db.String(500), default='')
    rating = db.Column(db.String(20), default='')
    reviews = db.Column(db.String(20), default='')
    source = db.Column(db.String(50), default='')
    email_found = db.Column(db.String(255), default='')
    email_tier = db.Column(db.String(20), default='')
    query = db.Column(db.String(500), default='')
    industry = db.Column(db.String(100), default='')
    biz_size = db.Column(db.String(20), default='')
    score = db.Column(db.Integer, default=0)
    reasoning = db.Column(db.Text, default='')
    pain_points_json = db.Column(db.Text, default='[]')
    owner_reachable = db.Column(db.Boolean, default=False)
    variant = db.Column(db.String(5), default='')
    email_subject = db.Column(db.String(500), default='')
    email_body = db.Column(db.Text, default='')
    revenue_setup = db.Column(db.Integer, default=0)
    revenue_monthly = db.Column(db.Integer, default=0)
    revenue_annual = db.Column(db.Integer, default=0)
    revenue_label = db.Column(db.String(500), default='')
    status = db.Column(db.String(30), default='pending')
    scraped_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)
    replied = db.Column(db.Boolean, default=False)
    bounced = db.Column(db.Boolean, default=False)
    unsubscribed = db.Column(db.Boolean, default=False)
    send_error = db.Column(db.String(500), default='')
    followup_1_due = db.Column(db.String(20), default='')
    followup_2_due = db.Column(db.String(20), default='')
    followup_1_sent = db.Column(db.Boolean, default=False)
    followup_2_sent = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<ScraperLead {self.name}>'

    @property
    def pain_points(self):
        import json
        try:
            return json.loads(self.pain_points_json or '[]')
        except Exception:
            return []

    @pain_points.setter
    def pain_points(self, value):
        import json
        self.pain_points_json = json.dumps(value or [])
