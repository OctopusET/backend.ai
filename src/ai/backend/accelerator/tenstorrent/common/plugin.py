import logging
from abc import ABCMeta, abstractmethod
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from pprint import pformat
from typing import Any

import aiodocker
from aiodocker import Docker

from ai.backend.accelerator.tenstorrent import __version__

from .types import AbstractTTDevice

try:
    from ai.backend.agent.resources import get_resource_spec_from_container  # type: ignore
except ImportError:
    from ai.backend.agent.docker.resources import get_resource_spec_from_container

from tt_smi.tt_smi_backend import TTSMIBackend
from tt_tools_common.utils_common.tools_utils import PciChip

from ai.backend.agent.resources import (
    AbstractAllocMap,
    AbstractComputePlugin,
    DeviceSlotInfo,
    DiscretePropertyAllocMap,
)
from ai.backend.agent.stats import (
    ContainerMeasurement,
    Measurement,
    MetricTypes,
    NodeMeasurement,
    ProcessMeasurement,
    StatContext,
)
from ai.backend.agent.types import Container, MountInfo
from ai.backend.common.logging import BraceStyleAdapter
from ai.backend.common.types import (
    AcceleratorMetadata,
    BinarySize,
    DeviceId,
    DeviceModelInfo,
    MetricKey,
    SlotName,
    SlotTypes,
)


@dataclass
class TTDeviceTelemetry:
    power_watts: Decimal
    temperature_celsius: Decimal
    memory_used_bytes: int
    memory_total_bytes: int


log = BraceStyleAdapter(logging.getLogger(__spec__.name))  # type: ignore


