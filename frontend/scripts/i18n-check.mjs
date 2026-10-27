// Fails when a locale is missing a key from en.json (or has keys en.json doesn't).
// `_review` (Darija review notes) is metadata and ignored. Run: pnpm i18n:check
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const dir = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "i18n");
const LOCALES = ["fr", "ar", "ar-TN"];

function keys(obj, prefix = "") {
  return Object.entries(obj).flatMap(([k, v]) => {
    if (k === "_review") return [];
    const path = prefix ? `${prefix}.${k}` : k;
    return v && typeof v === "object" && !Array.isArray(v) ? keys(v, path) : [path];
  });
}

const load = (name) => JSON.parse(readFileSync(join(dir, `${name}.json`), "utf8"));
const base = new Set(keys(load("en")));
let failed = false;

for (const locale of LOCALES) {
  const have = new Set(keys(load(locale)));
  const missing = [...base].filter((k) => !have.has(k));
  const extra = [...have].filter((k) => !base.has(k));
  for (const k of missing) console.error(`${locale}: missing ${k}`);
  for (const k of extra) console.error(`${locale}: not in en.json ${k}`);
  if (missing.length || extra.length) failed = true;
}

if (failed) process.exit(1);
console.log(`i18n ok: ${base.size} keys in en, ${LOCALES.join(", ")}`);
