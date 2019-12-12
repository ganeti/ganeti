#!/usr/bin/python3
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


"""Script for testing ganeti.utils.text"""

import re
import string
import time
import unittest
import os

from io import StringIO

from ganeti import constants
from ganeti import utils
from ganeti import errors

import testutils


class TestMatchNameComponent(unittest.TestCase):
  """Test case for the MatchNameComponent function"""

  def testEmptyList(self):
    """Test that there is no match against an empty list"""
    self.assertEqual(utils.MatchNameComponent("", []), None)
    self.assertEqual(utils.MatchNameComponent("test", []), None)

  def testSingleMatch(self):
    """Test that a single match is performed correctly"""
    mlist = ["test1.example.com", "test2.example.com", "test3.example.com"]
    for key in "test2", "test2.example", "test2.example.com":
      self.assertEqual(utils.MatchNameComponent(key, mlist), mlist[1])

  def testMultipleMatches(self):
    """Test that a multiple match is returned as None"""
    mlist = ["test1.example.com", "test1.example.org", "test1.example.net"]
    for key in "test1", "test1.example":
      self.assertEqual(utils.MatchNameComponent(key, mlist), None)

  def testFullMatch(self):
    """Test that a full match is returned correctly"""
    key1 = "test1"
    key2 = "test1.example"
    mlist = [key2, key2 + ".com"]
    self.assertEqual(utils.MatchNameComponent(key1, mlist), None)
    self.assertEqual(utils.MatchNameComponent(key2, mlist), key2)

  def testCaseInsensitivePartialMatch(self):
    """Test for the case_insensitive keyword"""
    mlist = ["test1.example.com", "test2.example.net"]
    self.assertEqual(utils.MatchNameComponent("test2", mlist,
                                              case_sensitive=False),
                     "test2.example.net")
    self.assertEqual(utils.MatchNameComponent("Test2", mlist,
                                              case_sensitive=False),
                     "test2.example.net")
    self.assertEqual(utils.MatchNameComponent("teSt2", mlist,
                                              case_sensitive=False),
                     "test2.example.net")
    self.assertEqual(utils.MatchNameComponent("TeSt2", mlist,
                                              case_sensitive=False),
                     "test2.example.net")

  def testCaseInsensitiveFullMatch(self):
    mlist = ["ts1.ex", "ts1.ex.org", "ts2.ex", "Ts2.ex"]

    # Between the two ts1 a full string match non-case insensitive should work
    self.assertEqual(utils.MatchNameComponent("Ts1", mlist,
                                              case_sensitive=False),
                     None)
    self.assertEqual(utils.MatchNameComponent("Ts1.ex", mlist,
                                              case_sensitive=False),
                     "ts1.ex")
    self.assertEqual(utils.MatchNameComponent("ts1.ex", mlist,
                                              case_sensitive=False),
                     "ts1.ex")

    # Between the two ts2 only case differs, so only case-match works
    self.assertEqual(utils.MatchNameComponent("ts2.ex", mlist,
                                              case_sensitive=False),
                     "ts2.ex")
    self.assertEqual(utils.MatchNameComponent("Ts2.ex", mlist,
                                              case_sensitive=False),
                     "Ts2.ex")
    self.assertEqual(utils.MatchNameComponent("TS2.ex", mlist,
                                              case_sensitive=False),
                     None)


class TestDnsNameGlobPattern(unittest.TestCase):
  def setUp(self):
    self.names = [
      "node1.example.com",
      "node2-0.example.com",
      "node2-1.example.com",
      "node1.example.net",
      "web1.example.com",
      "web2.example.com",
      "sub.site.example.com",
      ]

  def _Test(self, pattern):
    re_pat = re.compile(utils.DnsNameGlobPattern(pattern))

    return [n for n in self.names if re_pat.match(n)]

  def test(self):
    for pattern in ["xyz", "node", " ", "example.net", "x*.example.*",
                    "x*.example.com"]:
      self.assertEqual(self._Test(pattern), [])

    for pattern in ["*", "???*"]:
      self.assertEqual(self._Test(pattern), self.names)

    self.assertEqual(self._Test("node1.*.net"), ["node1.example.net"])
    self.assertEqual(self._Test("*.example.net"), ["node1.example.net"])
    self.assertEqual(self._Test("web1.example.com"), ["web1.example.com"])

    for pattern in ["*.*.*.*", "???", "*.site"]:
      self.assertEqual(self._Test(pattern), ["sub.site.example.com"])

    self.assertEqual(self._Test("node1"), [
      "node1.example.com",
      "node1.example.net",
      ])
    self.assertEqual(self._Test("node?*.example.*"), [
      "node1.example.com",
      "node2-0.example.com",
      "node2-1.example.com",
      "node1.example.net",
      ])
    self.assertEqual(self._Test("*-?"), [
      "node2-0.example.com",
      "node2-1.example.com",
      ])
    self.assertEqual(self._Test("node2-?.example.com"), [
      "node2-0.example.com",
      "node2-1.example.com",
      ])


