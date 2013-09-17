#
#

# Copyright (C) 2013 Google Inc.
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


"""Utility functions or the cmdlib test framework"""


import mock


# pylint: disable=C0103
def patchModule(module_under_test, mock_module, **kwargs):
  """Computes the module prefix required to mock parts of the Ganeti code.

  @type module_under_test: string
  @param module_under_test: the module within cmdlib which is tested. The
        "ganeti.cmdlib" prefix is optional.
  @type mock_module
  @param mock_module: the module which should be mocked.

  """
  if not module_under_test.startswith("ganeti.cmdlib"):
    module_under_test = "ganeti.cmdlib." + module_under_test
  return mock.patch("%s.%s" % (module_under_test, mock_module), **kwargs)
