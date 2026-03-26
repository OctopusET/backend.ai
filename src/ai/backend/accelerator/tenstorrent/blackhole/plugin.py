import logging
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from ai.backend.accelerator.tenstorrent.common.plugin import AbstractTTPlugin, TTDeviceTelemetry
from ai.backend.common.logging import BraceStyleAdapter
from ai.backend.common.types import (
    AcceleratorMetadata,
    DeviceId,
    DeviceName,
    SlotName,
    SlotTypes,
)

from .types import TTBlackholeDevice

VALID_CARD_TYPES: frozenset[str] = frozenset({
    "p100a",
    "p150a",
    "p150b",
    "p150c",
    "p300a",
    "p300b",
    "p300c",
})

# PCI device ID for Blackhole
BLACKHOLE_PCI_DEVICE_ID = "0xb140"

# DRAM size per Blackhole chip (32 GiB GDDR6)
BLACKHOLE_DRAM_BYTES = 32 * (1024 ** 3)

log = BraceStyleAdapter(logging.getLogger(__spec__.name))  # type: ignore


class TTBlackholePlugin(AbstractTTPlugin[TTBlackholeDevice]):
    key = DeviceName("tt")
    slot_types: Sequence[tuple[SlotName, SlotTypes]] = (
        (SlotName("tt.device"), SlotTypes("count")),
    )
    exclusive_slot_types: set[str] = {"tt.device"}

    _hwmon_paths: dict[DeviceId, Path]

    async def _list_devices(self) -> list[TTBlackholeDevice]:
        """Discover Tenstorrent devices using sysfs only (no TTSMIBackend)."""
        devices: list[TTBlackholeDevice] = []
        self._hwmon_paths = {}

        tt_class = Path("/sys/class/tenstorrent")
        if not tt_class.is_dir():
            return devices

        for entry in sorted(tt_class.iterdir()):
            # entry = /sys/class/tenstorrent/tenstorrent!N
            name = entry.name  # "tenstorrent!0"
            device_number = int(name.split("!")[-1])

            # Read card type from sysfs
            card_type_path = entry / "tt_card_type"
            if not card_type_path.exists():
                continue
            card_type = card_type_path.read_text().strip()
            if card_type not in VALID_CARD_TYPES:
                continue

            # Read serial
            serial_path = entry / "tt_serial"
            serial = serial_path.read_text().strip() if serial_path.exists() else "unknown"

            # Get PCI bus ID from device symlink
            device_link = entry / "device"
            if not device_link.is_symlink():
                continue
            bus_id = device_link.resolve().name  # "0000:XX:YY.Z"

            # hwmon
            hwmon_dir = device_link / "hwmon"
            if hwmon_dir.is_dir():
                hwmon_entries = list(hwmon_dir.iterdir())
                if hwmon_entries:
                    self._hwmon_paths[DeviceId(str(device_number))] = hwmon_entries[0]

            # NUMA node
            numa_path = device_link / "numa_node"
            numa_node = 0
            if numa_path.exists():
                numa_val = int(numa_path.read_text().strip())
                numa_node = max(0, numa_val)

            device = TTBlackholeDevice(
                model_name=f"Tenstorrent {card_type}",
                serial=DeviceId(serial),
                device_id=DeviceId(str(device_number)),
                device_number=device_number,
                hw_location=bus_id,
                memory_size=BLACKHOLE_DRAM_BYTES,
                processing_units=0,
                numa_node=numa_node,
                tt_pci_chip=None,  # type: ignore[arg-type]
                tt_device_idx=device_number,
            )
            devices.append(device)

        return devices

    def _read_hwmon(self, device_id: DeviceId, sensor: str) -> int | None:
        hwmon_path = self._hwmon_paths.get(device_id)
        if hwmon_path is None:
            return None
        try:
            return int((hwmon_path / sensor).read_text().strip())
        except (FileNotFoundError, ValueError):
            return None

    async def _gather_device_telemetry(self, device: TTBlackholeDevice) -> TTDeviceTelemetry:
        # Power: hwmon reports microwatts
        power_uw = self._read_hwmon(device.device_id, "power1_input")
        power_w = Decimal(power_uw) / Decimal(1_000_000) if power_uw is not None else Decimal(0)

        # Temperature: hwmon reports millidegrees
        temp_m = self._read_hwmon(device.device_id, "temp1_input")
        temp_c = Decimal(temp_m) / Decimal(1000) if temp_m is not None else Decimal(0)

        return TTDeviceTelemetry(
            power_watts=power_w,
            temperature_celsius=temp_c,
            memory_used_bytes=0,
            memory_total_bytes=device.memory_size,
        )

    def get_metadata(self) -> AcceleratorMetadata:
        return {
            "slot_name": "tt.device",
            "description": "Tenstorrent Blackhole",
            "human_readable_name": "Tenstorrent Blackhole Device",
            "display_unit": "blackhole",
            "number_format": {"binary": False, "round_length": 0},
            "display_icon": "npu",
        }
