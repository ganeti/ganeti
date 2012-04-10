#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Example for using L{ganeti.rapi.testutils}"""

import logging

from ganeti import rapi

import ganeti.rapi.testutils


def main():
  # Disable log output
  logging.getLogger("").setLevel(logging.CRITICAL)

  cl = rapi.testutils.InputTestClient()

  print "Testing features ..."
  assert isinstance(cl.GetFeatures(), list)

  print "Testing node evacuation ..."
  result = cl.EvacuateNode("inst1.example.com",
                           mode=rapi.client.NODE_EVAC_PRI)
  assert result is NotImplemented

  print "Testing listing instances ..."
  for bulk in [False, True]:
    result = cl.GetInstances(bulk=bulk)
    assert result is NotImplemented

  print "Testing renaming instance ..."
  result = cl.RenameInstance("inst1.example.com", "inst2.example.com")
  assert result is NotImplemented

  print "Testing renaming instance with error ..."
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

  print "Success!"


if __name__ == "__main__":
  main()
