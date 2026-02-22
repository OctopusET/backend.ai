from tt_tools_common.utils_common.tools_utils import PciChip

from ai.backend.agent.resources import AbstractComputeDevice
from ai.backend.common.types import DeviceId, DeviceName

__all__ = ("AbstractTTDevice",)


class AbstractTTDevice(AbstractComputeDevice):
    model_name: str
    serial: DeviceId
    device_number: int
    tt_pci_chip: PciChip
    tt_device_idx: int

    def __init__(
        self,
        model_name: str,
        serial: DeviceId,
        device_number: int,
        tt_pci_chip: PciChip,
        tt_device_idx: int,
        *args: object,
        device_name: DeviceName | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, device_name=device_name, **kwargs)
        self.model_name = model_name
        self.serial = serial
        self.device_number = device_number
        self.tt_pci_chip = tt_pci_chip
        self.tt_device_idx = tt_device_idx

    def __repr__(self) -> str:
        return self.__str__()
