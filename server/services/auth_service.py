"""Shared JWT token decoding used across blueprints."""
import jwt
from config import JWT_SECRET

def get_user_id_from_request(request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload["user_id"]
    except Exception as e:
        print(f"❌ Token decode error: {e}")
        return None