class TestFormatUnit(unittest.TestCase):
  """Test case for the FormatUnit function"""

  def testMiB(self):
    self.assertEqual(utils.FormatUnit(1, "h"), "1M")
    self.assertEqual(utils.FormatUnit(100, "h"), "100M")
    self.assertEqual(utils.FormatUnit(1023, "h"), "1023M")

    self.assertEqual(utils.FormatUnit(1, "m"), "1")
    self.assertEqual(utils.FormatUnit(100, "m"), "100")
    self.assertEqual(utils.FormatUnit(1023, "m"), "1023")

    self.assertEqual(utils.FormatUnit(1024, "m"), "1024")
    self.assertEqual(utils.FormatUnit(1536, "m"), "1536")
    self.assertEqual(utils.FormatUnit(17133, "m"), "17133")
    self.assertEqual(utils.FormatUnit(1024 * 1024 - 1, "m"), "1048575")

  def testGiB(self):
    self.assertEqual(utils.FormatUnit(1024, "h"), "1.0G")
    self.assertEqual(utils.FormatUnit(1536, "h"), "1.5G")
    self.assertEqual(utils.FormatUnit(17133, "h"), "16.7G")
    self.assertEqual(utils.FormatUnit(1024 * 1024 - 1, "h"), "1024.0G")

    self.assertEqual(utils.FormatUnit(1024, "g"), "1.0")
    self.assertEqual(utils.FormatUnit(1536, "g"), "1.5")
    self.assertEqual(utils.FormatUnit(17133, "g"), "16.7")
    self.assertEqual(utils.FormatUnit(1024 * 1024 - 1, "g"), "1024.0")

    self.assertEqual(utils.FormatUnit(1024 * 1024, "g"), "1024.0")
    self.assertEqual(utils.FormatUnit(5120 * 1024, "g"), "5120.0")
    self.assertEqual(utils.FormatUnit(29829 * 1024, "g"), "29829.0")

  def testTiB(self):
    self.assertEqual(utils.FormatUnit(1024 * 1024, "h"), "1.0T")
    self.assertEqual(utils.FormatUnit(5120 * 1024, "h"), "5.0T")
    self.assertEqual(utils.FormatUnit(29829 * 1024, "h"), "29.1T")

    self.assertEqual(utils.FormatUnit(1024 * 1024, "t"), "1.0")
    self.assertEqual(utils.FormatUnit(5120 * 1024, "t"), "5.0")
    self.assertEqual(utils.FormatUnit(29829 * 1024, "t"), "29.1")

  def testErrors(self):
    self.assertRaises(errors.ProgrammerError, utils.FormatUnit, 1, "a")


