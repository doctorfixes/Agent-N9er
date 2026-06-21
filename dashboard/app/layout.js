export const metadata = {
  title: "Agent N9er",
  description: "Watches every connected tool, drafts the work it finds, and dispatches autonomous agents to clear it — end to end.",
};

const TABS = [
  ["Mission Control", "/mission-control"],
  ["Signal Intelligence", "/signal-intelligence"],
  ["Task Pipeline", "/task-pipeline"],
  ["Agent Marketplace", "/agent-marketplace"],
  ["Integrations", "/integrations"],
];

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, background: "#0d0d14", color: "#e2e8f0", minHeight: "100vh" }}>
        <header style={{ background: "#12121f", borderBottom: "1px solid #2d2d44", padding: "0 24px", display: "flex", alignItems: "stretch" }}>
          <a
            href="/"
            style={{
              fontWeight: 700, fontSize: "1em", color: "#818cf8", textDecoration: "none",
              padding: "0 20px 0 0", marginRight: "8px", display: "flex", alignItems: "center",
              borderRight: "1px solid #2d2d44", whiteSpace: "nowrap", letterSpacing: "0.02em",
            }}
          >
            ⬡ Agent N9er
          </a>
          <nav style={{ display: "flex", alignItems: "stretch" }}>
            {TABS.map(([label, href]) => (
              <a
                key={href}
                href={href}
                style={{
                  padding: "0 16px", color: "#94a3b8", textDecoration: "none",
                  fontSize: "13px", display: "flex", alignItems: "center",
                  borderBottom: "2px solid transparent", transition: "color 0.15s",
                  whiteSpace: "nowrap",
                }}
              >
                {label}
              </a>
            ))}
          </nav>
        </header>
        <main style={{ padding: "28px 32px", maxWidth: "1400px", margin: "0 auto" }}>{children}</main>
      </body>
    </html>
  );
}
