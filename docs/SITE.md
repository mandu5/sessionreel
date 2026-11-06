# SessionReel documentation site

The selected 6 November 2026 A cinema design is implemented natively in
`docs/index.html`, `docs/site.css`, and `docs/site.js`. It adds a static entry
point to the existing repository documentation. No hosting configuration is
added or changed.

Build and preview with Python's standard library:

```sh
python3 scripts/build_site.py
python3 scripts/serve_site.py
```

The loopback-only preview server supports HTTP byte ranges. Chrome needs those
responses to seek the MP4 chapters; the standard `python3 -m http.server` does
not provide them. A future static host must also serve media byte ranges.

`build/site/` is a self-contained static output. The builder copies the original
`docs/demo.mp4`, `docs/demo.gif`, and `src/sessionreel/demo/demo-session.jsonl`.
It never reads personal sessions or invokes the video renderer, a model, or a
network service. `assets/provenance.json` records their source paths and SHA-256
hashes. The source files are unchanged.

The poster in `docs/assets/demo-poster.jpg` is the frame at 1.2 seconds of the
original MP4, after its initial fade-in. It can be regenerated locally:

```sh
ffmpeg -ss 1.2 -i docs/demo.mp4 -frames:v 1 -update 1 docs/assets/demo-poster.jpg
```

## Navigation and behavior

| Entry / action | Destination / behavior |
| --- | --- |
| Studio | Original 35-second demo, native video controls, play/pause button |
| Request / Inspect / Fail / Edit / Verify / Finish | Seek to six evenly divided video-time spans |
| Source | Original bundled JSONL download, repository source link, original event timestamps |
| Get SessionReel / Guide | Existing installation, session selection, plugin, and CLI instructions |
| Export | Existing plan/edit/render commands, formats, narration, redaction options |
| Download MP4 / GIF | Original repository files, byte for byte |
| Privacy / full CLI / design notes / Korean | Existing canonical repository documentation |
| Copy command(s) | Copy exact displayed text; select text if clipboard access fails |

The chapter labels are editorial navigation. Their seeks divide the video
evenly; the source timestamps in the Source section are **not** video time or
precisely aligned scene boundaries. The demo session and its test outcomes are
synthetic. Source provenance is visible beside the player and downloads.

The Python package, renderer, CLI, source sessions, tests, README files, and
existing MP4/GIF remain unchanged. This implementation does not include the
study's A/B/C chooser, feedback controls, prototype importer, or iframe shell.

## Provenance and licenses

The selected study used Design Studio's approved reference compositions. The
user confirmed personal GitHub reuse authorization on 5 November 2026. That
reference provenance is retained and the reference collection is not
relicensed as original MIT material. No study runtime or third-party animation
library is imported into this site.

Local website fonts are Pretendard 1.3.9 and Archivo Variable (Fontsource 5.3.0).
Their original SIL Open Font License notices are preserved under
`docs/assets/fonts/` and copied to the build. The original video retains its
original renderer fonts and appearance. Existing repository assets and code
retain the repository's existing license.

Revert the site implementation commit to remove this entry point. No package,
data, deployment, or hosting migration is needed.