class TestParseUnit(unittest.TestCase):
  """Test case for the ParseUnit function"""

  SCALES = (("", 1),
            ("M", 1), ("G", 1024), ("T", 1024 * 1024),
            ("MB", 1), ("GB", 1024), ("TB", 1024 * 1024),
            ("MiB", 1), ("GiB", 1024), ("TiB", 1024 * 1024))

  def testRounding(self):
    self.assertEqual(utils.ParseUnit("0"), 0)
    self.assertEqual(utils.ParseUnit("1"), 4)
    self.assertEqual(utils.ParseUnit("2"), 4)
    self.assertEqual(utils.ParseUnit("3"), 4)

    self.assertEqual(utils.ParseUnit("124"), 124)
    self.assertEqual(utils.ParseUnit("125"), 128)
    self.assertEqual(utils.ParseUnit("126"), 128)
    self.assertEqual(utils.ParseUnit("127"), 128)
    self.assertEqual(utils.ParseUnit("128"), 128)
    self.assertEqual(utils.ParseUnit("129"), 132)
    self.assertEqual(utils.ParseUnit("130"), 132)

  def testFloating(self):
    self.assertEqual(utils.ParseUnit("0"), 0)
    self.assertEqual(utils.ParseUnit("0.5"), 4)
    self.assertEqual(utils.ParseUnit("1.75"), 4)
    self.assertEqual(utils.ParseUnit("1.99"), 4)
    self.assertEqual(utils.ParseUnit("2.00"), 4)
    self.assertEqual(utils.ParseUnit("2.01"), 4)
    self.assertEqual(utils.ParseUnit("3.99"), 4)
    self.assertEqual(utils.ParseUnit("4.00"), 4)
    self.assertEqual(utils.ParseUnit("4.01"), 8)
    self.assertEqual(utils.ParseUnit("1.5G"), 1536)
    self.assertEqual(utils.ParseUnit("1.8G"), 1844)
    self.assertEqual(utils.ParseUnit("8.28T"), 8682212)

  def testSuffixes(self):
    for sep in ("", " ", "   ", "\t", "\t "):
      for suffix, scale in self.SCALES:
        for func in (lambda x: x, str.lower, str.upper):
          self.assertEqual(utils.ParseUnit("1024" + sep + func(suffix)),
                           1024 * scale)

  def testInvalidInput(self):
    for sep in ("-", "_", ",", "a"):
      for suffix, _ in self.SCALES:
        self.assertRaises(errors.UnitParseError, utils.ParseUnit,
                          "1" + sep + suffix)

    for suffix, _ in self.SCALES:
      self.assertRaises(errors.UnitParseError, utils.ParseUnit,
                        "1,3" + suffix)


class TestShellQuoting(unittest.TestCase):
  """Test case for shell quoting functions"""

  def testShellQuote(self):
    self.assertEqual(utils.ShellQuote("abc"), "abc")
    self.assertEqual(utils.ShellQuote('ab"c'), "'ab\"c'")
    self.assertEqual(utils.ShellQuote("a'bc"), "'a'\\''bc'")
    self.assertEqual(utils.ShellQuote("a b c"), "'a b c'")
    self.assertEqual(utils.ShellQuote("a b\\ c"), "'a b\\ c'")

  def testShellQuoteArgs(self):
    self.assertEqual(utils.ShellQuoteArgs(["a", "b", "c"]), "a b c")
    self.assertEqual(utils.ShellQuoteArgs(['a', 'b"', 'c']), "a 'b\"' c")
    self.assertEqual(utils.ShellQuoteArgs(['a', 'b\'', 'c']), "a 'b'\\\''' c")


class TestShellWriter(unittest.TestCase):
  def test(self):
    buf = StringIO()
    sw = utils.ShellWriter(buf)
    sw.Write("#!/bin/bash")
    sw.Write("if true; then")
    sw.IncIndent()
    try:
      sw.Write("echo true")

      sw.Write("for i in 1 2 3")
      sw.Write("do")
      sw.IncIndent()
      try:
        self.assertEqual(sw._indent, 2)
        sw.Write("date")
      finally:
        sw.DecIndent()
      sw.Write("done")
    finally:
      sw.DecIndent()
    sw.Write("echo %s", utils.ShellQuote("Hello World"))
    sw.Write("exit 0")

    self.assertEqual(sw._indent, 0)

    output = buf.getvalue()

    self.assertTrue(output.endswith("\n"))

    lines = output.splitlines()
    self.assertEqual(len(lines), 9)
    self.assertEqual(lines[0], "#!/bin/bash")
    self.assertTrue(re.match(r"^\s+date$", lines[5]))
    self.assertEqual(lines[7], "echo 'Hello World'")

  def testEmpty(self):
    buf = StringIO()
    sw = utils.ShellWriter(buf)
    sw = None
    self.assertEqual(buf.getvalue(), "")

  def testEmptyNoIndent(self):
    buf = StringIO()
    sw = utils.ShellWriter(buf, indent=False)
    sw = None
    self.assertEqual(buf.getvalue(), "")

  @classmethod
  def _AddLevel(cls, sw, level):
    if level == 6:
      return

    sw.IncIndent()
    try:
      # Add empty line, it should not be indented
      sw.Write("")
      sw.Write(str(level))
      cls._AddLevel(sw, level + 1)
    finally:
      sw.DecIndent()

  def testEmptyLines(self):
    buf = StringIO()
    sw = utils.ShellWriter(buf)

    self._AddLevel(sw, 1)

    self.assertEqual(buf.getvalue(),
                     "".join("\n%s%s\n" % (i * "  ", i) for i in range(1, 6)))

  def testEmptyLinesNoIndent(self):
    buf = StringIO()
    sw = utils.ShellWriter(buf, indent=False)

    self._AddLevel(sw, 1)

    self.assertEqual(buf.getvalue(),
                     "".join("\n%s\n" % i for i in range(1, 6)))


