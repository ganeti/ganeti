#!/usr/bin/python
#

# Copyright (C) 2009 Google Inc.
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


"""Script for unittesting documentation"""

import unittest
import re
import itertools
import operator

from ganeti import _autoconf
from ganeti import utils
from ganeti import cmdlib
from ganeti import build
from ganeti import compat
from ganeti import mcpu
from ganeti import opcodes
from ganeti import constants
from ganeti.rapi import baserlib
from ganeti.rapi import rlib2
from ganeti.rapi import connector

import testutils


VALID_URI_RE = re.compile(r"^[-/a-z0-9]*$")

RAPI_OPCODE_EXCLUDE = frozenset([
  # Not yet implemented
  opcodes.OpBackupQuery,
  opcodes.OpBackupRemove,
  opcodes.OpClusterConfigQuery,
  opcodes.OpClusterRepairDiskSizes,
  opcodes.OpClusterVerify,
  opcodes.OpClusterVerifyDisks,
  opcodes.OpInstanceChangeGroup,
  opcodes.OpInstanceMove,
  opcodes.OpInstanceRecreateDisks,
  opcodes.OpNodePowercycle,
  opcodes.OpNodeQueryvols,
  opcodes.OpOobCommand,
  opcodes.OpTagsSearch,

  # Difficult if not impossible
  opcodes.OpClusterDestroy,
  opcodes.OpClusterPostInit,
  opcodes.OpClusterRename,
  opcodes.OpNodeAdd,
  opcodes.OpNodeRemove,

  # Helper opcodes (e.g. submitted by LUs)
  opcodes.OpClusterVerifyConfig,
  opcodes.OpClusterVerifyGroup,
  opcodes.OpGroupEvacuate,
  opcodes.OpGroupVerifyDisks,

  # Test opcodes
  opcodes.OpTestAllocator,
  opcodes.OpTestDelay,
  opcodes.OpTestDummy,
  opcodes.OpTestJqueue,
  ])


def _ReadDocFile(filename):
  return utils.ReadFile("%s/doc/%s" %
                        (testutils.GetSourceDir(), filename))


class TestHooksDocs(unittest.TestCase):
  def test(self):
    """Check whether all hooks are documented.

    """
    hooksdoc = _ReadDocFile("hooks.rst")

    # Reverse mapping from LU to opcode
    lu2opcode = dict((lu, op)
                     for (op, lu) in mcpu.Processor.DISPATCH_TABLE.items())
    assert len(lu2opcode) == len(mcpu.Processor.DISPATCH_TABLE), \
      "Found duplicate entries"

    for name in dir(cmdlib):
      obj = getattr(cmdlib, name)

      if (isinstance(obj, type) and
          issubclass(obj, cmdlib.LogicalUnit) and
          hasattr(obj, "HPATH")):
        self._CheckHook(name, obj, hooksdoc, lu2opcode)

  def _CheckHook(self, name, lucls, hooksdoc, lu2opcode):
    opcls = lu2opcode.get(lucls, None)

    if lucls.HTYPE is None:
      return

    # TODO: Improve this test (e.g. find hooks documented but no longer
    # existing)

    if opcls:
      self.assertTrue(re.findall("^%s$" % re.escape(opcls.OP_ID),
                                 hooksdoc, re.M),
                      msg=("Missing hook documentation for %s" %
                           (opcls.OP_ID)))

    pattern = r"^:directory:\s*%s\s*$" % re.escape(lucls.HPATH)

    self.assert_(re.findall(pattern, hooksdoc, re.M),
                 msg=("Missing documentation for hook %s/%s" %
                      (lucls.HTYPE, lucls.HPATH)))


