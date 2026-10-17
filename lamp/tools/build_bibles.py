#!/usr/bin/env python3
"""Builds Lamp's Bible files from public-domain sources.

    python3 -I Tools/data/build_bibles.py SRC_DIR OUT_DIR

SRC_DIR holds the downloads: sm/<ID>.json (scrollmapper/bible_databases),
ebx/<id>/<id>_vpl.txt (eBible.org VPL) and usfm/<id>/*.usfm (eBible.org
https://ebible.org/Scriptures/<id>_usfm.zip, each unzipped into its own folder).
Writes OUT_DIR/<id>.json.z (raw DEFLATE, which Foundation reads with
NSData.decompressed(using: .zlib)) and OUT_DIR/bibles.json, the catalogue the app reads.

App format: {"id", "abbr", "name", "lang", "rtl", "license", "names": [66 book names],
"books": [[[verse, …] chapter, …] book, …], "paras"?, "heads"?} — verses by position
(verse n at index n-1, "" if absent). The two optional keys carry the layout:

  "paras": {"b.c": [1, 5, 9, …]}   verses that start a paragraph, ascending, always with 1.
                                   b = book index 0–65 (BOOKS order), c from 1.
  "heads": {"b.c.v": "Heading"}    section heading (USFM \\s, \\s1, \\s2…) printed before
                                   verse v; stacked headings are joined with "\\n".

Both come from the translation's own eBible USFM (USFM column below) when its paragraphing is
real and the chapter's verse count matches the text. A paragraph starts at verse v when \\p, \\m,
\\pi…, \\mi, \\pmo, \\b (stanza break), a heading, or the first poetry line after prose comes between
the previous verse's text and \\v v; breaks that fall mid-verse are dropped (\\nb is never a break).
\\ms, \\mr, \\r, \\d, \\sp, \\qa and \\qc are breaks, not headings. Translations whose USFM has no
paragraphing (only one \\p per chapter, or one per verse) borrow "paras" — never "heads" — from
DONORS (WEB, else BSB), chapter by chapter, wherever the verse counts agree; chapters with no usable
source are left out, and the app falls back to its own sentence-sized paragraphs there. Headings
containing Hebrew script are dropped.
"""
import collections, json, os, re, sys, zlib, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from books import BOOKS, NAMES

SRC, OUT = sys.argv[1], sys.argv[2]
CODES = [b[0] for b in BOOKS]
EN = [b[1] for b in BOOKS]
# USFM \id codes in BOOKS order; eleven differ from the VPL codes (SNG/SOL, EZK/EZE, JOL/JOE, NAM/NAH,
# MRK/MAR, JHN/JOH, PHP/PHI, JAS/JAM, 1JN/1JO, 2JN/2JO, 3JN/3JO).
USFM = ("GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM "
        "EZK DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL "
        "1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV").split()
assert len(USFM) == 66 and len(set(USFM)) == 66
assert sum(u == c for u, c in zip(USFM, CODES)) == 55

