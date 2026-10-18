import {createServer} from "vite";
const server=await createServer({cacheDir:"/tmp/nexus-chapter-reading-vite-cache",server:{host:"127.0.0.1",port:4198,strictPort:true,hmr:false}});await server.listen();
