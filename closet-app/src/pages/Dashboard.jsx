import { Link, useNavigate } from "react-router-dom";

export default function Dashboard() {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem("token");
    navigate("/", { replace: true });
  };

  return (
    <div className="min-h-screen p-8 bg-gray-50 relative">
      {/* 🔓 Logout button */}
      <button
        onClick={handleLogout}
        className="absolute top-4 right-4 bg-red-500 text-white px-4 py-2 rounded"
      >
        Log out
      </button>

      <h1 className="text-2xl font-bold mb-6">Welcome to Your Smart Closet 👗</h1>
      <ul className="space-y-4">
        <li><Link to="/closet" className="text-blue-600 hover:underline">Put images into your closet</Link></li>
        <li><Link to="/feed" className="text-blue-600 hover:underline">Feed of own and friends outfits</Link></li>
        <li><Link to="/discover" className="text-blue-600 hover:underline">Add new friends / discover members</Link></li>
        <li><Link to="/builder" className="text-blue-600 hover:underline">Build your own outfit</Link></li>
        <li><Link to="/recommend" className="text-blue-600 hover:underline">Outfit recommender</Link></li>
      </ul>
    </div>
  );
}