import threading
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

# Thread-local so each Flask request thread (and each background thread)
# gets its own client — avoids HTTP/2 connection conflicts under parallel load.
_local = threading.local()

def get_supa() -> Client:
    if not hasattr(_local, "client"):
        _local.client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _local.client

get_db = get_supa
