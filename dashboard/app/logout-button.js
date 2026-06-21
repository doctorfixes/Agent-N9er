"use client";

import { useRouter, usePathname } from "next/navigation";

export default function LogoutButton() {
  const router = useRouter();
  const pathname = usePathname();

  if (pathname === "/login") return null;

  async function handleLogout() {
    await fetch("/api/auth", { method: "DELETE" });
    router.push("/login");
    router.refresh();
  }

  return (
    <button
      onClick={handleLogout}
      style={{
        padding: "5px 14px", fontSize: "13px",
        background: "transparent", border: "1px solid #4b5563",
        borderRadius: "6px", cursor: "pointer", color: "#9ca3af",
      }}
    >
      Sign Out
    </button>
  );
}