TRANSLATIONS = [
    # id, abbr, name, lang, text source, license, eBible USFM id for paragraphs/headings (None: none on eBible)
    ("bsb", "BSB", "Berean Standard Bible", "en", ("sm", "BSB"), "Public domain (dedicated 2023). Berean Bible, bereanbible.com", "engbsb"),
    ("kjv", "KJV", "King James Version", "en", ("sm", "KJV"), "Public domain", "eng-kjv2006"),
    ("web", "WEB", "World English Bible", "en", ("eb", "engwebp"), "Public domain. World English Bible, ebible.org", "engwebp"),
    ("asv", "ASV", "American Standard Version", "en", ("sm", "ASV"), "Public domain", "eng-asv"),
    ("ylt", "YLT", "Young's Literal Translation", "en", ("sm", "YLT"), "Public domain", "engylt"),
    ("svd", "SVD", "الكتاب المقدس – ترجمة فان دايك", "ar", ("eb", "arb-vd"), "Public domain. Smith & Van Dyck, via ebible.org", "arb-vd"),
    ("rv1909", "RVA", "Reina-Valera 1909", "es", ("sm", "SpaRV"), "Public domain", "spaRV1909"),
    ("lsg", "LSG", "Louis Segond 1910", "fr", ("eb", "fraLSG"), "Public domain, via ebible.org", "fraLSG"),
    ("lut1912", "LUT", "Lutherbibel 1912", "de", ("eb", "deu1912"), "Public domain, via ebible.org", "deu1912"),
    ("blivre", "BLIVRE", "Bíblia Livre", "pt", ("eb", "porbr2018"), "Bíblia Livre © 2018 Diego Santos, Mario Sérgio e Marco Teles, CC BY 4.0, via ebible.org", "porbr2018"),
    ("synodal", "СИН", "Синодальный перевод", "ru", ("eb", "russyn"), "Public domain, via ebible.org", "russyn"),
    ("cuv", "CUV", "和合本 (简体)", "zh", ("eb", "cmn-cu89s"), "Public domain, via ebible.org", "cmn-cu89s"),
    ("kor1910", "KOR", "성경 (1910)", "ko", ("eb", "kor"), "Public domain, via ebible.org", "kor"),
    ("vie1934", "VI1934", "Kinh Thánh (1934)", "vi", ("eb", "vie1934"), "Public domain, via ebible.org", "vie1934"),
    ("adb1905", "ADB", "Ang Dating Biblia (1905)", "tl", ("sm", "TagAngBiblia"), "Public domain", None),
]
DONORS = ("engwebp", "engbsb")    # paragraphing lent, chapter by chapter, to translations without any
NO_HEADS = {"kjv", "asv", "ylt"}  # traditionally printed without section headings

TAG = re.compile(r"<[^>]+>|\\[a-z]+\*?|¶\s*")


def clean(t):
    t = TAG.sub("", t or "")
    return re.sub(r"\s+", " ", t).strip()


def from_scrollmapper(name):
    d = json.load(open(os.path.join(SRC, "sm", f"{name}.json"), encoding="utf-8"))
    assert len(d["books"]) == 66, (name, len(d["books"]))
    books = []
    for b in d["books"]:
        chapters = []
        for ch in b["chapters"]:
            vs = ch["verses"]
            n = max((v["verse"] for v in vs), default=0)
            arr = [""] * n
            for v in vs:
                arr[v["verse"] - 1] = clean(v["text"])
            chapters.append(arr)
        books.append(chapters)
    return books


def from_ebible(eid):
    path = os.path.join(SRC, "ebx", eid, f"{eid}_vpl.txt")
    data = {}
    for line in open(path, encoding="utf-8-sig"):
        m = re.match(r"^(\w{3}) (\d+):(\d+) ?(.*)$", line.rstrip("\n"))
        if not m:
            continue
        code, c, v, text = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        if code not in CODES:
            continue
        data.setdefault(code, {}).setdefault(c, {})[v] = clean(text)
    books = []
    for code in CODES:
        chs = data.get(code, {})
        n = max(chs) if chs else 0
        chapters = []
        for c in range(1, n + 1):
            vs = chs.get(c, {})
            m = max(vs) if vs else 0
            chapters.append([vs.get(i, "") for i in range(1, m + 1)])
        books.append(chapters)
    return books


# --- Paragraphs and headings from USFM -------------------------------------------------------

