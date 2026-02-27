import logging
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from tt_smi.tt_smi_backend import TTSMIBackend
from tt_tools_common.utils_common.tools_utils import detect_chips_with_callback

from ai.backend.accelerator.tenstorrent.common.plugin import AbstractTTPlugin
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

    async def _list_devices(self) -> list[TTBlackholeDevice]:
        devices: list[TTBlackholeDevice] = []

        tt_devices = detect_chips_with_callback(print_status=False)
        backend = TTSMIBackend(tt_devices, pretty_output=False)

        self._tt_devices = tt_devices
        self._tt_backend = backend

        for device_idx, pci_chip in enumerate(tt_devices):
            device_info = backend.get_device_info(device_idx)
            if device_info["board_type"] not in VALID_CARD_TYPES or device_info["bus_id"] == "N/A":
                continue
            log.debug("Config: {}", device_info)
            pci_idx, bus, _dev_fn = device_info["bus_id"].split(":", maxsplit=3)

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
                hw_location=device_info["bus_id"],
                memory_size=int(BinarySize.from_str(device_info["dram_speed"])) * 2,
                processing_units=0,
                numa_node=numa_node_idx,
                tt_pci_chip=pci_chip,
                tt_device_idx=device_idx,
            )
            devices.append(device)

        return devices

    async def _gather_device_telemetry(self, device: TTBlackholeDevice) -> Decimal:
        stat = self._tt_backend.get_chip_telemetry(device.tt_device_idx)
        return Decimal(stat["power"].strip())

    def get_metadata(self) -> AcceleratorMetadata:
        return {
            "slot_name": "tt-blackhole.device",
            "description": "Tenstorrent Blackhole",
            "human_readable_name": "Tenstorrent Blackhole Device",
            "display_unit": "blackhole",
            "number_format": {"binary": False, "round_length": 0},
            "display_icon": "npu",
        }
