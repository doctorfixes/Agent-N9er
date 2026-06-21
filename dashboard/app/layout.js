import LogoutButton from "./logout-button.js";

export const metadata = {
  title: "Agent N9er — Mission Control",
  description: "Autonomous task orchestration dashboard",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, padding: 0, background: "#f5f5f5" }}>
        <nav style={{ padding: "12px 24px", background: "#111827", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "24px" }}>
            <strong style={{ fontSize: "1.2em", color: "#f9fafb", letterSpacing: "0.02em" }}>Agent N9er</strong>
            <div style={{ display: "flex", gap: "4px" }}>
              <a href="/" style={{ padding: "6px 14px", borderRadius: "6px", fontSize: "13px", fontWeight: 500, color: "#d1d5db", textDecoration: "none" }}>Mission Control</a>
              <a href="/tasks" style={{ padding: "6px 14px", borderRadius: "6px", fontSize: "13px", fontWeight: 500, color: "#9ca3af", textDecoration: "none" }}>Task History</a>
              <a href="/leaderboard" style={{ padding: "6px 14px", borderRadius: "6px", fontSize: "13px", fontWeight: 500, color: "#9ca3af", textDecoration: "none" }}>Leaderboard</a>
            </div>
          </div>
          <LogoutButton />
        </nav>
        <main style={{ padding: "20px 24px" }}>{children}</main>
      </body>
    </html>
  );
}
