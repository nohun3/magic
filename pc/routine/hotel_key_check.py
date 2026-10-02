"""Recheck missing hotel keys before allowing the purchase sequence."""
import cv2

from pc.routine.timing import sleep_jittered


def check_hotel_key(settings, project_root, link, skill_panel, window_title,
                    screen_capture_cls):
    """Return True if seen, False after all valid misses, None if uncertain."""
    from pc.routine.step_buy_hotel_key import ensure_visible_skill_tab

    cfg = settings["icons"]["hotel_key"]
    paths = cfg.get("templates") or [cfg["template"]]
    templates = []
    for path in paths:
        template = cv2.imread(str(project_root / path))
        if template is None:
            print(f"  [hotel key] template unreadable: {path}; purchase blocked")
            return None
        templates.append((path, template))
    threshold = float(cfg.get("match_threshold", 0.85))
    attempts = max(2, int(cfg.get("absence_verify_attempts", 4)))
    interval = max(0.0, float(cfg.get("absence_verify_interval_seconds", 0.5)))
    uncertain = False
    for attempt in range(1, attempts + 1):
        if not ensure_visible_skill_tab(link, skill_panel, window_title, screen_capture_cls):
            print("  [hotel key] skill tab unavailable; purchase blocked")
            return None
        with screen_capture_cls(window_title=window_title) as cap:
            frame = cap.grab()
        region = skill_panel.relocate(frame)
        crop = None
        if region is None:
            uncertain = True
            print(f"  [hotel key] {attempt}/{attempts}: ROI missing; not an absence")
        else:
            crop = frame[region.top:region.top + region.height,
                         region.left:region.left + region.width]
            present = False
            for path, template in templates:
                if (template.shape[0] > crop.shape[0]
                        or template.shape[1] > crop.shape[1]):
                    uncertain = True
                    print(f"  [hotel key] template larger than ROI: {path}")
                    continue
                scores = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, position = cv2.minMaxLoc(scores)
                print(
                    f"  [hotel key] {attempt}/{attempts}: {path} "
                    f"score={score:.6f} threshold={threshold:.6f} position={position}"
                )
                present = present or score >= threshold
            if present:
                print("  [hotel key] present -- purchase skipped")
                return True
        # Bounded storage: latest unsuccessful observation only.
        try:
            directory = project_root / "output" / "hotel_key_diagnostics"
            directory.mkdir(parents=True, exist_ok=True)
            for name, pixels in (("screen", frame), ("roi", crop)):
                path = directory / f"latest_{name}.png"
                if pixels is None:
                    path.unlink(missing_ok=True)
                elif not cv2.imwrite(str(path), pixels):
                    print(f"  [hotel key] failed to save {path}")
            print(f"  [hotel key] diagnostic directory: {directory}")
        except Exception as exc:
            print(f"  [hotel key] diagnostic save failed: {exc}")
        if attempt < attempts:
            sleep_jittered(interval, jitter_seconds=0.0)
    if uncertain:
        print("  [hotel key] incomplete verification; purchase blocked")
        return None
    print(f"  [hotel key] absent in all {attempts} valid observations")
    return False
