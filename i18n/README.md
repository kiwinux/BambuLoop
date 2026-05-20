# BambuLoop translations

This directory holds locale JSON files for the BambuLoop backend.

## File format

One file per language, named with the ISO 639-1 code: `ko.json`, `en.json`,
`zh.json`, `ja.json`, etc. All files are UTF-8 with raw (non-escaped)
characters. Keys use dot notation (e.g. `error.no_file`).

```json
{
  "error.no_file": "...",
  "error.z_collision.bottom_mode.title": "...",
  "validator.verdict.safe": "..."
}
```

## Placeholders

Some strings include `{placeholder}` tokens that are substituted at runtime
with values such as filenames or temperatures. Keep the same placeholder
names in your translation:

```jsonc
// en.json
"error.parse_failed": "Parse failed: {error_type}: {error_message}"

// ko.json
"error.parse_failed": "파싱 실패: {error_type}: {error_message}"
```

## Adding a new language

1. Copy `en.json` to `<lang>.json` (using the language's ISO 639-1 code).
2. Translate each value, leaving the keys and placeholders intact.
3. (Optional) Add the language code to the frontend language selector.
4. Open a pull request.

`en.json` is the source of truth — every key must exist there. Keys missing
from a translation automatically fall back to the English value at runtime.

## Validation

Make sure your JSON is valid and uses the same keys as `en.json`:

```bash
python -c "
import json, pathlib
en = json.loads(pathlib.Path('i18n/en.json').read_text())
mine = json.loads(pathlib.Path('i18n/<lang>.json').read_text())
missing = set(en) - set(mine)
extra = set(mine) - set(en)
print('Missing keys:', missing or 'none')
print('Extra keys (typos?):', extra or 'none')
"
```
