from flask import Blueprint
inbox_bp = Blueprint('inbox', __name__, template_folder='../../templates')
from . import routes  # noqa: F401, E402
