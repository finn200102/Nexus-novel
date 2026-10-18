import {createServer} from "vite";
const server=await createServer({cacheDir:"/tmp/nexus-progressive-live-vite-cache",server:{host:"127.0.0.1",port:4203,strictPort:true,hmr:false}});await server.listen();
