#!/usr/bin/python3
#

# Copyright (C) 2012 Google Inc.
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


"""Example for using L{ganeti.rapi.testutils}"""

import logging

from ganeti import rapi

import ganeti.rapi.testutils


def main():
  # Disable log output
  logging.getLogger("").setLevel(logging.CRITICAL)

  cl = rapi.testutils.InputTestClient()

  print("Testing features ...")
  assert isinstance(cl.GetFeatures(), list)

  print("Testing node evacuation ...")
  result = cl.EvacuateNode("inst1.example.com",
                           mode=rapi.client.NODE_EVAC_PRI)
  assert result is NotImplemented

  print("Testing listing instances ...")
  for bulk in [False, True]:
    result = cl.GetInstances(bulk=bulk)
    assert result is NotImplemented

  print("Testing renaming instance ...")
  result = cl.RenameInstance("inst1.example.com", "inst2.example.com")
  assert result is NotImplemented

  print("Testing renaming instance with error ...")
  try:
    # This test deliberately uses an invalid value for the boolean parameter
    # "ip_check"
    result = cl.RenameInstance("inst1.example.com", "inst2.example.com",
                               ip_check=["non-boolean", "value"])
  except rapi.testutils.VerificationError:
    # Verification failed as expected
    pass
  else:
    raise Exception("This test should have failed")

  print("Success!")


if __name__ == "__main__":
  main()
