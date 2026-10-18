import {defineConfig,devices} from '@playwright/test';
import base from './playwright.config';
export default defineConfig({...base,testMatch:'**/source-lifecycle.spec.ts',outputDir:'/tmp/nexus-source-lifecycle-native-results',reporter:'line',
  use:{...base.use,baseURL:'http://127.0.0.1:4224',channel:undefined,video:'off'},
  projects:[{name:'chromium',use:{...devices['Desktop Chrome'],channel:undefined}},
    {name:'firefox',use:{...devices['Desktop Firefox'],channel:undefined}},
    {name:'webkit',use:{...devices['Desktop Safari'],channel:undefined}}],
  webServer:{command:'node e2e/source-lifecycle-vite-server.mjs',url:'http://127.0.0.1:4224',reuseExistingServer:false,timeout:30000}});
