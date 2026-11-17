"""Собирает роман из chapters/*.md в одностраничный сайт site/index.html.

Запуск:  python build_site.py
После правок в главах достаточно запустить ещё раз.
"""
import html
import json
import re
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHAPTERS = ROOT / "chapters"
OUT = ROOT / "site" / "index.html"
ILLU_SRC = ROOT / "illustrations"          # сюда класть картинки: 01a.jpg, 01b.jpg, ...
ILLU_OUT = ROOT / "site" / "img"
ILLU_PROMPTS = ROOT / "illustration_prompts.md"
ILLU_EXT = (".jpg", ".jpeg", ".png", ".webp", ".avif")

TITLE = "Системный Администратор"
AUTHOR = "Андрей Сорбье"
REPO_URL = "https://github.com/Sorbiers/sistemny-administrator"
# обсуждение «Ищем литературного редактора»
EDITOR_DISCUSSION_URL = REPO_URL + "/discussions/1"
ABOUT = ROOT / "site" / "about.html"
DONATE_URL = "https://ko-fi.com/sorbiers"
DONATE_LINE = (f'Сайт бесплатный и без рекламы. Если он вам нравится, автора можно отблагодарить: '
               f'<a href="{DONATE_URL}" target="_blank" rel="noopener">поддержать проект</a>.')
# справочные материалы: файл -> (страница, заголовок)
DOCS = {
    "synopsis.md": ("synopsis.html", "Синопсис"),
    "characters.md": ("characters.html", "Библия персонажей"),
    "worlds.md": ("worlds.html", "Библия мира"),
}


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)


def strip_marks(text: str) -> str:
    return re.sub(r"\*", "", text).strip()


def blocks_of(lines):
    block = []
    for line in lines:
        if line.strip() == "":
            if block:
                yield block
                block = []
        else:
            block.append(line.rstrip())
    if block:
        yield block


def is_log(block):
    return all(l.startswith("*") and l.endswith("*") and len(l) > 2 for l in block)


def teaser_of(text: str) -> str:
    text = strip_marks(text)
    m = re.match(r"^(.+?[.!?…])(\s|$)", text)
    sentence = m.group(1) if m else text
    if len(sentence) > 90:
        cut = sentence[:88].rsplit(" ", 1)[0]
        sentence = cut.rstrip(",;:—– ") + "…"
    return sentence


def parse_chapter(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    part = None
    title = None
    day, dream = [], []
    target = day
    log = None
    teaser = None
    words = 0

    for block in blocks_of(lines):
        first = block[0]
        if first.startswith("# "):
            part = first[2:].strip()
            continue
        if first.startswith("## "):
            title = first[3:].strip()
            continue
        if first.strip() == "---":
            target = dream
            continue
        words += sum(len(l.split()) for l in block)
        if log is None and target is day and not day and is_log(block):
            log = [strip_marks(l) for l in block]
            continue
        text = " ".join(block) if len(block) == 1 else None
        if text is not None and text.strip() == "Вход.":
            target.append('<p class="vhod">Вход.</p>')
            continue
        if teaser is None and target is day:
            teaser = teaser_of(block[0])
        body = "<br>".join(inline(l) for l in block)
        target.append(f"<p>{body}</p>")

    num = int(re.search(r"\d+", title or path.stem).group())
    date = None
    if log:
        m = re.search(r"(\d{1,2} \S+ \d{4})", log[0])
        date = m.group(1) if m else None
    return {
        "num": num,
        "title": title or f"Глава {num}",
        "part": part,
        "log": log,
        "day": day,
        "dream": dream,
        "teaser": teaser or "",
        "date": date,
        "minutes": max(1, round(words / 180)),
    }


def load_captions():
    """Подписи из illustration_prompts.md: заголовок «### 1А. Название» и строка *описания*."""
    caps = {}
    if not ILLU_PROMPTS.exists():
        return caps
    lines = ILLU_PROMPTS.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^### (\d+)([АБAB])\. (.+)$", line.strip())
        if not m:
            continue
        side = "a" if m.group(2) in "АA" else "b"
        desc = ""
        if i + 1 < len(lines) and lines[i + 1].startswith("*"):
            desc = strip_marks(lines[i + 1])
        caps[(int(m.group(1)), side)] = (m.group(3).strip(), desc)
    return caps


MAX_WIDTH = 1600   # ширина картинок на сайте; оригиналы в illustrations/ не меняются


def publish_image(src: Path, out_dir: Path, stem: str) -> str:
    """Кладёт в site/img уменьшенную JPEG-копию (через Pillow) или, без Pillow, сам файл."""
    try:
        from PIL import Image
    except ImportError:
        dest = out_dir / f"{stem}{src.suffix.lower()}"
        if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dest)
        return dest.name
    dest = out_dir / f"{stem}.jpg"
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        try:
            with Image.open(dest) as done:
                if done.width <= MAX_WIDTH:
                    return dest.name
        except Exception:
            pass
    with Image.open(src) as im:
        im = im.convert("RGB")
        if im.width > MAX_WIDTH:
            im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
        im.save(dest, "JPEG", quality=84, optimize=True, progressive=True)
    return dest.name


def find_illustrations(nums):
    """Ищет illustrations/NNa.* и NNb.* (также Na.*), копирует в site/img."""
    found = {}
    if not ILLU_SRC.exists():
        return found
    files = {p.name.lower(): p for p in ILLU_SRC.iterdir() if p.suffix.lower() in ILLU_EXT}
    ILLU_OUT.mkdir(parents=True, exist_ok=True)
    for n in nums:
        for side in ("a", "b"):
            for stem in (f"{n:02d}{side}", f"{n}{side}"):
                hit = next((files[stem + ext] for ext in ILLU_EXT if stem + ext in files), None)
                if hit:
                    found[(n, side)] = publish_image(hit, ILLU_OUT, f"{n:02d}{side}")
                    break
    # убрать из site/img картинки, которых больше нет в illustrations
    for old in ILLU_OUT.iterdir():
        if old.name not in found.values():
            old.unlink()
    return found


def figure(num, side, images, captions):
    name = images.get((num, side))
    if not name:
        return ""
    title, desc = captions.get((num, side), ("", ""))
    alt = html.escape(f"{title}. {desc}".strip(". ") if title else f"Иллюстрация к главе {num}")
    cap = ""  # подписи под картинками отключены; название остаётся в alt
    return (
        f'<figure class="illu illu-{side}">'
        f'<img src="img/{name}" alt="{alt}" loading="lazy" decoding="async">{cap}</figure>'
    )


