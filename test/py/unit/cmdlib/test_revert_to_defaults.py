#
#

# Copyright (C) 2026 the Ganeti project
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

"""_RevertToDefaults must never strip seed params (HV_SEED_PARAMS), even
when they equal the cluster default: seed params are owned by the
instance.
"""

import os
import sys
import unittest

from ganeti import constants
from ganeti.cmdlib import instance_create

# The CmdlibTestCase support lives in the legacy test tree; make it
# importable regardless of how pytest was invoked (the make target runs
# from a temp dir without the legacy tree on sys.path).
LEGACY_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__),
                                            "..", "..", "legacy"))
if LEGACY_PATH not in sys.path:
  sys.path.insert(0, LEGACY_PATH)

# pylint: disable=C0411,C0413,E0401
from cmdlib.testsupport.cmdlib_testcase import CmdlibTestCase


class TestRevertToDefaults(CmdlibTestCase):
  """The hvparam strip loop skips HV_SEED_PARAMS members."""

  def _GetTestModule(self):
    return "instance_create"

  def _MakeLu(self, hvparams):
    lu = instance_create.LUInstanceCreate.__new__(
        instance_create.LUInstanceCreate)
    lu.op = type("FakeOp", (), {})()
    lu.op.hypervisor = constants.HT_KVM
    lu.op.os_type = "mock_os"
    lu.op.hvparams = dict(hvparams)
    lu.op.beparams = {}
    lu.op.nics = []
    lu.op.osparams = {}
    lu.op.osparams_private = {}
    return lu

  def test_seed_param_survives_non_seed_param_stripped(self):
    """boot_type (a seed param) equal to the cluster default is kept,
    while a non-seed param equal to the default is reverted."""
    self.cluster.hvparams[constants.HT_KVM][constants.HV_BOOT_TYPE] = \
        constants.HT_BOOT_BIOS
    kernel_path = self.cluster.SimpleFillHV(
        constants.HT_KVM, "mock_os", {})[constants.HV_KERNEL_PATH]
    lu = self._MakeLu({
        constants.HV_BOOT_TYPE: constants.HT_BOOT_BIOS,
        constants.HV_KERNEL_PATH: kernel_path,
    })

    lu._RevertToDefaults(self.cluster)

    self.assertEqual(constants.HT_BOOT_BIOS,
                     lu.op.hvparams[constants.HV_BOOT_TYPE])
    self.assertNotIn(constants.HV_KERNEL_PATH, lu.op.hvparams)


if __name__ == "__main__":
  unittest.main()
