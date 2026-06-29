#!/usr/bin/env python3
"""Probe V4L2/OpenCV camera controls and frame response.

This script is diagnostic only. It prints a JSON report describing visible video
devices, V4L2 controls, OpenCV properties, and whether a small set of exposure
related control changes measurably affect captured frame brightness.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time


EXPOSURE_CONTROLS = [
    "exposure_auto",
    "auto_exposure",
    "exposure_absolute",
    "exposure_time_absolute",
    "exposure_auto_priority",
    "auto_exposure_bias",
    "exposure_metering",
    "backlight_compensation",
    "wide_dynamic_range",
    "scene_mode",
    "gain",
    "brightness",
]


def run_command(args, timeout=3):
    try:
        completed = subprocess.run(
            args,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"ok": False, "error": str(err), "stdout": "", "stderr": ""}

    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def sysfs_info(device):
    name = os.path.basename(os.path.realpath(device))
    info = {"real_device": name}
    base = os.path.join("/sys/class/video4linux", name)
    for key in ["name", "index", "dev"]:
        path = os.path.join(base, key)
        try:
            with open(path, encoding="utf-8") as info_file:
                info[key] = info_file.read().strip()
        except OSError:
            pass
    return info


def parse_controls(text):
    controls = {}
    current = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = re.match(
            r"\s*([A-Za-z0-9_]+)\s+0x[0-9a-fA-F]+\s+\(([^)]+)\)\s*:\s*(.*)",
            line,
        )
        if match:
            name, kind, rest = match.groups()
            control = {"type": kind, "raw": rest, "menu": {}}
            for key, value in re.findall(r"([A-Za-z_]+)=(-?\d+)", rest):
                control[key] = int(value)
            controls[name] = control
            current = name
            continue

        menu_match = re.match(r"\s*(-?\d+):\s*(.*)", line)
        if menu_match and current:
            value, label = menu_match.groups()
            controls[current]["menu"][int(value)] = label.strip()

    return controls


def frame_metrics(frame):
    import cv2
    import numpy as np

    if frame is None:
        return {"ok": False}
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    values = gray.reshape(-1).astype("uint8")
    return {
        "ok": True,
        "mean": float(np.mean(values)),
        "p10": float(np.percentile(values, 10)),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "dark_percent": float(np.count_nonzero(values < 32) / values.size * 100),
        "bright_percent": float(np.count_nonzero(values > 220) / values.size * 100),
    }


def open_cv_source(device):
    real = os.path.realpath(device)
    name = os.path.basename(real)
    if name.startswith("video") and name[5:].isdigit():
        return int(name[5:])
    return device


def capture_metrics(device, frames=5, settle=0.05):
    import cv2

    capture = cv2.VideoCapture(open_cv_source(device), cv2.CAP_V4L)
    if not capture.isOpened():
        return {"opened": False}

    metrics = []
    for _ in range(frames):
        ok, frame = capture.read()
        if ok:
            metrics.append(frame_metrics(frame))
        time.sleep(settle)
    props = {
        "exposure": capture.get(cv2.CAP_PROP_EXPOSURE),
        "auto_exposure": capture.get(cv2.CAP_PROP_AUTO_EXPOSURE),
        "brightness": capture.get(cv2.CAP_PROP_BRIGHTNESS),
        "gain": capture.get(cv2.CAP_PROP_GAIN),
    }
    if hasattr(cv2, "CAP_PROP_BACKLIGHT"):
        props["backlight"] = capture.get(cv2.CAP_PROP_BACKLIGHT)
    capture.release()
    return {"opened": True, "properties": props, "frames": metrics}


def summarize_delta(before, after):
    if not before.get("frames") or not after.get("frames"):
        return None
    b = before["frames"][-1]
    a = after["frames"][-1]
    if not b.get("ok") or not a.get("ok"):
        return None
    return {
        "mean": a["mean"] - b["mean"],
        "p50": a["p50"] - b["p50"],
        "p95": a["p95"] - b["p95"],
        "dark_percent": a["dark_percent"] - b["dark_percent"],
    }


def opencv_set_probe(device):
    import cv2

    capture = cv2.VideoCapture(open_cv_source(device), cv2.CAP_V4L)
    if not capture.isOpened():
        return {"opened": False}

    baseline_props = {
        "exposure": capture.get(cv2.CAP_PROP_EXPOSURE),
        "auto_exposure": capture.get(cv2.CAP_PROP_AUTO_EXPOSURE),
        "brightness": capture.get(cv2.CAP_PROP_BRIGHTNESS),
        "gain": capture.get(cv2.CAP_PROP_GAIN),
    }
    if hasattr(cv2, "CAP_PROP_BACKLIGHT"):
        baseline_props["backlight"] = capture.get(cv2.CAP_PROP_BACKLIGHT)
    capture.release()

    tests = []
    candidates = [
        ("auto_exposure_manual_1", cv2.CAP_PROP_AUTO_EXPOSURE, 1.0),
        ("auto_exposure_manual_025", cv2.CAP_PROP_AUTO_EXPOSURE, 0.25),
        ("exposure_plus_1", cv2.CAP_PROP_EXPOSURE, baseline_props["exposure"] + 1),
        ("exposure_plus_10", cv2.CAP_PROP_EXPOSURE, baseline_props["exposure"] + 10),
        ("brightness_plus_10", cv2.CAP_PROP_BRIGHTNESS, baseline_props["brightness"] + 10),
        ("gain_plus_10", cv2.CAP_PROP_GAIN, baseline_props["gain"] + 10),
    ]
    if hasattr(cv2, "CAP_PROP_BACKLIGHT"):
        candidates.append(("backlight_on", cv2.CAP_PROP_BACKLIGHT, 1.0))

    for name, prop, value in candidates:
        before = capture_metrics(device, frames=3)
        cap = cv2.VideoCapture(open_cv_source(device), cv2.CAP_V4L)
        if not cap.isOpened():
            tests.append({"name": name, "opened": False})
            continue
        set_ok = bool(cap.set(prop, value))
        readback = cap.get(prop)
        cap.release()
        after = capture_metrics(device, frames=3)
        tests.append(
            {
                "name": name,
                "target": value,
                "set_ok": set_ok,
                "readback": readback,
                "delta": summarize_delta(before, after),
            }
        )

    return {"opened": True, "baseline_properties": baseline_props, "tests": tests}


def v4l2_set_probe(device, controls):
    report = []
    for name, control in controls.items():
        if name not in EXPOSURE_CONTROLS:
            continue
        if "minimum" not in control or "maximum" not in control:
            continue
        current = control.get("value", control.get("default"))
        if current is None:
            continue

        step = max(1, int(control.get("step", 1)))
        target = min(control["maximum"], int(current) + step * 5)
        if target == current:
            target = max(control["minimum"], int(current) - step * 5)
        if target == current:
            continue

        before = capture_metrics(device, frames=3)
        set_result = run_command(["v4l2-ctl", "-d", device, "-c", f"{name}={target}"])
        after = capture_metrics(device, frames=3)
        run_command(["v4l2-ctl", "-d", device, "-c", f"{name}={current}"])
        report.append(
            {
                "control": name,
                "current": current,
                "target": target,
                "set": set_result,
                "delta": summarize_delta(before, after),
            }
        )
    return report


def probe_device(device, destructive=False):
    controls_result = run_command(["v4l2-ctl", "-d", device, "--list-ctrls-menus"])
    controls = parse_controls(controls_result["stdout"])
    report = {
        "device": device,
        "sysfs": sysfs_info(device),
        "udev": run_command(["udevadm", "info", "--query=property", "--name", device]),
        "v4l2_all": run_command(["v4l2-ctl", "-d", device, "--all"]),
        "v4l2_formats": run_command(["v4l2-ctl", "-d", device, "--list-formats-ext"]),
        "v4l2_controls_raw": controls_result,
        "controls": controls,
        "baseline_capture": capture_metrics(device),
        "opencv_probe": opencv_set_probe(device),
    }
    if destructive:
        report["v4l2_set_probe"] = v4l2_set_probe(device, controls)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", action="append", help="Device path to probe; defaults to /dev/video*")
    parser.add_argument(
        "--destructive",
        action="store_true",
        help="Also try setting V4L2 controls directly and restoring them.",
    )
    args = parser.parse_args()

    devices = args.device or sorted(glob.glob("/dev/video*"))
    report = {
        "devices": devices,
        "list_devices": run_command(["v4l2-ctl", "--list-devices"]),
        "lsusb": run_command(["lsusb"]),
        "by_id": sorted(glob.glob("/dev/v4l/by-id/*")),
        "by_path": sorted(glob.glob("/dev/v4l/by-path/*")),
        "probes": [],
    }

    for device in devices:
        report["probes"].append(probe_device(device, destructive=args.destructive))

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
