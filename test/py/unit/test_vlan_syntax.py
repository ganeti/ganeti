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

"""Unit tests for the strict VLAN syntax enforced by
NIC.CheckParameterSyntax.

A VLAN specification is valid only in canonical form: an access
(untagged) VLAN written as ".VID", a trunk (tagged-only) written as
":VID[:VID...]", or a hybrid written as ".VID:VID[:VID...]". Bare
numbers (e.g. "100", "100:200") are rejected.
"""

import unittest

from ganeti import constants
from ganeti import errors
from ganeti import objects


VALID = [".1", ".4094", ":1", ":100:200", ".100:200", ".1:2:3:4"]
INVALID = ["1", "100", "100:200", "1.2", ".01", ":01", "1:2", ":",
           ".", ".100:", "100.", ".pinky", ":pinky", ".100:pinky",
           ".-1", ":.100", ".100:.200", " :100", ":100 ", "0", ".0", ":0"]


class TestCheckVlanSyntax(unittest.TestCase):
  def _Check(self, vlan):
    nicparams = {
      constants.NIC_MODE: constants.NIC_MODE_BRIDGED,
      constants.NIC_LINK: "br_mock",
      constants.NIC_VLAN: vlan,
    }
    objects.NIC.CheckParameterSyntax(nicparams)

  def test_valid_specs(self):
    for vlan in VALID:
      self._Check(vlan)

  def test_invalid_specs(self):
    for vlan in INVALID:
      self.assertRaisesRegex(
        errors.ConfigurationError, "Invalid VLAN", self._Check, vlan)

  def test_empty_vlan_ok(self):
    # empty string is the unset default and must pass
    nicparams = {
      constants.NIC_MODE: constants.NIC_MODE_BRIDGED,
      constants.NIC_LINK: "br_mock",
    }
    objects.NIC.CheckParameterSyntax(nicparams)


if __name__ == "__main__":
  unittest.main()
