import {defineConfig} from 'vite';
import {resolve} from 'node:path';
export default defineConfig({plugins:[{name:'local-workbench-auth',apply:'serve',async transformIndexHtml(html){
  const response=await fetch('http://127.0.0.1:9120/');if(!response.ok)return html;
  const source=await response.text(),match=source.match(/window\.__HERMES_SESSION_TOKEN__\s*=\s*("(?:[^"\\]|\\.)*")/);
  if(!match)return html;const token=JSON.parse(match[1]);
  return html.replace('</head>','<script>window.__HERMES_SESSION_TOKEN__='+JSON.stringify(token)+';window.__HERMES_DASHBOARD_EMBEDDED_CHAT__=true;</script></head>');
}}],server:{proxy:{'/api':{target:'http://127.0.0.1:9120',ws:true},'/ws':{target:'ws://127.0.0.1:9120',ws:true},'/studio':'http://127.0.0.1:9120','/editor':'http://127.0.0.1:9120'}},build:{rollupOptions:{input:{main:resolve('index.html'),precision:resolve('precision-workspace.html')}}}});