NOTE = re.compile(r"\\(f|fe|ef|x|ex)\s.*?\\\1\*", re.S)          # footnotes, cross references
MARK = re.compile(r"\\(\+?[a-z]+[0-9]*)(\*?)")
BREAK = re.compile(r"(p|m|pi[0-9]?|mi|pc|pmo|pm|ph[0-9]?|pr|cls)$")  # prose paragraph starts
POETRY = re.compile(r"(q[0-9]?|qr|qm[0-9]?|qd|li[0-9]?|lim[0-9]?)$")
HEAD = re.compile(r"s[0-9]?$")
LINE = re.compile(r"(id|ide|h[0-9]?|toc[0-9a]*|mte?[0-9]?|ms[0-9]?|mr|r|sr|d|sp|cl|cp|cd|rem|sts|qa|qc|s[0-9]?|"
                  r"imte?[0-9]?|is[0-9]?|ip|ipi|im|imi|ipq|imq|ipr|iq[0-9]?|ib|ili[0-9]?|io[0-9]?|ior|iot|iex|ie|"
                  r"usfm|restore|periph)$")                         # markers whose text runs to end of line
HEBREW = re.compile("[\u0590-\u05ff\ufb1d-\ufb4f]")
VNUM = re.compile(r"\s+(\d+)[a-z]?(?:-\d+[a-z]?)?\s?")
CNUM = re.compile(r"\s+(\d+)")


def heading_text(s):
    s = re.sub(r"\\\+?w\s+([^|\\]*)(?:\|[^\\]*)?\\\+?w\*", r"\1", s)   # \w word|strong="…"\w*
    s = MARK.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_usfm_book(text):
    """One book → (paragraph starts {c: {v}}, headings {c: {v: text}}, last verse {c: n})."""
    text = NOTE.sub(" ", text)
    paras, heads, last = collections.defaultdict(set), collections.defaultdict(dict), collections.defaultdict(int)
    c = v = 0
    pend = False       # a break marker since the last verse text
    waiting = []       # headings waiting for the next verse
    poetry = False
    pos, skip_to = 0, -1
    for m in MARK.finditer(text):
        if m.start() < skip_to:
            continue
        if v and text[pos:m.start()].strip():
            pend = False                     # text after the marker: the break fell mid-verse
        tag, closing = m.group(1), m.group(2)
        pos = m.end()
        if closing or tag.startswith("+"):
            continue
        if tag == "c":
            n = CNUM.match(text, pos)
            if n:
                c, v, pos, pend = int(n.group(1)), 0, n.end(), True
        elif tag == "v":
            n = VNUM.match(text, pos)
            if not n or not c:
                continue
            v, pos = int(n.group(1)), n.end()
            last[c] = max(last[c], v)
            if pend or v == 1:
                paras[c].add(v)
            if waiting:
                heads[c][v] = "\n".join(waiting)
            pend, waiting = False, []
        elif LINE.match(tag):
            eol = text.find("\n", pos)
            eol = len(text) if eol < 0 else eol
            body = text[pos:eol]
            if re.search(r"\\v\s", body):    # "\d \v 1 …": the line carries verse text
                continue
            skip_to = pos = eol
            if c and HEAD.match(tag):
                h = heading_text(body)
                if h and not HEBREW.search(h):
                    waiting.append(h)
                pend = True
            elif c and tag in ("ms", "ms1", "ms2", "mr", "d", "sp", "qa", "qc"):  # qc: ASV acrostic letters
                pend = True
        elif tag == "b":
            pend = True
        elif BREAK.match(tag):
            pend, poetry = True, False
        elif POETRY.match(tag):
            pend, poetry = pend or not poetry, True   # only the first poetry line after prose
        # \nb and character markers change nothing
    return paras, heads, last


_markup = {}


def markup(eid):
    """SRC/usfm/<eid>/*.usfm → {book index: parse_usfm_book(…)}; None when not downloaded."""
    if eid not in _markup:
        d = os.path.join(SRC, "usfm", eid or "")
        found = None
        if eid and os.path.isdir(d):
            found = {}
            for f in sorted(os.listdir(d)):
                if f.lower().endswith((".usfm", ".sfm")):
                    t = open(os.path.join(d, f), encoding="utf-8-sig").read()
                    m = re.match(r"\s*\\id\s+(\w{3})", t)
                    if m and m.group(1) in USFM:
                        found[USFM.index(m.group(1))] = parse_usfm_book(t)
        _markup[eid] = found or None
    return _markup[eid]


