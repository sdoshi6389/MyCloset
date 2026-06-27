import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";

function isTokenValid(token) {
  if (!token) return false;
  try {
    // JWT payload is the second segment, base64url-encoded
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    // exp is in seconds; Date.now() is in ms
    return payload.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

export default function ProtectedRoute({ children }) {
  const [checked, setChecked] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!isTokenValid(token)) {
      // Clear stale/expired token so login page starts clean
      localStorage.removeItem("token");
      navigate("/", { replace: true, state: { expired: true } });
    } else {
      setChecked(true);
    }
  }, [navigate, location.pathname]);

  if (!checked) return null; // render nothing while checking (avoids flash)
  return children;
}
