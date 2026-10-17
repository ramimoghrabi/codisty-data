#!/usr/bin/env python3
"""Builds Lamp's study packs (downloaded on demand, Pro).

    python3 -I Tools/data/build_study.py STUDY_DIR OUT_DIR

  words-nt.json.z  {"b.c.v": [[original, transliteration, gloss, strong], …]}
      STEPBible TAGNT (CC BY 4.0, STEPBible.org) — the New Testament's Greek, word by word
  lexicon.json.z   {strong: [lemma, transliteration, gloss, short definition]}  (TBESG, CC BY)

Greek only: by the owner's decision the app carries no Hebrew.
  xrefs.json.z     {"b.c.v": ["b.c.v" | "b.c.v-b.c.v", …]}  OpenBible.info cross-references (CC BY), best first
  henry.json.z     {"b.c": [[from, to, text], …]}  Matthew Henry's Concise Commentary (public domain; CC0 edition)

Keys: b = book index 0-65, c and v start at 1, English (KJV) versification.
"""
import html, json, os, re, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from books import BOOKS

SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)

STEP = "Gen Exo Lev Num Deu Jos Jdg Rut 1Sa 2Sa 1Ki 2Ki 1Ch 2Ch Ezr Neh Est Job Psa Pro Ecc Sng Isa Jer Lam Ezk Dan Hos Jol Amo Oba Jon Mic Nam Hab Zep Hag Zec Mal Mat Mrk Luk Jhn Act Rom 1Co 2Co Gal Eph Php Col 1Th 2Th 1Ti 2Ti Tit Phm Heb Jas 1Pe 2Pe 1Jn 2Jn 3Jn Jud Rev".split()
OSIS = "Gen Exod Lev Num Deut Josh Judg Ruth 1Sam 2Sam 1Kgs 2Kgs 1Chr 2Chr Ezra Neh Esth Job Ps Prov Eccl Song Isa Jer Lam Ezek Dan Hos Joel Amos Obad Jonah Mic Nah Hab Zeph Hag Zech Mal Matt Mark Luke John Acts Rom 1Cor 2Cor Gal Eph Phil Col 1Thess 2Thess 1Tim 2Tim Titus Phlm Heb Jas 1Pet 2Pet 1John 2John 3John Jude Rev".split()
assert len(STEP) == 66 and len(OSIS) == 66
SI = {c: i for i, c in enumerate(STEP)}
OI = {c: i for i, c in enumerate(OSIS)}


