import os
from flask import Flask, jsonify
from flask_login import current_user, login_required
from dotenv import load_dotenv

load_dotenv()

from extensions import db, login_manager, migrate, scheduler
from models import User


def create_app():
    app = Flask(__name__)

    # Config
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-in-prod')
    db_url = os.environ.get('DATABASE_URL', 'sqlite:///leadflow.db')
    # Fix Heroku/Railway postgres:// -> postgresql://
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['GOOGLE_CLIENT_SECRETS_FILE'] = os.environ.get(
        'GOOGLE_CLIENT_SECRETS_FILE', 'google_credentials.json'
    )
    app.config['WTF_CSRF_ENABLED'] = True

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Inject logo_exists into all templates
    @app.context_processor
    def inject_globals():
        logo_path = os.path.join(app.static_folder, 'logo.png')
        return {'logo_exists': os.path.isfile(logo_path)}

    # Register blueprints
    from blueprints.auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.campaigns import campaigns_bp
    from blueprints.leads import leads_bp
    from blueprints.sequences import sequences_bp
    from blueprints.settings import settings_bp
    from blueprints.tasks import tasks_bp
    from blueprints.inbox import inbox_bp
    from blueprints.scraper import scraper_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(campaigns_bp, url_prefix='/campaigns')
    app.register_blueprint(leads_bp, url_prefix='/leads')
    app.register_blueprint(sequences_bp, url_prefix='/sequences')
    app.register_blueprint(settings_bp, url_prefix='/settings')
    app.register_blueprint(tasks_bp, url_prefix='/tasks')
    app.register_blueprint(inbox_bp, url_prefix='/inbox')
    app.register_blueprint(scraper_bp, url_prefix='/scraper')

    # Nav counts API
    @app.route('/api/nav-counts')
    @login_required
    def nav_counts():
        from models import TaskQueue, ReplyLog, EnrolledLead
        task_count = TaskQueue.query.filter_by(
            user_id=current_user.id, status='pending'
        ).count()
        # Count unhandled replies for current user
        reply_count = ReplyLog.query.join(
            EnrolledLead, ReplyLog.enrolled_lead_id == EnrolledLead.id
        ).join(
            __import__('models').Campaign, EnrolledLead.campaign_id == __import__('models').Campaign.id
        ).filter(
            __import__('models').Campaign.user_id == current_user.id,
            ReplyLog.handled == False
        ).count()
        return jsonify({'tasks': task_count, 'replies': reply_count})

    # Create tables + seed on first run
    with app.app_context():
        db.create_all()
        # Add any new columns that may not exist in older databases
        try:
            with db.engine.connect() as conn:
                conn.execute(db.text('ALTER TABLE users ADD COLUMN scraper_email_threshold INTEGER DEFAULT 6'))
                conn.commit()
        except Exception:
            pass  # Column already exists
        from seed_data import seed_builtin_data
        seed_builtin_data(app, db)

        # Create default admin if no users exist
        if not User.query.first():
            admin = User(email='admin@leadflow.ai', display_name='Admin', is_admin=True)
            admin.set_password('changeme')
            db.session.add(admin)
            db.session.commit()
            print('\n[LeadFlow AI] Default admin created: admin@leadflow.ai / changeme')
            print('[LeadFlow AI] Change this password immediately in Settings > Profile\n')

    # Start scheduler
    from scheduler_jobs import register_jobs
    register_jobs(scheduler, app)
    if not scheduler.running:
        try:
            scheduler.start()
        except Exception as e:
            print(f'[Scheduler] Warning: could not start scheduler: {e}')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
