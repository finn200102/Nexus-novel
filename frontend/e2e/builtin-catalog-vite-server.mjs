import {createServer} from 'vite';
const server=await createServer({cacheDir:'/tmp/nexus-builtin-catalog-vite-cache',server:{host:'127.0.0.1',port:4205,strictPort:true,hmr:false}});await server.listen();
