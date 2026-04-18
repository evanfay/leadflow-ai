import json
import os
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from . import settings_bp
from extensions import db
from models import EmailAccount, Template, User
from crypto_utils import encrypt, decrypt


@settings_bp.route('/')
@login_required
def index():
    return render_template('settings/index.html')


@settings_bp.route('/', methods=['POST'])
@login_required
def save_settings():
    # Save global settings to user record or an app config table
    flash('Settings saved.', 'success')
    return redirect(url_for('settings.index'))


@settings_bp.route('/email-accounts')
@login_required
def email_accounts():
    accounts = EmailAccount.query.filter_by(user_id=current_user.id).all()
    return render_template('settings/email_accounts.html', accounts=accounts)


@settings_bp.route('/email-accounts', methods=['POST'])
@login_required
def add_email_account():
    email_address = request.form.get('email_address', '').strip()
    smtp_password = request.form.get('smtp_password', '').strip()

    # daily_limit: 0 = no cap
    no_cap = request.form.get('no_cap') or (request.form.get('daily_limit', '30') == '0')
    daily_limit = 0 if no_cap else max(1, int(request.form.get('daily_limit', 30) or 30))

    warmup_enabled = bool(request.form.get('warmup_enabled'))
    warmup_tier = request.form.get('warmup_tier', 'medium')
    if warmup_tier not in ('slow', 'medium', 'aggressive'):
        warmup_tier = 'medium'

    if not email_address or not smtp_password:
        flash('Email address and password are required.', 'danger')
        return redirect(url_for('settings.email_accounts'))

    existing = EmailAccount.query.filter_by(
        user_id=current_user.id, email_address=email_address
    ).first()
    if existing:
        flash('That email account is already connected.', 'warning')
        return redirect(url_for('settings.email_accounts'))

    account = EmailAccount(
        user_id=current_user.id,
        email_address=email_address,
        auth_method='smtp',
        smtp_password_encrypted=encrypt(smtp_password),
        daily_limit=daily_limit,
        warmup_enabled=warmup_enabled,
        warmup_tier=warmup_tier,
        warmup_week=1,
        active=True,
    )
    db.session.add(account)
    db.session.commit()
    warmup_msg = f' Warmup: {warmup_tier} tier.' if warmup_enabled else ''
    flash(f'Account {email_address} added.{warmup_msg}', 'success')
    return redirect(url_for('settings.email_accounts'))


@settings_bp.route('/email-accounts/oauth/connect')
@login_required
def oauth_connect():
    """Start Gmail OAuth flow."""
    secrets_file = current_app.config.get('GOOGLE_CLIENT_SECRETS_FILE', 'google_credentials.json')
    if not os.path.exists(secrets_file):
        flash('Google OAuth credentials file not found. Please configure GOOGLE_CLIENT_SECRETS_FILE.', 'danger')
        return redirect(url_for('settings.email_accounts'))

    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(
            secrets_file,
            scopes=[
                'https://www.googleapis.com/auth/gmail.send',
                'https://www.googleapis.com/auth/gmail.readonly',
            ],
            redirect_uri=url_for('settings.oauth_callback', _external=True)
        )
        auth_url, state = flow.authorization_url(
            access_type='offline', include_granted_scopes='true', prompt='consent'
        )
        from flask import session
        session['oauth_state'] = state
        return redirect(auth_url)
    except Exception as e:
        flash(f'OAuth error: {e}', 'danger')
        return redirect(url_for('settings.email_accounts'))


@settings_bp.route('/email-accounts/oauth/callback')
@login_required
def oauth_callback():
    """Handle OAuth callback from Google."""
    secrets_file = current_app.config.get('GOOGLE_CLIENT_SECRETS_FILE', 'google_credentials.json')

    try:
        from google_auth_oauthlib.flow import Flow
        from flask import session
        flow = Flow.from_client_secrets_file(
            secrets_file,
            scopes=[
                'https://www.googleapis.com/auth/gmail.send',
                'https://www.googleapis.com/auth/gmail.readonly',
            ],
            redirect_uri=url_for('settings.oauth_callback', _external=True),
            state=session.get('oauth_state')
        )
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials

        # Get user's Gmail address
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds)
        profile = service.users().getProfile(userId='me').execute()
        email_address = profile['emailAddress']

        token_data = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
        }

        existing = EmailAccount.query.filter_by(
            user_id=current_user.id, email_address=email_address
        ).first()

        if existing:
            existing.oauth_token_encrypted = encrypt(json.dumps(token_data))
            existing.auth_method = 'oauth'
            existing.active = True
        else:
            account = EmailAccount(
                user_id=current_user.id,
                email_address=email_address,
                auth_method='oauth',
                oauth_token_encrypted=encrypt(json.dumps(token_data)),
                daily_limit=50,
                active=True,
            )
            db.session.add(account)

        db.session.commit()
        flash(f'Gmail account {email_address} connected!', 'success')
    except Exception as e:
        flash(f'OAuth callback error: {e}', 'danger')

    return redirect(url_for('settings.email_accounts'))