class AbstractTTPlugin[TDevice: AbstractTTDevice](AbstractComputePlugin, metaclass=ABCMeta):
    device_mask: Sequence[DeviceId] = []
    enabled: bool = True

    _all_devices: list[TDevice] | None

    _tt_devices: list[PciChip]
    _tt_backend: TTSMIBackend

    async def init(self, context: Any = None) -> None:
        self._all_devices = None

        raw_device_mask = self.plugin_config.get("device_mask")
        if raw_device_mask is not None:
            self.device_mask = [
                *map(lambda dev_id: DeviceId(dev_id), raw_device_mask.split(",")),
            ]

        try:
            detected_devices = await self.list_devices()
            log.info("detected devices:\n" + pformat(detected_devices))
            log.info("Tenstorrent {} acceleration is enabled.", self.key)
        except ImportError:
            log.warning("could not find Tenstorrent devices.")
            self.enabled = False

    async def list_devices(self) -> list[TDevice]:
        if self._all_devices is not None:
            return self._all_devices
        devices = await self._list_devices()
        self._all_devices = devices
        return devices

    @abstractmethod
    async def _list_devices(self) -> list[TDevice]:
        raise NotImplementedError

    @abstractmethod
    async def _gather_device_telemetry(self, device: TDevice) -> TTDeviceTelemetry:
        """Return telemetry for a single device."""
        raise NotImplementedError

    @abstractmethod
    def get_metadata(self) -> AcceleratorMetadata:
        raise NotImplementedError

    async def available_slots(self) -> Mapping[SlotName, Decimal]:
        devices = await self.list_devices()
        log.debug("available devices: {}", Decimal(len(devices)))
        return {
            self.slot_types[0][0]: Decimal(len(devices)),
        }

    def get_version(self) -> str:
        return __version__

    async def extra_info(self) -> Mapping[str, Any]:
        if self.enabled:
            return {
                f"{self.key.replace('-', '_')}_support": True,
            }
        return {}

    async def gather_node_measures(self, ctx: StatContext) -> Sequence[NodeMeasurement]:
        stat_prefix = self.key.replace("-", "_")
        power_total = Decimal("0")
        power_stats: dict[DeviceId, Measurement] = {}
        temp_max = Decimal("0")
        temp_stats: dict[DeviceId, Measurement] = {}
        mem_used_total = 0
        mem_total_total = 0
        mem_stats: dict[DeviceId, Measurement] = {}

        if self.enabled:
            for device in await self.list_devices():
                telemetry = await self._gather_device_telemetry(device)
                power_total += telemetry.power_watts
                power_stats[device.device_id] = Measurement(telemetry.power_watts)
                if telemetry.temperature_celsius > temp_max:
                    temp_max = telemetry.temperature_celsius
                temp_stats[device.device_id] = Measurement(telemetry.temperature_celsius)
                mem_used_total += telemetry.memory_used_bytes
                mem_total_total += telemetry.memory_total_bytes
                mem_stats[device.device_id] = Measurement(
                    Decimal(telemetry.memory_used_bytes),
                    Decimal(telemetry.memory_total_bytes),
                )

        return [
            NodeMeasurement(
                MetricKey(f"{stat_prefix}_power"),
                MetricTypes.USAGE,
                unit_hint="watts",
                stats_filter=frozenset({"max"}),
                per_node=Measurement(Decimal(power_total)),
                per_device=power_stats,
            ),
            NodeMeasurement(
                MetricKey(f"{stat_prefix}_temperature"),
                MetricTypes.GAUGE,
                unit_hint="celsius",
                stats_filter=frozenset({"max"}),
                per_node=Measurement(Decimal(temp_max)),
                per_device=temp_stats,
            ),
            NodeMeasurement(
                MetricKey(f"{stat_prefix}_mem"),
                MetricTypes.GAUGE,
                unit_hint="bytes",
                stats_filter=frozenset({"max"}),
                per_node=Measurement(Decimal(mem_used_total), Decimal(mem_total_total)),
                per_device=mem_stats,
            ),
        ]

    async def gather_container_measures(
        self,
        ctx: StatContext,
        container_ids: Sequence[str],
    ) -> Sequence[ContainerMeasurement]:
        power_stats: dict[str, Decimal] = {}
        stat_prefix = self.key.replace("-", "_")

        if self.enabled:
            device_telemetry_by_path: dict[str, TTDeviceTelemetry] = {}
            for device in await self.list_devices():
                path = f"/dev/tenstorrent/{device.device_number}"
                device_telemetry_by_path[path] = await self._gather_device_telemetry(device)

            for cid in container_ids:
                power_stats[cid] = Decimal("0")
                async with Docker() as docker:
                    container_info = await docker.containers.get(cid)
                for dev in container_info["HostConfig"]["Devices"]:
                    if dev["PathOnHost"] in device_telemetry_by_path:
                        power_stats[cid] += device_telemetry_by_path[dev["PathOnHost"]].power_watts

        return [
            ContainerMeasurement(
                MetricKey(f"{stat_prefix}_power"),
                MetricTypes.USAGE,
                unit_hint="watts",
                stats_filter=frozenset({"max"}),
                per_container={
                    cid: Measurement(Decimal(usage)) for cid, usage in power_stats.items()
                },
            ),
        ]

    async def create_alloc_map(self) -> DiscretePropertyAllocMap:
        devices = await self.list_devices()
        return DiscretePropertyAllocMap(
            device_slots={
                DeviceId(str(dev.device_id)): DeviceSlotInfo(
                    SlotTypes.COUNT, self.slot_types[0][0], Decimal(1)
                )
                for dev in devices
            },
            exclusive_slot_types=self.exclusive_slot_types,
        )

    async def generate_docker_args(
        self,
        docker: aiodocker.docker.Docker,
        device_alloc: Mapping[SlotName, Mapping[DeviceId, Decimal]],
    ) -> Mapping[str, Any]:
        devices: dict[str, str] = {}
        alloc_idx = 0
        for dev in await self.list_devices():
            if dev.device_id in device_alloc.get(self.slot_types[0][0], {}).keys():
                devices[f"/dev/tenstorrent/{dev.device_number}"] = f"/dev/tenstorrent/{alloc_idx}"
                alloc_idx += 1

        assigned_devices: dict[Path, Path] = {}
        for host_path, container_path in devices.items():
            try:
                Path(host_path).stat()
                assigned_devices[Path(host_path)] = Path(container_path)
            except FileNotFoundError:
                pass

        return {
            "HostConfig": {
                "CapAdd": ["IPC_LOCK", "SYS_RAWIO"],
                "IpcMode": "host",
                "Ulimits": [
                    {
                        "Name": "memlock",
                        "Hard": -1,
                        "Soft": -1,
                    },
                ],
                "Sysctls": {
                    "net.ipv6.conf.all.disable_ipv6": "0",
                },
                "Devices": [
                    {
                        "PathOnHost": host_path.as_posix(),
                        "PathInContainer": container_path.as_posix(),
                        "CgroupPermissions": "rwm",
                    }
                    for host_path, container_path in assigned_devices.items()
                ],
                "Mounts": [
                    {
                        "BindOptions": {},
                        "ReadOnly": False,
                        "Source": "/dev/hugepages-1G",
                        "Target": "/dev/hugepages-1G",
                        "Type": "bind",
                    },
                    {
                        "BindOptions": {},
                        "ReadOnly": False,
                        "Source": "/opt/backendai/cache/tt",
                        "Target": "/home/container_app_user/cache",
                        "Type": "bind",
                    },
                ],
            },
        }

    async def get_attached_devices(
        self,
        device_alloc: Mapping[SlotName, Mapping[DeviceId, Decimal]],
    ) -> Sequence[DeviceModelInfo]:
        device_ids: list[DeviceId] = []
        if self.slot_types[0][0] in device_alloc:
            device_ids.extend(device_alloc[self.slot_types[0][0]].keys())
        available_devices = await self.list_devices()
        attached_devices: list[DeviceModelInfo] = []
        for device in available_devices:
            if device.device_id in device_ids:
                proc = device.processing_units
                mem = BinarySize(device.memory_size)
                attached_devices.append({
                    "device_id": device.device_id,
                    "model_name": device.model_name,
                    "data": {
                        "smp": proc,
                        "mem": mem,
                    },
                })
        return attached_devices

    async def restore_from_container(
        self,
        container: Container,
        alloc_map: AbstractAllocMap,
    ) -> None:
        if not self.enabled:
            return
        resource_spec = await get_resource_spec_from_container(container.backend_obj)
        if resource_spec is None:
            return
        if hasattr(alloc_map, "apply_allocation"):
            for slot_name, _ in self.slot_types:
                alloc_map.apply_allocation({
                    slot_name: resource_spec.allocations.get(
                        self.key,
                        {},
                    ).get(
                        slot_name,
                        {
                            dev_id: Decimal(0)
                            for dev_id, dev_slot_info in alloc_map.device_slots.items()
                            if dev_slot_info.slot_name == slot_name
                        },
                    ),
                })
        else:
            alloc_map.allocations[self.slot_types[0][0]].update(
                resource_spec.allocations.get(
                    self.key,
                    {},
                ).get(
                    self.slot_types[0][0],
                    {},
                ),
            )

    async def generate_resource_data(
        self,
        device_alloc: Mapping[SlotName, Mapping[DeviceId, Decimal]],
    ) -> Mapping[str, str]:
        data: MutableMapping[str, str] = {}
        if not self.enabled:
            return data

        active_device_id_set: set[DeviceId] = set()
        for slot_type, per_device_alloc in device_alloc.items():
            for dev_id, alloc in per_device_alloc.items():
                if alloc > 0:
                    active_device_id_set.add(dev_id)
        active_device_ids = sorted(active_device_id_set)
        data["TT_GLOBAL_DEVICE_IDS"] = ",".join(
            f"{local_idx}:{global_id}" for local_idx, global_id in enumerate(active_device_ids)
        )
        return data

    async def generate_mounts(
        self,
        source_path: Path,
        device_alloc: Mapping[SlotName, Mapping[DeviceId, Decimal]],
    ) -> list[MountInfo]:
        return []

    async def cleanup(self) -> None:
        pass

    async def update_plugin_config(self, new_plugin_config: Mapping[str, Any]) -> None:
        pass

    async def get_hooks(self, distro: str, arch: str) -> Sequence[Path]:
        return []

    async def get_docker_networks(
        self,
        device_alloc: Mapping[SlotName, Mapping[DeviceId, Decimal]],
    ) -> list[str]:
        return []

    def _read_procfs_pids(self, device_number: int) -> set[int]:
        """Read PIDs from /proc/driver/tenstorrent/N/pids (stock tt-kmd)."""
        try:
            text = Path(f"/proc/driver/tenstorrent/{device_number}/pids").read_text()
            return {int(line) for line in text.splitlines() if line.strip()}
        except (FileNotFoundError, ValueError):
            return set()

    async def gather_process_measures(
        self,
        ctx: StatContext,
        pid_map: Mapping[int, str],
    ) -> Sequence[ProcessMeasurement]:
        if not self.enabled:
            return []

        stat_prefix = self.key.replace("-", "_")
        per_process_power: dict[int, Measurement] = {}

        for device in await self.list_devices():
            pids = self._read_procfs_pids(device.device_number)
            matched_pids = pids & pid_map.keys()
            if not matched_pids:
                continue
            telemetry = await self._gather_device_telemetry(device)
            for pid in matched_pids:
                if pid in per_process_power:
                    per_process_power[pid] = Measurement(
                        per_process_power[pid].value + telemetry.power_watts,
                    )
                else:
                    per_process_power[pid] = Measurement(telemetry.power_watts)

        if not per_process_power:
            return []

        return [
            ProcessMeasurement(
                MetricKey(f"{stat_prefix}_power"),
                MetricTypes.USAGE,
                unit_hint="watts",
                stats_filter=frozenset({"max"}),
                per_process=per_process_power,
            ),
        ]
