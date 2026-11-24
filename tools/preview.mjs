import { createServer } from "node:http";
import { createReadStream } from "node:fs";
import { realpath, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../docs/", import.meta.url));
export const prefix = "/BambuLoop/";
const types = {
  ".html":"text/html; charset=utf-8", ".css":"text/css; charset=utf-8",
  ".mjs":"text/javascript; charset=utf-8", ".js":"text/javascript; charset=utf-8",
  ".json":"application/json", ".wasm":"application/wasm", ".zip":"application/zip", ".txt":"text/plain; charset=utf-8"
};

export function preview(port = 4173) {
  const server = createServer(async (req, res) => {
    if (!["GET","HEAD"].includes(req.method)) { res.writeHead(405).end(); return; }
    try {
      const url = new URL(req.url, "http://127.0.0.1");
      if (url.pathname === "/" || url.pathname === prefix.slice(0,-1)) {
        res.writeHead(302, { Location: prefix }).end(); return;
      }
      if (!url.pathname.startsWith(prefix)) { res.writeHead(404).end(); return; }
      const relative = decodeURIComponent(url.pathname.slice(prefix.length)) || "index.html";
      const target = await realpath(path.join(root, relative));
      const local = path.relative(root, target);
      if (local.startsWith(".." + path.sep) || local === ".." || path.isAbsolute(local)) { res.writeHead(404).end(); return; }
      const info = await stat(target);
      if (!info.isFile()) { res.writeHead(404).end(); return; }
      res.writeHead(200, { "Content-Type": types[path.extname(target)] || "application/octet-stream",
                           "Content-Length": info.size, "X-Content-Type-Options": "nosniff" });
      if (req.method === "HEAD") res.end();
      else createReadStream(target).on("error", () => res.destroy()).pipe(res);
    } catch { res.writeHead(404).end(); }
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const server = await preview(Number(process.argv[2] || 4173));
  console.log("BambuLoop: http://127.0.0.1:" + server.address().port + prefix);
}
