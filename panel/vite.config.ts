import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Versão do painel: a do package.json (mude lá ao publicar), mostrada no rodapé, na Ajuda e nas boas-vindas.
const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8")) as { version: string };

// Em desenvolvimento (npm run dev) as chamadas /api vão para o FastAPI em :8000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
