from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from . import tasks_bp
from extensions import db
from models import TaskQueue, TaskStatus


@tasks_bp.route('/')
@login_required
def queue():
    type_filter = request.args.get('type', '')
    status_filter = request.args.get('status', TaskStatus.PENDING)

    query = TaskQueue.query.filter_by(user_id=current_user.id)

    if type_filter:
        query = query.filter_by(task_type=type_filter)

    if status_filter:
        query = query.filter_by(status=status_filter)

    tasks = query.order_by(TaskQueue.due_date.asc().nullslast()).all()

    return render_template('tasks/queue.html', tasks=tasks,
                           type_filter=type_filter, status_filter=status_filter)


@tasks_bp.route('/<int:task_id>/complete', methods=['POST'])
@login_required
def complete_task(task_id):
    task = TaskQueue.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    task.status = TaskStatus.COMPLETE
    db.session.commit()

    if request.is_json:
        return jsonify({'ok': True})
    flash('Task marked complete.', 'success')
    return redirect(url_for('tasks.queue'))


@tasks_bp.route('/<int:task_id>/skip', methods=['POST'])
@login_required
def skip_task(task_id):
    task = TaskQueue.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    task.status = TaskStatus.SKIPPED
    db.session.commit()

    if request.is_json:
        return jsonify({'ok': True})
    flash('Task skipped.', 'info')
    return redirect(url_for('tasks.queue'))


@tasks_bp.route('/<int:task_id>/reschedule', methods=['POST'])
@login_required
def reschedule_task(task_id):
    task = TaskQueue.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()

    days = int(request.form.get('days', 1))
    if task.due_date:
        task.due_date = task.due_date + timedelta(days=days)
    else:
        task.due_date = datetime.utcnow().date() + timedelta(days=days)

    db.session.commit()

    if request.is_json:
        return jsonify({'ok': True})
    flash(f'Task rescheduled by {days} day(s).', 'info')
    return redirect(url_for('tasks.queue'))
