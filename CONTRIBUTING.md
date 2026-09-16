# Contributing

> **English** · [Português](pt-br/CONTRIBUTING.md)

Corrections are welcome. This guide's value depends on being accurate, so a fix that keeps it
aligned with reality is worth more than new content.

**Language:** English is the source of truth. The Portuguese mirror in [`pt-br/`](pt-br/) may lag.
You do **not** have to update both — a Portuguese update can follow later.

---

## What is most useful

| Kind of change | Notes |
|---|---|
| **A command that no longer works** | Highest value. Include the version of the component involved |
| **A step that assumes too much** | This guide targets people comfortable with a terminal but not IT-advanced. Gaps in that assumption are bugs |
| **A fact that drifted** | Versions, flags, endpoints, file paths |
| **A security caveat that is missing** | The documents publish hostnames and run services; omissions matter |
| **Clearer wording** | Only if it shortens or removes ambiguity |
| **A new document** | Justify it — this guide deliberately stays small |

## What to avoid

- **Adding options.** Where two ways exist, the guide picks one. A pull request that adds "or you
  could also…" needs a reason.
- **Restating upstream docs.** Link instead of duplicating reference material.
- **Softening the honesty.** The documents distinguish *measured* from *estimated* and *validated*
  from *pending*. Do not turn an estimate into a claim.
- **De-personalising the case study.** Names are already placeholders (`admin`, `user-a`,
  `seudominio.com`) — keep them.

---

## Style

- English, second person, present tense. Short sentences.
- Tables over paragraphs where the content is enumerable.
- `bash` blocks are typed in a shell. `json` / `yaml` blocks are file contents.
- Anything skippable goes in a blockquote starting with `**Optional**.`
- **Numbers:** English uses `,` for thousands (`262,144`) and `.` for decimals (`46.5`). The
  Portuguese mirror uses the local convention (`262.144` / `46,5`). Leave IPs (`127.0.0.1`) and
  version numbers (`0.11.0`) untouched.
- Keep the status block at the top of each document truthful and current.

## Language policy

| | |
|---|---|
| **Source of truth** | English (`README.md`, `docs/`, `examples/`) |
| **Mirror** | Portuguese (`pt-br/`), same filenames, same structure |
| **Parity** | Not enforced. Portuguese may lag by a revision |
| **Switcher** | Every document carries a one-line language switcher at the top — keep it correct when you rename a file |

---

## Before opening a pull request

1. Verify the claim against the real system or the upstream documentation, and say so in the
   description.
2. Run the checks below.
3. Keep one logical change per pull request.

```bash
# local links resolve, fences balanced, language switchers present
python3 - <<'PY'
from pathlib import Path
import re
FENCE = chr(96) * 3
bad = []
for f in sorted(Path('.').rglob('*.md')):
    if '.git/' in str(f):
        continue
    t = f.read_text()
    if t.count(FENCE) % 2:
        bad.append(f'{f}: unbalanced fence')
    if not re.search(r'^\> .*(English|Português)', t, re.M):
        bad.append(f'{f}: missing language switcher')
    for u in re.findall(r'\[[^\]]*\]\(([^)]+)\)', t) + re.findall(r'<img[^>]+src="([^"]+)"', t):
        if u.startswith(('http', '#', 'mailto:')):
            continue
        p = u.split('#')[0]
        if p and not (f.parent / p).resolve().exists():
            bad.append(f'{f}: broken link {u}')
print('\n'.join(bad) if bad else 'links, fences and switchers OK')
PY

# every bash block parses
python3 - <<'PY'
from pathlib import Path
import re, subprocess
FENCE = chr(96) * 3
bad = 0
for f in sorted(Path('.').rglob('*.md')):
    if '.git/' in str(f):
        continue
    for m in re.finditer(FENCE + r'bash\n(.*?)' + FENCE, f.read_text(), re.S):
        code = m.group(1)
        if re.search(r'<[a-z_]+>', code):
            continue          # reference block with placeholders
        if subprocess.run(['bash', '-n'], input=code, text=True, capture_output=True).returncode:
            print('bash error in', f)
            bad += 1
print('bash blocks OK' if not bad else f'{bad} broken')
PY
```

## Reporting without a pull request

Open an issue with the document, the exact command, and what happened instead. Include the version
of whatever component is involved. That is enough for someone else to reproduce it.

## Licensing of contributions

By contributing you agree your changes are released under the same license as the repository:
[CC BY 4.0](LICENSE) for documentation, [MIT](LICENSE-CODE) for code. See [`NOTICE.md`](NOTICE.md)
for attribution and third-party components.