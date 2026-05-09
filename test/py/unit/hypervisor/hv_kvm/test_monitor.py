#
#

# Copyright (C) 2024 the Ganeti project
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

import threading
import socket
import tempfile
import time
from typing import Dict, List

import pytest

from ganeti.hypervisor.hv_kvm.monitor import (
  QmpConnection,
  QmpEvent,
  QmpMessage,
  QmpTimestamp,
)
from ganeti import errors, serializer

QMP_VERSION_MICRO = 50
QMP_VERSION_MINOR = 13
QMP_VERSION_MAJOR = 0

QMP_BANNER_DATA = {
  "QMP": {
    "version": {
      "package": "",
      "qemu": {
        "micro": QMP_VERSION_MICRO,
        "minor": QMP_VERSION_MINOR,
        "major": QMP_VERSION_MAJOR,
      },
      "capabilities": [],
    },
  }
}

EMPTY_RESPONSE = {
  "return": [],
}

FAKE_QMP_COMMANDS = {}


def simulate_qmp(command: str):
  """Register a function that will be executed by the given qmp command.

  @param command: The command on which the function listens
  """

  def decorator(func):
    FAKE_QMP_COMMANDS[command] = func
    return func

  return decorator


def encode_data(data: dict) -> bytes:
  return serializer.DumpJson(data) + QmpConnection._MESSAGE_END_TOKEN


def get_qmp_commands() -> List[str]:
  return list(FAKE_QMP_COMMANDS.keys())


def get_supported_commands() -> Dict:
  commands = {'return': []}
  for cmd in get_qmp_commands():
    command_item = {
      'name': cmd.replace('_', '-')
    }
    commands['return'].append(command_item)

  return commands


@simulate_qmp('test-command')
def simulate_test_command(sock: socket.socket, arguments: Dict):
  sock.send(encode_data({"return": arguments}))


@simulate_qmp('test-fire-event')
def simulate_test_fire_event(sock: socket.socket, arguments: Dict):
  sock.send(encode_data({"return": arguments}))
  event_data = {
    "event": "TEST_EVENT",
    "timestamp": {
      "seconds": 1401385907,
      "microseconds": 422329
    },
    "data": {}
  }
  time.sleep(0.2)
  sock.send(encode_data(event_data))


class FakeQmpSocket(threading.Thread):

  def __init__(self, socket_path):
    threading.Thread.__init__(self)
    self._is_running = True
    self._is_simulate = True
    self._conn = None
    self.socket_path = socket_path

    self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.socket.bind(self.socket_path)
    self.socket.listen(1)

  def run(self):

    conn, _ = self.socket.accept()
    self._conn = conn

    # send the banner first
    conn.send(encode_data(QMP_BANNER_DATA))

    # Expect qmp_capabilities and return an empty response
    conn.recv(4096)
    conn.send(encode_data(EMPTY_RESPONSE))

    # Expect query-commands and return the list of supported commands
    conn.recv(4096)
    conn.send(encode_data(get_supported_commands()))

    while self._is_running:
      while self._is_simulate:
        data = conn.recv(4096)
        if data != b'':
          msg = QmpMessage.build_from_json_string(data.decode('utf-8'))
          cmd = msg['execute']

          # check if the function exists with simulate_qmp decorator
          if cmd in FAKE_QMP_COMMANDS.keys():
            func = FAKE_QMP_COMMANDS[cmd]
            func(conn, msg.data.get('arguments', {}))

    conn.close()

  def send(self, data: bytes):
    self._is_simulate = False
    self._conn.send(data)
    self._is_simulate = True

  def stop(self):
    self._is_running = False
    self.socket.close()