def split_part(part: str):
    head, _, name = part.partition(". ")
    return head, name or ""


AUDIO_DIR = ROOT / "site" / "audio"


def player(num):
    """Плеер главы, если build_audio.py уже сделал site/audio/NN.mp3."""
    f = AUDIO_DIR / f"{num:02d}.mp3"
    if not f.exists():
        return ""
    v = int(f.stat().st_mtime)  # чтобы браузер взял новую запись после переозвучки
    return (f'<audio class="ch-audio" controls preload="none" src="audio/{f.name}?v={v}" '
            f'aria-label="Аудиоверсия главы {num}"></audio>')


FONTS_SRC = ROOT / "fonts"          # woff2 + fonts.css + OFL; раздаются с сайта, без Google
FONTS_OUT = ROOT / "site" / "fonts"
GOOGLE_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link href="https://fonts.googleapis.com/css2?family=PT+Mono&family=PT+Serif:ital,wght@0,400;0,700;1,400'
    '&display=swap" rel="stylesheet">')


def fonts_html():
    """Свои шрифты (site/fonts), если они есть; иначе — как раньше, с Google Fonts."""
    css = FONTS_SRC / "fonts.css"
    if not css.exists():
        return GOOGLE_FONTS
    return "<style>\n" + css.read_text(encoding="utf-8") + "</style>"


def publish_fonts():
    if not (FONTS_SRC / "fonts.css").exists():
        return 0
    FONTS_OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in FONTS_SRC.iterdir():
        if f.suffix in (".woff2", ".txt"):
            dst = FONTS_OUT / f.name
            if not dst.exists() or dst.stat().st_mtime < f.stat().st_mtime:
                shutil.copy2(f, dst)
            n += 1
    return n


FULL_AUDIO = AUDIO_DIR / "sistemny-administrator.mp3"


def download_link():
    """Ссылка на полную аудиокнигу (её собирает audiobook.py), если файл есть."""
    if not FULL_AUDIO.exists():
        return ""
    mb = FULL_AUDIO.stat().st_size / 2 ** 20
    v = int(FULL_AUDIO.stat().st_mtime)
    name = html.escape(f"{AUTHOR} — {TITLE}.mp3")
    return (f'<p class="download"><a href="audio/{FULL_AUDIO.name}?v={v}" download="{name}">'
            f'Скачать аудиокнигу <small>MP3 · {mb:.0f} МБ · с главами</small></a></p>')


def render(chapters, images=None, captions=None):
    images = images or {}
    captions = captions or {}
    parts = []
    for ch in chapters:
        if ch["part"]:
            parts.append({"title": ch["part"], "chapters": []})
        if not parts:
            parts.append({"title": "", "chapters": []})
        parts[-1]["chapters"].append(ch)

    total_words_min = sum(c["minutes"] for c in chapters)

    # --- оглавление
    toc_html = []
    drawer_html = []
    for pi, p in enumerate(parts, 1):
        head, name = split_part(p["title"])
        toc_html.append(
            f'<li class="toc-part"><a href="#part-{pi}" class="toc-part-head">'
            f'<span class="toc-part-num">{html.escape(head)}</span>'
            f'<span class="toc-part-name">{html.escape(name)}</span></a><ol>'
        )
        drawer_html.append(
            f'<li class="dr-part"><span>{html.escape(head)}. {html.escape(name)}</span><ol>'
        )
        for ch in p["chapters"]:
            date = f'<span class="toc-date">{html.escape(ch["date"])}</span>' if ch["date"] else ""
            toc_html.append(
                f'<li><a href="#ch-{ch["num"]}" class="toc-ch">'
                f'<span class="toc-n">{ch["num"]}</span>'
                f'<span class="toc-t">{inline(ch["teaser"])}{date}</span>'
                f'<span class="toc-m">{ch["minutes"]} мин</span></a></li>'
            )
            drawer_html.append(
                f'<li><a href="#ch-{ch["num"]}" data-ch="{ch["num"]}">'
                f'<span class="dr-n">{ch["num"]}</span>{inline(ch["teaser"])}</a></li>'
            )
        toc_html.append("</ol></li>")
        drawer_html.append("</ol></li>")

    # --- текст
    body = []
    pi = 0
    nums = [c["num"] for c in chapters]
    for i, ch in enumerate(chapters):
        if ch["part"]:
            pi += 1
            head, name = split_part(ch["part"])
            body.append(
                f'<section class="part" id="part-{pi}"><div class="col">'
                f'<p class="part-num">{html.escape(head)}</p>'
                f'<h2 class="part-name">{html.escape(name)}</h2></div></section>'
            )
        log = ""
        if ch["log"]:
            lines = "".join(f"<div>{html.escape(l)}</div>" for l in ch["log"])
            log = f'<div class="log" aria-label="Утренняя запись в тетради">{lines}</div>'
        prev_link = (
            f'<a href="#ch-{nums[i-1]}">← Глава {nums[i-1]}</a>' if i > 0 else "<span></span>"
        )
        next_link = (
            f'<a href="#ch-{nums[i+1]}">Глава {nums[i+1]} →</a>'
            if i + 1 < len(chapters)
            else '<a href="#end">Конец →</a>'
        )
        body.append(
            f'<article class="chapter" id="ch-{ch["num"]}" data-ch="{ch["num"]}">'
            f'<header class="ch-head col"><h3>{html.escape(ch["title"])}</h3>'
            f'<p class="ch-meta">{ch["minutes"]} мин чтения</p></header>'
            f'<section class="day">{figure(ch["num"], "a", images, captions)}'
            f'<div class="col">{log}{"".join(ch["day"])}</div></section>'
            f'<section class="dream">{figure(ch["num"], "b", images, captions)}'
            f'<div class="col">{"".join(ch["dream"])}</div></section>'
            f'<nav class="ch-nav col" aria-label="Навигация по главам">{prev_link}'
            f'<a href="#toc">Содержание</a>{next_link}</nav>'
            f"</article>"
        )

    page = TEMPLATE
    page = page.replace("%%FONTS%%", fonts_html())
    page = page.replace("%%TITLE%%", TITLE)
    page = page.replace("%%AUTHOR%%", AUTHOR)
    page = page.replace("%%LISTEN%%", '<a href="audio.html">Слушать</a>' if FULL_AUDIO.exists() else "")
    page = page.replace("%%DONATE%%", DONATE_LINE)
    page = page.replace("%%TOC%%", "".join(toc_html))
    page = page.replace("%%DRAWER%%", "".join(drawer_html))
    page = page.replace("%%BODY%%", "".join(body))
    page = page.replace("%%COUNT%%", str(len(chapters)))
    page = page.replace("%%HOURS%%", str(round(total_words_min / 60)))
    page = page.replace("%%LAST%%", json.dumps(nums[-1]))
    return page


TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%AUTHOR%% — %%TITLE%%</title>
<meta name="author" content="%%AUTHOR%%">
<meta name="description" content="Роман в двух мирах: офисная Москва 2001–2004 годов и мир, где герою открыто всё.">
%%FONTS%%
<style>
:root{
  --paper:#f2f0eb; --ink:#25231f; --muted:#706b63; --rule:#d9d4ca;
  --log-bg:#e5e2da; --log-ink:#34483c; --log-edge:#7d9686;
  --dream-bg:#16212a; --dream-ink:#e5e1d7; --dream-muted:#98a6ad; --dream-accent:#e2a95f;
  --accent:#3e6a58; --bar-bg:rgba(242,240,235,.94); --shadow:rgba(30,25,20,.18);
  --serif:"PT Serif",Georgia,"Times New Roman",serif;
  --mono:"PT Mono",Consolas,"Courier New",monospace;
  --fs:20px; --measure:33em;
  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#1a1917; --ink:#e3dfd6; --muted:#9b958b; --rule:#36332e;
    --log-bg:#22251f; --log-ink:#a8c7a6; --log-edge:#5d7a61;
    --dream-bg:#0c141a; --dream-ink:#dfe5e6; --dream-muted:#8c9ba2; --dream-accent:#e6b06a;
    --accent:#93c2ab; --bar-bg:rgba(26,25,23,.94); --shadow:rgba(0,0,0,.5);
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --paper:#1a1917; --ink:#e3dfd6; --muted:#9b958b; --rule:#36332e;
  --log-bg:#22251f; --log-ink:#a8c7a6; --log-edge:#5d7a61;
  --dream-bg:#0c141a; --dream-ink:#dfe5e6; --dream-muted:#8c9ba2; --dream-accent:#e6b06a;
  --accent:#93c2ab; --bar-bg:rgba(26,25,23,.94); --shadow:rgba(0,0,0,.5);
  color-scheme:dark;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:64px}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--serif);
  font-size:var(--fs);line-height:1.62;-webkit-text-size-adjust:100%;text-rendering:optimizeLegibility}
a{color:inherit}
.col{max-width:var(--measure);margin:0 auto;padding:0 16px}
@media (max-width:600px){:root{--fs:18px}}
/* на больших экранах колонка текста по ширине иллюстраций */
@media (min-width:900px){:root{--measure:1040px}}

/* прогресс и верхняя панель */
.progress{position:fixed;top:0;left:0;height:3px;width:0;background:var(--accent);z-index:30}
.bar{position:fixed;top:0;left:0;right:0;z-index:20;display:flex;align-items:center;gap:8px;
  padding:10px 16px;background:var(--bar-bg);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--rule);font-size:15px;transform:translateY(-100%);
  transition:transform .25s ease}
.bar.on{transform:none}
.bar-title{font-weight:700;text-decoration:none;white-space:nowrap}
.bar-where{color:var(--muted);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar button{font:inherit;font-size:14px;color:var(--ink);background:transparent;
  border:1px solid var(--rule);border-radius:6px;padding:5px 10px;cursor:pointer;line-height:1.2}
.bar button:hover{border-color:var(--muted)}
.bar button:focus-visible,.cover a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:600px){
  .bar{gap:6px;padding:8px 12px}
  .bar-where{display:none}
  .bar-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis}
  .bar button{padding:5px 8px;flex:none}
}

/* обложка */
.cover{min-height:100vh;min-height:100svh;display:flex;flex-direction:column;justify-content:center;
  align-items:center;text-align:center;padding:48px 16px;position:relative}
.cover-pre{font-family:var(--mono);font-size:14px;color:var(--muted);letter-spacing:.05em;margin:0 0 28px}
.cover h1{font-size:clamp(40px,8vw,86px);line-height:1.02;margin:0;font-weight:700;letter-spacing:-.01em}
.cover h1 span{display:block}
.cover-sub{font-style:italic;color:var(--muted);margin:22px 0 0;font-size:clamp(17px,2.4vw,21px)}
.worlds{display:flex;gap:0;margin:44px auto 0;max-width:560px;width:100%;
  border:1px solid var(--rule);border-radius:10px;overflow:hidden;font-size:15px;text-align:left}
