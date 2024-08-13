from typing import List, Any, Dict

from ganeti import utils
from ganeti import serializer
from ganeti import constants
from ganeti import objects
from ganeti.hypervisor.hv_kvm.types import QMPVCPUItem, \
                                        QMPMemoryDimmItem

import logging

_KVM_CMD_RUNTIME_INDEX = 0
_KVM_NICS_RUNTIME_INDEX = 1
_KVM_HV_RUNTIME_INDEX = 2
_KVM_DISKS_RUNTIME_INDEX = 3
_KVM_VCPU_RUNTIME_INDEX = 4
_KVM_MEM_RUNTIME_INDEX = 5

# Constans File?
_PCI_BUS = "pci.0"

_DEVICE_TYPE = {
  constants.HOTPLUG_TARGET_NIC: lambda hvp: hvp[constants.HV_NIC_TYPE],
  constants.HOTPLUG_TARGET_DISK: lambda hvp: hvp[constants.HV_DISK_TYPE],
  }

_DEVICE_DRIVER = {
  constants.HOTPLUG_TARGET_NIC:
    lambda ht: "virtio-net-pci" if ht == constants.HT_NIC_PARAVIRTUAL else ht,
  constants.HOTPLUG_TARGET_DISK:
    lambda ht: "virtio-blk-pci" if ht == constants.HT_DISK_PARAVIRTUAL else ht,
  }

class KVMRuntime:

  def __init__(self):
    self.data = []

  def __init__(self, data: List):
    assert len(data) == 6
    self.data = data

  def __getitem__(self, idx):
    return self.data[idx]

  def __eq__(self, other: 'KVMRuntime'):
    return self.kvm_cmd == other.kvm_cmd \
        and self.kvm_nics == other.kvm_nics \
        and self.up_hvp == other.up_hvp \
        and self.kvm_disks == other.kvm_disks \
        and self.kvm_vcpus == other.kvm_vcpus \
        and self.kvm_mem == other.kvm_mem


  @property
  def kvm_cmd(self) -> List[str]:
    return self.data[_KVM_CMD_RUNTIME_INDEX]


  @kvm_cmd.setter
  def kvm_cmd(self, kvm_cmd: List[str]):
    self.data[_KVM_CMD_RUNTIME_INDEX] = kvm_cmd


  @property
  def kvm_nics(self) -> List[Any]:
    return self.data[_KVM_NICS_RUNTIME_INDEX]


  @kvm_nics.setter
  def kvm_nics(self, kvm_nics: List[Any]):
    self.data[_KVM_NICS_RUNTIME_INDEX] = kvm_nics


  @property
  def up_hvp(self) -> Dict:
    return self.data[_KVM_HV_RUNTIME_INDEX]


  @up_hvp.setter
  def up_hvp(self, up_hvp: Dict):
    self.data[_KVM_HV_RUNTIME_INDEX] = up_hvp


  @property
  def kvm_disks(self) -> List[objects.Disk]:
    return self.data[_KVM_DISKS_RUNTIME_INDEX]


  @property
  def kvm_vcpus(self) -> List[QMPVCPUItem]:
    return self.data[_KVM_VCPU_RUNTIME_INDEX]

  @property
  def kvm_mem(self) -> List[QMPMemoryDimmItem]:
    return self.data[_KVM_MEM_RUNTIME_INDEX]


  def serialize(self) -> str:
    serialized_nics = [nic.ToDict() for nic in self.kvm_nics]
    serialized_disks = [(blk.ToDict(), link, uri)
                        for blk, link, uri in self.kvm_disks]

    serialized = serializer.Dump((self.kvm_cmd, serialized_nics,
                                      self.up_hvp,
                                      serialized_disks,
                                      self.kvm_vcpus,
                                      self.kvm_mem))

    return serialized


  @staticmethod
  def from_serialized(serialized: str, upgrade=True) -> 'KVMRuntime':
    logging.warning(f"serialized Runtime: '{serialized}'")


    loaded_runtime = serializer.Load(serialized)

    if upgrade:
      loaded_runtime = _upgrade_serialized_runtime(loaded_runtime)

    kvm_cmd = loaded_runtime[_KVM_CMD_RUNTIME_INDEX]
    up_hvp = loaded_runtime[_KVM_HV_RUNTIME_INDEX]
    nics = [objects.NIC.FromDict(nic) for nic in loaded_runtime[_KVM_NICS_RUNTIME_INDEX]]
    disks = [(objects.Disk.FromDict(sdisk), link, uri)
               for sdisk, link, uri in loaded_runtime[_KVM_DISKS_RUNTIME_INDEX]]
    vcpus = [QMPVCPUItem.from_dict(vcpu) for vcpu in loaded_runtime[_KVM_VCPU_RUNTIME_INDEX]]
    mem = [QMPMemoryDimmItem.from_dict(mem_item) for mem_item in loaded_runtime[_KVM_MEM_RUNTIME_INDEX]]

    return KVMRuntime([kvm_cmd, nics, up_hvp, disks, vcpus, mem])

