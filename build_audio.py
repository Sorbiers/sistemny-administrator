"""Аудиоверсия книги: chapters/NN.md -> site/audio/NN.mp3 через русский TTS из Gogolium (F:\\Gogol).

Конвейер тот же, что у Gogolium: num2ru.js (числа словами) -> rut2s.js (ударения из словаря,
паузы, предложения) -> Silero v4_ru (app\\tts\\src\\ssml_speak_tts_fixed.py). Подготовку SSML
делает gogol_ssml.js, вызывая функции Gogolium; синтез — его класс SSMLSpeakTTS, модель
загружается один раз.

Запускать Python'ом из окружения Gogolium (или audio.bat):
    F:\\Gogol\\app\\tts\\venv\\Scripts\\python.exe build_audio.py            # все главы
    ... build_audio.py --chapters 1-3                                       # только 1..3
    ... build_audio.py --chapters 1 --limit 8 --out test.mp3               # проба: первые 8 фрагментов
    ... build_audio.py --show --chapters 11                                 # показать SSML, ничего не писать

Каждый абзац кэшируется в audio_cache/ по хэшу SSML и голоса: после правки главы
переозвучиваются только изменённые абзацы, прерванный запуск продолжается с того же места.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

import audiobook

GOGOL = Path(os.environ.get("GOGOL_DIR", r"F:\Gogol"))
ROOT = Path(__file__).resolve().parent
CHAPTERS = ROOT / "chapters"
CACHE = ROOT / "audio_cache"
OUT_DIR = ROOT / "site" / "audio"

VOICE = "eugene"
SR = 48000
PAUSE_PARA = 0.7         # между абзацами
PAUSE_LOG = 0.5          # между строками утреннего «лога»
PAUSE_HEAD = 1.3         # после заголовков
PAUSE_SCENE = 2.2        # на месте «---» (переход день -> сон)

ORDINAL = ["", "первая", "вторая", "третья", "четвёртая", "пятая", "шестая", "седьмая",
           "восьмая", "девятая", "десятая", "одиннадцатая", "двенадцатая", "тринадцатая",
           "четырнадцатая", "пятнадцатая", "шестнадцатая", "семнадцатая", "восемнадцатая",
           "девятнадцатая", "двадцатая", "двадцать первая", "двадцать вторая",
           "двадцать третья", "двадцать четвёртая", "двадцать пятая", "двадцать шестая"]


# ------------------------------------------------------------------------------ text
STRESS_FILE = ROOT / "stress.json"
_stress = None


def stress_table():
    global _stress
    if _stress is None:
        _stress = json.loads(STRESS_FILE.read_text(encoding="utf-8")) if STRESS_FILE.exists() \
            else {"phrases": [], "words": {}}
    return _stress


def apply_stress(text):
    """\u0423\u0434\u0430\u0440\u0435\u043d\u0438\u044f \u0438\u0437 stress.json: \u0441\u043d\u0430\u0447\u0430\u043b\u0430 \u0444\u0440\u0430\u0437\u044b (\u043e\u043c\u043e\u0433\u0440\u0430\u0444\u044b \u043f\u043e \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\u0443), \u043f\u043e\u0442\u043e\u043c \u0441\u043b\u043e\u0432\u0430 \u043f\u043e \u0443\u043c\u043e\u043b\u0447\u0430\u043d\u0438\u044e.
    \u0421\u043b\u043e\u0432\u0430, \u0433\u0434\u0435 \u0443\u0436\u0435 \u0441\u0442\u043e\u0438\u0442 +, \u043d\u0435 \u0442\u0440\u043e\u0433\u0430\u044e\u0442\u0441\u044f; \u0437\u0430\u0433\u043b\u0430\u0432\u043d\u0430\u044f \u0431\u0443\u043a\u0432\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u044f\u0435\u0442\u0441\u044f."""
    table = stress_table()
    for plain, marked in table["phrases"]:
        text = text.replace(plain, marked)
    words = table["words"]

    def mark(m):
        w = m.group(0)
        if "+" in w:
            return w
        rep = words.get(w.lower())
        if not rep:
            return w
        if w[0].isupper():
            i = 1 if rep.startswith("+") else 0
            rep = rep[:i] + rep[i].upper() + rep[i + 1:]
        return rep

    return re.sub(r"[\u0410-\u042f\u0430-\u044f\u0401\u0451+]+", mark, text)


def clean(s):
    s = s.replace("*", "").replace("\u2011", "-").replace("\u00a0", " ")
    # \u0437\u043d\u0430\u043a \u0443\u0434\u0430\u0440\u0435\u043d\u0438\u044f \u0438\u0437 \u0442\u0435\u043a\u0441\u0442\u0430 \u043a\u043d\u0438\u0433\u0438 (\u041b\u043e\u0433\u0438\u0301\u043d\u043e\u0432) -> \u00ab+\u00bb \u043f\u0435\u0440\u0435\u0434 \u0433\u043b\u0430\u0441\u043d\u043e\u0439, \u043a\u0430\u043a \u0436\u0434\u0451\u0442 Silero
    s = re.sub(r"([\u0410\u0415\u0401\u0418\u041e\u0423\u042b\u042d\u042e\u042f\u0430\u0435\u0451\u0438\u043e\u0443\u044b\u044d\u044e\u044f])\u0301", r"+\1", s)
    s = re.sub(r"(\d+)\s*г\.", r"\1 года", s)            # «2002 г.» -> «2002 года»
    return re.sub(r"\s+", " ", s).strip()


def segments(md):
    """Глава -> список (текст абзаца, пауза после него)."""
    segs = []
    for block in re.split(r"\n\s*\n", md.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        first = lines[0]
        if first.startswith("## "):
            m = re.match(r"##\s*Глава\s+(\d+)\.?\s*(.*)", first)
            if m:
                n, rest = int(m.group(1)), m.group(2).strip()
                title = f"Глава {ORDINAL[n] if n < len(ORDINAL) else n}."
                segs.append((f"{title} {clean(rest)}".strip(), PAUSE_HEAD))
            else:
                segs.append((clean(first[3:]) + ".", PAUSE_HEAD))
            lines = lines[1:]
        elif first.startswith("# "):
            segs.append((clean(first[2:]).rstrip(".") + ".", PAUSE_HEAD))
            lines = lines[1:]
        if not lines:
            continue
        if all(re.fullmatch(r"-{3,}|\*{3,}", l) for l in lines):
            if segs:
                segs[-1] = (segs[-1][0], PAUSE_SCENE)
            continue
        if all(l.startswith("*") and l.endswith("*") for l in lines):   # строки «лога»
            for l in lines:
                segs.append((clean(l), PAUSE_LOG))
            segs[-1] = (segs[-1][0], PAUSE_PARA + 0.5)
            continue
        segs.append((clean(" ".join(lines)), PAUSE_PARA))
    return [(t, p) for t, p in segs if re.search(r"[A-Za-zА-Яа-яЁё0-9]", t)]


def to_ssml(texts):
    """Фрагменты -> по списку блоков <speak> на каждый (через gogol_ssml.js)."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.json"), os.path.join(tmp, "out.json")
        Path(src).write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
        subprocess.run(["node", str(ROOT / "gogol_ssml.js"), src, dst], check=True,
                       env={**os.environ, "GOGOL_DIR": str(GOGOL)})
        return json.loads(Path(dst).read_text(encoding="utf-8"))


