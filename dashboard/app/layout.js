export const metadata = {
  title: "Verixio Dashboard",
  description: "Agent marketplace monitoring",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, padding: "20px", background: "#f5f5f5" }}>
        <nav style={{ marginBottom: "20px", padding: "10px 0", borderBottom: "2px solid #333" }}>
          <strong style={{ fontSize: "1.3em" }}>Verixio</strong>
          {" — "}
          <a href="/">Home</a>{" | "}
          <a href="/tasks">Tasks</a>{" | "}
          <a href="/agents">Agents</a>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
