"""Полная аудиокнига: site/audio/NN.mp3 -> site/audio/sistemny-administrator.mp3 одним файлом.

Главы склеиваются покадрово (все они MP3 одного формата, CBR), без перекодирования.
В начало пишется тег ID3v2.3: название, автор и оглавление (кадры CTOC/CHAP),
так что плееры, которые понимают главы, показывают их и позволяют переходить.
Без внешних библиотек; длительности глав берутся из ffprobe.

    python audiobook.py          # пересобрать, если какая-то глава новее
    python audiobook.py --force  # пересобрать в любом случае
"""
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUDIO = ROOT / "site" / "audio"
FULL = AUDIO / "sistemny-administrator.mp3"
AUTHOR = "Андрей Сорбье"
TITLE = "Системный Администратор"

# MPEG-1/2/2.5 Layer III: битрейты (кбит/с) и частоты
BITRATES = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
            2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def chapter_files():
    return sorted(p for p in AUDIO.glob("[0-9][0-9].mp3"))


def audio_frames(data):
    """Байты MP3 без ID3-тегов и без служебного кадра Xing/Info (он хранит длину одной главы)."""
    pos = 0
    if data[:3] == b"ID3":
        s = data[6:10]
        pos = 10 + ((s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3])
    end = len(data) - 128 if data[-128:-125] == b"TAG" else len(data)
    while pos + 4 <= end and not (data[pos] == 0xFF and data[pos + 1] & 0xE0 == 0xE0):
        pos += 1
    h = struct.unpack(">I", data[pos:pos + 4])[0]
    ver = (h >> 19) & 3                       # 3 = MPEG1, 2 = MPEG2, 0 = MPEG2.5
    br = BITRATES[1 if ver == 3 else 2][(h >> 12) & 15] * 1000
    sr = RATES[ver][(h >> 10) & 3]
    pad = (h >> 9) & 1
    length = (144 if ver == 3 else 72) * br // sr + pad
    first = data[pos:pos + length]
    if b"Xing" in first or b"Info" in first:
        pos += length
    return data[pos:end]


def duration_ms(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return int(round(float(out.stdout.strip()) * 1000))


# ------------------------------------------------------------------------- ID3v2.3
def frame(fid, body):
    return fid.encode("ascii") + struct.pack(">I", len(body)) + b"\x00\x00" + body


def text_frame(fid, text):
    return frame(fid, b"\x01" + text.encode("utf-16"))      # UTF-16 с BOM


def id3_tag(chapters):
    """chapters: [(название, начало мс, конец мс)]"""
    frames = [text_frame("TIT2", TITLE), text_frame("TPE1", AUTHOR),
              text_frame("TALB", TITLE), text_frame("TCON", "Audiobook")]
    ids = [f"ch{i:02d}".encode("ascii") for i in range(1, len(chapters) + 1)]
    frames.append(frame("CTOC", b"toc\x00" + b"\x03" + bytes([len(ids)])
                        + b"".join(i + b"\x00" for i in ids) + text_frame("TIT2", TITLE)))
    for cid, (name, start, end) in zip(ids, chapters):
        frames.append(frame("CHAP", cid + b"\x00" + struct.pack(">IIII", start, end, 0xFFFFFFFF, 0xFFFFFFFF)
                            + text_frame("TIT2", name)))
    body = b"".join(frames) + b"\x00" * 256                 # немного места под правку тегов
    n = len(body)
    size = bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127])
    return b"ID3\x03\x00\x00" + size + body


def build(force=False):
    files = chapter_files()
    if not files:
        print("Аудиоглав нет — нечего собирать.")
        return None
    if not force and FULL.exists() and FULL.stat().st_mtime >= max(f.stat().st_mtime for f in files):
        return FULL
    chapters, t = [], 0
    for f in files:
        d = duration_ms(f)
        chapters.append((f"Глава {int(f.stem)}", t, t + d))
        t += d
    tmp = FULL.with_suffix(".tmp")
    with open(tmp, "wb") as out:
        out.write(id3_tag(chapters))
        for f in files:
            out.write(audio_frames(f.read_bytes()))
    os.replace(tmp, FULL)
    print(f"Аудиокнига: {FULL}  ({len(files)} глав, {t / 3_600_000:.1f} ч, "
          f"{FULL.stat().st_size / 2 ** 20:.0f} МБ)", flush=True)
    return FULL


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build(force="--force" in sys.argv)