@settings_bp.route('/email-accounts/<int:account_id>/delete', methods=['POST'])
@login_required
def delete_email_account(account_id):
    account = EmailAccount.query.filter_by(
        id=account_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(account)
    db.session.commit()
    flash(f'Account {account.email_address} removed.', 'success')
    return redirect(url_for('settings.email_accounts'))


@settings_bp.route('/email-accounts/<int:account_id>/update', methods=['POST'])
@login_required
def update_email_account(account_id):
    account = EmailAccount.query.filter_by(
        id=account_id, user_id=current_user.id
    ).first_or_404()

    # Daily cap
    daily_limit_raw = request.form.get('daily_limit', '30')
    try:
        daily_limit = int(daily_limit_raw)
    except (ValueError, TypeError):
        daily_limit = 30
    # No-cap: form sends 0 or the no_cap checkbox
    account.daily_limit = max(0, daily_limit)

    # Warmup
    account.warmup_enabled = bool(request.form.get('warmup_enabled'))
    tier = request.form.get('warmup_tier', 'medium')
    account.warmup_tier = tier if tier in ('slow', 'medium', 'aggressive') else 'medium'
    try:
        account.warmup_week = max(1, int(request.form.get('warmup_week', 1)))
    except (ValueError, TypeError):
        account.warmup_week = 1

    db.session.commit()
    flash(f'Settings updated for {account.email_address}.', 'success')
    return redirect(url_for('settings.email_accounts'))


@settings_bp.route('/email-accounts/<int:account_id>/toggle', methods=['POST'])
@login_required
def toggle_email_account(account_id):
    account = EmailAccount.query.filter_by(
        id=account_id, user_id=current_user.id
    ).first_or_404()
    account.active = not account.active
    db.session.commit()
    return jsonify({'ok': True, 'active': account.active})


@settings_bp.route('/templates')
@login_required
def templates():
    builtin = Template.query.filter_by(is_builtin=True).order_by(Template.touch_type, Template.name).all()
    custom = Template.query.filter_by(user_id=current_user.id, is_builtin=False).order_by(Template.name).all()
    return render_template('settings/templates.html', builtin=builtin, custom=custom)


@settings_bp.route('/templates', methods=['POST'])
@login_required
def create_template():
    name = request.form.get('name', '').strip()
    touch_type = request.form.get('touch_type', '').strip()
    subject = request.form.get('subject', '').strip()
    body = request.form.get('body', '').strip()

    if not name or not touch_type:
        flash('Name and touch type are required.', 'danger')
        return redirect(url_for('settings.templates'))

    template = Template(
        user_id=current_user.id,
        name=name,
        touch_type=touch_type,
        subject=subject,
        body=body,
        is_builtin=False,
    )
    db.session.add(template)
    db.session.commit()
    flash(f'Template "{name}" created.', 'success')
    return redirect(url_for('settings.templates'))


@settings_bp.route('/templates/<int:template_id>', methods=['POST'])
@login_required
def update_template(template_id):
    template = Template.query.filter_by(
        id=template_id, user_id=current_user.id, is_builtin=False
    ).first_or_404()

    template.name = request.form.get('name', template.name).strip()
    template.touch_type = request.form.get('touch_type', template.touch_type).strip()
    template.subject = request.form.get('subject', template.subject).strip()
    template.body = request.form.get('body', template.body).strip()
    db.session.commit()
    flash('Template updated.', 'success')
    return redirect(url_for('settings.templates'))


@settings_bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@login_required
def delete_template(template_id):
    template = Template.query.filter_by(
        id=template_id, user_id=current_user.id, is_builtin=False
    ).first_or_404()
    db.session.delete(template)
    db.session.commit()
    flash('Template deleted.', 'success')
    return redirect(url_for('settings.templates'))


@settings_bp.route('/deliverability')
@login_required
def deliverability():
    from scheduler_jobs import get_account_health, check_template_spam_score

    accounts = EmailAccount.query.filter_by(user_id=current_user.id).all()
    health = [get_account_health(a) for a in accounts]

    # Scan all templates (builtin + user's own)
    templates = Template.query.filter(
        (Template.user_id == current_user.id) | (Template.is_builtin == True)
    ).filter(Template.touch_type.in_([
        'observation', 'hypothesis', 'proof', 'soft_close', 'breakup',
        'not_now', 'link_clicked', 'reply_received', 'out_of_office'
    ])).order_by(Template.is_builtin.desc(), Template.name).all()

    template_scores = []
    for t in templates:
        score, flagged = check_template_spam_score(t.body or '')
        template_scores.append({
            'name': t.name,
            'touch_type': t.touch_type,
            'score': score,
            'flagged': flagged,
        })

    return render_template('settings/deliverability.html',
                           accounts=accounts, health=health,
                           template_scores=template_scores)


@settings_bp.route('/profile')
@login_required
def profile():
    return render_template('settings/profile.html')


@settings_bp.route('/profile', methods=['POST'])
@login_required
def update_profile():
    action = request.form.get('action', 'profile')

    if action == 'profile':
        current_user.display_name = request.form.get('display_name', '').strip()
        current_user.signature = request.form.get('signature', '').strip()
        db.session.commit()
        flash('Profile updated.', 'success')

    elif action == 'api_key':
        api_key = request.form.get('anthropic_api_key', '').strip()
        if api_key:
            current_user.anthropic_api_key_encrypted = encrypt(api_key)
            db.session.commit()
            flash('API key updated.', 'success')
        else:
            flash('API key cannot be empty.', 'danger')

    elif action == 'scraper':
        threshold = request.form.get('scraper_email_threshold', '6')
        try:
            threshold = max(1, min(10, int(threshold)))
        except (ValueError, TypeError):
            threshold = 6
        current_user.scraper_email_threshold = threshold
        db.session.commit()
        flash('Scraper settings saved.', 'success')

    elif action == 'password':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')

        if not current_user.check_password(current_pw):
            flash('Current password is incorrect.', 'danger')
        elif len(new_pw) < 8:
            flash('New password must be at least 8 characters.', 'danger')
        elif new_pw != confirm_pw:
            flash('Passwords do not match.', 'danger')
        else:
            current_user.set_password(new_pw)
            db.session.commit()
            flash('Password changed.', 'success')

    return redirect(url_for('settings.profile'))
