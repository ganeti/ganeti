#
#

# Copyright (C) 2007, 2008, 2009, 2010, 2011 Google Inc.
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


"""OS related QA tests.

"""

import os
import os.path

from ganeti import utils
from ganeti import constants
from ganeti import pathutils

from qa import qa_config
from qa import qa_utils
from qa import qa_error

from qa_utils import AssertCommand, AssertIn, AssertNotIn


_TEMP_OS_NAME = "TEMP-Ganeti-QA-OS"
_TEMP_OS_PATH = os.path.join(pathutils.OS_SEARCH_PATH[0], _TEMP_OS_NAME)

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
  cmd = ["gnt-os", "modify"]

  for hv_name, hv_params in hvp_dict.items():
    cmd.append("-H")
    options = []
    for key, value in hv_params.items():
      options.append("%s=%s" % (key, value))
    cmd.append("%s:%s" % (hv_name, ",".join(options)))

  cmd.append(_TEMP_OS_NAME)
  AssertCommand(cmd, fail=fail)


def _TestOsStates(os_name):
  """gnt-os modify, more stuff"""
  cmd = ["gnt-os", "modify"]

  for param in ["hidden", "blacklisted"]:
    for val in ["yes", "no"]:
      new_cmd = cmd + ["--%s" % param, val, os_name]
      AssertCommand(new_cmd)
      # check that double-running the command is OK
      AssertCommand(new_cmd)


def _SetupTempOs(node, dirname, variant, valid):
  """Creates a temporary OS definition on the given node.

  """
  sq = utils.ShellQuoteArgs
  parts = [
    sq(["rm", "-rf", dirname]),
    sq(["mkdir", "-p", dirname]),
    sq(["cd", dirname]),
    sq(["ln", "-fs", "/bin/true", "export"]),
    sq(["ln", "-fs", "/bin/true", "import"]),
    sq(["ln", "-fs", "/bin/true", "rename"]),
    sq(["ln", "-fs", "/bin/true", "verify"]),
    ]

  if valid:
    parts.append(sq(["ln", "-fs", "/bin/true", "create"]))

  parts.append(sq(["echo", str(constants.OS_API_V20)]) +
               " >ganeti_api_version")

  parts.append(sq(["echo", variant]) + " >variants.list")
  parts.append(sq(["echo", "funny this is funny"]) + " >parameters.list")

  cmd = " && ".join(parts)

  print(qa_utils.FormatInfo("Setting up %s with %s OS definition" %
                            (node.primary,
                             ["an invalid", "a valid"][int(valid)])))

  AssertCommand(cmd, node=node)


def _RemoveTempOs(node, dirname):
  """Removes a temporary OS definition.

  """
  AssertCommand(["rm", "-rf", dirname], node=node)


def _TestOs(mode, rapi_cb):
  """Generic function for OS definition testing

  """
  master = qa_config.GetMasterNode()

  name = _TEMP_OS_NAME
  variant = "default"
  fullname = "%s+%s" % (name, variant)
  dirname = _TEMP_OS_PATH

  # Ensure OS is usable
  cmd = ["gnt-os", "modify", "--hidden=no", "--blacklisted=no", name]
  AssertCommand(cmd)

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
      _SetupTempOs(node, dirname, variant, valid)

    # TODO: Use Python 2.6's itertools.permutations
    for (hidden, blacklisted) in [(False, False), (True, False),
                                  (False, True), (True, True)]:
      # Change OS' visibility
      cmd = ["gnt-os", "modify", "--hidden", ["no", "yes"][int(hidden)],
             "--blacklisted", ["no", "yes"][int(blacklisted)], name]
      AssertCommand(cmd)

      # Diagnose, checking exit status
      AssertCommand(["gnt-os", "diagnose"], fail=(mode != _ALL_VALID))

      # Diagnose again, ignoring exit status
      output = qa_utils.GetCommandOutput(master.primary,
                                         "gnt-os diagnose || :")
      for line in output.splitlines():
        if line.startswith("OS: %s [global status:" % name):
          break
      else:
        raise qa_error.Error("Didn't find OS '%s' in 'gnt-os diagnose'" % name)

      # Check info for all
      cmd = ["gnt-os", "info"]
      output = qa_utils.GetCommandOutput(master.primary,
                                         utils.ShellQuoteArgs(cmd))
      AssertIn("%s:" % name, output.splitlines())

      # Check info for OS
      cmd = ["gnt-os", "info", name]
      output = qa_utils.GetCommandOutput(master.primary,
                                         utils.ShellQuoteArgs(cmd)).splitlines()
      AssertIn("%s:" % name, output)
      for (field, value) in [("valid", mode == _ALL_VALID),
                             ("hidden", hidden),
                             ("blacklisted", blacklisted)]:
        AssertIn("  - %s: %s" % (field, value), output)

      # Only valid OSes should be listed
      cmd = ["gnt-os", "list", "--no-headers"]
      output = qa_utils.GetCommandOutput(master.primary,
                                         utils.ShellQuoteArgs(cmd))
      if mode == _ALL_VALID and not (hidden or blacklisted):
        assert_fn = AssertIn
      else:
        assert_fn = AssertNotIn
      assert_fn(fullname, output.splitlines())

      # Check via RAPI
      if rapi_cb:
        assert_fn(fullname, rapi_cb())
  finally:
    for node in nodes:
      _RemoveTempOs(node, dirname)


def TestOsValid(rapi_cb):
  """Testing valid OS definition"""
  return _TestOs(_ALL_VALID, rapi_cb)


def TestOsInvalid(rapi_cb):
  """Testing invalid OS definition"""
  return _TestOs(_ALL_INVALID, rapi_cb)


def TestOsPartiallyValid(rapi_cb):
  """Testing partially valid OS definition"""
  return _TestOs(_PARTIALLY_VALID, rapi_cb)


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


def TestOsStatesNonExisting():
  """Testing OS states with non-existing OS"""
  AssertCommand(["test", "-e", _TEMP_OS_PATH], fail=True)
  return _TestOsStates(_TEMP_OS_NAME)
