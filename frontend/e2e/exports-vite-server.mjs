// Real local attachment transport: Chromium/WebKit download managers bypass
// Playwright request routing for <a download>. No Nexus service is contacted.
import { createServer } from "vite";
const bytes = Buffer.from("Nexus deterministic M4B download fixture. Codec validation belongs to the encoder tests.");
let downloads = 0, authorizedHeader = false, cookiePresent = false;
const server = await createServer({
  server: { host: "127.0.0.1", port: 4188, strictPort: true, hmr: false },
  plugins: [{ name: "deterministic-export-attachment", configureServer(vite) {
    vite.middlewares.use((request, response, next) => {
      if (request.url === "/__fixture_exports/reset") { downloads = 0; authorizedHeader = false; cookiePresent = false; response.writeHead(204); response.end(); return; }
      if (request.url === "/__fixture_exports/requests") { response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify({ downloads, authorizedHeader, cookiePresent })); return; }
      if (request.url !== "/__fixture_exports/71.m4b") { next(); return; }
      downloads++; authorizedHeader = Boolean(request.headers.authorization);
      cookiePresent = request.headers.cookie?.includes("nexus_fixture_export=scoped-fixture") || false;
      if (!cookiePresent) { response.writeHead(403); response.end("Missing fixture download ticket"); return; }
      response.writeHead(200, { "Content-Type": "audio/mp4", "Content-Length": bytes.length,
        "Content-Disposition": 'attachment; filename="fixture-audiobook.m4b"', "Cache-Control": "private, no-store" });
      response.end(bytes);
    });
  } }],
});
await server.listen();
