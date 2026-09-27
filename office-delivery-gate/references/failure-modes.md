# Failure Modes Reference

Read this when the gate reports a failure, when a user says an Office file will not open,
or when deciding whether a defect is repairable or needs a source-level fix.

## Contents

1. Why visual checks are not enough
2. Symptom to cause table
3. The duplicate `a:latin` trap
4. Repairable versus source-level defects
5. Manual inspection commands

## 1. Why visual checks are not enough

LibreOffice and other tolerant parsers accept files that violate the OOXML schema.
Microsoft Office validates strictly and refuses them.

> A file that renders correctly in a screenshot can still be rejected by the person who
> opens it. Rendering is evidence of nothing about structural validity.

Never report a file as delivery-ready on the basis of a rendered image, a page count, or a
successful re-open in a tolerant viewer. Only a schema-level check supports that claim.

## 2. Symptom to cause table

| What the user sees | What is actually wrong |
| --- | --- |
| "檔案損毀，無法開啟" / repair prompt | Duplicated singleton child element, or wrong child order |
| File opens but a slide is blank | Missing relationship target, or an orphaned `r:embed` |
| Images show as red crosses | Media part corrupted, or extension does not match the bytes |
| "內容有問題" and Office removes content | Broken content-type override for a part |
| Presentation size mismatched or slides cut off | `sldSz` disagreeing with the slide layout |
| Only some slides fail | Defect is localised to specific slide parts; the rest are fine |

## 3. The duplicate `a:latin` trap

This is the highest-frequency defect produced by scripted PowerPoint generation, and it is
easy to introduce because the library adds the element for you.

`python-pptx`:

```python
run.font.name = "Microsoft JhengHei"   # already creates <a:latin> inside <a:rPr>
```

A well-meaning "also set the East Asian font" helper then appends more font elements:

```python
rPr = run._r.get_or_add_rPr()
rPr.append(rPr.makeelement(f"{{{A_NS}}}latin", {"typeface": FONT}))   # BUG: second <a:latin>
rPr.append(rPr.makeelement(f"{{{A_NS}}}ea",    {"typeface": FONT}))
rPr.append(rPr.makeelement(f"{{{A_NS}}}cs",    {"typeface": FONT}))
```

Result: `<a:latin/><a:latin/><a:ea/><a:cs/>`. Each of `a:latin`, `a:ea`, and `a:cs` may
appear **at most once**, and they must keep that order.

Correct helper — check before inserting so a repeat call cannot duplicate:

```python
def set_run_font(run, typeface):
    rPr = run._r.get_or_add_rPr()
    for tag in ("latin", "ea", "cs"):
        existing = rPr.find(f"{{{A_NS}}}{tag}")
        if existing is None:
            rPr.append(rPr.makeelement(f"{{{A_NS}}}{tag}", {"typeface": typeface}))
        else:
            existing.set("typeface", typeface)
```

Never `append` font elements blindly, and never assume a helper is idempotent.

## 4. Repairable versus source-level defects

| Repairable mechanically | Needs a source-level fix |
| --- | --- |
| Duplicated singleton children | A relationship pointing at a part that was never written |
| Wrong child element order | Wrong or invented data in a chart or table |
| `sldSz` inconsistent with the layout | A missing media file whose content is gone |
| — | Content the generator never actually emitted |

The repair script fixes only what it can determine from the file itself. Defects that would
require guessing intent are reported instead. Treat that as correct behaviour: a repaired
file that silently invents structure is worse than a blocked delivery.

## 5. Manual inspection commands

Count duplicate singletons directly:

```bash
python - <<'PY'
import re, zipfile
z = zipfile.ZipFile("deck.pptx")
for name in sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)):
    body = z.read(name).decode("utf-8")
    for rpr in re.findall(r"<a:rPr\b[^>]*>.*?</a:rPr>", body, flags=re.S):
        if rpr.count("<a:latin") > 1:
            print(f"{name}: duplicate <a:latin>")
PY
```

Confirm the package is intact at all:

```bash
unzip -t deck.pptx | tail -2
python /path/to/ooxml-integrity-check/scripts/validate_ooxml.py deck.pptx
```

Check whether a tolerant viewer is hiding the problem:

```bash
soffice --headless --convert-to pdf deck.pptx   # succeeds even on files Office rejects
```