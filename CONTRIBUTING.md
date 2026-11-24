# Contributing to BambuLoop

Thanks for your interest! BambuLoop is open source under the MIT license, and
contributions of any size are welcome — bug reports, feature requests, code,
translations, documentation.

BambuLoop processes files in a Web Worker using the bundled Python engine.
Build new features to work in the browser and keep files in the tab. We plan
to remove the local HTTP API in a future release.

## Reporting bugs

Open a GitHub issue with:

- What you tried to do
- What happened (full error message or G-code excerpt is best)
- Your slicer version (Bambu Studio version), filament, and nozzle settings
- Your browser and version if the issue occurs in the web app
- For a motion warning, the warning margin and the relevant rows from **Details**
  (line number, axis and G-code command). Share a small excerpt or a sample you
  can make public if it helps reproduce the issue.

## Suggesting features

Open an issue tagged `enhancement`. Describe the user-facing problem first,
the proposed solution second.

## Code contributions

1. Fork the repo and create a feature branch (`git checkout -b feat/my-change`).
2. Preview the browser app with `node tools/preview.mjs` and open
   [BambuLoop on localhost](http://127.0.0.1:4173/BambuLoop/).
3. For the native tests, install the development dependencies with
   `python -m pip install -r requirements.txt`. Run `python -m unittest discover`
   and `python test_smoke.py`. After changing engine code or its translations,
   refresh the Pages assets with `python tools/build_pages.py` and include them
   in your PR. Check them with `python tools/build_pages.py --check`.
4. For browser or engine changes, run `node tests/pages_smoke.mjs` (see
   **Static site tests** below). For generator changes, use **Generate dry-run**
   with a sliced Bambu Studio file and inspect the downloaded G-code.
5. Open a pull request describing the change.

### Code style

- Code, comments, and docstrings are **English only**. Non-English text inside
  a `.py` or `.html` file should be UI-visible content (KO_TO_EN dictionaries,
  i18n `desc.ko`, etc.), never code-level comments.
- Follow the existing style — type hints, descriptive comments around safety
  logic, no overly clever one-liners.
- Prefer the Python standard library for shared engine code. Keep Flask
  imports in the local HTTP API so the browser worker can load the engine.

### Safety-related changes

Anything that touches the eject sequence, Z-collision check, or M73 progress
logic deserves extra care:

- Add a comment explaining the safety invariant your change preserves.
- For motion validator changes, test an expected H2S path and an unexpected
  move. Include the warning margin and the expected classification for each.
- If a change could affect physical motion, include the results of a supervised
  dry-run on an empty bed on the target printer before submitting. For a new
  printer model, document its head travel limits and model-specific G-code.
- Update the corresponding sections of `README.md` and `README.ko.md` when
  user-visible behaviour changes.

## Translations (i18n)

Adding a new language is one of the easiest contributions and very welcome.

1. Copy `i18n/en.json` to `i18n/<lang>.json` (use the ISO 639-1 code, e.g.
   `zh.json` for Chinese, `ja.json` for Japanese).
2. Translate every value, leaving keys and `{placeholder}` tokens unchanged.
3. Validate key parity:
   ```bash
   python -c "
   import json, pathlib
   en = json.loads(pathlib.Path('i18n/en.json').read_text(encoding='utf-8'))
   mine = json.loads(pathlib.Path('i18n/<lang>.json').read_text(encoding='utf-8'))
   missing = set(en) - set(mine)
   extra = set(mine) - set(en)
   print('Missing:', missing or 'none')
   print('Extra:', extra or 'none')
   "
   ```
4. Run `python tools/build_pages.py` and include the updated browser bundle
   with your locale file. A translation-only PR is welcome.

The locale JSON files supply engine messages, including validation results
and errors. To offer a new language in the UI, also add its interface
strings and language selection in `docs/assets/app.mjs`.

## Code of conduct

Be kind. Assume good faith. We're all here to make a 3D printer do something
fun.

## License

By contributing, you agree that your contributions will be licensed under the
same MIT license that covers the project.

## Static site tests

The source UI lives in `docs/index.html` and `docs/assets/`. The Flask API and the browser worker share `job_service.py` and the G-code modules. `node tests/pages_smoke.mjs` serves the Pages subpath on loopback and checks real downloads in a disposable Chromium profile. Use Node 22.15 or newer and set `BAMBULOOP_CHROME` to a Chromium executable if it is outside the standard locations. Runtime provenance and licenses are in `docs/runtime/`.

For an optional native comparison, set `BAMBULOOP_REFERENCE_PYTHON` to a local Python executable. Run `node tests/pages_smoke.mjs --sample path/to/sliced.gcode.3mf` with a multi-plate input to also check an archived file. The test compares all archive members, validates each plate checksum and normalizes the generated timestamp.
