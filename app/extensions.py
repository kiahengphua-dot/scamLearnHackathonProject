from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# In-memory storage — fine for a single-process hackathon deployment.
# A real multi-worker deployment would need a shared backend (Redis etc.)
# for the limits to apply across processes, but that's out of scope here.
limiter = Limiter(key_func=get_remote_address)
