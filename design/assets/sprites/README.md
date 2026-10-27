# Sprites

Drop real pixel art here as `<name>.png` at 1× (native size, e.g. 16×16 icons, 32×32 buildings,
24×24 cat). The file name must match a key in `frontend/src/components/sprite/registry.ts`
(`coin.png`, `quizHall.png`, `catThinking.png` …). The `Sprite` component picks it up
automatically and stops drawing the generated placeholder — no code change.

Rules (docs/DESIGN.md): 16 px grid, Mediterranean palette from `design/tokens.json`, no text inside
sprites, openly licensed or our own art (record the source in docs/DECISIONS.md).