def has_paragraphs(mk):
    """False when the USFM only has one paragraph per chapter, or one per verse."""
    starts = sum(len(s) for p, _, _ in mk.values() for s in p.values())
    chapters = sum(len(n) for _, _, n in mk.values())
    verses = sum(sum(n.values()) for _, _, n in mk.values())
    return 0.02 <= (starts - chapters) / max(1, verses - chapters) <= 0.75


def layout(tid, eid, books):
    """→ (paras, heads, note) for the document; see the module docstring."""
    own = markup(eid)
    own_p = own if own and has_paragraphs(own) else None
    own_h = own if own and tid not in NO_HEADS else None
    sources = [(eid, own_p)] + [(d, markup(d)) for d in DONORS if d != eid]
    paras, heads, used = {}, {}, collections.Counter()

    def fits(mk, b, c, n):
        return mk is not None and b in mk and mk[b][2].get(c) == n

    for b, chapters in enumerate(books):
        for c, verses in enumerate(chapters, 1):
            n = len(verses)

            def present(v):  # the first verse from v on that this translation has
                while v <= n and not verses[v - 1]:
                    v += 1
                return v if v <= n else None

            src = next(((d, mk) for d, mk in sources if fits(mk, b, c, n)), (None, None))
            used[src[0]] += 1
            if src[1]:
                starts = src[1][b][0].get(c, set())
                paras[f"{b}.{c}"] = sorted({1} | {p for p in map(present, starts) if p})
            if fits(own_h, b, c, n):
                for v, h in sorted(own_h[b][1].get(c, {}).items()):
                    p = present(v)
                    if p:
                        k = f"{b}.{c}.{p}"
                        heads[k] = heads[k] + "\n" + h if k in heads else h
    if own_p:
        note = f"own USFM {eid}"
    elif own:
        note = f"{eid} USFM has no paragraphing; paras borrowed"
    else:
        note = "no USFM on eBible; paras borrowed"
    note += " (" + ", ".join(f"{d or 'none'}: {k} ch" for d, k in used.most_common()) + ")"
    return paras, heads, note


def deflate(doc):
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return co.compress(raw) + co.flush()


def main():
    os.makedirs(OUT, exist_ok=True)
    catalogue = []
    for tid, abbr, name, lang, (kind, src), lic, eid in TRANSLATIONS:
        books = from_scrollmapper(src) if kind == "sm" else from_ebible(src)
        verses = sum(len(c) for b in books for c in b)
        empty = sum(1 for b in books for c in b for v in c if not v)
        names = EN if lang == "en" else NAMES[lang]
        doc = {"id": tid, "abbr": abbr, "name": name, "lang": lang, "rtl": lang == "ar", "license": lic,
               "names": names, "books": books}
        plain = len(deflate(doc))
        paras, heads, note = layout(tid, eid, books)
        if paras:
            doc["paras"] = paras
        if heads:
            doc["heads"] = heads
        z = deflate(doc)
        open(os.path.join(OUT, f"{tid}.json.z"), "wb").write(z)
        catalogue.append({"id": tid, "abbr": abbr, "name": name, "lang": lang, "rtl": lang == "ar", "license": lic,
                          "bytes": len(z), "sha": hashlib.sha256(z).hexdigest()[:16], "version": 1})
        starts = sum(len(p) for p in paras.values())
        print(f"{abbr:7} {lang} {len(books)} books {sum(len(b) for b in books)} ch {verses} verses ({empty} empty) "
              f"{len(z) // 1024} KB (+{100 * (len(z) - plain) / plain:.1f}%) · {starts} paragraph starts in "
              f"{len(paras)} ch, {len(heads)} headings · {note}")
    json.dump({"version": 1, "translations": catalogue}, open(os.path.join(OUT, "bibles.json"), "w"), ensure_ascii=False, indent=1)


main()
