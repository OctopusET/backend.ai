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

from .types import TTn300Device

VALID_CARD_TYPE = "n300"

log = BraceStyleAdapter(logging.getLogger(__spec__.name))  # type: ignore


class TTn300Plugin(AbstractTTPlugin[TTn300Device]):
    key = DeviceName("tt")
    slot_types: Sequence[tuple[SlotName, SlotTypes]] = (
        (SlotName("tt.device"), SlotTypes("count")),
    )
    exclusive_slot_types: set[str] = {"tt.device"}

    async def _list_devices(self) -> list[TTn300Device]:
        devices: list[TTn300Device] = []

        tt_devices = detect_chips_with_callback(print_status=False)
        backend = TTSMIBackend(tt_devices, pretty_output=False)

        self._tt_devices = tt_devices
        self._tt_backend = backend

        for device_idx, pci_chip in enumerate(tt_devices):
            device_info = backend.get_device_info(device_idx)
            if device_info["board_type"] not in VALID_CARD_TYPE or device_info["bus_id"] == "N/A":
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

            device = TTn300Device(
                model_name="Tenstorrent n300",
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

    async def _gather_device_telemetry(self, device: TTn300Device) -> TTDeviceTelemetry:
        left_stat = self._tt_backend.get_chip_telemetry(device.tt_device_idx)
        right_stat = self._tt_backend.get_chip_telemetry(device.tt_device_idx + 1)
        power = Decimal(left_stat["power"].strip()) + Decimal(right_stat["power"].strip())
        temp_left = Decimal(left_stat.get("asic_temperature", "0").strip())
        temp_right = Decimal(right_stat.get("asic_temperature", "0").strip())
        return TTDeviceTelemetry(
            power_watts=power,
            temperature_celsius=max(temp_left, temp_right),
            memory_used_bytes=0,
            memory_total_bytes=device.memory_size,
        )

    def get_metadata(self) -> AcceleratorMetadata:
        return {
            "slot_name": "tt.device",
            "description": "Tenstorrent n300",
            "human_readable_name": "Tenstorrent n300 Device",
            "display_unit": "n300",
            "number_format": {"binary": False, "round_length": 0},
            "display_icon": "npu",
        }