class TestQmpConnection:

  @pytest.fixture
  def fake_socket_path(self) -> str:
    return tempfile.NamedTemporaryFile().name

  @pytest.fixture
  def fake_qmp_socket(self, fake_socket_path):
    fake_qmp_socket = FakeQmpSocket(fake_socket_path)
    fake_qmp_socket.daemon = True
    fake_qmp_socket.start()

    yield fake_qmp_socket

    fake_qmp_socket.stop()

  @pytest.fixture
  def fake_qmp(self, fake_qmp_socket, fake_socket_path):
    qmp = QmpConnection(fake_socket_path)
    qmp.timeout = 1
    yield qmp

    if qmp.is_connected():
      qmp.close()

  def test_connect(self, fake_qmp: QmpConnection):
    fake_qmp.connect()

    # check version is successfully parsed
    assert fake_qmp.version == (
      QMP_VERSION_MAJOR,
      QMP_VERSION_MINOR,
      QMP_VERSION_MICRO
    )

    # check supported commands
    assert (fake_qmp.supported_commands ==
            frozenset(
              item["name"] for item in get_supported_commands()['return']))

  def test_recv_qmp(self, fake_qmp: QmpConnection, fake_qmp_socket):
    fake_qmp.connect()

    # get one qmp message with multiple socket send pieces
    send_pieces = ['{"ret', 'ur', 'n": {}}\r\n']
    for piece in send_pieces:
      fake_qmp_socket.send(piece.encode('utf-8'))
    qmp = fake_qmp.recv_qmp()
    assert qmp == QmpMessage.build_from_json_string("".join(send_pieces))

    # send two messages in one send and parse two
    two_msgs = ['{"return": [{"name": "quit"}, {"name": "eject"}]}\r\n',
                '{"return": {"running": true, "singlestep": false}}\r\n']
    # combine the two strings into one
    fake_qmp_socket.send("".join(two_msgs).encode('utf-8'))
    qmp_msg0 = fake_qmp.recv_qmp()
    qmp_msg1 = fake_qmp.recv_qmp()
    assert (qmp_msg0 == QmpMessage.build_from_json_string(two_msgs[0]) and
            qmp_msg1 == QmpMessage.build_from_json_string(two_msgs[1]))

  def test_execute_qmp(self, fake_qmp: QmpConnection):
    arguments = {
      'test1': 123,
      'test2': "test"
    }

    fake_qmp.connect()

    # run test command and check the returned arguments
    msg = fake_qmp.execute_qmp("test-command", arguments)
    assert msg == arguments

    # run command that does not exist
    with pytest.raises(Exception) as exc_info:
      fake_qmp.execute_qmp("non_existing_command")
    assert exc_info.type.__name__ == "QmpCommandNotSupported"

  def test_wait_for_qmp_event(self, fake_qmp: QmpConnection):
    fake_qmp.connect()

    # test None if timeout exceeds
    none_event = fake_qmp.wait_for_qmp_event(['NONE_EXISTING_EVENT'], 0.1)
    assert none_event is None

    fake_qmp.execute_qmp("test-fire-event")
    test_event = fake_qmp.wait_for_qmp_event(['TEST_EVENT'], 0.3)
    assert test_event.event_type == "TEST_EVENT"

  def test_is_connected(self, fake_qmp: QmpConnection):
    assert not fake_qmp.is_connected()
    fake_qmp.connect()
    assert fake_qmp.is_connected()
    fake_qmp.close()
    assert not fake_qmp.is_connected()


