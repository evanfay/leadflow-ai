from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from . import auth_bp
from extensions import db
from models import User


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.display_name or user.email}!', 'success')
            return redirect(next_page or url_for('dashboard.index'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        display_name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        is_admin = bool(request.form.get('is_admin'))

        if not email or not password:
            flash('Email and password are required.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash(f'User {email} already exists.', 'danger')
        else:
            user = User(email=email, display_name=display_name, is_admin=is_admin)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f'User {email} created successfully.', 'success')

        return redirect(url_for('auth.admin_users'))

    users = User.query.order_by(User.created_at).all()
    return render_template('auth/admin_users.html', users=users)


@auth_bp.route('/admin/users/<int:user_id>', methods=['DELETE', 'POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403

    if user_id == current_user.id:
        if request.is_json:
            return jsonify({'error': 'Cannot delete your own account'}), 400
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('auth.admin_users'))

    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()

    if request.is_json:
        return jsonify({'ok': True})
    flash(f'User {user.email} deleted.', 'success')
    return redirect(url_for('auth.admin_users'))
