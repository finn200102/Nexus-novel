import { createServer } from "vite";
const server = await createServer({ server: { host: "127.0.0.1", port: 4194, strictPort: true, hmr: false } });
await server.listen();
