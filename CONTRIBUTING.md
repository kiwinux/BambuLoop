# Contributing to BambuLoop

Thanks for your interest! BambuLoop is open source under the MIT license, and
contributions of any size are welcome — bug reports, feature requests, code,
translations, documentation.

## Reporting bugs

Open a GitHub issue with:

- What you tried to do
- What happened (full error message or G-code excerpt is best)
- Your slicer version (Bambu Studio version), filament, and nozzle settings
- The generated G-code if relevant (a Pastebin link is fine — they get large)

## Suggesting features

Open an issue tagged `enhancement`. Describe the user-facing problem first,
the proposed solution second.

## Code contributions

1. Fork the repo and create a feature branch (`git checkout -b feat/my-change`).
2. Make your changes.
3. Run the smoke test: `python test_smoke.py` should print all green.
4. If you change G-code generation, also test the **dry-run** mode in the web
   UI on at least one real `.gcode` file from Bambu Studio.
5. Open a pull request describing the change.

### Code style

- Code, comments, and docstrings are **English only**. Non-English text inside
  a `.py` or `.html` file should be UI-visible content (KO_TO_EN dictionaries,
  i18n `desc.ko`, etc.), never code-level comments.
- Follow the existing style — type hints, descriptive comments around safety
  logic, no overly clever one-liners.
- Avoid introducing new dependencies unless they meaningfully simplify
  something. Stick to the standard library + Flask where possible.

### Safety-related changes

Anything that touches the eject sequence, Z-collision check, or M73 progress
logic deserves extra care:

- Add a comment explaining the safety invariant your change preserves.
- If the change could affect physical motion, run a real dry-run with the
  Bambu Studio dry-run feature on H2S before submitting.
- Update the corresponding section of `README.md` if the user-visible behaviour
  changes.

## Translations (i18n)

Adding a new language is one of the easiest contributions and very welcome.

1. Copy `i18n/en.json` to `i18n/<lang>.json` (use the ISO 639-1 code, e.g.
   `zh.json` for Chinese, `ja.json` for Japanese).
2. Translate every value, leaving keys and `{placeholder}` tokens unchanged.
3. Validate key parity:
   ```bash
   python -c "
   import json, pathlib
   en = json.loads(pathlib.Path('i18n/en.json').read_text())
   mine = json.loads(pathlib.Path('i18n/<lang>.json').read_text())
   missing = set(en) - set(mine)
   extra = set(mine) - set(en)
   print('Missing:', missing or 'none')
   print('Extra:', extra or 'none')
   "
   ```
4. Open a PR with just the new file. We'll wire up the frontend language
   toggle in a follow-up.

The frontend currently has UI strings hard-coded for `ko` / `en`. Migrating
those to the same `i18n/` system is on the roadmap; until then, full UI
translations to a third language require a frontend pass too. Backend strings
(error messages, validator labels, etc.) will already be picked up
automatically from your new JSON file.

## Code of conduct

Be kind. Assume good faith. We're all here to make a 3D printer do something
fun.

## License

By contributing, you agree that your contributions will be licensed under the
same MIT license that covers the project.
