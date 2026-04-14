from flask import Blueprint
campaigns_bp = Blueprint('campaigns', __name__, template_folder='../../templates')
from . import routes  # noqa: F401, E402
