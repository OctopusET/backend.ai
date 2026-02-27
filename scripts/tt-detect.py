"""Tenstorrent Blackhole device detection test.

Verifies that tt-smi can see Blackhole-based boards and reports
device info, telemetry, and computed memory size.
"""

import json
import sys

from tt_smi.tt_smi_backend import TTSMIBackend
from tt_tools_common.utils_common.tools_utils import detect_chips_with_callback

BLACKHOLE_BOARD_TYPES = frozenset({
    "p100a",
    "p150a",
    "p150b",
    "p150c",
    "p300a",
    "p300b",
    "p300c",
})


def main() -> int:
    chips = detect_chips_with_callback(print_status=False)
    backend = TTSMIBackend(chips, pretty_output=False)

    print(f"Total chips detected: {len(chips)}")

    found = False
    for i in range(len(chips)):
        info = backend.get_device_info(i)
        board_type = info["board_type"]
        print(f"\nChip {i}: board_type={board_type}, bus_id={info['bus_id']}")

        if board_type not in BLACKHOLE_BOARD_TYPES:
            print("  Skipped (not a Blackhole board)")
            continue
        if info["bus_id"] == "N/A":
            print("  Skipped (no PCI bus ID)")
            continue

        found = True
        print(f"  Device info: {json.dumps(info, indent=2, default=str)}")

        try:
            telem = backend.get_chip_telemetry(i)
            print(f"  Telemetry:   {json.dumps(telem, indent=2, default=str)}")
        except Exception as e:
            print(f"  Telemetry:   ERROR: {e}")

        dram_speed = info["dram_speed"]
        size_str = dram_speed.upper().replace("G", "")
        memory_gb = int(size_str) * 2
        print(f"  Memory: dram_speed={dram_speed} -> {memory_gb} GB")

    if found:
        print("\nSUCCESS: Blackhole device(s) detected")
        return 0
    else:
        print("\nFAILURE: No Blackhole devices found")
        return 1


if __name__ == "__main__":
    sys.exit(main())
