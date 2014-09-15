#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.hypervisor.hv_chroot"""

import unittest
import tempfile
import shutil

from ganeti import constants
from ganeti import objects
from ganeti import hypervisor

from ganeti.hypervisor import hv_chroot

import testutils


class TestConsole(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def test(self):
    instance = objects.Instance(name="fake.example.com",
                                primary_node="node837-uuid")
    node = objects.Node(name="node837", uuid="node837-uuid", ndparams={})
    group = objects.NodeGroup(name="group164", ndparams={})
    cons = hv_chroot.ChrootManager.GetInstanceConsole(instance, node, group,
                                                      {}, {},
                                                      root_dir=self.tmpdir)
    self.assertEqual(cons.Validate(), None)
    self.assertEqual(cons.kind, constants.CONS_SSH)
    self.assertEqual(cons.host, node.name)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