# -----------------------------------------------------------------------------
# _HasPCIDevice walks pci_bridge subtrees so q35 leafs (which live behind
# a pre-allocated pcie-root-port, not on the top-level pcie.0 bus) are
# found by hot-add / hot-del verification.
# -----------------------------------------------------------------------------
class TestHasPCIDevice:
  def _qmp_with_pci_devices(self, monkeypatch, devices):
    qmp = QmpConnection("/tmp/nonexistent-test-socket")
    monkeypatch.setattr(qmp, "_GetPCIDevices", lambda: devices)
    return qmp

  def test_finds_top_level_device(self, monkeypatch):
    # The static-MF group on q35 (and every PCI device on i440fx) is
    # a top-level entry. The original flat scan covered this case;
    # the recursive version must still cover it.
    qmp = self._qmp_with_pci_devices(monkeypatch, [
      {"qdev_id": "", "slot": 0, "function": 0},
      {"qdev_id": "spice", "slot": 2, "function": 3},
    ])
    assert qmp._HasPCIDevice("spice")
    assert not qmp._HasPCIDevice("not-here")

  def test_finds_device_nested_behind_pcie_root_port(self, monkeypatch):
    # q35 shape: pcie-root-port at top-level slot 3 hosts the actual
    # leaf one bus down via pci_bridge.devices.
    qmp = self._qmp_with_pci_devices(monkeypatch, [
      {"qdev_id": "rp3", "slot": 3, "function": 0,
       "class_info": {"desc": "PCI bridge"},
       "pci_bridge": {
         "bus": {"secondary": 1},
         "devices": [
           {"qdev_id": "nic-abc-1234", "bus": 1, "slot": 0,
            "function": 0,
            "class_info": {"desc": "Ethernet controller"}},
         ]}},
    ])
    assert qmp._HasPCIDevice("nic-abc-1234")
    # The bridge itself is also a real PCI device with a qdev_id; it
    # must remain findable (cold-boot pool root-ports are looked up
    # this way during runtime initialisation).
    assert qmp._HasPCIDevice("rp3")
    assert not qmp._HasPCIDevice("nic-xyz")

  def test_handles_empty_bridge(self, monkeypatch):
    # A pre-allocated empty pcie-root-port (no leaf attached yet) must
    # not trip the recursion or short-circuit it for other entries.
    qmp = self._qmp_with_pci_devices(monkeypatch, [
      {"qdev_id": "rp7", "slot": 7, "function": 0,
       "pci_bridge": {"bus": {"secondary": 5}, "devices": []}},
      {"qdev_id": "spice", "slot": 2, "function": 3},
    ])
    assert qmp._HasPCIDevice("rp7")
    assert qmp._HasPCIDevice("spice")
    assert not qmp._HasPCIDevice("anything-else")

  def test_finds_either_top_level_or_nested(self, monkeypatch):
    # Realistic q35 mix: balloon at top-level slot 0x02, NIC behind
    # rp3, disk behind rp4. All three must be findable.
    qmp = self._qmp_with_pci_devices(monkeypatch, [
      {"qdev_id": "", "slot": 2, "function": 0},  # balloon (anonymous)
      {"qdev_id": "rp3", "slot": 3, "function": 0,
       "pci_bridge": {"bus": {"secondary": 1}, "devices": [
         {"qdev_id": "nic-aaaa", "bus": 1, "slot": 0, "function": 0},
       ]}},
      {"qdev_id": "rp4", "slot": 4, "function": 0,
       "pci_bridge": {"bus": {"secondary": 2}, "devices": [
         {"qdev_id": "disk-bbbb", "bus": 2, "slot": 0, "function": 0},
       ]}},
    ])
    assert qmp._HasPCIDevice("nic-aaaa")
    assert qmp._HasPCIDevice("disk-bbbb")
    assert qmp._HasPCIDevice("rp3")
    assert qmp._HasPCIDevice("rp4")
    assert not qmp._HasPCIDevice("missing")


