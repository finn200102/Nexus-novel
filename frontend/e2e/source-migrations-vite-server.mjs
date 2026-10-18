import { createServer } from "vite";
const server = await createServer({ server: { host: "127.0.0.1", port: 4196, strictPort: true, hmr: false } });
await server.listen();
