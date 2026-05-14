const REALM = "ropeway-demo";

declare const process: {
  env: Record<string, string | undefined>;
};

function unauthorized(): Response {
  return new Response("Authentication required.", {
    status: 401,
    headers: {
      "Cache-Control": "no-store",
      "WWW-Authenticate": `Basic realm="${REALM}", charset="UTF-8"`,
    },
  });
}

function timingSafeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  const length = Math.max(leftBytes.length, rightBytes.length);
  let diff = leftBytes.length ^ rightBytes.length;

  for (let index = 0; index < length; index += 1) {
    diff |= (leftBytes[index] ?? 0) ^ (rightBytes[index] ?? 0);
  }

  return diff === 0;
}

function parseBasicAuth(header: string | null): { user: string; password: string } | null {
  if (!header?.startsWith("Basic ")) {
    return null;
  }

  let decoded: string;
  try {
    decoded = atob(header.slice("Basic ".length));
  } catch {
    return null;
  }

  const separator = decoded.indexOf(":");
  if (separator < 0) {
    return null;
  }

  return {
    user: decoded.slice(0, separator),
    password: decoded.slice(separator + 1),
  };
}

export default function middleware(request: Request): Response | undefined {
  const expectedUser = process.env.BASIC_AUTH_USER;
  const expectedPassword = process.env.BASIC_AUTH_PASSWORD;

  if (!expectedUser || !expectedPassword) {
    return new Response("Basic auth is not configured.", {
      status: 500,
      headers: { "Cache-Control": "no-store" },
    });
  }

  const credentials = parseBasicAuth(request.headers.get("authorization"));
  if (!credentials) {
    return unauthorized();
  }

  if (
    !timingSafeEqual(credentials.user, expectedUser) ||
    !timingSafeEqual(credentials.password, expectedPassword)
  ) {
    return unauthorized();
  }

  return undefined;
}
