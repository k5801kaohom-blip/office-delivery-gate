---
name: office-delivery-gate
description: 觸發詞：交付前檢查、交付前確認、檔案驗證、確認檔案能開、PPTX 驗證、交付把關、檔案完整性、檢查簡報、把關 Office 檔案。Validate and repair OOXML files (PPTX, DOCX, XLSX) before delivering them, and diagnose Office files that will not open. Use whenever you generate or edit an Office file programmatically, whenever you are about to deliver or attach a .pptx/.docx/.xlsx, and whenever a user reports a file that Microsoft Office calls corrupt, shows a repair prompt, cannot open, or opens with missing content. Covers the duplicate a:latin trap that produced unopenable decks, content-preservation checks, and the four-step validate/repair/re-validate/confirm procedure.
metadata:
  alias_zh-TW: Office 交付前檢查
  short_alias_zh-TW: 交付檢查
  keywords_zh-TW: 交付檢查、Office 交付前檢查、交付前檢查、交付前確認、檔案驗證、確認檔案能開、PPTX 驗證、交付把關、檔案完整性、檢查簡報、把關 Office 檔案
---

# Office Delivery Gate

Programmatically generated Office files can be structurally invalid while still rendering
perfectly in LibreOffice, Google Slides, or a PDF conversion. Microsoft Office validates
strictly and rejects them. A visual check cannot detect this.

This skill exists because that gap has caused real damage: a deck was inspected page by page,
rendered correctly, and was still refused by the user's PowerPoint. The defect was a single
duplicated XML element.

**The rule:** an Office file is not delivery-ready until a schema-level check has passed.
Rendering, page count, and "it opened in LibreOffice" are not evidence of validity.

## When to use

- Before delivering, attaching, or uploading ANY `.pptx`, `.docx`, or `.xlsx` you produced
  with code (python-pptx, openpyxl, lxml, template surgery, a generation skill).
- Before delivering a deck produced by the `screenshot-to-comic-slides` skill, or any deck
  built by adding text boxes, fonts, or headings to generated slides.
- Whenever a user says a file will not open, shows a repair prompt, looks corrupt, or opens
  with content missing.
- Whenever you edited an Office file's XML directly.

Do not skip this because the file looks fine. That is precisely the failure mode.

## The four-step procedure

Run the gate. It performs all four steps and refuses to clear a file that does not survive
all of them:

```bash
python scripts/delivery_gate.py deck.pptx
python scripts/delivery_gate.py output/ --repair --json gate_report.json
```

| Step | What happens | Why it is separate |
| --- | --- | --- |
| 1. Validate | Ten structural checks run against the package | Detect the defect before touching anything |
| 2. Repair | Only when `--repair` is given and the defect is mechanical | Fixing is a decision, not a default |
| 3. Re-validate | The repaired file is checked from scratch | A repair that is itself invalid is worse than none |
| 4. Confirm content | Slide/sheet/media/text counts are compared before and after | A valid file that lost content is still a failed delivery |

Exit code `0` means safe to deliver. `1` means at least one file is blocked.
`2` is a usage or environment error.

> **Never deliver or attach a file the gate marked BLOCKED.** Fix the source, or tell the user
> what is wrong. Handing over a blocked file repeats the exact failure this skill prevents.

### Reading the result

```text
  SAFE     deck.pptx   (8 problem(s) repaired, content preserved)
  BLOCKED  other.pptx  repair changed media: 16 -> 14
```

A `SAFE` line with a repaired count is normal: the file had defects, they were mechanical,
and the content survived. Blocked files list the failing checks and the offending parts.

## Verify the gate itself before trusting it

A validator that has never failed anything proves nothing. Prove the chain works by injecting
a real defect into a copy of a known-good file and asserting the whole path behaves:

```bash
python scripts/selftest_gate.py clean_deck.pptx
```

This injects the duplicate `a:latin` defect, then asserts the validator catches it, the gate
repairs it, re-validation passes, and content is preserved. Run it after installing the skill,
after changing any script, or when you need to demonstrate the mechanism works.

## Do not trust the renderer

| Check | What it actually proves |
| --- | --- |
| Slide images look correct | Nothing about structural validity |
| LibreOffice opens the file | Nothing — LibreOffice accepts files Office rejects |
| `unzip -t` passes | Zip integrity only; XML can still be invalid |
| File size looks reasonable | Nothing about schema conformance |
| Gate reports all checks passed | **The only claim you may make about validity** |

When you tell a user a file is ready, base it on the gate result. Never say "I opened it and it
looks fine" as a validity claim.

## Highest-frequency cause: the duplicate `a:latin` trap

`python-pptx` already creates `<a:latin>` when you set a font:

```python
run.font.name = "Microsoft JhengHei"   # creates <a:latin> inside <a:rPr>
```

A helper that then appends elements for the East Asian face produces
`<a:latin/><a:latin/><a:ea/><a:cs/>`. Each of `a:latin`, `a:ea`, and `a:cs` may appear **at
most once**, in that order. PowerPoint reports the file as corrupt; LibreOffice renders it
without complaint.

Correct approach — look before inserting, so repeated calls cannot duplicate:

```python
def set_run_font(run, typeface):
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    rPr = run._r.get_or_add_rPr()
    for tag in ("latin", "ea", "cs"):
        existing = rPr.find(f"{{{A}}}{tag}")
        if existing is None:
            rPr.append(rPr.makeelement(f"{{{A}}}{tag}", {"typeface": typeface}))
        else:
            existing.set("typeface", typeface)
```

Never `append` font elements blindly, and never assume a helper is idempotent.

Read `references/failure-modes.md` for the full symptom-to-cause table, the repairable versus
source-level distinction, and manual inspection commands.

## Reporting to the user

State what was checked and what the result was. Be concrete:

- Safe: "十二個結構檢查全部通過，可以交付。" plus the file.
- Repaired: name the defect and confirm content survived. For example: 偵測到 8 處重複的
  `<a:latin>`，已修復並重新驗證通過，8 頁與 16 張圖片完整保留。
- Blocked: name the failing check, the affected parts, and what must change at the source.
  Do not deliver the file.

Never claim a file is openable based on inspection alone, and never describe a repair you did
not verify.

## Bundled resources

- `scripts/delivery_gate.py` — the four-step gate; validates, optionally repairs, re-validates,
  and confirms content. Use this as the default entry point.
- `scripts/selftest_gate.py` — injects a real defect and asserts the whole chain behaves, so you
  can prove the gate works rather than assume it.
- `references/failure-modes.md` — symptom-to-cause table, the `a:latin` trap in detail,
  repairable versus source-level defects, manual inspection commands.
- `templates/delivery_report.example.json` — shape of the consolidated `--json` report.

This skill validates and repairs; the `ooxml-integrity-check` skill holds the underlying
validator and repairer. The gate locates them automatically, or reads `OOXML_SKILL_DIR` when
they live elsewhere.