# -----------------------------------------------------------------------------
# HotDelNic must wait for DEVICE_DELETED before issuing netdev_del.
# On q35/PCIe the guest's pciehp driver mediates detach asynchronously;
# netdev_del before the event causes a QEMU error.
# -----------------------------------------------------------------------------
class TestHotDelNic:
  """Unit tests for the event-based hot-unplug path in HotDelNic."""

  def _qmp(self, monkeypatch):
    """Return a QmpConnection with the transport mocked out."""
    qmp = QmpConnection("/tmp/nonexistent-test-socket")
    # Make _ensure_connection think we are already connected so it does
    # not attempt a real socket open/close around the call.
    monkeypatch.setattr(qmp, "is_connected", lambda: True)
    return qmp

  def _make_event(self, event_type):
    ts = QmpTimestamp(seconds=0, microseconds=0)
    return QmpEvent(ts, event_type, {})

  def test_success_calls_device_del_then_netdev_del(self, monkeypatch):
    qmp = self._qmp(monkeypatch)
    calls = []
    monkeypatch.setattr(qmp, "execute_qmp",
                        lambda cmd, args=None: calls.append(cmd))
    deleted = self._make_event("DEVICE_DELETED")
    monkeypatch.setattr(qmp, "wait_for_qmp_event",
                        lambda types, timeout: deleted)

    qmp.HotDelNic("nic-abc123")

    assert calls == ["device_del", "netdev_del"]

  def test_timeout_raises_hypervisor_error_with_pciehp_hint(
      self, monkeypatch):
    qmp = self._qmp(monkeypatch)
    monkeypatch.setattr(qmp, "execute_qmp", lambda cmd, args=None: None)
    monkeypatch.setattr(qmp, "wait_for_qmp_event",
                        lambda types, timeout: None)

    with pytest.raises(errors.HypervisorError, match="pciehp"):
      qmp.HotDelNic("nic-abc123")

  def test_guest_error_event_raises_hypervisor_error(self, monkeypatch):
    qmp = self._qmp(monkeypatch)
    monkeypatch.setattr(qmp, "execute_qmp", lambda cmd, args=None: None)
    guest_err = self._make_event("DEVICE_UNPLUG_GUEST_ERROR")
    monkeypatch.setattr(qmp, "wait_for_qmp_event",
                        lambda types, timeout: guest_err)

    with pytest.raises(errors.HypervisorError,
                       match="DEVICE_UNPLUG_GUEST_ERROR"):
      qmp.HotDelNic("nic-abc123")

  def test_netdev_del_not_called_on_guest_error(self, monkeypatch):
    qmp = self._qmp(monkeypatch)
    calls = []
    monkeypatch.setattr(qmp, "execute_qmp",
                        lambda cmd, args=None: calls.append(cmd))
    guest_err = self._make_event("DEVICE_UNPLUG_GUEST_ERROR")
    monkeypatch.setattr(qmp, "wait_for_qmp_event",
                        lambda types, timeout: guest_err)

    with pytest.raises(errors.HypervisorError):
      qmp.HotDelNic("nic-abc123")

    assert "netdev_del" not in calls

  def test_netdev_del_not_called_on_timeout(self, monkeypatch):
    qmp = self._qmp(monkeypatch)
    calls = []
    monkeypatch.setattr(qmp, "execute_qmp",
                        lambda cmd, args=None: calls.append(cmd))
    monkeypatch.setattr(qmp, "wait_for_qmp_event",
                        lambda types, timeout: None)

    with pytest.raises(errors.HypervisorError):
      qmp.HotDelNic("nic-abc123")

    assert "netdev_del" not in calls


