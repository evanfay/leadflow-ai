"""LeadFlow AI launcher."""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from app import app

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
