#!/usr/bin/python
#

# Copyright (C) 2010, 2011 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""Script for testing the hypervisor.hv_kvm module"""

import threading
import tempfile
import unittest
import socket
import os

from ganeti import serializer
from ganeti import constants
from ganeti import compat
from ganeti import objects
from ganeti import errors

from ganeti.hypervisor import hv_kvm

import testutils


class QmpStub(threading.Thread):
  """Stub for a QMP endpoint for a KVM instance

  """
  _QMP_BANNER_DATA = {"QMP": {"version": {
                      "package": "",
                      "qemu": {"micro": 50, "minor": 13, "major": 0},
                      "capabilities": [],
                      }}}
  _EMPTY_RESPONSE = {"return": []}

  def __init__(self, socket_filename, server_responses):
    """Creates a QMP stub

    @type socket_filename: string
    @param socket_filename: filename of the UNIX socket that will be created
                            this class and used for the communication
    @type server_responses: list
    @param server_responses: list of responses that the server sends in response
                             to whatever it receives
    """
    threading.Thread.__init__(self)
    self.socket_filename = socket_filename
    self.script = server_responses

    self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    self.socket.bind(self.socket_filename)
    self.socket.listen(1)

  def run(self):
    # Hypothesis: the messages we receive contain only a complete QMP message
    # encoded in JSON.
    conn, addr = self.socket.accept()

    # Send the banner as the first thing
    conn.send(self.encode_string(self._QMP_BANNER_DATA))

    # Expect qmp_capabilities and return an empty response
    conn.recv(4096)
    conn.send(self.encode_string(self._EMPTY_RESPONSE))

    while True:
      # We ignore the expected message, as the purpose of this object is not
      # to verify the correctness of the communication but to act as a
      # partner for the SUT (System Under Test, that is QmpConnection)
      msg = conn.recv(4096)
      if not msg:
        break

      if not self.script:
        break
      response = self.script.pop(0)
      if isinstance(response, str):
        conn.send(response)
      elif isinstance(response, list):
        for chunk in response:
          conn.send(chunk)
      else:
        raise errors.ProgrammerError("Unknown response type for %s" % response)

    conn.close()

  def encode_string(self, message):
    return (serializer.DumpJson(message, indent=False) +
            hv_kvm.QmpConnection._MESSAGE_END_TOKEN)


class TestQmpMessage(testutils.GanetiTestCase):
  def testSerialization(self):
    test_data = {"execute": "command", "arguments": ["a", "b", "c"]}
    message = hv_kvm.QmpMessage(test_data)

    for k, v in test_data.items():
      self.failUnless(message[k] == v)

    rebuilt_message = hv_kvm.QmpMessage.BuildFromJsonString(str(message))
    self.failUnless(rebuilt_message == message)


class TestQmp(testutils.GanetiTestCase):
  def testQmp(self):
    requests = [
      {"execute": "query-kvm", "arguments": []},
      {"execute": "eject", "arguments": {"device": "ide1-cd0"}},
      {"execute": "query-status", "arguments": []},
      {"execute": "query-name", "arguments": []},
      ]

    server_responses = [
      # One message, one send()
      '{"return": {"enabled": true, "present": true}}\r\n',

      # Message sent using multiple send()
      ['{"retur', 'n": {}}\r\n'],

      # Multiple messages sent using one send()
      '{"return": [{"name": "quit"}, {"name": "eject"}]}\r\n'
      '{"return": {"running": true, "singlestep": false}}\r\n',
      ]

    expected_responses = [
      {"return": {"enabled": True, "present": True}},
      {"return": {}},
      {"return": [{"name": "quit"}, {"name": "eject"}]},
      {"return": {"running": True, "singlestep": False}},
      ]

    # Set up the stub
    socket_file = tempfile.NamedTemporaryFile()
    os.remove(socket_file.name)
    qmp_stub = QmpStub(socket_file.name, server_responses)
    qmp_stub.start()

    # Set up the QMP connection
    qmp_connection = hv_kvm.QmpConnection(socket_file.name)
    qmp_connection.connect()

    # Format the script
    for request, expected_response in zip(requests, expected_responses):
      response = qmp_connection.Execute(request)
      self.failUnless(response == hv_kvm.QmpMessage(expected_response))


class TestConsole(unittest.TestCase):
  def _Test(self, instance, hvparams):
    cons = hv_kvm.KVMHypervisor.GetInstanceConsole(instance, hvparams, {})
    self.assertTrue(cons.Validate())
    return cons

  def testSerial(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node6017")
    hvparams = {
      constants.HV_SERIAL_CONSOLE: True,
      constants.HV_VNC_BIND_ADDRESS: None,
      constants.HV_KVM_SPICE_BIND: None,
      }
    cons = self._Test(instance, hvparams)
    self.assertEqual(cons.kind, constants.CONS_SSH)
    self.assertEqual(cons.host, instance.primary_node)
    self.assertEqual(cons.command[0], constants.KVM_CONSOLE_WRAPPER)
    self.assertEqual(cons.command[1], constants.SOCAT_PATH)

  def testVnc(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node7235",
                                network_port=constants.VNC_BASE_PORT + 10)
    hvparams = {
      constants.HV_SERIAL_CONSOLE: False,
      constants.HV_VNC_BIND_ADDRESS: "192.0.2.1",
      constants.HV_KVM_SPICE_BIND: None,
      }
    cons = self._Test(instance, hvparams)
    self.assertEqual(cons.kind, constants.CONS_VNC)
    self.assertEqual(cons.host, "192.0.2.1")
    self.assertEqual(cons.port, constants.VNC_BASE_PORT + 10)
    self.assertEqual(cons.display, 10)

  def testSpice(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node7235",
                                network_port=11000)
    hvparams = {
      constants.HV_SERIAL_CONSOLE: False,
      constants.HV_VNC_BIND_ADDRESS: None,
      constants.HV_KVM_SPICE_BIND: "192.0.2.1",
      }
    cons = self._Test(instance, hvparams)
    self.assertEqual(cons.kind, constants.CONS_SPICE)
    self.assertEqual(cons.host, "192.0.2.1")
    self.assertEqual(cons.port, 11000)

  def testNoConsole(self):
    instance = objects.Instance(name="kvm.example.com",
                                primary_node="node24325",
                                network_port=0)
    hvparams = {
      constants.HV_SERIAL_CONSOLE: False,
      constants.HV_VNC_BIND_ADDRESS: None,
      constants.HV_KVM_SPICE_BIND: None,
      }
    cons = self._Test(instance, hvparams)
    self.assertEqual(cons.kind, constants.CONS_MESSAGE)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