def key(blocks):
    return hashlib.sha1(f"silero-v4_ru|{VOICE}|{SR}|".encode() + "\n".join(blocks).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- audio
def read_wav(path):
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32767


def write_wav(path, audio):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    tmp = Path(str(path) + ".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def load_engine():
    sys.path.insert(0, str(GOGOL / "app" / "tts" / "src"))
    from ssml_speak_tts_fixed import SSMLSpeakTTS
    with contextlib.redirect_stdout(io.StringIO()):
        return SSMLSpeakTTS(quiet=True)


def speak(engine, blocks):
    out = []
    for b in blocks:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            a = engine.ssml_to_audio(b, VOICE)
        msg = buf.getvalue()
        if "Error" in msg or "⚠" in msg:
            print("   ! " + msg.strip().splitlines()[0][:150], flush=True)
        out.append(np.asarray(a, dtype=np.float32))
    return np.concatenate(out) if out else np.zeros(int(SR * 0.1), dtype=np.float32)


def encode_mp3(audio, path, title):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "ch.wav"
        write_wav(wav, audio)
        tmp_out = path.with_suffix(".tmp.mp3")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-ac", "1", "-ar", "24000", "-b:a", "64k",
             "-metadata", f"title={title}", "-metadata", f"artist={audiobook.AUTHOR}",
             "-metadata", f"album={audiobook.TITLE}", str(tmp_out)],
            check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        os.replace(tmp_out, path)


def parse_range(s, last):
    nums = set()
    for part in s.split(","):
        a, _, b = part.partition("-")
        nums.update(range(int(a), int(b or a) + 1))
    return sorted(n for n in nums if 1 <= n <= last)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    files = sorted(CHAPTERS.glob("[0-9][0-9].md"))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chapters", default=f"1-{len(files)}")
    ap.add_argument("--limit", type=int, help="только первые N фрагментов (для пробы)")
    ap.add_argument("--out", help="куда писать (по умолчанию site/audio/NN.mp3)")
    ap.add_argument("--show", action="store_true", help="показать SSML и выйти")
    ap.add_argument("--prune", action="store_true",
                    help="удалить из audio_cache фрагменты, которых больше нет в книге (при полной сборке — всегда)")
    args = ap.parse_args()
    full = args.chapters == f"1-{len(files)}" and not args.limit and not args.out

    plan = []
    for n in parse_range(args.chapters, len(files)):
        segs = segments((CHAPTERS / f"{n:02d}.md").read_text(encoding="utf-8"))
        if args.limit:
            segs = segs[:args.limit]
        ssml = to_ssml([apply_stress(t) for t, _ in segs])
        plan.append((n, [(blocks, p) for blocks, (_, p) in zip(ssml, segs)]))

    if args.show:
        for n, segs in plan:
            for blocks, p in segs:
                print(f"[{n:02d} +{p}s] " + " ".join(re.sub(r"<[^>]+>", "", b) for b in blocks))
        return

    CACHE.mkdir(exist_ok=True)
    todo = [(n, b) for n, segs in plan for b, _ in segs if not (CACHE / f"{key(b)}.wav").exists()]
    todo_chars = sum(len("".join(b)) for _, b in todo)
    print(f"Глав: {len(plan)}, абзацев озвучить: {len(todo)}, голос {VOICE}", flush=True)

    engine = None
    done = done_chars = 0
    t0 = time.time()
    for n, segs in plan:
        out = Path(args.out) if args.out else OUT_DIR / f"{n:02d}.mp3"
        for blocks, _ in segs:
            f = CACHE / f"{key(blocks)}.wav"
            if f.exists():
                continue
            if engine is None:
                print("Загружаю Silero ...", flush=True)
                engine = load_engine()
                t0 = time.time()
            write_wav(f, speak(engine, blocks))
            done += 1
            done_chars += len("".join(blocks))
            if done % 20 == 0 or done == len(todo):
                el = time.time() - t0
                print(f"[гл.{n:02d} {done}/{len(todo)}] {el / 60:.1f} мин, "
                      f"осталось ~{el / done_chars * (todo_chars - done_chars) / 60:.0f} мин", flush=True)
        newest = max((CACHE / f"{key(b)}.wav").stat().st_mtime for b, _ in segs)
        if out.exists() and out.stat().st_mtime >= newest and not args.out:
            continue
        pieces = [np.zeros(int(SR * 0.3), dtype=np.float32)]
        for blocks, pause in segs:
            pieces += [read_wav(CACHE / f"{key(blocks)}.wav"), np.zeros(int(SR * pause), dtype=np.float32)]
        audio = np.concatenate(pieces)
        encode_mp3(audio, out, f"Глава {n}")
        print(f"Глава {n:02d}: {out}  ({len(audio) / SR / 60:.1f} мин)", flush=True)

    if args.prune or full:
        prune(files, {key(b) for _, segs in plan for b, _ in segs} if full else None)
    if not args.out:
        audiobook.build()   # полная книга одним файлом, если какая-то глава обновилась


def prune(files, keep=None):
    """Удаляет из кэша записи абзацев, которых в нынешнем тексте книги уже нет."""
    if keep is None:
        keep = set()
        for f in files:
            segs = segments(f.read_text(encoding="utf-8"))
            keep |= {key(b) for b in to_ssml([apply_stress(t) for t, _ in segs])}
    stale = [p for p in CACHE.glob("*.wav") if p.stem not in keep]
    for p in stale:
        p.unlink()
    print(f"Кэш: удалено устаревших фрагментов {len(stale)}, осталось {len(keep)}", flush=True)


if __name__ == "__main__":
    main()
