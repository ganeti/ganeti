#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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


"""Script for testing ganeti.impexpd"""

import os
import sys
import re
import unittest

from ganeti import constants
from ganeti import objects
from ganeti import compat
from ganeti import utils
from ganeti import errors
from ganeti import impexpd

import testutils


class CmdBuilderConfig(objects.ConfigObject):
  __slots__ = [
    "bind",
    "key",
    "cert",
    "ca",
    "host",
    "port",
    "compress",
    "magic",
    "connect_timeout",
    "connect_retries",
    "cmd_prefix",
    "cmd_suffix",
    ]


def CheckCmdWord(cmd, word):
  wre = re.compile(r"\b%s\b" % re.escape(word))
  return compat.any(wre.search(i) for i in cmd)


class TestCommandBuilder(unittest.TestCase):
  def test(self):
    for mode in [constants.IEM_IMPORT, constants.IEM_EXPORT]:
      if mode == constants.IEM_IMPORT:
        comprcmd = "gunzip"
      elif mode == constants.IEM_EXPORT:
        comprcmd = "gzip"

      for compress in [constants.IEC_NONE, constants.IEC_GZIP]:
        for magic in [None, 10 * "-", "HelloWorld", "J9plh4nFo2",
                      "24A02A81-2264-4B51-A882-A2AB9D85B420"]:
          opts = CmdBuilderConfig(magic=magic, compress=compress)
          builder = impexpd.CommandBuilder(mode, opts, 1, 2, 3)

          magic_cmd = builder._GetMagicCommand()
          dd_cmd = builder._GetDdCommand()

          if magic:
            self.assert_(("M=%s" % magic) in magic_cmd)
            self.assert_(("M=%s" % magic) in dd_cmd)
          else:
            self.assertFalse(magic_cmd)

        for host in ["localhost", "1.2.3.4", "192.0.2.99"]:
          for port in [0, 1, 1234, 7856, 45452]:
            for cmd_prefix in [None, "PrefixCommandGoesHere|",
                               "dd if=/dev/hda bs=1048576 |"]:
              for cmd_suffix in [None, "< /some/file/name",
                                 "| dd of=/dev/null"]:
                opts = CmdBuilderConfig(host=host, port=port, compress=compress,
                                        cmd_prefix=cmd_prefix,
                                        cmd_suffix=cmd_suffix)

                builder = impexpd.CommandBuilder(mode, opts, 1, 2, 3)

                # Check complete command
                cmd = builder.GetCommand()
                self.assert_(isinstance(cmd, list))

                if compress == constants.IEC_GZIP:
                  self.assert_(CheckCmdWord(cmd, comprcmd))

                if cmd_prefix is not None:
                  self.assert_(cmd_prefix in i for i in cmd)

                if cmd_suffix is not None:
                  self.assert_(cmd_suffix in i for i in cmd)

                # Check socat command
                socat_cmd = builder._GetSocatCommand()

                if mode == constants.IEM_IMPORT:
                  ssl_addr = socat_cmd[-2].split(",")
                  self.assert_(("OPENSSL-LISTEN:%s" % port) in ssl_addr)
                elif mode == constants.IEM_EXPORT:
                  ssl_addr = socat_cmd[-1].split(",")
                  self.assert_(("OPENSSL:%s:%s" % (host, port)) in ssl_addr)

                self.assert_("verify=1" in ssl_addr)

  def testCommaError(self):
    opts = CmdBuilderConfig(host="localhost", port=1234,
                            ca="/some/path/with,a/,comma")

    for mode in [constants.IEM_IMPORT, constants.IEM_EXPORT]:
      builder = impexpd.CommandBuilder(mode, opts, 1, 2, 3)
      self.assertRaises(errors.GenericError, builder.GetCommand)

  def testOptionLengthError(self):
    testopts = [
      CmdBuilderConfig(bind="0.0.0.0" + ("A" * impexpd.SOCAT_OPTION_MAXLEN),
                       port=1234, ca="/tmp/ca"),
      CmdBuilderConfig(host="localhost", port=1234,
                       ca="/tmp/ca" + ("B" * impexpd.SOCAT_OPTION_MAXLEN)),
      CmdBuilderConfig(host="localhost", port=1234,
                       key="/tmp/key" + ("B" * impexpd.SOCAT_OPTION_MAXLEN)),
      ]

    for opts in testopts:
      for mode in [constants.IEM_IMPORT, constants.IEM_EXPORT]:
        builder = impexpd.CommandBuilder(mode, opts, 1, 2, 3)
        self.assertRaises(errors.GenericError, builder.GetCommand)

      opts.host = "localhost" + ("A" * impexpd.SOCAT_OPTION_MAXLEN)
      builder = impexpd.CommandBuilder(constants.IEM_EXPORT, opts, 1, 2, 3)
      self.assertRaises(errors.GenericError, builder.GetCommand)

  def testModeError(self):
    mode = "foobarbaz"

    assert mode not in [constants.IEM_IMPORT, constants.IEM_EXPORT]

    opts = CmdBuilderConfig(host="localhost", port=1234)
    builder = impexpd.CommandBuilder(mode, opts, 1, 2, 3)
    self.assertRaises(errors.GenericError, builder.GetCommand)


class TestCalcThroughput(unittest.TestCase):
  def test(self):
    self.assertEqual(impexpd._CalcThroughput([]), None)
    self.assertEqual(impexpd._CalcThroughput([(0, 0)]), None)

    samples = [
      (0.0, 0.0),
      (10.0, 100.0),
      ]
    self.assertAlmostEqual(impexpd._CalcThroughput(samples), 10.0, 3)

    samples = [
      (5.0, 7.0),
      (10.0, 100.0),
      (16.0, 181.0),
      ]
    self.assertAlmostEqual(impexpd._CalcThroughput(samples), 15.818, 3)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
