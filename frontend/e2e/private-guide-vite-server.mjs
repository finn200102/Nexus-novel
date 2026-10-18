import {createServer} from 'vite';
import {realpathSync} from 'node:fs';
const server=await createServer({cacheDir:'/tmp/nexus-private-guide-vite-cache',server:{host:'127.0.0.1',port:4211,strictPort:true,hmr:false,fs:{allow:[process.cwd(),realpathSync('node_modules')]}}});await server.listen();
