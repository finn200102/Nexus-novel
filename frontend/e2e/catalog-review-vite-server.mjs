import {createServer} from "vite";
const server=await createServer({cacheDir:"/tmp/nexus-catalog-review-vite-cache",server:{host:"127.0.0.1",port:4202,strictPort:true,hmr:false}});await server.listen();
