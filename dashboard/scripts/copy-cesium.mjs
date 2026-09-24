import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const src = join(root, "node_modules", "cesium", "Build", "Cesium");
const dst = join(root, "public", "cesium");

if (!existsSync(src)) {
  console.log("cesium not installed — skipping asset copy");
  process.exit(0);
}

mkdirSync(dst, { recursive: true });
for (const dir of ["Workers", "Assets", "Widgets", "ThirdParty"]) {
  cpSync(join(src, dir), join(dst, dir), { recursive: true });
}
console.log("cesium runtime assets copied to public/cesium");
