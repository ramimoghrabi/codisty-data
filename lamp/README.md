# Lamp data

Files the Lamp Bible app downloads from https://data.codisty.com/lamp/.

- `bibles.json` — the catalogue of translations (id, name, language, licence, size, checksum).
- `<id>.json.z` — one translation: raw DEFLATE JSON with book names, verses, paragraph starts (`paras`) and section headings (`heads`).
- `words-nt.json.z`, `lexicon.json.z` — Greek New Testament words and the Greek dictionary (STEPBible.org, CC BY 4.0).
- `xrefs.json.z` — cross references (OpenBible.info, CC BY).
- `henry.json.z` — Matthew Henry's Concise Commentary (public domain).

Every text is public domain or openly licensed; see each translation's `license`. No Hebrew content by design.
Rebuild with `lamp/tools/build_bibles.py` and `lamp/tools/build_study.py` (sources listed in their docstrings).
