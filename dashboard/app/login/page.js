"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!username || !password) {
      setError("CREDENTIALS REQUIRED");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const resp = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (resp.ok) {
        router.push("/");
        router.refresh();
      } else {
        setError("ACCESS DENIED");
      }
    } catch {
      setError("CONNECTION FAILED");
    }
    setLoading(false);
  };

  return (
    <div className="login-container">
      <div className="login-box">
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 700, color: "var(--accent-cyan)", letterSpacing: "0.1em" }}>
            AGENT N9ER
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginTop: 6, letterSpacing: "0.15em", textTransform: "uppercase" }}>
            Command Center Access
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: "block", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              Operator ID
            </label>
            <input
              className="cmd-input"
              style={{ width: "100%" }}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
            />
          </div>
          <div style={{ marginBottom: 24 }}>
            <label style={{ display: "block", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              Access Key
            </label>
            <input
              className="cmd-input"
              style={{ width: "100%" }}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          {error && (
            <div style={{
              marginBottom: 16, padding: "8px 12px", borderRadius: 4,
              background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)",
              fontFamily: "var(--font-mono)", fontSize: 11, color: "#f87171", textAlign: "center",
            }}>
              {error}
            </div>
          )}

          <button
            className="cmd-btn primary"
            style={{ width: "100%", padding: "10px 16px" }}
            type="submit"
            disabled={loading}
          >
            {loading ? "AUTHENTICATING..." : "AUTHENTICATE"}
          </button>
        </form>
      </div>
    </div>
  );
}
