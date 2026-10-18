import {realpathSync} from 'node:fs';
import {createServer} from 'vite';
const server=await createServer({server:{host:'127.0.0.1',port:4224,strictPort:true,hmr:false,fs:{allow:[process.cwd(),realpathSync('node_modules')]}}});
await server.listen();
