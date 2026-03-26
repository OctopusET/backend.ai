from ai.backend.accelerator.tenstorrent.common.types import AbstractTTDevice
from ai.backend.common.types import DeviceName

__all__ = ("TTn300Device",)


class TTn300Device(AbstractTTDevice):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, device_name=DeviceName("tt"), **kwargs)

    def __str__(self) -> str:
        return (
            f"TTn300Device <{self.hw_location}, Memory {self.memory_size}, NUMA Node"
            f" #{self.numa_node}>"
        )
