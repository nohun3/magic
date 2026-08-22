# HP/MP Detector

HP and MP are read by:

1. **Anchor location** — find `templates/roi_hpmp_anchor.png` (the
   dragon skull ornament between the two bars) in the captured frame
   with `cv2.matchTemplate`. This locates the bar wherever it is in the
   frame, so it doesn't break just because the window ended up in a
   different position.
2. **Fixed offset** — HP's and MP's OCR-able text regions are read from
   a fixed pixel offset off the anchor's position (`hp.content_offset` /
   `mp.content_offset` in `pc/config/settings.yaml`), not from matching
   the bar image itself.
3. **OCR** — crop that region and run PaddleOCR on it to read the
   printed `"HP:190/190"` / `"MP:330/426"` text directly, instead of
   estimating a fill percentage from pixel colors.

## Why an anchor instead of matching the bar directly

Earlier versions matched `roi_hp.png`/`roi_mp.png` (whole-bar images)
directly. Two escalating problems showed up:

- The pixel-color-fill heuristic (before OCR existed) misread MP's
  subtle fill/empty color contrast in practice.
- Switching to OCR fixed reading the value, but **locating** the bar via
  the whole-bar image was still broken: `roi_hp.png`/`roi_mp.png` were
  captured at 100% HP/MP (fully filled), and the match score against a
  partially-filled or near-empty bar drops as the value moves away from
  full -- measured as low as ~0.55 at ordinary gameplay levels, and
  simulated down to ~0.33 at 1% fill. No single threshold works: too
  strict and the first-ever match (before any cache exists) can fail
  and never recover if HP/MP wasn't near-full at that moment; too loose
  and it risks false-matching something else. This was the real cause
  of HP/MP intermittently reading "N/A" throughout a session, not just
  at startup.

The skull ornament's pixels never change no matter what HP/MP currently
is (measured a **1.0** match score at every fill level tested, including
100% HP with MP anywhere from ~0% to 100% over a 90-second live check,
0 failures out of 268 reads). Anchoring on it and reading each bar via a
fixed offset is fill-percentage-proof by construction — the location
match no longer has anything to do with the value being read.

A second, independent OCR-side issue was also found and fixed
separately: PaddleOCR occasionally misreads the "/" between current and
max as a stray digit (e.g. `"45/414"` read back as `"451414"`). See
`resilient_gauge_reader.py` — it remembers the last successfully-read
max and uses it to recover from exactly this failure mode. This is a
second line of defense on top of the anchor fix, not a replacement for it.

## Recalibrating

If the bar's look/position changes (different UI theme, different
window size, different game) or matching stops working:

1. Capture a fresh frame:
   ```
   python -m pc.capture.test_capture single
   ```
   This saves `output/capture_test.png`.

2. Crop out **just the skull ornament** between the two bars — make sure
   the crop doesn't include any of the red/blue fill area on either
   side (even a sliver will make the match score sensitive to HP/MP
   again, defeating the point):
   ```python
   import cv2
   img = cv2.imread("output/capture_test.png")
   crop = img[758:820, 880:948]  # adjust to the skull's location
   cv2.imwrite("templates/roi_hpmp_anchor.png", crop)
   ```

3. Re-measure the offsets from the anchor to each bar's text region.
   The easiest way is to still have (or temporarily restore) the old
   whole-bar templates and compare their matched positions to the
   anchor's:
   ```python
   from pc.detector.template_locator import locate_template
   anchor_m = locate_template(img, cv2.imread("templates/roi_hpmp_anchor.png"), 0.0)
   hp_m = locate_template(img, cv2.imread("templates/roi_hp.png"), 0.0)
   print(hp_m.region.left - anchor_m.region.left, hp_m.region.top - anchor_m.region.top,
         hp_m.region.width, hp_m.region.height)
   ```
   Put the printed `(left, top, width, height)` into `hp.content_offset`
   (and similarly for `mp.content_offset`) in `pc/config/settings.yaml`.

4. Verify with:
   ```
   python -m pc.detector.test_detector single
   ```
   and check `output/detector_test.png` — the matched box should sit
   exactly on the bar regardless of the current HP/MP level, and the
   printed value should match what's on screen.

## Notes

- `roi_hpmp_anchor.match_threshold` (0.9) only has to distinguish "the
  skull is on screen" from "it isn't" — comfortably strict since the
  anchor itself is 100% static, unlike hp/mp's old per-bar thresholds.
- OCR is comparatively slow (hundreds of ms per call) — much slower than
  the old pixel-counting approach. Detection should be polled at its own
  rate, not tied to capture FPS; that's handled in the
  condition/scheduling layer (Step 4+), not here.
- `enable_mkldnn=False` in `ocr_reader.py` works around a
  PaddlePaddle 3.x + oneDNN inference bug on this machine. Safe to try
  removing if paddlepaddle is upgraded later.
