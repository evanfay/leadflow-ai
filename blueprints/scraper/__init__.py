from flask import Blueprint
scraper_bp = Blueprint('scraper', __name__, template_folder='../../templates')
from . import routes  # noqa: F401, E402
