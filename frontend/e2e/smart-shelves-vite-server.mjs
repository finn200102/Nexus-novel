import {createServer} from "vite";
const server=await createServer({cacheDir:"/tmp/nexus-smart-shelves-vite-cache",server:{host:"127.0.0.1",port:4200,strictPort:true,hmr:false}});await server.listen();