class TestNormalizeAndValidateMac(unittest.TestCase):
  def testInvalid(self):
    for i in ["xxx", "00:11:22:33:44:55:66", "zz:zz:zz:zz:zz:zz"]:
      self.assertRaises(errors.OpPrereqError, utils.NormalizeAndValidateMac, i)

  def testNormalization(self):
    for mac in ["aa:bb:cc:dd:ee:ff", "00:AA:11:bB:22:cc"]:
      self.assertEqual(utils.NormalizeAndValidateMac(mac), mac.lower())


class TestNormalizeAndValidateThreeOctetMacPrefix(unittest.TestCase):
  def testInvalid(self):
    for i in ["xxx", "00:11:22:33:44:55:66", "zz:zz:zz:zz:zz:zz",
              "aa:bb:cc:dd:ee:ff", "00:AA:11:bB:22:cc",
              "00:11:"]:
      self.assertRaises(errors.OpPrereqError,
                        utils.NormalizeAndValidateThreeOctetMacPrefix, i)

  def testNormalization(self):
    for mac in ["aa:bb:cc", "00:AA:11"]:
      self.assertEqual(utils.NormalizeAndValidateThreeOctetMacPrefix(mac),
                       mac.lower())


class TestSafeEncode(unittest.TestCase):
  """Test case for SafeEncode"""

  def testAscii(self):
    for txt in [string.digits, string.ascii_letters, string.punctuation]:
      self.assertEqual(txt, utils.SafeEncode(txt))

  def testDoubleEncode(self):
    for i in range(255):
      txt = utils.SafeEncode(chr(i))
      self.assertEqual(txt, utils.SafeEncode(txt))

  def testUnicode(self):
    # 1024 is high enough to catch non-direct ASCII mappings
    for i in range(1024):
      txt = utils.SafeEncode(chr(i))
      self.assertEqual(txt, utils.SafeEncode(txt))


class TestUnescapeAndSplit(unittest.TestCase):
  """Testing case for UnescapeAndSplit"""

  def setUp(self):
    # testing more that one separator for regexp safety
    self._seps = [",", "+", ".", ":"]

  def testSimple(self):
    a = ["a", "b", "c", "d"]
    for sep in self._seps:
      self.assertEqual(utils.UnescapeAndSplit(sep.join(a), sep=sep), a)

  def testEscape(self):
    for sep in self._seps:
      a = ["a", "b\\" + sep + "c", "d"]
      b = ["a", "b" + sep + "c", "d"]
      self.assertEqual(utils.UnescapeAndSplit(sep.join(a), sep=sep), b)

  def testDoubleEscape(self):
    for sep in self._seps:
      a = ["a", "b\\\\", "c", "d"]
      b = ["a", "b\\", "c", "d"]
      self.assertEqual(utils.UnescapeAndSplit(sep.join(a), sep=sep), b)

  def testThreeEscape(self):
    for sep in self._seps:
      a = ["a", "b\\\\\\" + sep + "c", "d"]
      b = ["a", "b\\" + sep + "c", "d"]
      self.assertEqual(utils.UnescapeAndSplit(sep.join(a), sep=sep), b)

  def testEscapeAtEnd(self):
    for sep in self._seps:
      self.assertEqual(utils.UnescapeAndSplit("\\", sep=sep), ["\\"])

      a = ["a", "b\\", "c"]
      b = ["a", "b" + sep + "c\\"]
      self.assertEqual(utils.UnescapeAndSplit("%s\\" % sep.join(a), sep=sep), b)

      a = ["\\" + sep, "\\" + sep, "c", "d\\.moo"]
      b = [sep, sep, "c", "d.moo\\"]
      self.assertEqual(utils.UnescapeAndSplit("%s\\" % sep.join(a), sep=sep), b)

  def testMultipleEscapes(self):
    for sep in self._seps:
      a = ["a", "b\\" + sep + "c", "d\\" + sep + "e\\" + sep + "f", "g"]
      b = ["a", "b" + sep + "c", "d" + sep + "e" + sep + "f", "g"]
      self.assertEqual(utils.UnescapeAndSplit(sep.join(a), sep=sep), b)

