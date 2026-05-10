from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from . import sequences_bp
from extensions import db
from models import Sequence, SequenceStep, Template, StepTemplate


@sequences_bp.route('/')
@login_required
def list_sequences():
    builtin = Sequence.query.filter_by(is_builtin=True).order_by(Sequence.name).all()
    custom = Sequence.query.filter_by(user_id=current_user.id, is_builtin=False).order_by(Sequence.name).all()
    return render_template('sequences/list.html', builtin=builtin, custom=custom)


def _get_templates():
    """Return all templates available to the current user (own + builtins)."""
    return Template.query.filter(
        (Template.user_id == current_user.id) | (Template.is_builtin == True)
    ).order_by(Template.is_builtin.desc(), Template.name).all()


def _save_step_templates(step, template_id_str):
    """Attach a single pinned template to a step (replaces any existing)."""
    if not template_id_str or not template_id_str.strip():
        return
    try:
        tid = int(template_id_str)
    except ValueError:
        return
    t = Template.query.get(tid)
    if not t:
        return
    st = StepTemplate(step_id=step.id, template_id=tid, variant_label='A', is_active=True)
    db.session.add(st)


@sequences_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_sequence():
    templates = _get_templates()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            flash('Sequence name is required.', 'danger')
            return render_template('sequences/builder.html', templates=templates)

        seq = Sequence(
            user_id=current_user.id,
            name=name,
            description=description,
            is_builtin=False,
        )
        db.session.add(seq)
        db.session.flush()

        # Parse steps from form
        # Form sends: step_day[], step_channel[], step_slot[], step_auto[], step_template_id[]
        days = request.form.getlist('step_day')
        channels = request.form.getlist('step_channel')
        slots = request.form.getlist('step_slot')
        autos = request.form.getlist('step_auto')
        template_ids = request.form.getlist('step_template_id')

        for i, day in enumerate(days):
            try:
                step = SequenceStep(
                    sequence_id=seq.id,
                    day_offset=int(day),
                    channel=channels[i] if i < len(channels) else 'Email',
                    template_slot=slots[i] if i < len(slots) else 'observation',
                    is_auto=(str(i) in autos or autos[i] == 'true' if i < len(autos) else True),
                )
                db.session.add(step)
                db.session.flush()
                _save_step_templates(step, template_ids[i] if i < len(template_ids) else '')
            except (ValueError, IndexError):
                continue

        db.session.commit()
        flash(f'Sequence "{name}" created!', 'success')
        return redirect(url_for('sequences.list_sequences'))

    return render_template('sequences/builder.html', templates=templates)


@sequences_bp.route('/<int:seq_id>')
@login_required
def view_sequence(seq_id):
    seq = Sequence.query.filter(
        (Sequence.id == seq_id) &
        ((Sequence.user_id == current_user.id) | (Sequence.is_builtin == True))
    ).first_or_404()
    steps = seq.steps.order_by(SequenceStep.day_offset).all()
    # Build map: step_id -> first active template name
    step_template_map = {}
    for step in steps:
        st = step.step_templates.filter_by(is_active=True).first()
        if st:
            step_template_map[step.id] = st.template
    return render_template('sequences/view.html', seq=seq, steps=steps,
                           step_template_map=step_template_map)


@sequences_bp.route('/<int:seq_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_sequence(seq_id):
    seq = Sequence.query.filter_by(id=seq_id, user_id=current_user.id, is_builtin=False).first_or_404()
    templates = _get_templates()

    if request.method == 'POST':
        seq.name = request.form.get('name', seq.name).strip()
        seq.description = request.form.get('description', seq.description).strip()

        # Delete existing steps and re-add
        for step in seq.steps.all():
            db.session.delete(step)
        db.session.flush()

        days = request.form.getlist('step_day')
        channels = request.form.getlist('step_channel')
        slots = request.form.getlist('step_slot')
        autos = request.form.getlist('step_auto')
        template_ids = request.form.getlist('step_template_id')

        for i, day in enumerate(days):
            try:
                step = SequenceStep(
                    sequence_id=seq.id,
                    day_offset=int(day),
                    channel=channels[i] if i < len(channels) else 'Email',
                    template_slot=slots[i] if i < len(slots) else 'observation',
                    is_auto=(str(i) in autos),
                )
                db.session.add(step)
                db.session.flush()
                _save_step_templates(step, template_ids[i] if i < len(template_ids) else '')
            except (ValueError, IndexError):
                continue

        db.session.commit()
        flash(f'Sequence "{seq.name}" updated.', 'success')
        return redirect(url_for('sequences.list_sequences'))

    steps = seq.steps.order_by(SequenceStep.day_offset).all()
    # Build map: step_id -> pinned template_id (for pre-selecting on edit)
    step_template_id_map = {}
    for step in steps:
        st = step.step_templates.filter_by(is_active=True).first()
        if st:
            step_template_id_map[step.id] = st.template_id
    return render_template('sequences/builder.html', seq=seq, steps=steps,
                           templates=templates, step_template_id_map=step_template_id_map)


@sequences_bp.route('/<int:seq_id>/delete', methods=['POST'])
@login_required
def delete_sequence(seq_id):
    seq = Sequence.query.filter_by(id=seq_id, user_id=current_user.id, is_builtin=False).first_or_404()
    name = seq.name
    db.session.delete(seq)
    db.session.commit()
    flash(f'Sequence "{name}" deleted.', 'success')
    return redirect(url_for('sequences.list_sequences'))
