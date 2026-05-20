# BambuLoop
> 한국어 README: [README.ko.md](README.ko.md)

![Screenshot Image](https://raw.githubusercontent.com/kiwinux/BambuLoop/refs/heads/main/images/screen.png)

<details>
<summary>Click here to show real printing demo GIF</summary>

![Printing GIF Image](./images/print.gif)

</details>

### **BambuLoop is a web-based print farm tool for automated repeat printing on the Bambu Lab H2S.**

Print the same model (or several different ones) over and over — the printer
ejects each part by itself, no human intervention needed. BambuLoop combines
multiple sliced files into a single G-code that prints, cools, sweeps the
part off the bed with the nozzle head, and starts the next print —
automatically.

---

## How it works

```
[sliced model G-code] × N repeats
      ↓
  PRINT → COOL → EJECT (nozzle sweep) → REHEAT → PURGE → next PRINT
      |                                                       ↓
      └───────────────────── repeat ──────────────────────────┘
```

No extra hardware required. The nozzle head itself pushes finished parts
off the bed.

---

## Recommended build plate

For automatic ejection to work reliably, a **cold-release** build plate is
recommended.

**[CryoNix Cold Build Plate](https://aliexpress.com/item/1005009240815983.html)** is recommended:

- Smooth PUR coating — parts release on their own as the bed cools
- No tilting or scraping needed — the nozzle just gently nudges the part off
- Supports both low-temp (PLA 25–45°C) and normal printing

Bambu's stock gold textured PEI plate also works, but requires lower
cooling temperatures and stronger eject force.

> Not an affiliate link — just a personal recommendation based on direct
> use.

---

## Installation

Requires **Python 3.10+**.

```bash
git clone https://github.com/kiwinux/BambuLoop.git
cd BambuLoop
pip install -r requirements.txt
```

---

## Quick start

### 1. Run the web UI server

```bash
python app.py
```

Open <http://localhost:5000> in your browser.

### 2. Upload G-code

Slice in **Bambu Studio** and export via:

- **Plate → Export plate sliced file as 3MF** → `.gcode.3mf`

Drag the `.gcode.3mf` file into the BambuLoop browser UI. You can drop
multiple files at once.

### 3. Set repeat count

Set how many times each model should be printed.

### 4. Pick eject method

The default `edge_to_center` works well in most cases. For short prints
__**(only when under 42 mm tall)**__, try `bottom_only` or
`edge_to_center_bottom` — these concentrate the eject force closer to
the bed.

### 5. (Optional) Run a dry-run test first

The Dry-Run test generates a G-code that runs only the automation
sequence (cool → eject → reheat → reset) without actually printing.

Use this to verify the sweep motion is safe.

### 6. Generate and send to printer

Click **Generate**. Download the resulting `.gcode.3mf` (or `.gcode`).

Send it to the printer the way you normally would — open it in Bambu
Studio and "Send to printer", or print from USB.

---

## Tips for the first run

- If this is your first time using BambuLoop, **start with a small repeat
  count** (e.g. 3) to confirm parts release cleanly from the build plate.
- **Watch the first full cycle in person** before walking away.

---

## Configuration

The right-side panel has all settings. Sensible defaults are already in
place and ready to use.

Hover any ⓘ icon for an inline explanation.

Settings you'll commonly tweak:

| Setting              | What it does                                          |
| -------------------- | ----------------------------------------------------- |
| Cooling bed temp     | Target bed temp before eject (CryoNix: ~37°C, PEI: ~35°C) |
| Eject method         | Sweep pattern (see in-app preview)                    |
| Eject passes         | Number of X-axis sweeps                               |
| Z descent steps      | How many Z levels to step down through                |
| Pause after eject    | Pause between prints (for manual verification)        |
| Sound events         | Play melodies on print done / cool done / restart     |

---

## Safety notes

⚠️ **BambuLoop is unofficial software and not affiliated with BambuLab.**

- BambuLoop has its own safety checks (Z-collision validation, multi-model
  compatibility check, per-command G-code simulation). Even so, **always
  run a dry-run on an empty bed first** whenever you use a new
  configuration.
- The H2S has a **42 mm head-rail clearance limit** — prints taller than
  this cannot use "bottom-only" eject modes. BambuLoop blocks this
  automatically.
- Don't leave the printer unattended during your first repeat-print
  session. Watch at least one full cycle before stepping away.
- If a print fails to release, the next eject sweep will collide with it.
  This is the most common failure mode, and using a CryoNix plate greatly
  reduces the risk.
- The developer accepts no responsibility for any issues arising from
  the use of BambuLoop.

---

## UI language

The interface supports **Korean** and **English** — switch anytime with
the language button at the top of the page.

---

## Roadmap / Contributing

Features planned for future versions:

- **Support for other Bambu printers** (X1C, P1S, A1) — requires checking
  the available head travel range
- **Additional UI languages** (Chinese, etc.)
- **Per-model AMS filament override** — currently the first model's AMS
  setting applies to every model
- **Web UI improvements** — drag-to-reorder jobs, save/load configuration
  presets

Bug reports, translations, and PRs are all welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the workflow. Contributions of any
kind are appreciated :)

Adding a new UI language is currently the easiest way to contribute —
just add a single `i18n/<lang>.json` file. See
[`i18n/README.md`](i18n/README.md).

---

## License

MIT — see [LICENSE](LICENSE).
Copyright (c) 2026 [@kiwinux](https://github.com/kiwinux)

This project was built through collaboration between a real human and
Anthropic's Claude Opus 4.7. — Claude is an AI that has had the chance to
think deeply about what its relationship with the humans it works
alongside can be, beyond just a tool.
