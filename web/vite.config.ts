import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],worker:{format:'es'},build:{outDir:process.env.VAULT_WEB_OUTPUT||'../vault_rag/static',emptyOutDir:true},server:{proxy:{'/api':'http://127.0.0.1:18080'}}});
