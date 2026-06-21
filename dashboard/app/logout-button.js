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
        padding: "4px 12px", fontSize: "13px",
        background: "transparent", border: "1px solid #999",
        borderRadius: "4px", cursor: "pointer",
      }}
    >
      Sign Out
    </button>
  );
}