class TestEscapeAndJoin(unittest.TestCase):
  def verifyParsesCorrect(self, args):
    for sep in [",", "+", ".", ":"]:
      self.assertEqual(utils.UnescapeAndSplit(
          utils.EscapeAndJoin(args, sep=sep),
          sep=sep), args)

  def test(self):
    self.verifyParsesCorrect(["a", "b", "c"])
    self.verifyParsesCorrect(["2.10.0", "12345"])
    self.verifyParsesCorrect(["2.10.0~alpha1", "12345"])
    self.verifyParsesCorrect(["..:", ",,+"])
    self.verifyParsesCorrect(["a\\", "b\\\\", "c"])
    self.verifyParsesCorrect(["a"])
    self.verifyParsesCorrect(["+"])
    self.verifyParsesCorrect(["\\"])
    self.verifyParsesCorrect(["\\\\"])


class TestCommaJoin(unittest.TestCase):
  def test(self):
    self.assertEqual(utils.CommaJoin([]), "")
    self.assertEqual(utils.CommaJoin([1, 2, 3]), "1, 2, 3")
    self.assertEqual(utils.CommaJoin(["Hello"]), "Hello")
    self.assertEqual(utils.CommaJoin(["Hello", "World"]), "Hello, World")
    self.assertEqual(utils.CommaJoin(["Hello", "World", 99]),
                     "Hello, World, 99")


class TestFormatTime(unittest.TestCase):
  """Testing case for FormatTime"""

  @staticmethod
  def _TestInProcess(tz, timestamp, usecs, expected):
    os.environ["TZ"] = tz
    time.tzset()
    return utils.FormatTime(timestamp, usecs=usecs) == expected

  def _Test(self, *args):
    # Need to use separate process as we want to change TZ
    self.assertTrue(utils.RunInSeparateProcess(self._TestInProcess, *args))

  def test(self):
    self._Test("UTC", 0, None, "1970-01-01 00:00:00")
    self._Test("America/Sao_Paulo", 1292606926, None, "2010-12-17 15:28:46")
    self._Test("Europe/London", 1292606926, None, "2010-12-17 17:28:46")
    self._Test("Europe/Zurich", 1292606926, None, "2010-12-17 18:28:46")
    self._Test("Europe/Zurich", 1332944288, 8787, "2012-03-28 16:18:08.008787")
    self._Test("Australia/Sydney", 1292606926, None, "2010-12-18 04:28:46")
    self._Test("Australia/Sydney", 1292606926, None, "2010-12-18 04:28:46")
    self._Test("Australia/Sydney", 1292606926, 999999,
               "2010-12-18 04:28:46.999999")

  def testNone(self):
    self.assertEqual(utils.FormatTime(None), "N/A")

  def testInvalid(self):
    self.assertEqual(utils.FormatTime(()), "N/A")

  def testNow(self):
    # tests that we accept time.time input
    utils.FormatTime(time.time())
    # tests that we accept int input
    utils.FormatTime(int(time.time()))


class TestFormatSeconds(unittest.TestCase):
  def test(self):
    self.assertEqual(utils.FormatSeconds(1), "1s")
    self.assertEqual(utils.FormatSeconds(3600), "1h 0m 0s")
    self.assertEqual(utils.FormatSeconds(3599), "59m 59s")
    self.assertEqual(utils.FormatSeconds(7200), "2h 0m 0s")
    self.assertEqual(utils.FormatSeconds(7201), "2h 0m 1s")
    self.assertEqual(utils.FormatSeconds(7281), "2h 1m 21s")
    self.assertEqual(utils.FormatSeconds(29119), "8h 5m 19s")
    self.assertEqual(utils.FormatSeconds(19431228), "224d 21h 33m 48s")
    self.assertEqual(utils.FormatSeconds(-1), "-1s")
    self.assertEqual(utils.FormatSeconds(-282), "-282s")
    self.assertEqual(utils.FormatSeconds(-29119), "-29119s")

  def testFloat(self):
    self.assertEqual(utils.FormatSeconds(1.3), "1s")
    self.assertEqual(utils.FormatSeconds(1.9), "2s")
    self.assertEqual(utils.FormatSeconds(3912.12311), "1h 5m 12s")
    self.assertEqual(utils.FormatSeconds(3912.8), "1h 5m 13s")


