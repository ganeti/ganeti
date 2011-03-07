#
#

# Copyright (C) 2007, 2008, 2009, 2010, 2011 Google Inc.
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


"""OS related QA tests.

"""

import os
import os.path

from ganeti import utils
from ganeti import constants

import qa_config
import qa_utils

from qa_utils import AssertCommand


_TEMP_OS_NAME = "TEMP-Ganeti-QA-OS"
_TEMP_OS_PATH = os.path.join(constants.OS_SEARCH_PATH[0], _TEMP_OS_NAME)

(_ALL_VALID,
 _ALL_INVALID,
 _PARTIALLY_VALID) = range(1, 4)


def TestOsList():
  """gnt-os list"""
  AssertCommand(["gnt-os", "list"])


def TestOsDiagnose():
  """gnt-os diagnose"""
  AssertCommand(["gnt-os", "diagnose"])


def _TestOsModify(hvp_dict, fail=False):
  """gnt-os modify"""
  cmd = ['gnt-os', 'modify']

  for hv_name, hv_params in hvp_dict.items():
    cmd.append('-H')
    options = []
    for key, value in hv_params.items():
      options.append("%s=%s" % (key, value))
    cmd.append('%s:%s' % (hv_name, ','.join(options)))

  cmd.append(_TEMP_OS_NAME)
  AssertCommand(cmd, fail=fail)


def _TestOsStates():
  """gnt-os modify, more stuff"""
  cmd = ["gnt-os", "modify"]

  for param in ["hidden", "blacklisted"]:
    for val in ["yes", "no"]:
      new_cmd = cmd + ["--%s" % param, val, _TEMP_OS_NAME]
      AssertCommand(new_cmd)
      # check that double-running the command is OK
      AssertCommand(new_cmd)


def _SetupTempOs(node, dirname, valid):
  """Creates a temporary OS definition on the given node.

  """
  sq = utils.ShellQuoteArgs
  parts = [sq(["rm", "-rf", dirname]),
           sq(["mkdir", "-p", dirname]),
           sq(["cd", dirname]),
           sq(["ln", "-fs", "/bin/true", "export"]),
           sq(["ln", "-fs", "/bin/true", "import"]),
           sq(["ln", "-fs", "/bin/true", "rename"])]

  if valid:
    parts.append(sq(["ln", "-fs", "/bin/true", "create"]))

  parts.append(sq(["echo", str(constants.OS_API_V10)]) +
               " >ganeti_api_version")

  cmd = ' && '.join(parts)

  print qa_utils.FormatInfo("Setting up %s with %s OS definition" %
                            (node["primary"],
                             ["an invalid", "a valid"][int(valid)]))

  AssertCommand(cmd, node=node)


def _RemoveTempOs(node, dirname):
  """Removes a temporary OS definition.

  """
  AssertCommand(["rm", "-rf", dirname], node=node)


def _TestOs(mode):
  """Generic function for OS definition testing

  """
  dirname = _TEMP_OS_PATH

  nodes = []
  try:
    for i, node in enumerate(qa_config.get("nodes")):
      nodes.append(node)
      if mode == _ALL_INVALID:
        valid = False
      elif mode == _ALL_VALID:
        valid = True
      elif mode == _PARTIALLY_VALID:
        valid = bool(i % 2)
      else:
        raise AssertionError("Unknown mode %s" % mode)
      _SetupTempOs(node, dirname, valid)

    AssertCommand(["gnt-os", "diagnose"], fail=(mode != _ALL_VALID))
  finally:
    for node in nodes:
      _RemoveTempOs(node, dirname)


def TestOsValid():
  """Testing valid OS definition"""
  return _TestOs(_ALL_VALID)


def TestOsInvalid():
  """Testing invalid OS definition"""
  return _TestOs(_ALL_INVALID)


def TestOsPartiallyValid():
  """Testing partially valid OS definition"""
  return _TestOs(_PARTIALLY_VALID)


def TestOsModifyValid():
  """Testing a valid os modify invocation"""
  hv_dict = {
    constants.HT_XEN_PVM: {
      constants.HV_ROOT_PATH: "/dev/sda5",
      },
    constants.HT_XEN_HVM: {
      constants.HV_ACPI: False,
      constants.HV_PAE: True,
      },
    }

  return _TestOsModify(hv_dict)


def TestOsModifyInvalid():
  """Testing an invalid os modify invocation"""
  hv_dict = {
    "blahblahblubb": {"bar": ""},
    }

  return _TestOsModify(hv_dict, fail=True)


def TestOsStates():
  """Testing OS states"""

  return _TestOsStates()
