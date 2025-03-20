import sys
import os

# Add root directory to path to import app.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app

# For Vercel to find your Flask app
if __name__ == '__main__':
    app.run()
