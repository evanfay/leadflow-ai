import csv
import io
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from . import leads_bp
from extensions import db
from models import Lead, Campaign, EnrolledLead, EnrolledStatus


@leads_bp.route('/')
@login_required
def pool():
    q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    company_filter = request.args.get('company', '').strip()

    query = Lead.query.filter_by(user_id=current_user.id)

    if q:
        query = query.filter(
            (Lead.first_name.ilike(f'%{q}%')) |
            (Lead.last_name.ilike(f'%{q}%')) |
            (Lead.email.ilike(f'%{q}%')) |
            (Lead.company.ilike(f'%{q}%'))
        )

    if company_filter:
        query = query.filter(Lead.company.ilike(f'%{company_filter}%'))

    leads = query.order_by(Lead.created_at.desc()).all()

    # Campaigns for bulk enroll dropdown
    campaigns = Campaign.query.filter_by(user_id=current_user.id).order_by(Campaign.name).all()

    return render_template('leads/pool.html', leads=leads, campaigns=campaigns,
                           q=q, status_filter=status_filter)


@leads_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash('Please select a file.', 'danger')
            return redirect(url_for('leads.upload'))

        filename = file.filename.lower()
        rows = []

        try:
            if filename.endswith('.csv'):
                content = file.stream.read().decode('utf-8-sig', errors='replace')
                reader = csv.DictReader(io.StringIO(content))
                rows = list(reader)
            elif filename.endswith(('.xlsx', '.xls')):
                import openpyxl
                wb = openpyxl.load_workbook(file.stream)
                ws = wb.active
                headers = [str(c.value or '').strip() for c in next(ws.iter_rows(max_row=1))]
                for row in ws.iter_rows(min_row=2, values_only=True):
                    rows.append(dict(zip(headers, [str(v or '') for v in row])))
            else:
                flash('Only CSV and Excel files are supported.', 'danger')
                return redirect(url_for('leads.upload'))
        except Exception as e:
            flash(f'Error reading file: {e}', 'danger')
            return redirect(url_for('leads.upload'))

        if not rows:
            flash('File is empty or could not be read.', 'warning')
            return redirect(url_for('leads.upload'))

        # Parse column mapping from form
        mapping = {
            'email': request.form.get('col_email', ''),
            'first_name': request.form.get('col_first_name', ''),
            'last_name': request.form.get('col_last_name', ''),
            'company': request.form.get('col_company', ''),
            'title': request.form.get('col_title', ''),
            'website': request.form.get('col_website', ''),
            'phone': request.form.get('col_phone', ''),
            'linkedin_url': request.form.get('col_linkedin', ''),
            'signal_1': request.form.get('col_signal_1', ''),
            'signal_2': request.form.get('col_signal_2', ''),
        }

        if not mapping['email']:
            # Auto-detect: look for column named 'email'
            for col in (rows[0].keys() if rows else []):
                if 'email' in col.lower():
                    mapping['email'] = col
                    break

        if not mapping['email']:
            flash('Could not find email column. Please map columns.', 'danger')
            headers = list(rows[0].keys()) if rows else []
            return render_template('leads/upload.html', rows=rows[:5], headers=headers,
                                   mapping=mapping)

        imported = 0
        skipped = 0
        for row in rows:
            email = row.get(mapping['email'], '').strip()
            if not email or '@' not in email:
                skipped += 1
                continue

            # Check for duplicate
            existing = Lead.query.filter_by(user_id=current_user.id, email=email).first()
            if existing:
                skipped += 1
                continue

            def gv(col_key):
                col = mapping.get(col_key, '')
                return row.get(col, '').strip() if col else ''

            lead = Lead(
                user_id=current_user.id,
                email=email,
                first_name=gv('first_name'),
                last_name=gv('last_name'),
                company=gv('company'),
                title=gv('title'),
                website=gv('website'),
                phone=gv('phone'),
                linkedin_url=gv('linkedin_url'),
                signal_1=gv('signal_1'),
                signal_2=gv('signal_2'),
                source='upload',
            )
            db.session.add(lead)
            imported += 1

        db.session.commit()
        flash(f'Imported {imported} leads. {skipped} duplicates or invalid rows skipped.', 'success')
        return redirect(url_for('leads.pool'))

    return render_template('leads/upload.html', rows=[], headers=[], mapping={})