def write(name, obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    z = co.compress(raw) + co.flush()
    open(os.path.join(OUT, name), "wb").write(z)
    print(f"{name}: {len(obj)} keys, {len(raw) // 1024} KB raw, {len(z) // 1024} KB compressed")


def words(files):
    out = {}
    for f in files:
        for line in open(os.path.join(SRC, f), encoding="utf-8"):
            m = re.match(r"^([1-3A-Z][a-zA-Z0-9]{2})\.(\d+)\.(\d+)[^#\t]*#\d+=\w+\t", line)
            if not m or m.group(1) not in SI:
                continue
            cols = line.rstrip("\n").split("\t")
            key = f"{SI[m.group(1)]}.{int(m.group(2))}.{int(m.group(3))}"
            if f.startswith("TAGNT"):
                # "οὕτως (houtōs)"  gloss  "G3779=ADV"
                mm = re.match(r"^(.*?)\s*\((.*?)\)\s*$", cols[1])
                orig, tr = (mm.group(1), mm.group(2)) if mm else (cols[1], "")
                gloss, strong = cols[2], cols[3].split("=")[0]
            else:
                # Hebrew with "/" between parts, transliteration, gloss, "H9003/{H7225G}"
                orig, tr, gloss = cols[1].replace("/", ""), cols[2].replace("/", "").replace(".", ""), cols[3]
                braces = re.findall(r"\{(H\d+[A-Z]?)\}", cols[4])
                strong = braces[0] if braces else cols[4].split("/")[-1]
            gloss = re.sub(r"\s+", " ", gloss.replace("<", "").replace(">", "").replace("/", " ")).strip()
            out.setdefault(key, []).append([orig.strip(), tr.strip(), gloss, strong.strip()])
    return out


def lexicon():
    out = {}
    for f in ("TBESG_-.txt",):
        for line in open(os.path.join(SRC, f), encoding="utf-8"):
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 8 or not re.match(r"^[GH]\d{4}[A-Z]?$", cols[0]):
                continue
            d = re.sub(r"<ref='[^']*'>([^<]*)</ref>", r"\1", cols[7])
            d = re.sub(r"<BR\s*/?>", " ", d, flags=re.I)
            d = re.sub(r"<[^>]+>", "", d)
            d = html.unescape(re.sub(r"\s+", " ", d)).replace("__", "")
            # No Hebrew anywhere (owner's decision): drop the "[in LXX chiefly for …;]" notes and any stray Hebrew letters.
            d = re.sub(r"\[in LXX[^\]]*\]\s*", "", d)
            d = re.sub(r"[\u0590-\u05FF\uFB1D-\uFB4F]+", "", d)
            d = re.sub(r"\(\s*[,;]?\s*\)|\[\s*[,;]?\s*\]", "", d)
            d = re.sub(r"\s+([,;.])", r"\1", re.sub(r"\s+", " ", d)).strip()
            if len(d) > 700:
                d = d[:700].rsplit(" ", 1)[0] + "…"
            entry = [cols[3], cols[4], cols[6], d]
            key = cols[1].split("=")[0].strip()          # the extended number, e.g. H0430G
            if re.match(r"^[GH]\d{4}[A-Z]?$", key):
                out.setdefault(key, entry)
            out.setdefault(cols[0], entry)                # and the plain one
    return out


def ref(s):
    m = re.match(r"^(\w+)\.(\d+)\.(\d+)$", s)
    if not m or m.group(1) not in OI:
        return None
    return f"{OI[m.group(1)]}.{int(m.group(2))}.{int(m.group(3))}"


def xrefs():
    rows = {}
    for line in open(os.path.join(SRC, "cross_references.txt"), encoding="utf-8"):
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 3 or not cols[2].lstrip("-").isdigit():
            continue
        votes = int(cols[2])
        if votes < 3:
            continue
        frm = ref(cols[0])
        parts = cols[1].split("-")
        a = ref(parts[0])
        b = ref(parts[1]) if len(parts) > 1 else None
        if not frm or not a:
            continue
        rows.setdefault(frm, []).append((votes, a + ("-" + b if b else "")))
    return {k: [t for _, t in sorted(v, key=lambda x: -x[0])[:12]] for k, v in rows.items()}


def henry():
    out = {}
    slug = lambda name: name.lower().replace(" ", "-").replace("song-of-songs", "song-of-solomon")
    for i, (_, name, _, _) in enumerate(BOOKS):
        d = os.path.join(SRC, "mhc", slug(name))
        if not os.path.isdir(d):
            print("missing commentary for", name)
            continue
        for f in os.listdir(d):
            m = re.match(r"chapter-(\d+)\.md$", f)
            if not m:
                continue
            text = open(os.path.join(d, f), encoding="utf-8").read()
            secs = []
            for mm in re.finditer(r"^## Verses? (\d+)(?:\s*[–-]\s*(\d+))?\s*\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S):
                a = int(mm.group(1)); b = int(mm.group(2) or a)
                body = re.sub(r"\s+", " ", mm.group(3)).strip()
                if body:
                    secs.append([a, b, body])
            if secs:
                out[f"{i}.{int(m.group(1))}"] = sorted(secs)
    return out


write("words-nt.json.z", words(["TAGNT_Mat-Jhn.txt", "TAGNT_Act-Rev.txt"]))
write("lexicon.json.z", lexicon())
write("xrefs.json.z", xrefs())
write("henry.json.z", henry())
