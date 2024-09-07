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

from ganeti.hypervisor.hv_kvm.monitor import QmpConnection, QmpMessage
from ganeti import serializer

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
    self.socket_path = socket_path

    self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.socket.bind(self.socket_path)
    self.socket.listen(1)

  def run(self):

    conn, _ = self.socket.accept()

    # send the banner first
    conn.send(encode_data(QMP_BANNER_DATA))

    # Expect qmp_capabilities and return an empty response
    conn.recv(4096)
    conn.send(encode_data(EMPTY_RESPONSE))

    # Expect query-commands and return the list of supported commands
    conn.recv(4096)
    conn.send(encode_data(get_supported_commands()))

    while self._is_running:
      data = conn.recv(4096)
      if data != b'':
        msg = QmpMessage.build_from_json_string(data.decode('utf-8'))
        cmd = msg['execute']

        # search for a function in this file with name simulate_<command>
        if cmd in FAKE_QMP_COMMANDS.keys():
          func = FAKE_QMP_COMMANDS[cmd]
          func(conn, msg.data.get('arguments', {}))

    conn.close()

  def stop(self):
    self._is_running = False
    self.socket.close()


class TestQmpConnection:

  @pytest.fixture
  def fake_qmp(self):
    socket_path = tempfile.NamedTemporaryFile().name
    #  os.remove(socket_path)

    fake_qmp_socket = FakeQmpSocket(socket_path)
    fake_qmp_socket.daemon = True
    fake_qmp_socket.start()
    qmp = QmpConnection(socket_path)
    qmp.timeout = 1
    yield qmp

    fake_qmp_socket.stop()

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
    none_event = fake_qmp.wait_for_qmp_event('NONE_EXISTING_EVENT', 0.1)
    assert none_event is None

    fake_qmp.execute_qmp("test-fire-event")
    test_event = fake_qmp.wait_for_qmp_event('TEST_EVENT', 0.3)
    assert test_event.event_type == "TEST_EVENT"
