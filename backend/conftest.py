import os
import sys

# Ensure the backend package root (containing ``app``) is importable no
# matter from which directory pytest is invoked.
BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