# Upgrade durchführen vor Deserialisierung
def _upgrade_serialized_runtime(loaded_runtime: Any) -> List:
  """Upgrade runtime data

  Remove any deprecated fields or change the format of the data.
  The runtime files are not upgraded when Ganeti is upgraded, so the required
  modification have to be performed here.

  @type loaded_runtime: List
  @param loaded_runtime: List of unserialized items (dict or list)
  @return: List[cmd, nic dicts, hvparams, bdev dicts]
  @rtype: List

  """
  kvm_cmd, serialized_nics, hvparams = loaded_runtime[:3]
  if len(loaded_runtime) >= 4:
    serialized_disks = loaded_runtime[3]
  else:
    serialized_disks = []

  if len(loaded_runtime) >= 5:
    kvm_vcpus = loaded_runtime[4]
  else:
    kvm_vcpus = []

  if len(loaded_runtime) >= 6:
    kvm_mem = loaded_runtime[5]
  else:
    kvm_mem = []

  def update_hvinfo(dev, dev_type):
    """ Remove deprecated pci slot and substitute it with hvinfo """
    if "hvinfo" not in dev:
      dev["hvinfo"] = {}
      uuid = dev["uuid"]
      # Ganeti used to save the PCI slot of paravirtual devices
      # (virtio-blk-pci, virtio-net-pci) in runtime files during
      # _GenerateKVMRuntime() and HotAddDevice().
      # In this case we had a -device QEMU option in the command line with id,
      # drive|netdev, bus, and addr params. All other devices did not have an
      # id nor placed explicitly on a bus.
      # hot- prefix is removed in 2.16. Here we add it explicitly to
      # handle old instances in the cluster properly.
      if "pci" in dev:
        # This is practically the old _GenerateDeviceKVMId()
        hv_dev_type = _DEVICE_TYPE[dev_type](hvparams)
        dev["hvinfo"]["driver"] = _DEVICE_DRIVER[dev_type](hv_dev_type)
        dev["hvinfo"]["id"] = "hot%s-%s-%s-%s" % (dev_type.lower(),
                                                  uuid.split("-")[0],
                                                  "pci",
                                                  dev["pci"])
        dev["hvinfo"]["addr"] = hex(dev["pci"])
        dev["hvinfo"]["bus"] = _PCI_BUS
        del dev["pci"]

  for nic in serialized_nics:
    # Add a dummy uuid slot if an pre-2.8 NIC is found
    if "uuid" not in nic:
      nic["uuid"] = utils.NewUUID()
    update_hvinfo(nic, constants.HOTPLUG_TARGET_NIC)

  for disk_entry in serialized_disks:
    # We have a (Disk, link, uri) tuple
    update_hvinfo(disk_entry[0], constants.HOTPLUG_TARGET_DISK)

  # Handle KVM command line argument changes
  try:
    idx = kvm_cmd.index("-localtime")
  except ValueError:
    pass
  else:
    kvm_cmd[idx:idx+1] = ["-rtc", "base=localtime"]

  try:
    idx = kvm_cmd.index("-balloon")
  except ValueError:
    pass
  else:
    balloon_args = kvm_cmd[idx+1].split(",")[1:]
    balloon_str = "virtio-balloon"
    if balloon_args:
      balloon_str += ",%s" % ",".join(balloon_args)

    kvm_cmd[idx:idx+2] = ["-device", balloon_str]

  try:
    idx = kvm_cmd.index("-vnc")
  except ValueError:
    pass
  else:
    # Check to see if TLS is enabled
    orig_vnc_args = kvm_cmd[idx+1].split(",")
    vnc_args = []
    tls_obj = None
    tls_obj_args = ["id=vnctls0", "endpoint=server"]
    for arg in orig_vnc_args:
      if arg == "tls":
        tls_obj = "tls-creds-anon"
        vnc_args.append("tls-creds=vnctls0")
        continue

      elif arg.startswith("x509verify=") or arg.startswith("x509="):
        pki_path = arg.split("=", 1)[-1]
        tls_obj = "tls-creds-x509"
        tls_obj_args.append("dir=%s" % pki_path)
        if arg.startswith("x509verify="):
          tls_obj_args.append("verify-peer=yes")
        else:
          tls_obj_args.append("verify-peer=no")
        continue

      vnc_args.append(arg)

    if tls_obj is not None:
      vnc_cmd = ["-vnc", ",".join(vnc_args)]
      tls_obj_cmd = ["-object",
                     "%s,%s" % (tls_obj, ",".join(tls_obj_args))]

      # Replace the original vnc argument with the new ones
      kvm_cmd[idx:idx+2] = tls_obj_cmd + vnc_cmd

    # with 3.1 the 'default' value for disk_discard has been dropped
    # and replaced by 'ignore'
    if constants.HV_DISK_DISCARD in hvparams \
      and hvparams[constants.HV_DISK_DISCARD] not in \
        constants.HT_VALID_DISCARD_TYPES:
      hvparams[constants.HV_DISK_DISCARD] = constants.HT_DISCARD_IGNORE

  return [kvm_cmd, serialized_nics, hvparams, serialized_disks, kvm_vcpus, kvm_mem]