# -----------------------------------------------------------------------------
# WaitForDeviceClaim closes the hot-add side of the hotplug contract: after
# device_add succeeds, the guest's pciehp driver must online the slot (assign
# BAR addresses, wire IRQ) before any follow-up operation (in particular
# hot-unplug) is safe on q35. Without this wait, a fast unplug-then-replug
# races against pciehp and DEVICE_DELETED never fires.
# -----------------------------------------------------------------------------
class TestWaitForDeviceClaim:

  def _qmp(self, monkeypatch):
    qmp = QmpConnection("/tmp/nonexistent-test-socket")
    monkeypatch.setattr(qmp, "is_connected", lambda: True)
    return qmp

  def _dev(self, qdev_id, regions=None, irq=0):
    return {
      "qdev_id": qdev_id,
      "irq": irq,
      "regions": regions if regions is not None else [],
    }

  @staticmethod
  def _unmapped_region():
    return {"bar": 0, "size": 16384, "address": -1, "type": "memory"}

  @staticmethod
  def _mapped_region():
    return {"bar": 0, "size": 16384, "address": 0xfe000000, "type": "memory"}

  def test_returns_immediately_when_bars_already_mapped(self, monkeypatch):
    qmp = self._qmp(monkeypatch)
    device = self._dev("nic-abc", regions=[self._mapped_region()])
    monkeypatch.setattr(qmp, "_GetPCIDevices", lambda: [device])
    sleeps = []
    monkeypatch.setattr(
      "ganeti.hypervisor.hv_kvm.monitor.time.sleep", sleeps.append)

    qmp.WaitForDeviceClaim("nic-abc")

    assert sleeps == []

  def test_returns_when_irq_is_assigned_even_with_unmapped_bars(
      self, monkeypatch):
    # INTx-only devices may surface irq before any BAR is allocated; the
    # predicate must accept either signal so it works for both INTx and
    # MSI-X-capable virtio.
    qmp = self._qmp(monkeypatch)
    device = self._dev("nic-abc", regions=[self._unmapped_region()], irq=11)
    monkeypatch.setattr(qmp, "_GetPCIDevices", lambda: [device])

    qmp.WaitForDeviceClaim("nic-abc")

  def test_polls_until_bars_become_mapped(self, monkeypatch):
    qmp = self._qmp(monkeypatch)
    snapshots = [
      [self._dev("nic-abc", regions=[self._unmapped_region()])],
      [self._dev("nic-abc", regions=[self._unmapped_region()])],
      [self._dev("nic-abc", regions=[self._mapped_region()])],
    ]
    monkeypatch.setattr(qmp, "_GetPCIDevices", lambda: snapshots.pop(0))
    monkeypatch.setattr(
      "ganeti.hypervisor.hv_kvm.monitor.time.sleep", lambda _s: None)

    qmp.WaitForDeviceClaim("nic-abc")

    # all three snapshots should have been consumed
    assert snapshots == []

  def test_no_op_when_device_is_not_on_pci_bus(self, monkeypatch):
    # SCSI luns behind an HBA, USB devices, ... do not appear in
    # query-pci. The wait must not fail for them — QEMU acceptance has
    # already been verified by _VerifyHotplugCommand.
    qmp = self._qmp(monkeypatch)
    monkeypatch.setattr(qmp, "_GetPCIDevices", lambda: [])
    sleeps = []
    monkeypatch.setattr(
      "ganeti.hypervisor.hv_kvm.monitor.time.sleep", sleeps.append)

    qmp.WaitForDeviceClaim("scsi-lun-0")

    assert sleeps == []

  def test_finds_device_behind_pcie_root_port(self, monkeypatch):
    # q35 leafs live one bus down behind a pre-allocated
    # pcie-root-port. The walk must recurse into pci_bridge.devices.
    qmp = self._qmp(monkeypatch)
    monkeypatch.setattr(qmp, "_GetPCIDevices", lambda: [
      {"qdev_id": "rp3", "slot": 3, "function": 0,
       "pci_bridge": {"bus": {"secondary": 1}, "devices": [
         self._dev("nic-abc", regions=[self._mapped_region()]),
       ]}},
    ])

    qmp.WaitForDeviceClaim("nic-abc")

  def test_raises_with_pciehp_hint_after_timeout(self, monkeypatch):
    qmp = self._qmp(monkeypatch)
    monkeypatch.setattr(qmp, "_GetPCIDevices", lambda: [
      self._dev("nic-abc", regions=[self._unmapped_region()]),
    ])
    monkeypatch.setattr(
      "ganeti.hypervisor.hv_kvm.monitor.time.sleep", lambda _s: None)

    with pytest.raises(errors.HypervisorError, match="pciehp"):
      qmp.WaitForDeviceClaim("nic-abc", timeout=0)


class TestFilterHvinfo:
  """_filter_hvinfo selects keys forwarded to the device_add QMP call."""

  def test_forwards_acpi_index(self):
    # On q35, the NIC's hvinfo carries acpi-index for stable eno<N>
    # naming; without it the hot-added NIC falls back to enp<bus>s0.
    qmp = QmpConnection("/tmp/nonexistent-test-socket")
    hvinfo = {
      "driver": "virtio-net-pci",
      "id": "nic-abc",
      "bus": "rp3",
      "addr": "0x0",
      "acpi-index": 1,
    }
    assert qmp._filter_hvinfo(hvinfo) == hvinfo

  def test_drops_unknown_keys(self):
    qmp = QmpConnection("/tmp/nonexistent-test-socket")
    hvinfo = {"driver": "virtio-net-pci", "id": "x", "garbage": True}
    assert qmp._filter_hvinfo(hvinfo) == {"driver": "virtio-net-pci", "id": "x"}