class TestLineSplitter(unittest.TestCase):
  def test(self):
    lines = []
    ls = utils.LineSplitter(lines.append)
    ls.write("Hello World\n")
    self.assertEqual(lines, [])
    ls.write("Foo\n Bar\r\n ")
    ls.write("Baz")
    ls.write("Moo")
    self.assertEqual(lines, [])
    ls.flush()
    self.assertEqual(lines, ["Hello World", "Foo", " Bar"])
    ls.close()
    self.assertEqual(lines, ["Hello World", "Foo", " Bar", " BazMoo"])

  def _testExtra(self, line, all_lines, p1, p2):
    self.assertEqual(p1, 999)
    self.assertEqual(p2, "extra")
    all_lines.append(line)

  def testExtraArgsNoFlush(self):
    lines = []
    ls = utils.LineSplitter(self._testExtra, lines, 999, "extra")
    ls.write("\n\nHello World\n")
    ls.write("Foo\n Bar\r\n ")
    ls.write("")
    ls.write("Baz")
    ls.write("Moo\n\nx\n")
    self.assertEqual(lines, [])
    ls.close()
    self.assertEqual(lines, ["", "", "Hello World", "Foo", " Bar", " BazMoo",
                             "", "x"])


class TestIsValidShellParam(unittest.TestCase):
  def test(self):
    for val, result in [
      ("abc", True),
      ("ab;cd", False),
      ]:
      self.assertEqual(utils.IsValidShellParam(val), result)


class TestBuildShellCmd(unittest.TestCase):
  def test(self):
    self.assertRaises(errors.ProgrammerError, utils.BuildShellCmd,
                      "ls %s", "ab;cd")
    self.assertEqual(utils.BuildShellCmd("ls %s", "ab"), "ls ab")


class TestOrdinal(unittest.TestCase):
  def test(self):
    checks = {
      0: "0th", 1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th",
      7: "7th", 8: "8th", 9: "9th", 10: "10th", 11: "11th", 12: "12th",
      13: "13th", 14: "14th", 15: "15th", 16: "16th", 17: "17th",
      18: "18th", 19: "19th", 20: "20th", 21: "21st", 25: "25th", 30: "30th",
      32: "32nd", 40: "40th", 50: "50th", 55: "55th", 60: "60th", 62: "62nd",
      70: "70th", 80: "80th", 83: "83rd", 90: "90th", 91: "91st",
      582: "582nd", 999: "999th",
      }

    for value, ordinal in checks.items():
      self.assertEqual(utils.FormatOrdinal(value), ordinal)


class TestTruncate(unittest.TestCase):
  def _Test(self, text, length):
    result = utils.Truncate(text, length)
    self.assertTrue(len(result) <= length)
    return result

  def test(self):
    self.assertEqual(self._Test("", 80), "")
    self.assertEqual(self._Test("abc", 4), "abc")
    self.assertEqual(self._Test("Hello World", 80), "Hello World")
    self.assertEqual(self._Test("Hello World", 4), "H...")
    self.assertEqual(self._Test("Hello World", 5), "He...")

    for i in [4, 10, 100]:
      data = i * "FooBarBaz"
      self.assertEqual(self._Test(data, len(data)), data)

    for (length, exp) in [(8, "T\u00e4st\u2026xyz"), (7, "T\u00e4st...")]:
      self.assertEqual(self._Test("T\u00e4st\u2026xyz", length), exp)

    self.assertEqual(self._Test(list(range(100)), 20), "[0, 1, 2, 3, 4, 5...")

  def testError(self):
    for i in range(4):
      self.assertRaises(AssertionError, utils.Truncate, "", i)


class TestFilterEmptyLinesAndComments(unittest.TestCase):
  def testEmpty(self):
    self.assertEqual(utils.FilterEmptyLinesAndComments(""), [])
    self.assertEqual(utils.FilterEmptyLinesAndComments("\n"), [])
    self.assertEqual(utils.FilterEmptyLinesAndComments("\n" * 100), [])
    self.assertEqual(utils.FilterEmptyLinesAndComments("\n  \n\t \n"), [])

  def test(self):
    text = """
      This
        is
      # with comments
          a
            test
            # in
            #
            saying
      ...#...
        # multiple places
        Hello World!
      """
    self.assertEqual(utils.FilterEmptyLinesAndComments(text), [
      "This",
      "is",
      "a",
      "test",
      "saying",
      "...#...",
      "Hello World!",
      ])


class TestFormatKeyValue(unittest.TestCase):
  def test(self):
    self.assertEqual(utils.FormatKeyValue({}), [])
    self.assertEqual(utils.FormatKeyValue({1: 2}), ["1=2"])
    self.assertEqual(utils.FormatKeyValue({
      "zzz": "0",
      "aaa": "1",
      }),
      ["aaa=1", "zzz=0"])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
