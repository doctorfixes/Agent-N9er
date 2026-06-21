import { createToken, validateCredentials } from "../../../lib/auth.js";

export async function POST(request) {
  try {
    const { username, password } = await request.json();

    if (!username || !password) {
      return Response.json(
        { error: "Username and password required" },
        { status: 400 }
      );
    }

    if (!validateCredentials(username, password)) {
      return Response.json({ error: "Invalid credentials" }, { status: 401 });
    }

    const token = await createToken(username);

    const response = Response.json({ ok: 1, username });
    response.headers.set(
      "Set-Cookie",
      `token=${token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=28800`
    );
    return response;
  } catch {
    return Response.json({ error: "Invalid request" }, { status: 400 });
  }
}

export async function DELETE() {
  const response = Response.json({ ok: 1 });
  response.headers.set(
    "Set-Cookie",
    "token=; HttpOnly; Path=/; Max-Age=0"
  );
  return response;
}
