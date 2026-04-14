from flask import Blueprint
tasks_bp = Blueprint('tasks', __name__, template_folder='../../templates')
from . import routes  # noqa: F401, E402
