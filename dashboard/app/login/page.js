"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const resp = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!resp.ok) {
        const data = await resp.json();
        setError(data.error || "Login failed");
        setLoading(false);
        return;
      }

      router.push("/");
      router.refresh();
    } catch {
      setError("Network error");
      setLoading(false);
    }
  }

  return (
    <div style={{
      display: "flex", justifyContent: "center", alignItems: "center",
      minHeight: "80vh",
    }}>
      <div style={{
        background: "white", padding: "40px", borderRadius: "8px",
        boxShadow: "0 2px 10px rgba(0,0,0,0.1)", width: "100%", maxWidth: "380px",
      }}>
        <h1 style={{ margin: "0 0 8px 0", fontSize: "1.5em" }}>Agent N9er</h1>
        <p style={{ margin: "0 0 24px 0", color: "#666", fontSize: "14px" }}>
          Sign in to Mission Control
        </p>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: "16px" }}>
            <label style={{ display: "block", marginBottom: "4px", fontSize: "14px", fontWeight: 500 }}>
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              style={{
                width: "100%", padding: "8px", fontSize: "14px",
                border: "1px solid #ccc", borderRadius: "4px", boxSizing: "border-box",
              }}
            />
          </div>

          <div style={{ marginBottom: "20px" }}>
            <label style={{ display: "block", marginBottom: "4px", fontSize: "14px", fontWeight: 500 }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              style={{
                width: "100%", padding: "8px", fontSize: "14px",
                border: "1px solid #ccc", borderRadius: "4px", boxSizing: "border-box",
              }}
            />
          </div>

          {error && (
            <p style={{ color: "#d32f2f", fontSize: "13px", margin: "0 0 16px 0" }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%", padding: "10px", fontSize: "14px", fontWeight: 600,
              background: "#111827", color: "white", border: "none", borderRadius: "6px",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
      </div>
    </div>
  );
}
