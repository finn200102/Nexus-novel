import {defineConfig,devices} from '@playwright/test';
import base from './playwright.config';
export default defineConfig({...base,testMatch:'**/saved-recordings.spec.ts',outputDir:'/tmp/nexus-saved-recordings-native-results',reporter:'line',
  use:{...base.use,baseURL:'http://127.0.0.1:4222',channel:undefined,video:'off'},
  projects:[{name:'chromium',use:{...devices['Desktop Chrome'],channel:undefined}},
    {name:'firefox',use:{...devices['Desktop Firefox'],channel:undefined}},
    {name:'webkit',use:{...devices['Desktop Safari'],channel:undefined}}],
  webServer:{command:'node e2e/saved-recordings-vite-server.mjs',url:'http://127.0.0.1:4222',reuseExistingServer:false,timeout:30000}});
