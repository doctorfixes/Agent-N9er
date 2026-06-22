import "./globals.css";
import LogoutButton from "./logout-button.js";
import TickerBar from "./ticker.js";

export const metadata = {
  title: "AGENT N9ER // COMMAND CENTER",
  description: "Autonomous task orchestration command center",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
      </head>
      <body>
        <div className="scanline-overlay" />
        <nav className="cmd-nav">
          <div className="cmd-nav-brand">
            <span className="logo">Agent N9er</span>
            <span className="divider" />
            <span className="env-tag">Command Center</span>
          </div>
          <div className="cmd-nav-links">
            <a href="/">Mission Control</a>
            <a href="/prospects">Prospects</a>
            <a href="/revenue">Revenue</a>
            <a href="/tasks">Tasks</a>
            <a href="/analytics">Analytics</a>
            <a href="/leaderboard">Agents</a>
            <a href="/admin" className="nav-admin">Admin</a>
          </div>
          <LogoutButton />
        </nav>
        <TickerBar />
        <main style={{ padding: "16px 20px", minHeight: "calc(100vh - 80px)" }}>{children}</main>
      </body>
    </html>
  );
}
