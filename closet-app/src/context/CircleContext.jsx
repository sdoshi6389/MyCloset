import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";

const API = "http://localhost:5000";
const CircleContext = createContext();

export function CircleProvider({ children }) {
  const [circles, setCircles]           = useState([]);
  const [activeCircle, setActiveCircle] = useState(null); // null = "Just Me"

  const fetchCircles = useCallback(async () => {
    const token = localStorage.getItem("token");
    if (!token) return;
    try {
      const res = await axios.get(`${API}/circles`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setCircles(res.data);
    } catch (e) {
      // not logged in yet — silent
    }
  }, []);

  useEffect(() => { fetchCircles(); }, [fetchCircles]);

  return (
    <CircleContext.Provider value={{ circles, activeCircle, setActiveCircle, refreshCircles: fetchCircles }}>
      {children}
    </CircleContext.Provider>
  );
}

export function useCircle() {
  return useContext(CircleContext);
}
