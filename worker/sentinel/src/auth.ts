/**
 * Auth — Bearer token validation for protected endpoints.
 */

/**
 * Validate that the request has a valid Bearer token.
 *
 * @param request   - Incoming request
 * @param expected  - Expected token value (from env secret)
 * @returns         - True if authorized
 */
export function validateBearer(request: Request, expected: string): boolean {
    const header = request.headers.get("Authorization");
    if (!header) return false;

    const parts = header.split(" ");
    if (parts.length !== 2 || parts[0] !== "Bearer") return false;

    return parts[1] === expected;
}

/**
 * Create a 401 Unauthorized response.
 */
export function unauthorized(): Response {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
    });
}
