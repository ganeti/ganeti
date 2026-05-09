#
#

# Copyright (C) 2014 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Qemu monitor control classes

"""


import os
import socket
import io
import logging
import time

from typing import Dict, Optional, Union, List
from collections import namedtuple
from bitarray import bitarray

from ganeti import errors
from ganeti import utils
from ganeti import constants
from ganeti import serializer

from ganeti.hypervisor.hv_kvm import kvm_utils


class QmpCommandNotSupported(errors.HypervisorError):
  """QMP command not supported by the monitor.

  This is raised in case a QmpMonitor instance is asked to execute a command
  not supported by the instance.

  This is a KVM-specific exception, intended to assist in falling back to using
  the human monitor for operations QMP does not support.

  """
  pass

class QmpTimeoutError(errors.HypervisorError):
  """QMP socket timeout error """


class QmpMessage:
  """QEMU Messaging Protocol (QMP) message.

  """
  def __init__(self, data: Dict):
    self.data = data

  def __getitem__(self, field_name):
    """Get the value of the required field if present, or None.

    Overrides the [] operator to provide access to the message data,
    returning None if the required item is not in the message
    @return: the value of the field_name field, or None if field_name
             is not contained in the message

    """
    return self.data.get(field_name, None)

  def __setitem__(self, field_name, field_value):
    self.data[field_name] = field_value

  def __eq__(self, other: Union['QmpMessage', Dict]):
    if isinstance(other, QmpMessage):
      return self.data == other.data
    elif isinstance(other, dict):
      return self.data == other

    return False

  def __len__(self):
    """Return the number of fields stored in this QmpMessage.

    """
    return len(self.data)

  def __delitem__(self, key):
    del self.data[key]

  @staticmethod
  def build_from_json_string(json_string: str) -> 'QmpMessage':
    """Build a QmpMessage from a JSON encoded string.

    @param json_string: JSON string representing the message
    @return: a L{QmpMessage} built from json_string

    """
    # Parse the string
    data = serializer.LoadJson(json_string)
    return QmpMessage(data)

  def to_bytes(self) -> bytes:
    # The protocol expects the JSON object to be sent as a single line.
    return serializer.DumpJson(self.data)

  # debug only
  def to_json_string(self) -> str:
    return self.to_bytes().decode("utf-8")

  def __eq__(self, other: 'QmpMessage') -> bool:
    # compare only the data dict
    return self.data == other.data


# define QMP timestamp as namedtuple
QmpTimestamp = namedtuple('QMPTimestamp', 'seconds microseconds')


class QmpEvent:
  """QEMU event message from a qmp socket.

  """

  def __init__(self, timestamp: QmpTimestamp, event_type: str, data: Dict):
    self._timestamp = timestamp
    self._event_type = event_type
    self._data = data

  def __getitem__(self, field_name: str) -> any:
    return self._data.get(field_name, None)

  @property
  def timestamp(self) -> QmpTimestamp:
    return self._timestamp

  @property
  def event_type(self)-> str:
    return self._event_type

  @staticmethod
  def build_from_data(data: Dict) -> 'QmpEvent':
    """Build a QmpEvent from a data dict."""
    timestamp = QmpTimestamp(
      seconds=data['timestamp']['seconds'],
      microseconds=data['timestamp']['microseconds']
    )
    return QmpEvent(
      timestamp=timestamp,
      event_type=data['event'],
      data=data['data']
    )


def _ensure_connection(fn):
  """Decorator that wraps MonitorSocket external methods"""
  def wrapper(*args, **kwargs):
    """Ensure proper connect/close and exception propagation"""
    mon = args[0]
    already_connected = mon.is_connected()
    if not already_connected:
      mon.connect()
    try:
      ret = fn(*args, **kwargs)
    finally:
      # In general this decorator wraps external methods.
      # Here we close the connection only if we initiated it before,
      # to protect us from using the socket after closing it
      # in case we invoke a decorated method internally by accident.
      if not already_connected:
        mon.close()
    return ret
  return wrapper


class UnixFileSocketConnection:

  def __init__(self, socket_path: str, timeout: Union[int, float]):
    self.socket_path = socket_path
    self.timeout = timeout
    self.sock = None
    self._connected = False

  def __enter__(self):
    self.connect()
    return self

  def __exit__(self, exc_type, exc_value, exc_traceback):
    self.close()

  def connect(self):
    if not self.is_connected():
      self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      self.sock.settimeout(self.timeout)
      self.sock.connect(self.socket_path)
      self._connected = True

      logging.debug("Create Socket Connection to %s.", {self.socket_path})

  def close(self):
    if self.is_connected():
      self.sock.close()
      self._connected = False

      logging.debug("Socket Connection to %s closed.", {self.socket_path})

  def is_connected(self) -> bool:
    return self._connected

  def send(self, data: bytes):
    self.sock.sendall(data)

  def recv(self, bufsize: int) -> bytes:
    return self.sock.recv(bufsize)

  def reset_timeout(self) -> None:
    """Reset the timeout to self.timeout"""
    self.sock.settimeout(self.timeout)


class QemuMonitorSocket(UnixFileSocketConnection):
  _ERROR_CLASS_KEY = "class"
  _ERROR_DESC_KEY = "desc"
  _EXECUTE_KEY = "execute"
  _ARGUMENTS_KEY = "arguments"
  _EVENT_KEY = "event"
  _ERROR_KEY = "error"
  _RETURN_KEY = "return"
  _MESSAGE_END_TOKEN = b"\r\n"
  _SEND_END_TOKEN = b"\n"

  def __init__(self, socket_path: str, timeout):
    super().__init__(socket_path, timeout)
    self._buffer = b""

  def execute_qmp(self, command: str, arguments: Dict = None) -> QmpMessage:
    message = QmpMessage({self._EXECUTE_KEY: command})

    if arguments:
      message[self._ARGUMENTS_KEY] = arguments

    self.send_qmp(message)
    return self.get_qmp_response(command)

  def send_qmp(self, message: QmpMessage):
    self.send(message.to_bytes() + b'\n')

  def get_qmp_response(self, command) -> Dict:
    while True:
      response = self.recv_qmp()
      err = response[self._ERROR_KEY]
      if err:
        raise errors.HypervisorError("kvm: error executing the {}"
                                     " command: {} ({}):".format(
                                      command,
                                      err[self._ERROR_DESC_KEY],
                                      err[self._ERROR_CLASS_KEY]))
      elif response[self._EVENT_KEY]:
        continue

      return response[self._RETURN_KEY]

  def wait_for_qmp_event(self, event_types: List[str],
                         timeout: Union[int, float]) -> Optional[QmpEvent]:
    """Waits for one of the specified events and returns it.
       If the timeout is reached, returns None.

    """

    self.sock.settimeout(timeout)
    try:
      while True:
        response = self.recv_qmp()
        if response[self._EVENT_KEY]:
          event = QmpEvent.build_from_data(response.data)
          if event.event_type in event_types:
            self.reset_timeout()
            return event
          else:
            continue
    except QmpTimeoutError:
      self.reset_timeout()

    return None

  def recv_qmp(self) -> QmpMessage:

    message = self._read_buffer()
    # check if the message is already in the buffer
    if message:
      return message

    recv_buffer = io.BytesIO(self._buffer)
    recv_buffer.seek(len(self._buffer))

    try:
      while True:
        data = self.recv(4096)
        if not data:
          break
        recv_buffer.write(data)
        self._buffer = recv_buffer.getvalue()

        message = self._read_buffer()
        if message:
          return message

    except socket.timeout as err:
      raise QmpTimeoutError("Timeout while receiving a QMP message: "
                                   f"{err}") from err
    except socket.error as err:
      raise errors.HypervisorError("Unable to receive data from KVM using the"
                                   f" QMP protocol: {err}")

  def _read_buffer(self) -> QmpMessage:
    message = None

    # Check if we got the message end token (CRLF, as per the QEMU Protocol
    # Specification 0.1 - Section 2.1.1)
    pos = self._buffer.find(self._MESSAGE_END_TOKEN)
    if pos >= 0:
      try:
        message = QmpMessage.build_from_json_string(self._buffer[:pos + 1])
      except Exception as err:
        raise errors.ProgrammerError(f"QMP data serialization error: {err}")
      self._buffer = self._buffer[pos + 1:]

    return message


class QmpConnection(QemuMonitorSocket):
  """Connection to the QEMU Monitor using the QEMU Monitor Protocol (QMP).

  """
  _QMP_TIMEOUT = 5
  # On q35 the guest's pciehp driver mediates detach; 30 s covers driver
  # release and BAR deallocation on a loaded 1-vcpu guest.
  _HOT_UNPLUG_EVENT_TIMEOUT = 30
  # Mirrors _HOT_UNPLUG_EVENT_TIMEOUT for the hot-add side. After
  # device_add succeeds on q35, the guest's pciehp must online the slot
  # and assign BAR addresses before any follow-up operation (in
  # particular hot-unplug) is safe. Successful claims are sub-second on
  # a responsive guest; 5 s is generous.
  _HOT_PLUG_CLAIM_TIMEOUT = 5
  _HOT_PLUG_CLAIM_POLL_INTERVAL = 0.1
  _FIRST_MESSAGE_KEY = "QMP"
  _RETURN_KEY = "return"
  _ACTUAL_KEY = ACTUAL_KEY = "actual"
  _VERSION_KEY = "version"
  _PACKAGE_KEY = "package"
  _QEMU_KEY = "qemu"
  _CAPABILITIES_COMMAND = "qmp_capabilities"
  _QUERY_COMMANDS = "query-commands"
  _MESSAGE_END_TOKEN = b"\r\n"
  # List of valid attributes for the device_add QMP command.
  # Extra attributes found in device's hvinfo will be ignored.
  _DEVICE_ATTRIBUTES = [
    "driver", "id", "bus", "addr", "channel", "scsi-id", "lun",
    "acpi-index",
    ]

  def __init__(self, socket_path: str):
    super().__init__(socket_path, self._QMP_TIMEOUT)
    self.version = None
    self.package = None
    self.supported_commands = None

  def __enter__(self):
    self.connect()
    return self

  def __exit__(self, exc_type, exc_value, tb):
    self.close()

  def execute_qmp(self, command: str, arguments: Dict = None) -> QmpMessage:
    # During the first calls of Execute, the list of supported commands has not
    # yet been populated, so we can't use it.
    if (self.supported_commands is not None and
        command not in self.supported_commands):
      raise QmpCommandNotSupported(f"Instance does not support the '{command}'"
                                    " QMP command.")

    message = QmpMessage({self._EXECUTE_KEY: command})
    if arguments:
      message[self._ARGUMENTS_KEY] = arguments
    logging.debug("QMP JSON Command: %s", message.to_json_string())
    self.send_qmp(message)

    ret = self.get_qmp_response(command)
    if command not in [self._QUERY_COMMANDS, self._CAPABILITIES_COMMAND]:
      logging.debug("QMP Response: %s %s: %s", command, arguments, ret)
    return ret

  def connect(self):
    """Connects to the QMP monitor.

    Connects to the UNIX socket and makes sure that we can actually send and
    receive data to the kvm instance via QMP.

    @raise errors.HypervisorError: when there are communication errors
    @raise errors.ProgrammerError: when there are data serialization errors

    """
    super(QmpConnection, self).connect()
    # sometimes we receive asynchronous events instead of the intended greeting
    # message - we ignore these for now. However, only 5 times to not get stuck
    # in an endless connect() loop.
    for x in range(0, 4):
      # Check if we receive a correct greeting message from the server
      # (As per the QEMU Protocol Specification 0.1 - section 2.2)
      greeting = self.recv_qmp()
      if greeting[self._EVENT_KEY]:
        continue
      if not greeting[self._FIRST_MESSAGE_KEY]:
        self.close()
        raise errors.HypervisorError("kvm: QMP communication error (wrong"
                                     " server greeting)")
      else:
        break

    # Extract the version info from the greeting and make it available to users
    # of the monitor.
    version_info = greeting[self._FIRST_MESSAGE_KEY][self._VERSION_KEY]

    self.version = (version_info[self._QEMU_KEY]["major"],
                    version_info[self._QEMU_KEY]["minor"],
                    version_info[self._QEMU_KEY]["micro"])
    self.package = version_info[self._PACKAGE_KEY].strip()

    # This is needed because QMP can return more than one greetings
    # see https://groups.google.com/d/msg/ganeti-devel/gZYcvHKDooU/SnukC8dgS5AJ
    self._buffer = b""

    # Let's put the monitor in command mode using the qmp_capabilities
    # command, or else no command will be executable.
    # (As per the QEMU Protocol Specification 0.1 - section 4)
    self.execute_qmp(self._CAPABILITIES_COMMAND)
    self.supported_commands = self._GetSupportedCommands()

  def _GetSupportedCommands(self):
    """Update the list of supported commands.

    """
    result = self.execute_qmp(self._QUERY_COMMANDS)
    return frozenset(com["name"] for com in result)

  def _filter_hvinfo(self, hvinfo):
    """Filter non valid keys of the device's hvinfo (if any)."""
    ret = {}
    for k in self._DEVICE_ATTRIBUTES:
      if k in hvinfo:
        ret[k] = hvinfo[k]

    return ret

  @_ensure_connection
  def HotAddNic(self, nic, devid, tapfds=None, vhostfds=None, features=None,
                is_chrooted=False):
    """Hot-add a NIC

    First pass the tapfds, then netdev_add and then device_add

    """
    if tapfds is None:
      tapfds = []
    if vhostfds is None:
      vhostfds = []
    if features is None:
      features = {}

    enable_vhost = features.get("vhost", False)
    enable_mq, virtio_net_queues = features.get("mq", (False, 1))

    fdnames = []
    for i, fd in enumerate(tapfds):
      fdname = "%s-%d" % (devid, i)
      self._GetFd(fd, fdname)
      fdnames.append(fdname)

    arguments = {
      "type": "tap",
      "id": devid,
      "fds": ":".join(fdnames),
    }

    if enable_vhost:
      fdnames = []
      for i, fd in enumerate(vhostfds):
        fdname = "%s-vhost-%d" % (devid, i)
        self._GetFd(fd, fdname)
        fdnames.append(fdname)

      arguments.update({
        "vhost": True,
        "vhostfds": ":".join(fdnames),
        })
    self.execute_qmp("netdev_add", arguments)

    arguments = {
      "netdev": devid,
      "mac": nic.mac,
    }
    if is_chrooted:
      # do not try to load a rom file when we are running qemu chrooted
      arguments.update({
        "romfile": "",
      })
    # _filter_hvinfo drops keys not in _DEVICE_ATTRIBUTES; on q35 the
    # NIC's hvinfo also carries acpi-index for stable eno<N> naming.
    arguments.update(self._filter_hvinfo(nic.hvinfo))
    if enable_mq:
      arguments.update({
        "mq": True,
        "vectors": (2 * virtio_net_queues + 2),
        })
    self.execute_qmp("device_add", arguments)

  @_ensure_connection
  def HotDelNic(self, devid):
    """Hot-del a NIC

    Issues device_del, then waits for DEVICE_DELETED before removing the
    netdev backend.  On q35/PCIe the guest's pciehp driver must release
    the device before QEMU can detach it; netdev_del must not run until
    then or QEMU will error on a still-live frontend.

    """
    self.execute_qmp("device_del", {"id": devid})

    event = self.wait_for_qmp_event(
      ["DEVICE_DELETED", "DEVICE_UNPLUG_GUEST_ERROR"],
      self._HOT_UNPLUG_EVENT_TIMEOUT)
    if event is None:
      raise errors.HypervisorError(
        f"Hot-unplug of {devid} not acknowledged by guest within"
        f" {self._HOT_UNPLUG_EVENT_TIMEOUT}s. On q35 the guest's PCIe"
        " hotplug driver (pciehp) must release the device before QEMU"
        " can remove it. Verify the guest's kernel has"
        " CONFIG_HOTPLUG_PCI_PCIE and is responsive.")
    elif event.event_type == "DEVICE_UNPLUG_GUEST_ERROR":
      raise errors.HypervisorError(
        f"DEVICE_UNPLUG_GUEST_ERROR event occurred for {devid}")

    self.execute_qmp("netdev_del", {"id": devid})

  @_ensure_connection
  def HotAddDisk(self, disk, access_mode, cache_writeback, direct, blockdevice):
    """Hot-add a disk

    """

    if access_mode == constants.DISK_KERNELSPACE:
      qemu_version = self.GetVersion()
      if qemu_version >= (9, 0, 0) and direct:
        # starting with qemu v9 it is required to
        # use O_DIRECT for opening the blockdevice
        # when `direct` is set
        flags = os.O_RDWR|os.O_DIRECT
      else:
        flags = os.O_RDWR
      fd = os.open(blockdevice["file"]["filename"], flags)
      fdset = self._AddFd(fd)
      os.close(fd)
      blockdevice["file"]["filename"] = "/dev/fdset/%s" % fdset
    else:
      fdset = None

    dev_arguments = {
      "drive": blockdevice["node-name"],
      "write-cache": kvm_utils.TranslateBoolToOnOff(cache_writeback)
    }
    # Note that hvinfo that _GenerateDeviceHVInfo() creates
    # should include *only* the driver, id, bus, and
    # addr or channel, scsi-id, and lun keys
    dev_arguments.update(self._filter_hvinfo(disk.hvinfo))

    self.execute_qmp("blockdev-add", blockdevice)
    self.execute_qmp("device_add", dev_arguments)

    if fdset is not None:
      self._RemoveFdset(fdset)

  @_ensure_connection
  def HotDelDisk(self, devid):
    """Hot-del a Disk

    """
    self.execute_qmp("device_del", {"id": devid})

    event = self.wait_for_qmp_event(
      ["DEVICE_DELETED", "DEVICE_UNPLUG_GUEST_ERROR"],
      self._HOT_UNPLUG_EVENT_TIMEOUT)
    if event is None:
      raise errors.HypervisorError(
        f"Hot-unplug of {devid} not acknowledged by guest within"
        f" {self._HOT_UNPLUG_EVENT_TIMEOUT}s. On q35 the guest's PCIe"
        " hotplug driver (pciehp) must release the device before QEMU"
        " can remove it. Verify the guest's kernel has"
        " CONFIG_HOTPLUG_PCI_PCIE and is responsive.")
    elif event.event_type == "DEVICE_UNPLUG_GUEST_ERROR":
      raise errors.HypervisorError(
        f"DEVICE_UNPLUG_GUEST_ERROR event occurred for {devid}")

    self.execute_qmp("blockdev-del", {"node-name": devid})

  def _GetPCIDevices(self):
    """Get the devices of the first PCI bus of a running instance.

    """
    pci = self.execute_qmp("query-pci")
    bus = pci[0]
    devices = bus["devices"]
    return devices


  @_ensure_connection
  def ResizeBlockDevice(self, disk_id: str, new_size: int):
    """ Notify the guest about a disk change.
    """
    arguments = {
      "node-name": disk_id,
      "size": new_size
    }

    self.execute_qmp("block_resize", arguments)


  def _HasPCIDevice(self, devid):
    """Check if a specific device ID exists on the PCI bus.

    Walks C{pci_bridge} subtrees too: on q35 leaf devices live behind
    a pre-allocated C{pcie-root-port}, not on the top-level C{pcie.0}
    bus, so a flat scan of the top-level C{devices} list misses them.
    On i440fx the leaves sit directly on C{pci.0} with no
    C{pci_bridge} field, so the recursion is a no-op there.
    """
    return self._GetPCIDeviceInfo(devid) is not None

  def _GetPCIDeviceInfo(self, devid):
    """Return the full C{query-pci} entry for a given qdev_id.

    Same recursive walk as L{_HasPCIDevice} (handles q35 leaves behind a
    C{pcie-root-port}), but returns the device dict so callers can
    inspect runtime fields such as C{regions} and C{irq}. Returns
    C{None} if the device is not present on a PCI bus (e.g. SCSI luns
    behind an HBA).

    """
    def _walk(devices):
      for device in devices:
        if device.get("qdev_id") == devid:
          return device
        found = _walk((device.get("pci_bridge") or {}).get("devices", []))
        if found is not None:
          return found
      return None

    return _walk(self._GetPCIDevices())

  @staticmethod
  def _IsPCIDeviceClaimed(info):
    """Check whether the guest has visibly claimed a PCI device.

    The C{query-pci} fields that move once the guest's PCI subsystem
    (pciehp on q35) has finished bringing the slot up:

      - Any BAR C{regions[*].address} flips from C{-1} (the QEMU
        placeholder for an unassigned BAR) to a real bus address once
        the guest allocates PCI resources. This is the primary signal
        because it requires guest-side action.
      - C{irq} flips from C{0} to a non-zero line once INTx is wired.
        This is a secondary signal: virtio-pci with MSI-X may
        legitimately keep C{irq=0} even when fully online, so it must
        not be used as the sole indicator.

    Use (BAR populated) OR (irq != 0) so both INTx-only and MSI-X
    device types are covered.

    """
    for region in info.get("regions", []):
      if region.get("address", -1) != -1:
        return True
    if info.get("irq", 0):
      return True
    return False

  @_ensure_connection
  def WaitForDeviceClaim(self, devid, timeout=None):
    """Wait for the guest to claim a freshly hot-added PCI(e) device.

    There is no QEMU signal which will tell us that a given PCI(e)
    device has been picked up / claimed by the guest. So we need to
    figure out a different way of detecting the guest has accepted
    the device. Especially on Q35 chipsets it is important to feed
    failure back to the user because subsequent HotRemove requests to
    the same device will fail if the guest has never claimed the device
    in the first place.

    Runs on both chipsets. On i440fx leaves attach directly to C{pci.0}
    and BARs are assigned synchronously at C{device_add} time, so the
    predicate (BAR mapped OR C{irq != 0}) is normally satisfied on the
    first poll and the call returns immediately. On q35 the guest's
    pciehp driver has to online the slot first, so the wait may take
    up to C{timeout} seconds before BARs/IRQ are observable. We
    deliberately run it on both paths so the BAR/IRQ predicate is the
    single source of truth for "device is usable" - keeping the
    behavioural contract identical between chipsets.

    @raise errors.HypervisorError: if the device is still unclaimed
        after C{timeout} seconds.

    """
    if timeout is None:
      timeout = self._HOT_PLUG_CLAIM_TIMEOUT

    deadline = time.monotonic() + timeout
    while True:
      info = self._GetPCIDeviceInfo(devid)
      if info is None:
        return
      if self._IsPCIDeviceClaimed(info):
        return
      if time.monotonic() >= deadline:
        raise errors.HypervisorError(
          f"Guest did not claim hot-added device {devid} within"
          f" {timeout}s. On q35 the guest's PCIe hotplug driver"
          " (pciehp) must bring the device online before it is usable."
          " Verify the guest's kernel has CONFIG_HOTPLUG_PCI_PCIE"
          " enabled and is responsive.")
      time.sleep(self._HOT_PLUG_CLAIM_POLL_INTERVAL)

  def _GetBlockDevices(self):
    """Get the block devices of a running instance.

    The query-block QMP command returns a list of dictionaries
    including information for each virtual disk. For example:

    [{"device": "disk-049f140d", "inserted": {"file": ..., "image": ...}}]

    @rtype: list of dicts
    @return: Info about the virtual disks of the instance.

    """
    devices = self.execute_qmp("query-block")
    return devices


  def _HasBlockDevice(self, devid):
    """Check if a specific device ID exists among block devices.

    """
    for d in self._GetBlockDevices():
      if d["device"] == devid:
        return True

    return False

  @_ensure_connection
  def HasDevice(self, devid):
    """Check if a specific device exists or not on a running instance.

    It first checks the PCI devices and then the block devices.

    """
    if (self._HasPCIDevice(devid) or self._HasBlockDevice(devid)):
      return True

    return False

  @_ensure_connection
  def GetFreePCISlot(self):
    """Get the first available PCI slot of a running instance.

    """
    slots = bitarray(constants.QEMU_PCI_SLOTS)
    slots.setall(False)  # pylint: disable=E1101
    for d in self._GetPCIDevices():
      slot = d["slot"]
      slots[slot] = True

    return utils.GetFreeSlot(slots)

  @_ensure_connection
  def CheckDiskHotAddSupport(self):
    """Check if disk hotplug is possible

    Hotplug is *not* supported in case the add-fd and blockdev-add qmp commands
    are not supported

    """
    def _raise(reason):
      raise errors.HotplugError("Cannot hot-add disk: %s." % reason)

    if "add-fd" not in self.supported_commands:
      _raise("add-fd qmp command is not supported")

    if "blockdev-add" not in self.supported_commands:
      _raise("blockdev-add qmp command is not supported")

  @_ensure_connection
  def CheckNicHotAddSupport(self):
    """Check if NIC hotplug is possible

    Hotplug is *not* supported in case the getfd and netdev_add qmp commands
    are not supported

    """
    def _raise(reason):
      raise errors.HotplugError("Cannot hot-add NIC: %s." % reason)

    if "getfd" not in self.supported_commands:
      _raise("getfd qmp command is not supported")

    if "netdev_add" not in self.supported_commands:
      _raise("netdev_add qmp command is not supported")

  @_ensure_connection
  def GetVersion(self):
    """Return the QMP/qemu version field

    Accessing the version attribute directly might result in an error
    since the socket might not be yet connected. This getter method
    uses the @_ensure_connection decorator to work around this problem.
    """
    return self.version

  @_ensure_connection
  def HasDynamicAutoReadOnly(self):
    """Check if QEMU uses dynamic auto-read-only for block devices

    Use QMP schema introspection (QEMU 2.5+) to check for the
    dynamic-auto-read-only feature.
    """
    schema = self.execute_qmp("query-qmp-schema")

    # QEMU 4.0 did not have a feature flag, but has dynamic auto-read-only
    # support.
    if self.version[:2] == (4, 0):
      return True

    return any([x for x in schema
                if "dynamic-auto-read-only" in x.get("features",[])])

  @_ensure_connection
  def SetMigrationParameters(self, max_bandwidth, downtime_limit):
    """Configute live migration parameters

    """

    arguments = {
      "max-bandwidth": max_bandwidth,
      "downtime-limit": downtime_limit,
    }

    if self.version >= (3, 0, 0):
      arguments["max-postcopy-bandwidth"] = max_bandwidth

    self.execute_qmp("migrate-set-parameters", arguments)

  @_ensure_connection
  def SetMigrationCapabilities(self, capabilities, state):
    """Configure live migration capabilities

    """

    arguments = {
      "capabilities": []
    }
    for capability in capabilities:
      arguments["capabilities"].append({
        "capability": capability,
        "state": state,
      })

    self.execute_qmp("migrate-set-capabilities", arguments)

  @_ensure_connection
  def StopGuestEmulation(self):
    """Pause the running guest

    """

    self.execute_qmp("stop")

  @_ensure_connection
  def ContinueGuestEmulation(self):
    """Continue the previously paused guest

    """

    self.execute_qmp("cont")

  @_ensure_connection
  def StartMigration(self, target, port):
    """Start migration of an instance

    """

    arguments = {
      "uri": "tcp:%s:%s" % (target, port)
    }

    self.execute_qmp("migrate", arguments)

  @_ensure_connection
  def StartPostcopyMigration(self):
    """ Start postcopy-ram migration

    """

    self.execute_qmp("migrate-start-postcopy")

  @_ensure_connection
  def GetCpuInformation(self):
    """ Retrieve CPU/thread information
        uses the query-cpus-fast which does not interrupt the guest
    """

    return self.execute_qmp("query-cpus-fast")

  @_ensure_connection
  def GetMigrationStatus(self):
    """Retrieve the current migration status

    """

    return self.execute_qmp("query-migrate")

  @_ensure_connection
  def SetSpicePassword(self, spice_pwd):
    """Set Spice password of an instance

    """
    arguments = {
      "protocol": "spice",
      "password": spice_pwd,
    }

    self.execute_qmp("set_password", arguments)

  @_ensure_connection
  def SetVNCPassword(self, vnc_pwd):
    """Set VNC password of an instance

    """
    arguments = {
      "protocol": "vnc",
      "password": vnc_pwd,
    }

    self.execute_qmp("set_password", arguments)

  @_ensure_connection
  def SetBalloonMemory(self, memory):
    self.execute_qmp("balloon", {"value": memory * 1048576})

  @_ensure_connection
  def Powerdown(self):
    self.execute_qmp("system_powerdown")

  def _GetFd(self, fd, fdname):
    """Wrapper around the getfd qmp command

    Send an fd to a running process via SCM_RIGHTS and then use the getfd qmp
    command to name it properly so that it can be used later by NIC
    hotplugging.

    @type fd: int
    @param fd: The file descriptor to pass
    @raise errors.HypervisorError: If getfd fails for some reason

    """
    try:
      utils.SendFds(self.sock, b" ", [fd])
      arguments = {
          "fdname": fdname,
          }
      self.execute_qmp("getfd", arguments)
    except errors.HypervisorError as err:
      logging.info("Passing fd %s via SCM_RIGHTS failed: %s", fd, err)
      raise

  def _AddFd(self, fd):
    """Wrapper around add-fd qmp command

    Send fd to a running process via SCM_RIGHTS and then add-fd qmp command to
    add it to an fdset so that it can be used later by disk hotplugging.

    @type fd: int
    @param fd: The file descriptor to pass

    @return: The fdset ID that the fd has been added to
    @raise errors.HypervisorError: If add-fd fails for some reason

    """
    try:
      utils.SendFds(self.sock, b" ", [fd])
      # Omit fdset-id and let qemu create a new one (see qmp-commands.hx)
      response = self.execute_qmp("add-fd")
      fdset = response["fdset-id"]
    except errors.HypervisorError as err:
      logging.info("Passing fd %s via SCM_RIGHTS failed: %s", fd, err)
      raise

    return fdset

  def _RemoveFdset(self, fdset):
    """Wrapper around remove-fd qmp command

    Remove the file descriptor previously passed. After qemu has dup'd the fd
    (e.g. during disk hotplug), it can be safely removed.

    """
    # Omit the fd to cleanup all fds in the fdset (see qemu/qmp-commands.hx)
    try:
      self.execute_qmp("remove-fd", {"fdset-id": fdset})
    except errors.HypervisorError as err:
      # There is no big deal if we cannot remove an fdset. This cleanup here is
      # done on a best effort basis. Upon next hot-add a new fdset will be
      # created. If we raise an exception here, that is after drive_add has
      # succeeded, the whole hot-add action will fail and the runtime file will
      # not be updated which will make the instance non migrate-able
      logging.info("Removing fdset with id %s failed: %s", fdset, err)