@leads_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_lead():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            flash('Email is required.', 'danger')
            return render_template('leads/new.html')

        existing = Lead.query.filter_by(user_id=current_user.id, email=email).first()
        if existing:
            flash('A lead with that email already exists.', 'warning')
            return redirect(url_for('leads.detail', lead_id=existing.id))

        lead = Lead(
            user_id=current_user.id,
            email=email,
            first_name=request.form.get('first_name', '').strip(),
            last_name=request.form.get('last_name', '').strip(),
            company=request.form.get('company', '').strip(),
            title=request.form.get('title', '').strip(),
            website=request.form.get('website', '').strip(),
            phone=request.form.get('phone', '').strip(),
            linkedin_url=request.form.get('linkedin_url', '').strip(),
            signal_1=request.form.get('signal_1', '').strip(),
            signal_2=request.form.get('signal_2', '').strip(),
            signal_3=request.form.get('signal_3', '').strip(),
            account_grade=request.form.get('account_grade', 'B'),
            notes=request.form.get('notes', '').strip(),
            source='manual',
        )
        db.session.add(lead)
        db.session.commit()
        flash(f'Lead {lead.full_name} added!', 'success')
        return redirect(url_for('leads.detail', lead_id=lead.id))

    return render_template('leads/new.html')


@leads_bp.route('/<int:lead_id>')
@login_required
def detail(lead_id):
    lead = Lead.query.filter_by(id=lead_id, user_id=current_user.id).first_or_404()
    enrolled = EnrolledLead.query.filter_by(lead_id=lead_id).all()
    campaigns = Campaign.query.filter_by(user_id=current_user.id).all()
    return render_template('leads/detail.html', lead=lead, enrolled=enrolled, campaigns=campaigns)


@leads_bp.route('/<int:lead_id>', methods=['PATCH', 'POST'])
@login_required
def update_lead(lead_id):
    lead = Lead.query.filter_by(id=lead_id, user_id=current_user.id).first_or_404()

    data = request.get_json(silent=True) or request.form

    for field in ['first_name', 'last_name', 'email', 'company', 'title',
                  'website', 'phone', 'linkedin_url', 'signal_1', 'signal_2',
                  'signal_3', 'account_grade', 'notes']:
        if field in data:
            setattr(lead, field, data[field])

    if 'do_not_contact' in data:
        val = data['do_not_contact']
        lead.do_not_contact = val in (True, 'true', '1', 'on')

    db.session.commit()

    if request.is_json:
        return jsonify({'ok': True})
    flash('Lead updated.', 'success')
    return redirect(url_for('leads.detail', lead_id=lead_id))


@leads_bp.route('/<int:lead_id>/delete', methods=['POST'])
@login_required
def delete_lead(lead_id):
    lead = Lead.query.filter_by(id=lead_id, user_id=current_user.id).first_or_404()
    db.session.delete(lead)
    db.session.commit()
    flash('Lead deleted.', 'success')
    return redirect(url_for('leads.pool'))


@leads_bp.route('/<int:lead_id>/enroll', methods=['POST'])
@login_required
def enroll_lead(lead_id):
    lead = Lead.query.filter_by(id=lead_id, user_id=current_user.id).first_or_404()
    campaign_id = request.form.get('campaign_id') or (request.get_json(silent=True) or {}).get('campaign_id')

    if not campaign_id:
        flash('Please select a campaign.', 'warning')
        return redirect(url_for('leads.detail', lead_id=lead_id))

    campaign = Campaign.query.filter_by(id=int(campaign_id), user_id=current_user.id).first_or_404()

    existing = EnrolledLead.query.filter_by(campaign_id=campaign.id, lead_id=lead.id).first()
    if existing:
        flash('Lead is already enrolled in that campaign.', 'warning')
        return redirect(url_for('leads.detail', lead_id=lead_id))

    el = EnrolledLead(
        campaign_id=campaign.id,
        lead_id=lead.id,
        status=EnrolledStatus.ACTIVE,
    )
    db.session.add(el)
    db.session.commit()
    flash(f'Lead enrolled in campaign "{campaign.name}".', 'success')
    return redirect(url_for('leads.detail', lead_id=lead_id))


@leads_bp.route('/bulk-enroll', methods=['POST'])
@login_required
def bulk_enroll():
    data = request.form
    lead_ids = request.form.getlist('lead_ids')
    campaign_id = data.get('campaign_id')

    if not lead_ids or not campaign_id:
        flash('Select leads and a campaign.', 'warning')
        return redirect(url_for('leads.pool'))

    campaign = Campaign.query.filter_by(id=int(campaign_id), user_id=current_user.id).first_or_404()

    enrolled = 0
    skipped = 0
    for lid in lead_ids:
        lead = Lead.query.filter_by(id=int(lid), user_id=current_user.id).first()
        if not lead:
            continue
        existing = EnrolledLead.query.filter_by(campaign_id=campaign.id, lead_id=lead.id).first()
        if existing:
            skipped += 1
            continue
        el = EnrolledLead(campaign_id=campaign.id, lead_id=lead.id, status=EnrolledStatus.ACTIVE)
        db.session.add(el)
        enrolled += 1

    db.session.commit()
    flash(f'Enrolled {enrolled} leads in "{campaign.name}". {skipped} already enrolled.', 'success')
    return redirect(url_for('leads.pool'))
