import sys, os

# Add backend folder to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Now import the Flask app
from app import app

if __name__ == "__main__":
    app.run()
