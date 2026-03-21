import logging
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from tt_smi.tt_smi_backend import TTSMIBackend
from tt_tools_common.utils_common.tools_utils import detect_chips_with_callback

from ai.backend.accelerator.tenstorrent.common.plugin import AbstractTTPlugin, TTDeviceTelemetry
from ai.backend.accelerator.tenstorrent.utils import resolve_pci_sysfs_path
from ai.backend.common.logging import BraceStyleAdapter
from ai.backend.common.types import (
    AcceleratorMetadata,
    BinarySize,
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

log = BraceStyleAdapter(logging.getLogger(__spec__.name))  # type: ignore


class TTBlackholePlugin(AbstractTTPlugin[TTBlackholeDevice]):
    key = DeviceName("tt-blackhole")
    slot_types: Sequence[tuple[SlotName, SlotTypes]] = (
        (SlotName("tt-blackhole.device"), SlotTypes("count")),
    )
    exclusive_slot_types: set[str] = {"tt-blackhole.device"}

    _hwmon_paths: dict[DeviceId, Path]

    async def _list_devices(self) -> list[TTBlackholeDevice]:
        devices: list[TTBlackholeDevice] = []
        self._hwmon_paths = {}

        tt_devices = detect_chips_with_callback(print_status=False)
        backend = TTSMIBackend(tt_devices, pretty_output=False)

        self._tt_devices = tt_devices
        self._tt_backend = backend

        for device_idx, pci_chip in enumerate(tt_devices):
            device_info = backend.get_device_info(device_idx)
            if device_info["board_type"] not in VALID_CARD_TYPES or device_info["bus_id"] == "N/A":
                continue
            log.debug("Config: {}", device_info)

            bus_id = device_info["bus_id"]
            pci_sysfs = Path(f"/sys/bus/pci/devices/{bus_id}")
            hwmon_dir = pci_sysfs / "hwmon"
            if hwmon_dir.is_dir():
                hwmon_entries = list(hwmon_dir.iterdir())
                if hwmon_entries:
                    self._hwmon_paths[DeviceId(str(device_idx))] = hwmon_entries[0]

            pci_idx, bus, _dev_fn = bus_id.split(":", maxsplit=3)
            pci_base_path = resolve_pci_sysfs_path(f"{pci_idx}:{bus}")
            if not pci_base_path:
                raise RuntimeError("PCI device file not found in the sysfs!")

            numa_node_idx_path = Path(pci_base_path) / "device" / "numa_node"
            numa_node_idx = int(numa_node_idx_path.read_text())
            if numa_node_idx < 0:
                numa_node_idx = 0

            device = TTBlackholeDevice(
                model_name=f"Tenstorrent {device_info['board_type']}",
                serial=DeviceId(device_info["board_id"]),
                device_id=DeviceId(str(device_idx)),
                device_number=int(device_idx),
                hw_location=bus_id,
                memory_size=int(BinarySize.from_str(device_info["dram_speed"])) * 2,
                processing_units=0,
                numa_node=numa_node_idx,
                tt_pci_chip=pci_chip,
                tt_device_idx=device_idx,
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
        # Power: hwmon reports microwatts, convert to watts
        power_uw = self._read_hwmon(device.device_id, "power1_input")
        if power_uw is not None:
            power_w = Decimal(power_uw) / Decimal(1_000_000)
        else:
            stat = self._tt_backend.get_chip_telemetry(device.tt_device_idx)
            power_w = Decimal(stat["power"].strip())

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
            "slot_name": "tt-blackhole.device",
            "description": "Tenstorrent Blackhole",
            "human_readable_name": "Tenstorrent Blackhole Device",
            "display_unit": "blackhole",
            "number_format": {"binary": False, "round_length": 0},
            "display_icon": "npu",
        }
