import {createServer} from "vite";
const server=await createServer({cacheDir:"/tmp/nexus-catalog-watch-vite-cache",server:{host:"127.0.0.1",port:4201,strictPort:true,hmr:false}});await server.listen();
