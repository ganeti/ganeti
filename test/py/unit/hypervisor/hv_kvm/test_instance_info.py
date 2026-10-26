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

import errno
from unittest import mock

import pytest

from ganeti.hypervisor import hv_kvm
from ganeti.hypervisor import hv_base


@pytest.fixture
def hypervisor():
  # The constructor only ensures the runtime directories exist; stub that out
  # so the tests can run without touching the filesystem.
  with mock.patch("ganeti.utils.EnsureDirs"):
    yield hv_kvm.KVMHypervisor()


class TestGetInstanceInfoSocketRace:
  """Regression tests for transient QMP socket races.

  During parallel instance creation/removal (exercised by the QA test
  TestParallelMaxInstanceCreationPerformance) an instance may be queried while
  it is still starting up -- before qemu has created its QMP control socket --
  or while it is being torn down, after the socket has already been removed.
  In that window socket.connect() raises FileNotFoundError, which previously
  escaped GetInstanceInfo/GetAllInstancesInfo and failed the whole node RPC,
  aborting unrelated instance-creation jobs via the IAllocator.

  """

  def test_missing_qmp_socket_is_non_fatal(self, hypervisor):
    with mock.patch.object(hypervisor, "_InstancePidAlive",
                           return_value=("file", 1234, True)), \
         mock.patch.object(hypervisor, "_InstancePidInfo",
                           return_value=(1234, 768, 2)), \
         mock.patch.object(hypervisor, "_InstanceQmpMonitor",
                           return_value="/nonexistent/socket"), \
         mock.patch("ganeti.hypervisor.hv_kvm.QmpConnection") as qmp:
      qmp.return_value.connect.side_effect = \
          FileNotFoundError(errno.ENOENT, "No such file or directory")

      info = hypervisor.GetInstanceInfo("inst1.example.com")

    # We must still get the pid-derived information back instead of an error.
    assert info is not None
    name, pid, memory, vcpus, state, _ = info
    assert name == "inst1.example.com"
    assert pid == 1234
    assert memory == 768
    assert vcpus == 2
    assert state == hv_base.HvInstanceState.RUNNING

  def test_get_all_instances_info_skips_instance_in_flux(self, hypervisor):
    def _GetInstanceInfo(name, hvparams=None):
      if name.startswith("bad"):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")
      return (name, 1234, 768, 2, hv_base.HvInstanceState.RUNNING, 0)

    with mock.patch("os.listdir",
                    return_value=["good.example.com.conf",
                                  "bad.example.com.conf"]), \
         mock.patch.object(hypervisor, "GetInstanceInfo",
                           side_effect=_GetInstanceInfo):
      data = hypervisor.GetAllInstancesInfo()

    # The instance in flux is skipped; the healthy one is still reported.
    assert [d[0] for d in data] == ["good.example.com"]
