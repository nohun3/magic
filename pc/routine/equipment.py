"""Confirm equipment icons in roi_skill before toggling through Arduino."""
import cv2

from pc.routine.timing import send_random_key_tap, sleep_jittered


def ensure_equipment(settings, project_root, link, skill_panel, window_title,
                     screen_capture_cls, target):
    from pc.routine.step_move_to_hotel import ensure_skill_tab

    if target not in (1, 2):
        raise ValueError("Equipment target must be 1 or 2")
    cfg = settings["equipment"]
    templates = {}
    for number in (1, 2):
        path = project_root / cfg[f"device_{number}_template"]
        template = cv2.imread(str(path))
        if template is None:
            print(f"  [equipment] cannot load {path}")
            return False
        templates[number] = template
    if not ensure_skill_tab(link):
        print("  [equipment] F2 skill tab failed")
        return False

    attempts = max(2, int(cfg["verify_attempts"]))
    interval = max(0.0, float(cfg["verify_interval_seconds"]))
    threshold = float(cfg["match_threshold"])
    margin = float(cfg["score_margin"])

    def read_state():
        previous = None
        for attempt in range(attempts):
            with screen_capture_cls(window_title=window_title) as cap:
                frame = cap.grab()
            region = skill_panel.relocate(frame)
            current = None
            if region is None:
                print("  [equipment] roi_skill not found")
            else:
                crop = frame[region.top:region.top + region.height,
                             region.left:region.left + region.width]
                scores = {}
                for number, template in templates.items():
                    if (template.shape[0] > crop.shape[0]
                            or template.shape[1] > crop.shape[1]):
                        scores[number] = -1.0
                    else:
                        result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
                        scores[number] = float(cv2.minMaxLoc(result)[1])
                best = max(scores, key=scores.get)
                if (scores[best] >= threshold
                        and scores[best] - scores[3 - best] >= margin):
                    current = best
                print(
                    f"  [equipment] set1={scores[1]:.3f} set2={scores[2]:.3f} "
                    f"threshold={threshold:.2f} margin={margin:.2f} state={current}"
                )
            if current is not None and current == previous:
                return current
            previous = current
            if attempt + 1 < attempts:
                sleep_jittered(interval, jitter_seconds=0.0)
        return None

    current = read_state()
    if current == target:
        print(f"  [equipment] set {target} already active")
        return True
    if current is None:
        print("  [equipment] state uncertain -- no toggle sent")
        return False
    key = str(cfg["toggle_key"])
    ok, hold_ms = send_random_key_tap(link, key)
    print(f"  [equipment] {current} -> {target}: {key} ({hold_ms}ms), ACK={ok}")
    if not ok:
        return False
    sleep_jittered(max(0.0, float(cfg["settle_seconds"])), jitter_seconds=0.0)
    if read_state() != target:
        print(f"  [equipment] set {target} not confirmed")
        return False
    print(f"  [equipment] set {target} confirmed")
    return True