.worlds div{flex:1;padding:14px 16px;line-height:1.4}
.worlds b{display:block;font-size:13px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px}
.worlds .w-day{color:var(--muted)}
.worlds .w-dream{background:var(--dream-bg);color:var(--dream-muted)}
.worlds .w-dream b{color:var(--dream-accent)}
.cover-actions{display:flex;gap:12px;margin-top:36px;flex-wrap:wrap;justify-content:center}
.cover-actions a{font-size:16px;text-decoration:none;padding:11px 20px;border-radius:8px;border:1px solid var(--rule)}
.cover-actions a.primary{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.cover-meta{margin-top:22px;font-size:14px;color:var(--muted)}
/* знак ударения рисуется отдельно: в моноширинном шрифте комбинируемый акут съезжает на соседнюю букву */
.acc{position:relative;display:inline-block}
.acc::after{content:"\00B4";position:absolute;left:0;right:0;top:-.5em;text-align:center}
.cover-about{position:absolute;top:16px;right:16px;font-size:16px;font-weight:700;color:var(--ink);
  text-decoration:none;display:inline-flex;align-items:center;gap:8px;padding:8px 16px;
  border:1px solid var(--ink);border-radius:999px;background:var(--paper)}
.cover-about::before{content:"i";display:inline-grid;place-items:center;width:20px;height:20px;
  border-radius:50%;background:var(--ink);color:var(--paper);font-size:13px;font-style:italic;font-family:var(--serif)}
.cover-about:hover{background:var(--ink);color:var(--paper)}
.cover-about:hover::before{background:var(--paper);color:var(--ink)}
@media (max-width:600px){.cover-about{position:static;margin:0 0 28px}}
.bar-about{font-size:14px;color:var(--accent);font-weight:700;text-decoration:none;white-space:nowrap;
  border-bottom:2px solid var(--accent)}
.bar-about:hover{color:var(--ink);border-color:var(--ink)}
@media (max-width:600px){.bar-about{display:none}}
.fiction{font-size:15px;color:var(--muted);font-style:italic;max-width:32em;margin:18px auto 0;padding:0 16px}
.cover-author{font-size:clamp(18px,2.6vw,24px);letter-spacing:.04em;margin:0 0 14px}
.download{margin-top:18px;font-size:15px}
.download a{display:inline-flex;gap:8px;align-items:baseline}
.download small{color:var(--muted);font-size:13px}
.resume{margin-top:18px;font-size:15px;display:none}
.resume.on{display:block}
.resume a{color:var(--accent)}
@media (max-width:480px){.worlds{flex-direction:column}}

/* содержание */
.toc{padding:72px 0 40px;border-top:1px solid var(--rule)}
.toc h2{font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:400;margin:0 0 28px}
.toc ol{list-style:none;margin:0;padding:0}
.toc-part{margin-bottom:30px}
.toc-part-head{display:flex;gap:10px;align-items:baseline;text-decoration:none;margin-bottom:8px;flex-wrap:wrap}
.toc-part-num{font-size:14px;color:var(--muted);letter-spacing:.06em;text-transform:uppercase}
.toc-part-name{font-size:24px;font-weight:700}
.toc-ch{display:grid;grid-template-columns:2.2em 1fr auto;gap:10px;align-items:baseline;
  text-decoration:none;padding:7px 0;border-bottom:1px solid var(--rule);font-size:17px;line-height:1.4}
.toc-ch:hover .toc-t{color:var(--accent)}
.toc-n{font-family:var(--mono);font-size:14px;color:var(--muted)}
.toc-date{display:block;font-size:13px;color:var(--muted);font-family:var(--mono);margin-top:2px}
.toc-m{font-size:13px;color:var(--muted);white-space:nowrap}

/* части и главы */
.part{padding:110px 0 70px;text-align:center}
.part-num{margin:0;font-size:15px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.part-name{margin:12px 0 0;font-size:clamp(34px,6vw,54px);line-height:1.1}
.chapter{padding-top:40px}
.ch-head{padding-top:30px;padding-bottom:18px}
.ch-head h3{margin:0;font-size:30px;font-weight:700}
.ch-meta{margin:4px 0 0;font-size:14px;color:var(--muted)}
.ch-audio{display:block;width:100%;max-width:520px;margin:14px 0 0;height:40px}
.day{padding:10px 0 56px}
.day p,.dream p{margin:0 0 .25em;text-indent:1.4em;hyphens:auto;-webkit-hyphens:auto}
.day .log + p,.ch-head + .day p:first-child{text-indent:0}
.log{font-family:var(--mono);font-size:.74em;line-height:1.6;background:var(--log-bg);color:var(--log-ink);
  border-left:3px solid var(--log-edge);padding:14px 16px;margin:0 0 30px;border-radius:0 6px 6px 0;
  overflow-wrap:anywhere}
.log div + div{margin-top:2px}
.dream{background:var(--dream-bg);color:var(--dream-ink);padding:64px 0 72px}
.dream em{color:var(--dream-muted)}
.dream p.vhod,.day p.vhod{text-indent:0;font-family:var(--mono);color:var(--dream-accent);
  letter-spacing:.12em;font-size:.84em;margin:0 0 1.6em}
.dream p.vhod::after{content:"";display:inline-block;width:.55em;height:1em;margin-left:.3em;
  vertical-align:-.12em;background:var(--dream-accent);animation:blink 1.1s steps(1) infinite}
.dream p.vhod + p{text-indent:0}
@keyframes blink{50%{opacity:0}}
@media (prefers-reduced-motion:reduce){.dream p.vhod::after{animation:none}}
.illu{max-width:1040px;margin:6px auto 40px;padding:0 16px}
.illu img{display:block;width:100%;height:auto;border-radius:4px;background:var(--log-bg);
  box-shadow:0 10px 30px var(--shadow)}
.illu figcaption{text-align:center;font-size:15px;font-style:italic;color:var(--muted);margin-top:10px}
.dream .illu{margin-top:-14px}
.dream .illu img{background:#1f2c36}
.dream .illu figcaption{color:var(--dream-muted)}
.ch-nav{display:flex;justify-content:space-between;gap:12px;padding-top:22px;padding-bottom:22px;
  font-size:15px;color:var(--muted)}
.ch-nav a{text-decoration:none}
.ch-nav a:hover{color:var(--accent)}

.end{text-align:center;padding:110px 16px 140px}
.end p{margin:0;font-style:italic;color:var(--muted)}
.end .fin{font-style:normal;font-size:34px;color:var(--ink);margin-bottom:14px;font-weight:700}

/* выдвижное содержание */
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(380px,88vw);background:var(--paper);
  border-left:1px solid var(--rule);box-shadow:-8px 0 30px var(--shadow);z-index:40;
  transform:translateX(105%);transition:transform .25s ease;overflow-y:auto;padding:18px 18px 40px;font-size:15px}
.drawer.on{transform:none}
.drawer-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.drawer-head b{font-size:16px}
.drawer button{font:inherit;color:var(--ink);background:transparent;border:1px solid var(--rule);border-radius:6px;padding:4px 10px;cursor:pointer}
.drawer ol{list-style:none;margin:0;padding:0}
.dr-part{margin-top:14px}
.dr-part > span{display:block;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.drawer a{display:flex;gap:10px;text-decoration:none;padding:6px 8px;border-radius:6px;line-height:1.35}
.drawer a:hover{background:var(--log-bg)}
.drawer a.cur{background:var(--log-bg);color:var(--accent)}
.dr-n{font-family:var(--mono);color:var(--muted);min-width:1.6em}
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:35;opacity:0;pointer-events:none;transition:opacity .25s}
.scrim.on{opacity:1;pointer-events:auto}
</style>
</head>
<body>
<div class="progress" id="progress"></div>

<header class="bar" id="bar">
  <a class="bar-title" href="#top">%%TITLE%%</a>
  <span class="bar-where" id="where"></span>
  <a class="bar-about" href="audio.html">Слушать</a>
  <a class="bar-about" href="about.html">О проекте</a>
  <button type="button" id="smaller" aria-label="Уменьшить шрифт">A−</button>
  <button type="button" id="bigger" aria-label="Увеличить шрифт">A+</button>
  <button type="button" id="theme" aria-label="Сменить тему">◐</button>
  <button type="button" id="open-drawer">Главы</button>
</header>

<section class="cover" id="top">
  <a class="cover-about" href="about.html">О проекте</a>
  <p class="cover-author">%%AUTHOR%%</p>
  <h1><span>Системный</span><span>Администратор</span></h1>
  <p class="cover-sub">Роман в двух мирах</p>
  <div class="worlds">
    <div class="w-day"><b>Наше время</b>Москва, 2001–2004. Фирма деревянных окон, бухгалтерия, чужая почта.</div>
    <div class="w-dream"><b>Вход</b>Каждую ночь — туда, где ему открыто всё.</div>
  </div>
  <div class="cover-actions">
    <a class="primary" href="#ch-1">Начать читать</a>
    <a href="#toc">Содержание</a>
    %%LISTEN%%
  </div>
  <p class="resume" id="resume">Вы остановились на <a href="#" id="resume-link"></a></p>
  <p class="cover-meta">%%COUNT%% глав · около %%HOURS%% часов чтения</p>
  <p class="cover-meta">%%DONATE%%</p>
</section>

<section class="toc" id="toc">
  <div class="col">
    <h2>Содержание</h2>
    <ol>%%TOC%%</ol>
  </div>
</section>

<main>%%BODY%%</main>

<section class="end" id="end">
  <p class="fin">Конец</p>
  <p><a href="#toc">К содержанию</a></p>
  <p class="fiction">Все персонажи, организации и события вымышлены. Любое сходство с реальными
    людьми и организациями случайно.</p>
  <p class="fiction"><a href="about.html">О проекте и правах</a></p>
  <p class="fiction">%%DONATE%%</p>
</section>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer" aria-label="Главы" aria-hidden="true">
  <div class="drawer-head"><b>Главы</b><button type="button" id="close-drawer">Закрыть</button></div>
  <ol>%%DRAWER%%</ol>
</aside>

<script>
(function(){
  var KEY = "sysadmin-reader";
  function load(){ try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch(e){ return {}; } }
  function save(s){ try { localStorage.setItem(KEY, JSON.stringify(s)); } catch(e){} }
  var state = load();
  var root = document.documentElement;

  if (state.theme) root.setAttribute("data-theme", state.theme);
  if (state.fs) root.style.setProperty("--fs", state.fs + "px");

  document.getElementById("theme").addEventListener("click", function(){
    var cur = root.getAttribute("data-theme");
    if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var next = cur === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    state.theme = next; save(state);
  });
  function setFs(delta){
    var cur = parseFloat(getComputedStyle(root).getPropertyValue("--fs")) || 20;
    var next = Math.min(28, Math.max(15, cur + delta));
    root.style.setProperty("--fs", next + "px");
    state.fs = next; save(state);
  }
  document.getElementById("smaller").addEventListener("click", function(){ setFs(-1); });
  document.getElementById("bigger").addEventListener("click", function(){ setFs(1); });

  var drawer = document.getElementById("drawer"), scrim = document.getElementById("scrim");
  function openDrawer(on){
    drawer.classList.toggle("on", on); scrim.classList.toggle("on", on);
    drawer.setAttribute("aria-hidden", on ? "false" : "true");
    if (on) { var c = drawer.querySelector("a.cur"); if (c) c.scrollIntoView({block:"center"}); }
  }
  document.getElementById("open-drawer").addEventListener("click", function(){ openDrawer(true); });
  document.getElementById("close-drawer").addEventListener("click", function(){ openDrawer(false); });
  scrim.addEventListener("click", function(){ openDrawer(false); });
  drawer.addEventListener("click", function(e){ if (e.target.closest("a")) openDrawer(false); });
  document.addEventListener("keydown", function(e){ if (e.key === "Escape") openDrawer(false); });

  var bar = document.getElementById("bar"), where = document.getElementById("where");
  var progress = document.getElementById("progress");
  var cover = document.getElementById("top");
  var chapters = Array.prototype.slice.call(document.querySelectorAll(".chapter"));
  var links = {};
  Array.prototype.forEach.call(drawer.querySelectorAll("a[data-ch]"), function(a){ links[a.dataset.ch] = a; });
  var current = null, saveTimer = null;

  function partOf(ch){
    var el = ch;
    while (el && !(el.classList && el.classList.contains("part"))) el = el.previousElementSibling;
    return el ? el.querySelector(".part-name").textContent : "";
  }
  function onScroll(){
    var y = window.scrollY, h = document.documentElement.scrollHeight - innerHeight;
    progress.style.width = (h > 0 ? (y / h * 100) : 0) + "%";
    bar.classList.toggle("on", y > cover.offsetHeight - 80);
    var found = null;
    for (var i = 0; i < chapters.length; i++){
      if (chapters[i].getBoundingClientRect().top <= 120) found = chapters[i]; else break;
    }
    if (found !== current){
      if (current && links[current.dataset.ch]) links[current.dataset.ch].classList.remove("cur");
      current = found;
      if (current){
        if (links[current.dataset.ch]) links[current.dataset.ch].classList.add("cur");
        where.textContent = partOf(current) + " · Глава " + current.dataset.ch;
      } else where.textContent = "";
    }
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function(){
      if (current){ state.ch = current.dataset.ch; state.y = Math.round(y); save(state); }
    }, 400);
  }
  addEventListener("scroll", onScroll, {passive:true});
  addEventListener("resize", onScroll);

  if (state.ch && state.ch !== "1" && !location.hash){
    var r = document.getElementById("resume"), rl = document.getElementById("resume-link");
    rl.textContent = "главе " + state.ch;
    rl.href = "#ch-" + state.ch;
    rl.addEventListener("click", function(e){
      if (state.y){ e.preventDefault(); scrollTo({top: state.y, behavior: "auto"}); }
    });
    r.classList.add("on");
  }
  onScroll();
})();
</script>
</body>
</html>
"""


ABOUT_TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>О проекте — %%TITLE%%</title>
<meta name="author" content="%%AUTHOR%%">
<meta name="description" content="Кто и чем делал роман «%%TITLE%%»: текст, редактура, иллюстрации, озвучание, сайт.">
%%FONTS%%
<style>
%%BASE_CSS%%
.page{max-width:44em;margin:0 auto;padding:40px 16px 80px}
.back{font-size:15px;color:var(--muted);text-decoration:none;border-bottom:1px solid var(--rule)}
.back:hover{color:var(--ink)}
h1{font-size:clamp(32px,6vw,52px);line-height:1.08;margin:28px 0 6px}
.lead{color:var(--muted);font-style:italic;margin:0 0 36px}
h2{font-size:15px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
  margin:40px 0 10px;font-weight:700;font-family:var(--mono)}
dl{margin:0;display:grid;grid-template-columns:minmax(9em,15em) 1fr;gap:10px 22px}
dt{color:var(--muted)}
dd{margin:0}
@media (max-width:600px){dl{grid-template-columns:1fr;gap:2px}dd{margin-bottom:12px}}
a{color:var(--accent)}
.wip{background:var(--log-bg);border-left:3px solid var(--dream-accent);padding:10px 14px;
  font-size:16px;margin:0 0 8px}
.wanted{color:#c0392b;font-weight:700}
:root[data-theme="dark"] .wanted{color:#ff7b6b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .wanted{color:#ff7b6b}}
.note{font-size:16px;color:var(--muted);margin-top:44px;border-top:1px solid var(--rule);padding-top:18px}
</style>
<script>
  try { var s = JSON.parse(localStorage.getItem("sysadmin-reader")) || {};
        if (s.theme) document.documentElement.setAttribute("data-theme", s.theme); } catch (e) {}
</script>
</head>
<body>
<main class="page">
  <a class="back" href="index.html">← К книге</a>
  <h1>О проекте</h1>
  <p class="lead">%%AUTHOR%% · «%%TITLE%%» · роман в двух мирах</p>
  <p class="wip"><b>Проект в работе.</b> Текст, иллюстрации, аудиоверсия и материалы к роману
    дорабатываются — возможны обновления контента.</p>

  <h2>Текст</h2>
  <dl>
    <dt>Оригинальная идея</dt><dd>%%AUTHOR%%</dd>
    <dt>Автор текста</dt><dd>%%AUTHOR%% в соавторстве с моделями
      <a href="https://www.anthropic.com/claude/fable">Claude Fable 5.2</a> и
      <a href="https://www.anthropic.com/claude">Claude Opus 5.5</a>
      (<a href="https://www.anthropic.com">Anthropic</a>)</dd>
    <dt>Редактор, корректор</dt><dd><a href="https://claude.com">Claude</a></dd>
    <dt>Литературный редактор</dt><dd><a class="wanted" href="%%EDITOR_URL%%">Ищется</a> —
      если хотите взяться, напишите в <a href="%%EDITOR_URL%%">обсуждении на GitHub</a></dd>
    <dt><a href="synopsis.html">Синопсис</a>, библии <a href="characters.html">персонажей</a>
      и <a href="worlds.html">мира</a></dt><dd>%%AUTHOR%% и Claude</dd>
  </dl>

  <h2>Иллюстрации</h2>
  <dl>
    <dt>Генерация</dt><dd><a href="https://gemini.google.com">Google Gemini</a>
      (модель изображений Nano Banana)</dd>
    <dt>Промпты</dt><dd>%%AUTHOR%%</dd>
  </dl>

  <h2>Озвучание</h2>
  <dl>
    <dt>Синтез речи</dt><dd><a href="https://github.com/snakers4/silero-models">Silero TTS</a>,
      модель <code>v4_ru</code>, голос <b>eugene</b> — © <a href="https://silero.ai">Silero Team</a>,
      лицензия <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.ru">CC BY-NC-SA 4.0</a>;
      запускается локально на <a href="https://pytorch.org">PyTorch</a></dd>
    <dt>Конвейер</dt><dd><a href="https://github.com/Sorbiers/gogolium">Gogolium</a> (%%AUTHOR%%):
      числа словами, словарь ударений, паузы и разметка SSML</dd>
    <dt>Ударения в омографах</dt><dd>Claude — по контексту, для всех 310 неоднозначных слов книги</dd>
    <dt>Сборка аудиокниги</dt><dd>Claude; <a href="https://ffmpeg.org">FFmpeg</a> для MP3, оглавление — теги ID3 (CHAP)</dd>
    <dt>Слушать и скачать</dt><dd><a href="audio.html">Аудиокнига</a></dd>
  </dl>

  <h2>Сайт</h2>
  <dl>
    <dt>Вёрстка и генератор</dt><dd>Claude в <a href="https://claude.com/claude-code">Claude Code</a>,
      на <a href="https://www.python.org">Python</a> и <a href="https://python-pillow.org">Pillow</a></dd>
    <dt>Шрифты</dt><dd><a href="https://fonts.google.com/specimen/PT+Serif">PT Serif</a> и
      <a href="https://fonts.google.com/specimen/PT+Mono">PT Mono</a> — ParaType; раздаются с этого сайта
      (<a href="fonts/OFL-ptserif.txt">лицензия</a>), посетители не обращаются к Google</dd>
    <dt>Исходный код</dt><dd><a href="%%REPO_URL%%">GitHub</a> — инструменты сборки сайта и озвучки,
      синопсис и библии; без текста романа и аудио</dd>
    <dt>Поддержать</dt><dd><a href="%%DONATE_URL%%">Ko-fi</a> — сайт бесплатный и без рекламы</dd>
  </dl>

  <h2>Права и лицензии</h2>
  <dl>
    <dt>Текст романа</dt><dd>© %%YEAR%% %%AUTHOR%%. Права Anthropic на результаты работы Claude переданы автору
      (<a href="https://www.anthropic.com/legal/consumer-terms">условия Anthropic</a>, раздел 4).</dd>
    <dt>Иллюстрации</dt><dd>Google не претендует на права на созданные изображения
      (<a href="https://policies.google.com/terms">Условия использования Google</a>).
      Файлы содержат невидимую метку SynthID и метаданные C2PA о происхождении.</dd>
    <dt>Аудиоверсия</dt><dd>Синтезирована моделью Silero (<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.ru">CC BY-NC-SA 4.0</a>):
      распространяется бесплатно и только для некоммерческого использования.</dd>
    <dt>Шрифты</dt><dd>PT Serif, PT Mono — <a href="https://openfontlicense.org">SIL Open Font License 1.1</a></dd>
    <dt>Инструменты</dt><dd>Gogolium — MIT; PyTorch — BSD; FFmpeg — LGPL; Python — PSF; Pillow — MIT-CMU.
      На результаты (текст, аудио, сайт) их лицензии не распространяются.</dd>
  </dl>

  <p class="note">Все персонажи, организации и события вымышлены. Любое сходство с реальными
    людьми и организациями случайно.<br>
    Текст романа © %%YEAR%% %%AUTHOR%%. Все права защищены.
    Аудиоверсия — только для некоммерческого использования.</p>
</main>
</body>
</html>
"""


def render_about():
    base_css = TEMPLATE[TEMPLATE.index(":root{"):TEMPLATE.index("/* прогресс")]
    page = ABOUT_TEMPLATE.replace("%%BASE_CSS%%", base_css).replace("%%FONTS%%", fonts_html())
    for k, v in {"TITLE": TITLE, "AUTHOR": AUTHOR, "EDITOR_URL": EDITOR_DISCUSSION_URL,
                 "REPO_URL": REPO_URL, "DONATE_URL": DONATE_URL,
                 "YEAR": str(time.localtime().tm_year)}.items():
        page = page.replace(f"%%{k}%%", html.escape(v))
    ABOUT.write_text(page, encoding="utf-8")


SUB_TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%PAGE%% — %%TITLE%%</title>
<meta name="author" content="%%AUTHOR%%">
<meta name="description" content="%%DESC%%">
%%FONTS%%
<style>
%%BASE_CSS%%
.page{max-width:48em;margin:0 auto;padding:40px 16px 80px}
.nav{display:flex;gap:18px;flex-wrap:wrap;font-size:15px}
.nav a{color:var(--muted);text-decoration:none;border-bottom:1px solid var(--rule)}
.nav a:hover{color:var(--ink)}
h1{font-size:clamp(30px,5.5vw,48px);line-height:1.1;margin:28px 0 8px}
.lead{color:var(--muted);font-style:italic;margin:0 0 30px}
a{color:var(--accent)}
.md h1{font-size:30px;margin:44px 0 10px}
.md h2{font-size:24px;margin:40px 0 10px}
.md h3{font-size:20px;margin:30px 0 8px}
.md h4{font-size:18px;margin:24px 0 6px}
.md table{border-collapse:collapse;width:100%;font-size:16px;margin:14px 0;display:block;overflow-x:auto}
.md th,.md td{border:1px solid var(--rule);padding:6px 10px;text-align:left;vertical-align:top}
.md th{background:var(--log-bg)}
.md code{font-family:var(--mono);font-size:.9em}
.md blockquote{margin:16px 0;padding:4px 16px;border-left:3px solid var(--rule);color:var(--muted)}
.md hr{border:0;border-top:1px solid var(--rule);margin:32px 0}
.portraits{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:14px 0 22px}
.portraits figure{margin:0}
.portraits img{display:block;width:100%;aspect-ratio:1/1;object-fit:cover;object-position:top;
  border-radius:8px;box-shadow:0 2px 10px var(--shadow)}
.portraits figcaption{font-size:14px;color:var(--muted);margin-top:6px;line-height:1.35}
@media (max-width:600px){.portraits{grid-template-columns:1fr 1fr}}
.spoiler{background:var(--log-bg);border-left:3px solid var(--log-edge);padding:10px 14px;font-size:16px}
.chlist{list-style:none;padding:0;margin:0}
.chlist li{padding:14px 0;border-bottom:1px solid var(--rule)}
.chlist .t{display:flex;gap:12px;align-items:baseline;justify-content:space-between;flex-wrap:wrap}
.chlist .n{font-weight:700}
.chlist .d{color:var(--muted);font-size:14px;font-family:var(--mono)}
.chlist audio{display:block;width:100%;margin-top:8px;height:40px}
.full{border:1px solid var(--rule);border-radius:10px;padding:16px 18px;margin:0 0 30px}
.full a.btn{display:inline-block;background:var(--ink);color:var(--paper);text-decoration:none;
  padding:10px 18px;border-radius:8px;margin-top:6px}
.licence{font-size:16px;border-top:1px solid var(--rule);margin-top:40px;padding-top:16px}
.note{font-size:15px;color:var(--muted);margin-top:40px}
</style>
<script>
  try { var s = JSON.parse(localStorage.getItem("sysadmin-reader")) || {};
        if (s.theme) document.documentElement.setAttribute("data-theme", s.theme); } catch (e) {}
</script>
</head>
<body>
<main class="page">
  <nav class="nav"><a href="index.html">← К книге</a><a href="audio.html">Слушать</a><a href="about.html">О проекте</a></nav>
  <h1>%%PAGE%%</h1>
  <p class="lead">%%AUTHOR%% · «%%TITLE%%»</p>
%%BODY%%
  <p class="note">%%DONATE%%</p>
</main>
%%SCRIPT%%
</body>
</html>
"""


def write_subpage(path, page_title, body, desc, script=""):
    base_css = TEMPLATE[TEMPLATE.index(":root{"):TEMPLATE.index("/* прогресс")]
    out = (SUB_TEMPLATE.replace("%%BASE_CSS%%", base_css).replace("%%FONTS%%", fonts_html())
           .replace("%%SCRIPT%%", script).replace("%%BODY%%", body).replace("%%DONATE%%", DONATE_LINE))
    for k, v in {"PAGE": page_title, "TITLE": TITLE, "AUTHOR": AUTHOR, "DESC": desc}.items():
        out = out.replace(f"%%{k}%%", html.escape(v))
    path.write_text(out, encoding="utf-8")


AUDIO_SCRIPT = """<script>
(function(){
  // одна глава за раз; по окончании включается следующая
  var players = Array.prototype.slice.call(document.querySelectorAll('audio'));
  players.forEach(function(a, i){
    a.addEventListener('play', function(){ players.forEach(function(b){ if (b !== a) b.pause(); }); });
    a.addEventListener('ended', function(){
      var next = players[i + 1];
      if (next){ next.closest('li').scrollIntoView({behavior:'smooth', block:'center'}); next.play(); }
    });
  });
})();
</script>"""


def mp3_minutes(path):
    """Длительность MP3 (CBR) по размеру и битрейту первого кадра — без внешних программ."""
    data = path.read_bytes()[:20000]
    s = data[6:10]
    pos = 10 + ((s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3]) if data[:3] == b"ID3" else 0
    if pos > len(data) - 4:   # длинный тег (оглавление) — дочитать начало аудио
        data = path.read_bytes()[:pos + 20000]
    pos = data.find(b"\xff", pos)
    while pos >= 0 and (data[pos + 1] & 0xE0) != 0xE0:
        pos = data.find(b"\xff", pos + 1)
    if pos < 0:
        return None
    h = int.from_bytes(data[pos:pos + 4], "big")
    mpeg1 = (h >> 19) & 3 == 3
    table = ([0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320] if mpeg1
             else [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160])
    kbps = table[(h >> 12) & 15]
    return round(path.stat().st_size * 8 / (kbps * 1000) / 60) if kbps else None


def render_audio(chapters):
    """Отдельная страница аудиоверсии: полная книга, главы с плеерами, лицензия."""
    page = ROOT / "site" / "audio.html"
    if not FULL_AUDIO.exists():
        if page.exists():
            page.unlink()
        return 0
    mb = FULL_AUDIO.stat().st_size / 2 ** 20
    hours = (mp3_minutes(FULL_AUDIO) or 0) / 60
    name = html.escape(f"{AUTHOR} — {TITLE}.mp3")
    items = []
    for ch in chapters:
        f = AUDIO_DIR / f"{ch['num']:02d}.mp3"
        if not f.exists():
            continue
        v = int(f.stat().st_mtime)
        mins = mp3_minutes(f)
        items.append(
            f'<li><div class="t"><span><span class="n">Глава {ch["num"]}</span> — {inline(ch["teaser"])}</span>'
            f'<span class="d">{mins} мин</span></div>'
            f'<audio controls preload="none" src="audio/{f.name}?v={v}" '
            f'aria-label="Глава {ch["num"]}"></audio></li>')
    body = f"""
  <div class="full">
    <p style="margin:0">Вся книга одним файлом: {len(items)} глав, около {hours:.0f} часов, MP3 {mb:.0f} МБ,
      с оглавлением по главам (видно в плеерах, которые понимают главы).</p>
    <a class="btn" href="audio/{FULL_AUDIO.name}?v={int(FULL_AUDIO.stat().st_mtime)}" download="{name}">Скачать аудиокнигу</a>
  </div>
  <ol class="chlist">{''.join(items)}</ol>
  <div class="licence">
    <p><b>Лицензия аудиоверсии.</b> Озвучено синтезатором речи
      <a href="https://github.com/snakers4/silero-models">Silero TTS</a> (модель <code>v4_ru</code>, голос eugene,
      © <a href="https://silero.ai">Silero Team</a>), модели которого распространяются по лицензии
      <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.ru">CC BY-NC-SA 4.0</a>.</p>
    <p>Аудиоверсию можно бесплатно слушать, скачивать и делиться ею в некоммерческих целях с указанием автора
      и ссылкой на эту страницу. Продавать её, выкладывать на платные площадки или сопровождать рекламой нельзя.
      Текст романа © {html.escape(AUTHOR)}, все права защищены.</p>
    <p>Подготовка текста и ударения — <a href="https://github.com/Sorbiers/gogolium">Gogolium</a> и Claude.
      Подробнее — <a href="about.html">О проекте</a>.</p>
  </div>"""
    write_subpage(page, "Аудиокнига", body, f"Аудиоверсия романа «{TITLE}»: главы и полная книга в MP3.",
                  AUDIO_SCRIPT)
    return len(items)


PORTRAITS_SRC = ROOT / "portraits"
PORTRAITS_OUT = ROOT / "site" / "portraits"


def add_portraits(body_html):
    """Вставляет галереи портретов из portraits/portraits.json под заголовки персонажей."""
    cfg = PORTRAITS_SRC / "portraits.json"
    if not cfg.exists():
        return body_html
    conf = {k: v for k, v in json.loads(cfg.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    PORTRAITS_OUT.mkdir(parents=True, exist_ok=True)
    used = set()

    def gallery(items):
        figs = []
        for fname, caption in items:
            src = PORTRAITS_SRC / fname
            if not src.exists():
                print(f"Портрет не найден: {src}")
                continue
            name = publish_image(src, PORTRAITS_OUT, Path(fname).stem)
            used.add(name)
            cap = html.escape(caption)
            figs.append(f'<figure><a href="portraits/{name}"><img src="portraits/{name}" alt="{cap}" '
                        f'loading="lazy" decoding="async"></a><figcaption>{cap}</figcaption></figure>')
        return f'<div class="portraits">{"".join(figs)}</div>' if figs else ""

    def place(m):
        title = re.sub(r"<[^>]+>", "", m.group(2)).replace("́", "")
        for key, items in conf.items():
            if title.startswith(key):
                return m.group(0) + gallery(items)
        return m.group(0)

    body_html = re.sub(r"(<h[23][^>]*>)(.*?)</h[23]>", place, body_html)
    for old in PORTRAITS_OUT.iterdir():
        if old.name not in used:
            old.unlink()
    return body_html


def render_docs():
    """Синопсис и библии -> отдельные страницы (нужен пакет markdown)."""
    try:
        import markdown
    except ImportError:
        print("Пакет markdown не установлен — страницы синопсиса и библий пропущены (pip install markdown)")
        return []
    made = []
    for src, (out, title) in DOCS.items():
        p = ROOT / src
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        text = re.sub(r"\A#\s+.*\n", "", text)          # свой заголовок страницы
        body_md = markdown.markdown(text, extensions=["tables", "sane_lists"])
        if src == "characters.md":
            body_md = add_portraits(body_md)
        kind = "Синопсис раскрывает" if src == "synopsis.md" else "Рабочий материал автора: раскрывает"
        body = (f'  <p class="spoiler">{kind} весь сюжет, включая финал. '
                'Если вы ещё не читали роман — сначала <a href="index.html">книга</a>.</p>\n'
                f'  <div class="md">{body_md}</div>')
        write_subpage(ROOT / "site" / out, title, body, f"{title} романа «{TITLE}» — рабочий материал автора.")
        made.append(out)
    return made


def main():
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    files = sorted(CHAPTERS.glob("*.md"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    chapters = [parse_chapter(p) for p in files]
    chapters.sort(key=lambda c: c["num"])
    OUT.parent.mkdir(exist_ok=True)
    nums = [c["num"] for c in chapters]
    images = find_illustrations(nums)
    captions = load_captions()
    OUT.write_text(render(chapters, images, captions), encoding="utf-8")
    render_about()
    publish_fonts()
    n_audio = render_audio(chapters)
    docs = render_docs()
    words = sum(c["minutes"] for c in chapters) * 180
    print(f"Собрано: {OUT}  ({len(chapters)} глав, ~{words} слов)")
    print(f"Иллюстраций: {len(images)} из {len(nums) * 2}"
          + ("" if ILLU_SRC.exists() else f"  (папки {ILLU_SRC.name} нет)"))
    print(f"Аудиостраница: {n_audio} глав" if n_audio else "Аудиостраницы нет (нет полной аудиокниги)")
    print(f"Справочные страницы: {', '.join(docs) or 'нет'}")


if __name__ == "__main__":
    main()
