from flask import Blueprint
sequences_bp = Blueprint('sequences', __name__, template_folder='../../templates')
from . import routes  # noqa: F401, E402
