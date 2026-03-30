import { authMiddleware } from "@clerk/nextjs";

export default authMiddleware({
  publicRoutes: ["/", "/sign-in", "/sign-up", "/api/webhooks"],
});

export const config = {
  matcher: ["/dashboard/:path*", "/api/v1/:path*"],
};
