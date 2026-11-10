"""Cut the raw clips into docs/report/video/final.mp4 (+ final-subtitled.mp4). Reproducible:
    bash scripts/video/edit.sh          # = C:/Python311/python.exe scripts/video/edit.py
Inputs: docs/report/video/raw/*.webm (record.ts), vo/NN.mp3 (voiceover.py) or voiceover.wav,
optional music.mp3. Each shot is a list of source pieces (start, end, speed) chosen from the
contact sheets; speed > 1 only for typing, uploads and loading (hint, score and RTL flip stay 1×).
Captions, subtitles and the end card are PNGs drawn with Pillow and overlaid with fades.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
V = ROOT / "docs/report/video"
RAW, VO, WORK = V / "raw", V / "vo", V / "raw/_edit"
W, H, FPS, XF = 1920, 1080, 30, 0.3
BG = "0x16324a"
FONT_B = "C:/Windows/Fonts/segoeuib.ttf"
FONT_R = "C:/Windows/Fonts/segoeui.ttf"
REPO_URL = "https://github.com/LHedi22/WieAct-TechChallenge"
NOTE = "Recorded on our local open-source models (Ollama) after the platform slots closed"

# --------------------------------------------------------------------------------------------
# Timeline. start = second in the final video. pieces = (clip, src_start, src_end, speed).
# layout: full | sbs (two clips side by side) | phone (second clip in a phone frame, right).
# vo = voiceover line number placed at the shot start (+ vo_delay).
# --------------------------------------------------------------------------------------------
TIMELINE: list[dict] = json.loads((Path(__file__).with_name("timeline.json")).read_text("utf-8"))
END = 90.0
# Clips recorded at deviceScaleFactor 1 (memory, see NOTES.md): the 1440×900 page sits in the
# top-left of the 1728×1080 recording, so they are cropped to it unless a piece gives a zoom crop.
DSF1 = {"04-map", "05-island", "06-loading", "06-quiz", "08-tutor", "09-studio", "11-audio",
        "12-teachback", "13-stats"}


def run(cmd: list[str]):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(" ".join(cmd)[:2000])
        print(r.stderr[-3000:])
        sys.exit(1)
    return r.stdout


def dur(f: Path) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]))


# ---------------------------------------------------------------- pieces → one shot clip
def piece(clip: str, a: float, b: float, speed: float, out: Path, box: tuple[int, int], crop=None):
    """Cut [a,b] of a raw clip, change speed, optionally crop [x,y,w,h] (source px) to zoom in,
    fit into box (keeping aspect), 30 fps, no audio."""
    bw, bh = box
    zoom = f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}," if crop else ""
    vf = (f"setpts=(PTS-STARTPTS)/{speed},fps={FPS},{zoom}"
          f"scale={bw}:{bh}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={bw}:{bh}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1,format=yuv420p")
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(RAW / f"{clip}.webm"),
         "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", str(out)])


def concat(parts: list[Path], out: Path, length: float, box: tuple[int, int]):
    """Concatenate parts and force an exact length (freeze the last frame / trim)."""
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
    tmp = out.with_name(out.stem + "_c.mp4")
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(tmp)])
    run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), "-vf",
         f"tpad=stop_mode=clone:stop_duration=30,trim=duration={length:.3f},setpts=PTS-STARTPTS",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-r", str(FPS), str(out)])


def build_stream(pieces: list, name: str, length: float, box: tuple[int, int]) -> Path:
    parts = []
    for i, pc in enumerate(pieces):
        clip, a, b, sp = pc[:4]
        p = WORK / f"{name}_p{i}.mp4"
        crop = pc[4] if len(pc) > 4 else ([0, 0, 1440, 900] if clip in DSF1 else None)
        piece(clip, a, b, sp, p, box, crop)
        parts.append(p)
    out = WORK / f"{name}_s.mp4"
    concat(parts, out, length, box)
    return out


def phone_frame(w: int, h: int) -> Path:
    """Rounded black phone bezel PNG with a transparent screen hole (screen = w×h)."""
    pad = 14
    img = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w + 2 * pad - 1, h + 2 * pad - 1], radius=46, fill=(18, 18, 22, 255))
    d.rounded_rectangle([pad, pad, pad + w - 1, pad + h - 1], radius=32, fill=(0, 0, 0, 0))
    shadow = Image.new("RGBA", (img.width + 60, img.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([30, 36, 30 + img.width, 36 + img.height], radius=46,
                                             fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    shadow.alpha_composite(img, (30, 30))
    f = WORK / "phone_frame.png"
    shadow.save(f)
    return f


def label_png(text: str, name: str, size=26) -> Path:
    font = ImageFont.truetype(FONT_B, size)
    l, t, r, b = font.getbbox(text)
    img = Image.new("RGBA", (r - l + 32, b - t + 18), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=img.height // 2, fill=(255, 255, 255, 235))
    d.text((16 - l, 9 - t), text, font=font, fill=(22, 50, 74, 255))
    f = WORK / f"{name}.png"
    img.save(f)
    return f


def render_shot(i: int, shot: dict, length: float) -> Path:
    out = WORK / f"shot{i:02d}.mp4"
    lay = shot.get("layout", "full")
    if lay == "full":
        s = build_stream(shot["pieces"], f"shot{i:02d}", length, (W, H))
        run(["ffmpeg", "-v", "error", "-y", "-i", str(s), "-c", "copy", str(out)])
    elif lay == "sbs":
        bw, bh = 940, 588
        left = build_stream(shot["pieces"], f"shot{i:02d}L", length, (bw, bh))
        right = build_stream(shot["pieces2"], f"shot{i:02d}R", length, (bw, bh))
        la, lb = label_png(shot["labels"][0], f"lab{i}a"), label_png(shot["labels"][1], f"lab{i}b")
        y = (H - bh) // 2
        fc = (f"color={BG}:s={W}x{H}:r={FPS}:d={length:.3f}[bg];"
              f"[bg][0:v]overlay=13:{y}[a];[a][1:v]overlay={W - bw - 13}:{y}[b];"
              f"[b][2:v]overlay=13+({bw}-w)/2:{y - 62}[c];[c][3:v]overlay={W - bw - 13}+({bw}-w)/2:{y - 62},format=yuv420p")
        run(["ffmpeg", "-v", "error", "-y", "-i", str(left), "-i", str(right), "-i", str(la), "-i", str(lb),
             "-filter_complex", fc, "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "14", "-r", str(FPS), str(out)])
    elif lay == "phone":
        main = build_stream(shot["pieces"], f"shot{i:02d}M", length, (W, H))
        pw, ph = 420, 908
        phone = build_stream(shot["pieces2"], f"shot{i:02d}P", length - shot["phone_at"], (pw, ph))
        frame = phone_frame(pw, ph)
        x, y = W - pw - 120, (H - ph) // 2
        t0 = shot["phone_at"]
        fc = (f"[1:v]setpts=PTS+{t0}/TB[p];"
              f"[0:v][p]overlay={x}:{y}:enable='gte(t,{t0})'[a];"
              f"[a][2:v]overlay={x - 44}:{y - 44}:enable='gte(t,{t0})',format=yuv420p")
        run(["ffmpeg", "-v", "error", "-y", "-i", str(main), "-i", str(phone), "-loop", "1", "-i", str(frame),
             "-filter_complex", fc, "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "14", "-r", str(FPS), str(out)])
    elif lay == "image":
        run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(shot["image"]), "-vf",
             f"scale={W}:{H},fps={FPS},format=yuv420p", "-t", f"{length:.3f}", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "14", str(out)])
    return out


# ---------------------------------------------------------------- overlays
def pill_png(text: str, name: str, size=38) -> Path:
    font = ImageFont.truetype(FONT_B, size)
    l, t, r, b = font.getbbox(text)
    img = Image.new("RGBA", (r - l + 56, b - t + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=img.height // 2, fill=(0, 0, 0, 178))
    d.text((28 - l, 15 - t), text, font=font, fill=(255, 255, 255, 255))
    f = WORK / f"{name}.png"
    img.save(f)
    return f


def subtitle_png(text: str, name: str, size=40) -> Path:
    font = ImageFont.truetype(FONT_B, size)
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        cand = (cur + " " + w_).strip()
        if font.getlength(cand) > 1500 and cur:
            lines.append(cur)
            cur = w_
        else:
            cur = cand
    lines.append(cur)
    lh = size + 14
    widths = [font.getlength(x) for x in lines]
    img = Image.new("RGBA", (int(max(widths)) + 48, lh * len(lines) + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=16, fill=(0, 0, 0, 165))
    for k, line in enumerate(lines):
        d.text(((img.width - widths[k]) / 2, 8 + k * lh), line, font=font, fill=(255, 236, 160, 255))
    f = WORK / f"{name}.png"
    img.save(f)
    return f


def note_png() -> Path:
    font = ImageFont.truetype(FONT_R, 20)
    l, t, r, b = font.getbbox(NOTE)
    img = Image.new("RGBA", (r - l + 24, b - t + 14), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=10, fill=(0, 0, 0, 120))
    d.text((12 - l, 7 - t), NOTE, font=font, fill=(255, 255, 255, 220))
    f = WORK / "note.png"
    img.save(f)
    return f


def end_card() -> Path:
    img = Image.new("RGB", (W, H), (22, 50, 74))
    d = ImageDraw.Draw(img)
    for y in range(H):  # gentle sea gradient
        c = int(22 + 30 * y / H), int(50 + 60 * y / H), int(74 + 70 * y / H)
        d.line([(0, y), (W, y)], fill=c)
    big, mid, small = (ImageFont.truetype(FONT_B, 110), ImageFont.truetype(FONT_B, 48),
                       ImageFont.truetype(FONT_R, 30))
    # little pixel island as a logo
    px = 14
    ox, oy = 170, 300
    island = ["....GGGG....", "..GGGGGGGG..", ".GGGGGGGGGG.", "SSSSSSSSSSSS", ".SSSSSSSSSS."]
    for r_, row in enumerate(island):
        for c_, ch in enumerate(row):
            col = {"G": (110, 160, 80), "S": (232, 205, 150)}.get(ch)
            if col:
                d.rectangle([ox + c_ * px, oy + r_ * px, ox + (c_ + 1) * px - 1, oy + (r_ + 1) * px - 1], fill=col)
    d.text((170, 390), "Learning World", font=big, fill=(255, 255, 255))
    d.text((174, 530), "Learn it, explain it, own it.", font=mid, fill=(255, 214, 120))
    d.text((174, 620), "GenAI peer-learning companion · EdNova · IEEE WIE ACT 5.0", font=small, fill=(220, 232, 240))
    d.text((174, 668), "EN · FR · العربية · Darija", font=small, fill=(220, 232, 240))
    qr = qrcode.QRCode(border=2, box_size=12)
    qr.add_data(REPO_URL)
    qimg = qr.make_image(fill_color=(22, 50, 74), back_color=(255, 255, 255)).convert("RGB").resize((380, 380), Image.NEAREST)
    img.paste(qimg, (W - 380 - 200, 300))
    url = REPO_URL.replace("https://", "")
    tw = small.getlength(url)
    d.text((W - 200 - 190 - tw / 2, 700), url, font=small, fill=(255, 255, 255))
    f = WORK / "endcard.png"
    img.save(f)
    return f


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    starts = [s["start"] for s in TIMELINE]
    shots = []
    for i, s in enumerate(TIMELINE):
        nxt = starts[i + 1] if i + 1 < len(TIMELINE) else END
        length = (nxt - s["start"]) + (XF if i > 0 else 0)
        if s.get("layout") == "image" and s.get("image") == "endcard":
            s = {**s, "image": end_card()}
        print(f"shot {i:02d} {s.get('name', '')} {length:.2f}s", flush=True)
        shots.append(render_shot(i, s, length))

    # crossfade chain
    inputs, fc, prev = [], [], "0:v"
    for f in shots:
        inputs += ["-i", str(f)]
    for i in range(1, len(shots)):
        off = starts[i] - XF
        lab = f"x{i}"
        fc.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}[{lab}]")
        prev = lab
    base = WORK / "base.mp4"
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc), "-map", f"[{prev}]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-r", str(FPS), str(base)])
    print("base", dur(base))

    # audio: VO lines at their shot starts, optional ducked music, loudnorm
    vo_wav = V / "voiceover.wav"
    a_inputs, a_fc, labels = [], [], []
    if vo_wav.exists():
        a_inputs += ["-i", str(vo_wav)]
        labels.append("0:a")
        vo_lines = []
    else:
        vo_lines = [(s["vo"], s["start"] + s.get("vo_delay", 0.25)) for s in TIMELINE if s.get("vo")]
        for k, (n, t) in enumerate(vo_lines):
            a_inputs += ["-i", str(VO / f"{n:02d}.mp3")]
            ms = int(t * 1000)
            a_fc.append(f"[{k}:a]aresample=48000,adelay={ms}|{ms},apad[v{k}]")
            labels.append(f"v{k}")
        # never let a line overlap the next one
        for k in range(len(vo_lines) - 1):
            n, t = vo_lines[k]
            d_ = dur(VO / f"{n:02d}.mp3")
            if t + d_ > vo_lines[k + 1][1] - 0.05:
                print(f"WARNING VO line {n} ({d_:.2f}s at {t:.2f}) overlaps line {vo_lines[k+1][0]}")
    nvo = len(labels)
    a_fc.append("".join(f"[{x}]" for x in labels) + f"amix=inputs={nvo}:normalize=0:duration=longest,atrim=0:{END}[voice]")
    music = V / "music.mp3"
    if music.exists():
        mi = len(a_inputs) // 2
        a_inputs += ["-stream_loop", "-1", "-i", str(music)]
        a_fc.append("[voice]asplit=2[vk][vs]")
        a_fc.append(f"[{mi}:a]aresample=48000,volume=0.35,atrim=0:{END}[m]")
        a_fc.append("[m][vs]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[md]")
        a_fc.append(f"[vk][md]amix=inputs=2:normalize=0,afade=t=out:st={END - 1.2}:d=1.2[mix]")
        last = "mix"
    else:
        last = "voice"
    a_fc.append(f"[{last}]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,atrim=0:{END}[aout]")
    audio = WORK / "audio.m4a"
    run(["ffmpeg", "-v", "error", "-y", *a_inputs, "-filter_complex", ";".join(a_fc), "-map", "[aout]",
         "-c:a", "aac", "-b:a", "192k", str(audio)])

    # captions (+ note) → final; + subtitles → final-subtitled
    note = note_png()
    lines = (VO / "lines.txt").read_text("utf-8").splitlines() if (VO / "lines.txt").exists() else []
    cap_items, sub_items = [], []
    for i, s in enumerate(TIMELINE):
        nxt = starts[i + 1] if i + 1 < len(TIMELINE) else END
        if s.get("caption"):
            cap_items.append((pill_png(s["caption"], f"cap{i:02d}"), s["start"] + 0.35, nxt - 0.15))
    for s in TIMELINE:
        if s.get("vo") and lines and not vo_wav.exists():
            n = s["vo"]
            t = s["start"] + s.get("vo_delay", 0.25)
            sub_items.append((subtitle_png(lines[n - 1], f"sub{n:02d}"), t, t + dur(VO / f"{n:02d}.mp3") + 0.3))

    def burn(items_extra: list, out: Path, sub_y: int):
        ins = ["-i", str(base), "-i", str(audio), "-loop", "1", "-t", str(END), "-i", str(note)]
        fc2, prev2, k = [], "0:v", 3
        fc2.append(f"[{prev2}][2:v]overlay=W-w-24:H-h-22:enable='lt(t,{END - 4.2})'[n0]")
        prev2 = "n0"
        for j, (png, a, b, kind) in enumerate(items_extra):
            d_ = max(0.4, b - a)
            ins += ["-loop", "1", "-t", f"{d_:.3f}", "-i", str(png)]
            fc2.append(f"[{k}:v]format=rgba,fade=t=in:st=0:d=0.25:alpha=1,fade=t=out:st={d_ - 0.25:.3f}:d=0.25:alpha=1,"
                       f"setpts=PTS-STARTPTS+{a:.3f}/TB[o{j}]")
            pos = "52:H-h-56" if kind == "cap" else f"(W-w)/2:{sub_y}-h"
            fc2.append(f"[{prev2}][o{j}]overlay={pos}:eof_action=pass[l{j}]")
            prev2, k = f"l{j}", k + 1
        fc2.append(f"[{prev2}]format=yuv420p[vout]")
        run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(fc2), "-map", "[vout]", "-map", "1:a",
             "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-r", str(FPS), "-c:a", "copy", "-t", str(END), "-movflags", "+faststart", str(out)])
        print(out, dur(out))

    caps = [(p, a, b, "cap") for p, a, b in cap_items]
    burn(caps, V / "final.mp4", 0)
    subs = [(p, a, b, "sub") for p, a, b in sub_items]
    burn(caps + subs, V / "final-subtitled.mp4", H - 150)


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    main()
