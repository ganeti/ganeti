from typing import Dict
from dataclasses import dataclass, asdict

@dataclass
class QMPVCPUItem:
  """This dataclass represents a qmp vcpu device.
  """

  cpu_id: str
  driver: str
  socket_id: int
  core_id: int
  thread_id: int


  def to_dict(self) -> Dict:
    return asdict(self)


  def to_qmp_vcpu(self) -> Dict:
    """Transfer a QMPVCPUItem to a dict, what can be
       passed as argument to the device_add qmp command.
    """

    return {
        "id": self.cpu_id,
        "driver": self.driver,
        "socket-id": self.socket_id,
        "core-id": self.core_id,
        "thread-id": self.thread_id
    }


  @staticmethod
  def from_dict(items: Dict)-> 'QMPVCPUItem':
    return QMPVCPUItem(**items)


  @staticmethod
  def from_qmp_vcpu(vcpu: Dict) -> 'QMPVCPUItem':
    """Creates a QMPVCPUItem from a dict, that returned
       by the query-hotpluggable-cpus qmp command.
    """

    props = vcpu['props']
    cpu_id = f"cpu-{props['socket-id']}"

    return QMPVCPUItem(
      cpu_id=cpu_id,
      driver=vcpu['type'],
      socket_id=props['socket-id'],
      core_id=props['core-id'],
      thread_id=props['thread-id']
    )

@dataclass
class QMPMemoryBackendItem:
  id: str
  size: int # size in Bytes


  def __post_init__(self):
    # force size is an integer
    if not isinstance(self.size, int):
        self.value = int(self.size)

  def to_qmp(self) -> Dict:
    return {
      "id": self.id,
      "size": self.size,
      "qom-type": "memory-backend-ram"
    }

@dataclass
class QMPMemoryDimmItem:
  id: str
  memdev: QMPMemoryBackendItem

  def to_qmp(self) -> Dict:
    return {
      "id": self.id,
      "memdev": self.memdev.id,
      "driver": "pc-dimm"
    }
