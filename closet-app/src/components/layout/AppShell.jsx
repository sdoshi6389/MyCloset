import Sidebar from "./Sidebar";
import AmbientField from "../common/AmbientField";
import "./AppShell.css";

export default function AppShell({ children }) {
  return (
    <div className="app-shell">
      {/* Same colour field as the landing, dimmed so content stays readable. */}
      <AmbientField variant="app" />
      <Sidebar />
      <main className="app-main">{children}</main>
    </div>
  );
}
