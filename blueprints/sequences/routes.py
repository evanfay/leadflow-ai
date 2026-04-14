from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from . import sequences_bp
from extensions import db
from models import Sequence, SequenceStep


@sequences_bp.route('/')
@login_required
def list_sequences():
    builtin = Sequence.query.filter_by(is_builtin=True).order_by(Sequence.name).all()
    custom = Sequence.query.filter_by(user_id=current_user.id, is_builtin=False).order_by(Sequence.name).all()
    return render_template('sequences/list.html', builtin=builtin, custom=custom)


@sequences_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_sequence():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            flash('Sequence name is required.', 'danger')
            return render_template('sequences/builder.html')

        seq = Sequence(
            user_id=current_user.id,
            name=name,
            description=description,
            is_builtin=False,
        )
        db.session.add(seq)
        db.session.flush()

        # Parse steps from form
        # Form sends: step_day[], step_channel[], step_slot[], step_auto[]
        days = request.form.getlist('step_day')
        channels = request.form.getlist('step_channel')
        slots = request.form.getlist('step_slot')
        autos = request.form.getlist('step_auto')

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
            except (ValueError, IndexError):
                continue

        db.session.commit()
        flash(f'Sequence "{name}" created!', 'success')
        return redirect(url_for('sequences.list_sequences'))

    return render_template('sequences/builder.html')


@sequences_bp.route('/<int:seq_id>')
@login_required
def view_sequence(seq_id):
    seq = Sequence.query.filter(
        (Sequence.id == seq_id) &
        ((Sequence.user_id == current_user.id) | (Sequence.is_builtin == True))
    ).first_or_404()
    steps = seq.steps.order_by(SequenceStep.day_offset).all()
    return render_template('sequences/view.html', seq=seq, steps=steps)


@sequences_bp.route('/<int:seq_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_sequence(seq_id):
    seq = Sequence.query.filter_by(id=seq_id, user_id=current_user.id, is_builtin=False).first_or_404()

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
            except (ValueError, IndexError):
                continue

        db.session.commit()
        flash(f'Sequence "{seq.name}" updated.', 'success')
        return redirect(url_for('sequences.list_sequences'))

    steps = seq.steps.order_by(SequenceStep.day_offset).all()
    return render_template('sequences/builder.html', seq=seq, steps=steps)


@sequences_bp.route('/<int:seq_id>/delete', methods=['POST'])
@login_required
def delete_sequence(seq_id):
    seq = Sequence.query.filter_by(id=seq_id, user_id=current_user.id, is_builtin=False).first_or_404()
    name = seq.name
    db.session.delete(seq)
    db.session.commit()
    flash(f'Sequence "{name}" deleted.', 'success')
    return redirect(url_for('sequences.list_sequences'))