class TestRapiDocs(unittest.TestCase):
  def _CheckRapiResource(self, uri, fixup, handler):
    docline = "%s resource." % uri
    self.assertEqual(handler.__doc__.splitlines()[0].strip(), docline,
                     msg=("First line of %r's docstring is not %r" %
                          (handler, docline)))

    # Apply fixes before testing
    for (rx, value) in fixup.items():
      uri = rx.sub(value, uri)

    self.assertTrue(VALID_URI_RE.match(uri), msg="Invalid URI %r" % uri)

  def test(self):
    """Check whether all RAPI resources are documented.

    """
    rapidoc = _ReadDocFile("rapi.rst")

    node_name = re.escape("[node_name]")
    instance_name = re.escape("[instance_name]")
    group_name = re.escape("[group_name]")
    job_id = re.escape("[job_id]")
    disk_index = re.escape("[disk_index]")
    query_res = re.escape("[resource]")

    resources = connector.GetHandlers(node_name, instance_name, group_name,
                                      job_id, disk_index, query_res)

    handler_dups = utils.FindDuplicates(resources.values())
    self.assertFalse(handler_dups,
                     msg=("Resource handlers used more than once: %r" %
                          handler_dups))

    uri_check_fixup = {
      re.compile(node_name): "node1examplecom",
      re.compile(instance_name): "inst1examplecom",
      re.compile(group_name): "group4440",
      re.compile(job_id): "9409",
      re.compile(disk_index): "123",
      re.compile(query_res): "lock",
      }

    assert compat.all(VALID_URI_RE.match(value)
                      for value in uri_check_fixup.values()), \
           "Fixup values must be valid URIs, too"

    titles = []

    prevline = None
    for line in rapidoc.splitlines():
      if re.match(r"^\++$", line):
        titles.append(prevline)

      prevline = line

    prefix_exception = frozenset(["/", "/version", "/2"])

    undocumented = []
    used_uris = []

    for key, handler in resources.iteritems():
      # Regex objects
      if hasattr(key, "match"):
        self.assert_(key.pattern.startswith("^/2/"),
                     msg="Pattern %r does not start with '^/2/'" % key.pattern)
        self.assertEqual(key.pattern[-1], "$")

        found = False
        for title in titles:
          if title.startswith("``") and title.endswith("``"):
            uri = title[2:-2]
            if key.match(uri):
              self._CheckRapiResource(uri, uri_check_fixup, handler)
              used_uris.append(uri)
              found = True
              break

        if not found:
          # TODO: Find better way of identifying resource
          undocumented.append(key.pattern)

      else:
        self.assert_(key.startswith("/2/") or key in prefix_exception,
                     msg="Path %r does not start with '/2/'" % key)

        if ("``%s``" % key) in titles:
          self._CheckRapiResource(key, {}, handler)
          used_uris.append(key)
        else:
          undocumented.append(key)

    self.failIf(undocumented,
                msg=("Missing RAPI resource documentation for %s" %
                     utils.CommaJoin(undocumented)))

    uri_dups = utils.FindDuplicates(used_uris)
    self.failIf(uri_dups,
                msg=("URIs matched by more than one resource: %s" %
                     utils.CommaJoin(uri_dups)))

    self._FindRapiMissing(resources.values())
    self._CheckTagHandlers(resources.values())

  def _FindRapiMissing(self, handlers):
    used = frozenset(itertools.chain(*map(baserlib.GetResourceOpcodes,
                                          handlers)))

    unexpected = used & RAPI_OPCODE_EXCLUDE
    self.assertFalse(unexpected,
      msg=("Found RAPI resources for excluded opcodes: %s" %
           utils.CommaJoin(_GetOpIds(unexpected))))

    missing = (frozenset(opcodes.OP_MAPPING.values()) - used -
               RAPI_OPCODE_EXCLUDE)
    self.assertFalse(missing,
      msg=("Missing RAPI resources for opcodes: %s" %
           utils.CommaJoin(_GetOpIds(missing))))

  def _CheckTagHandlers(self, handlers):
    tag_handlers = filter(lambda x: issubclass(x, rlib2._R_Tags), handlers)
    self.assertEqual(frozenset(map(operator.attrgetter("TAG_LEVEL"),
                                   tag_handlers)),
                     constants.VALID_TAG_TYPES)


def _GetOpIds(ops):
  """Returns C{OP_ID} for all opcodes in passed sequence.

  """
  return sorted(opcls.OP_ID for opcls in ops)


class TestManpages(unittest.TestCase):
  """Manpage tests"""

  @staticmethod
  def _ReadManFile(name):
    return utils.ReadFile("%s/man/%s.rst" %
                          (testutils.GetSourceDir(), name))

  @staticmethod
  def _LoadScript(name):
    return build.LoadModule("scripts/%s" % name)

  def test(self):
    for script in _autoconf.GNT_SCRIPTS:
      self._CheckManpage(script,
                         self._ReadManFile(script),
                         self._LoadScript(script).commands.keys())

  def _CheckManpage(self, script, mantext, commands):
    missing = []

    for cmd in commands:
      pattern = r"^(\| )?\*\*%s\*\*" % re.escape(cmd)
      if not re.findall(pattern, mantext, re.DOTALL | re.MULTILINE):
        missing.append(cmd)

    self.failIf(missing,
                msg=("Manpage for '%s' missing documentation for %s" %
                     (script, utils.CommaJoin(missing))))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
