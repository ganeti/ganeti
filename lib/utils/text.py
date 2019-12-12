#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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

"""Utility functions for manipulating or working with text.

"""


import re
import os
import time
import numbers
import collections

from ganeti import errors
from ganeti import compat


#: Unit checker regexp
_PARSEUNIT_REGEX = re.compile(r"^([.\d]+)\s*([a-zA-Z]+)?$")

#: Characters which don't need to be quoted for shell commands
_SHELL_UNQUOTED_RE = re.compile("^[-.,=:/_+@A-Za-z0-9]+$")

#: Shell param checker regexp
_SHELLPARAM_REGEX = re.compile(r"^[-a-zA-Z0-9._+/:%@]+$")

#: ASCII equivalent of unicode character 'HORIZONTAL ELLIPSIS' (U+2026)
_ASCII_ELLIPSIS = "..."

#: MAC address octet
_MAC_ADDR_OCTET_RE = r"[0-9a-f]{2}"


def MatchNameComponent(key, name_list, case_sensitive=True):
  """Try to match a name against a list.

  This function will try to match a name like test1 against a list
  like C{['test1.example.com', 'test2.example.com', ...]}. Against
  this list, I{'test1'} as well as I{'test1.example'} will match, but
  not I{'test1.ex'}. A multiple match will be considered as no match
  at all (e.g. I{'test1'} against C{['test1.example.com',
  'test1.example.org']}), except when the key fully matches an entry
  (e.g. I{'test1'} against C{['test1', 'test1.example.com']}).

  @type key: str
  @param key: the name to be searched
  @type name_list: list
  @param name_list: the list of strings against which to search the key
  @type case_sensitive: boolean
  @param case_sensitive: whether to provide a case-sensitive match

  @rtype: None or str
  @return: None if there is no match I{or} if there are multiple matches,
      otherwise the element from the list which matches

  """
  if key in name_list:
    return key

  re_flags = 0
  if not case_sensitive:
    re_flags |= re.IGNORECASE
    key = key.upper()

  name_re = re.compile(r"^%s(\..*)?$" % re.escape(key), re_flags)

  names_filtered = []
  string_matches = []
  for name in name_list:
    if name_re.match(name) is not None:
      names_filtered.append(name)
      if not case_sensitive and key == name.upper():
        string_matches.append(name)

  if len(string_matches) == 1:
    return string_matches[0]
  if len(names_filtered) == 1:
    return names_filtered[0]

  return None


def _DnsNameGlobHelper(match):
  """Helper function for L{DnsNameGlobPattern}.

  Returns regular expression pattern for parts of the pattern.

  """
  text = match.group(0)

  if text == "*":
    return "[^.]*"
  elif text == "?":
    return "[^.]"
  else:
    return re.escape(text)


def DnsNameGlobPattern(pattern):
  """Generates regular expression from DNS name globbing pattern.

  A DNS name globbing pattern (e.g. C{*.site}) is converted to a regular
  expression. Escape sequences or ranges (e.g. [a-z]) are not supported.

  Matching always starts at the leftmost part. An asterisk (*) matches all
  characters except the dot (.) separating DNS name parts. A question mark (?)
  matches a single character except the dot (.).

  @type pattern: string
  @param pattern: DNS name globbing pattern
  @rtype: string
  @return: Regular expression

  """
  return r"^%s(\..*)?$" % re.sub(r"\*|\?|[^*?]*", _DnsNameGlobHelper, pattern)


def FormatUnit(value, units, roman=False):
  """Formats an incoming number of MiB with the appropriate unit.

  @type value: int
  @param value: integer representing the value in MiB (1048576)
  @type units: char
  @param units: the type of formatting we should do:
      - 'h' for automatic scaling
      - 'm' for MiBs
      - 'g' for GiBs
      - 't' for TiBs
  @rtype: str
  @return: the formatted value (with suffix)

  """
  if units not in ("m", "g", "t", "h"):
    raise errors.ProgrammerError("Invalid unit specified '%s'" % str(units))

  if not isinstance(value, numbers.Real):
    raise errors.ProgrammerError("Invalid value specified '%s (%s)'" % (
        value, type(value)))

  suffix = ""

  if units == "m" or (units == "h" and value < 1024):
    if units == "h":
      suffix = "M"
    return "%s%s" % (compat.RomanOrRounded(value, 0, roman), suffix)

  elif units == "g" or (units == "h" and value < (1024 * 1024)):
    if units == "h":
      suffix = "G"
    return "%s%s" % (compat.RomanOrRounded(float(value) / 1024, 1, roman),
                     suffix)

  else:
    if units == "h":
      suffix = "T"
    return "%s%s" % (compat.RomanOrRounded(float(value) / 1024 / 1024, 1,
                                           roman), suffix)


def ParseUnit(input_string):
  """Tries to extract number and scale from the given string.

  Input must be in the format C{NUMBER+ [DOT NUMBER+] SPACE*
  [UNIT]}. If no unit is specified, it defaults to MiB. Return value
  is always an int in MiB.

  """
  m = _PARSEUNIT_REGEX.match(str(input_string))
  if not m:
    raise errors.UnitParseError("Invalid format")

  value = float(m.groups()[0])

  unit = m.groups()[1]
  if unit:
    lcunit = unit.lower()
  else:
    lcunit = "m"

  if lcunit in ("m", "mb", "mib"):
    # Value already in MiB
    pass

  elif lcunit in ("g", "gb", "gib"):
    value *= 1024

  elif lcunit in ("t", "tb", "tib"):
    value *= 1024 * 1024

  else:
    raise errors.UnitParseError("Unknown unit: %s" % unit)

  # Make sure we round up
  if int(value) < value:
    value += 1

  # Round up to the next multiple of 4
  value = int(value)
  if value % 4:
    value += 4 - value % 4

  return value


def ShellQuote(value):
  """Quotes shell argument according to POSIX.

  @type value: str
  @param value: the argument to be quoted
  @rtype: str
  @return: the quoted value

  """
  if _SHELL_UNQUOTED_RE.match(value):
    return value
  else:
    return "'%s'" % value.replace("'", "'\\''")


def ShellQuoteArgs(args):
  """Quotes a list of shell arguments.

  @type args: list
  @param args: list of arguments to be quoted
  @rtype: str
  @return: the quoted arguments concatenated with spaces

  """
  return " ".join([ShellQuote(i) for i in args])


def ShellCombineCommands(cmdlist):
  """Out of a list of shell comands construct a single one.

  """
  return ["/bin/sh", "-c", " && ".join(ShellQuoteArgs(c) for c in cmdlist)]


class ShellWriter(object):
  """Helper class to write scripts with indentation.

  """
  INDENT_STR = "  "

  def __init__(self, fh, indent=True):
    """Initializes this class.

    """
    self._fh = fh
    self._indent_enabled = indent
    self._indent = 0

  def IncIndent(self):
    """Increase indentation level by 1.

    """
    self._indent += 1

  def DecIndent(self):
    """Decrease indentation level by 1.

    """
    assert self._indent > 0
    self._indent -= 1

  def Write(self, txt, *args):
    """Write line to output file.

    """
    assert self._indent >= 0

    if args:
      line = txt % args
    else:
      line = txt

    if line and self._indent_enabled:
      # Indent only if there's something on the line
      self._fh.write(self._indent * self.INDENT_STR)

    self._fh.write(line)

    self._fh.write("\n")


def GenerateSecret(numbytes=20):
  """Generates a random secret.

  This will generate a pseudo-random secret returning an hex string
  (so that it can be used where an ASCII string is needed).

  @param numbytes: the number of bytes which will be represented by the returned
      string (defaulting to 20, the length of a SHA1 hash)
  @rtype: str
  @return: an hex representation of the pseudo-random sequence

  """
  return os.urandom(numbytes).hex()


def _MakeMacAddrRegexp(octets):
  """Builds a regular expression for verifying MAC addresses.

  @type octets: integer
  @param octets: How many octets to expect (1-6)
  @return: Compiled regular expression

  """
  assert octets > 0
  assert octets <= 6

  return re.compile("^%s$" % ":".join([_MAC_ADDR_OCTET_RE] * octets),
                    re.I)


#: Regular expression for full MAC address
_MAC_CHECK_RE = _MakeMacAddrRegexp(6)

#: Regular expression for half a MAC address
_MAC_PREFIX_CHECK_RE = _MakeMacAddrRegexp(3)


def _MacAddressCheck(check_re, mac, msg):
  """Checks a MAC address using a regular expression.

  @param check_re: Compiled regular expression as returned by C{re.compile}
  @type mac: string
  @param mac: MAC address to be validated
  @type msg: string
  @param msg: Error message (%s will be replaced with MAC address)

  """
  if check_re.match(mac):
    return mac.lower()

  raise errors.OpPrereqError(msg % mac, errors.ECODE_INVAL)


def NormalizeAndValidateMac(mac):
  """Normalizes and check if a MAC address is valid and contains six octets.

  Checks whether the supplied MAC address is formally correct. Accepts
  colon-separated format only. Normalize it to all lower case.

  @type mac: string
  @param mac: MAC address to be validated
  @rtype: string
  @return: Normalized and validated MAC address
  @raise errors.OpPrereqError: If the MAC address isn't valid

  """
  return _MacAddressCheck(_MAC_CHECK_RE, mac, "Invalid MAC address '%s'")


def NormalizeAndValidateThreeOctetMacPrefix(mac):
  """Normalizes a potential MAC address prefix (three octets).

  Checks whether the supplied string is a valid MAC address prefix consisting
  of three colon-separated octets. The result is normalized to all lower case.

  @type mac: string
  @param mac: Prefix to be validated
  @rtype: string
  @return: Normalized and validated prefix
  @raise errors.OpPrereqError: If the MAC address prefix isn't valid

  """
  return _MacAddressCheck(_MAC_PREFIX_CHECK_RE, mac,
                          "Invalid MAC address prefix '%s'")


def SafeEncode(text):
  """Return a 'safe' version of a source string.

  This function mangles the input string and returns a version that
  should be safe to display/encode as ASCII. To this end, we first
  convert it to ASCII using the 'backslashreplace' encoding which
  should get rid of any non-ASCII chars, and then we process it
  through a loop copied from the string repr sources in the python; we
  don't use string_escape anymore since that escape single quotes and
  backslashes too, and that is too much; and that escaping is not
  stable, i.e. string_escape(string_escape(x)) != string_escape(x).

  @type text: str or unicode
  @param text: input data
  @rtype: str
  @return: a safe version of text

  """
  if not isinstance(text, str):
    raise TypeError("Only str can be SafeEncoded")

  text = text.encode("ascii", "backslashreplace").decode("ascii")
  resu = ""
  for char in text:
    c = ord(char)
    if char == "\t":
      resu += r"\t"
    elif char == "\n":
      resu += r"\n"
    elif char == "\r":
      resu += r'\'r'
    elif c < 32 or c >= 127: # non-printable
      resu += "\\x%02x" % (c & 0xff)
    else:
      resu += char
  return resu


def UnescapeAndSplit(text, sep=","):
  r"""Split and unescape a string based on a given separator.

  This function splits a string based on a separator where the
  separator itself can be escape in order to be an element of the
  elements. The escaping rules are (assuming coma being the
  separator):
    - a plain , separates the elements
    - a sequence \\\\, (double backslash plus comma) is handled as a
      backslash plus a separator comma
    - a sequence \, (backslash plus comma) is handled as a
      non-separator comma

  @type text: string
  @param text: the string to split
  @type sep: string
  @param text: the separator
  @rtype: string
  @return: a list of strings

  """
  # we split the list by sep (with no escaping at this stage)
  slist = text.split(sep)
  # next, we revisit the elements and if any of them ended with an odd
  # number of backslashes, then we join it with the next
  rlist = []
  while slist:
    e1 = slist.pop(0)
    if e1.endswith("\\"):
      num_b = len(e1) - len(e1.rstrip("\\"))
      if num_b % 2 == 1 and slist:
        e2 = slist.pop(0)
        # Merge the two elements and push the result back to the source list for
        # revisiting. If e2 ended with backslashes, further merging may need to
        # be done.
        slist.insert(0, e1 + sep + e2)
        continue
    # here the backslashes remain (all), and will be reduced in the next step
    rlist.append(e1)
  # finally, replace backslash-something with something
  rlist = [re.sub(r"\\(.)", r"\1", v) for v in rlist]
  return rlist


def EscapeAndJoin(slist, sep=","):
  """Encode a list in a way parsable by UnescapeAndSplit.

  @type slist: list of strings
  @param slist: the strings to be encoded
  @rtype: string
  @return: the encoding of the list oas a string

  """
  return sep.join([re.sub("\\" + sep, "\\\\" + sep,
                          re.sub(r"\\", r"\\\\", v)) for v in slist])


def CommaJoin(names):
  """Nicely join a set of identifiers.

  @param names: set, list or tuple
  @return: a string with the formatted results

  """
  return ", ".join([str(val) for val in names])


def FormatTime(val, usecs=None):
  """Formats a time value.

  @type val: float or None
  @param val: Timestamp as returned by time.time() (seconds since Epoch,
    1970-01-01 00:00:00 UTC)
  @return: a string value or N/A if we don't have a valid timestamp

  """
  if val is None or not isinstance(val, (int, float)):
    return "N/A"

  # these two codes works on Linux, but they are not guaranteed on all
  # platforms
  result = time.strftime("%F %T", time.localtime(val))

  if usecs is not None:
    result += ".%06d" % usecs

  return result


def FormatSeconds(secs):
  """Formats seconds for easier reading.

  @type secs: number
  @param secs: Number of seconds
  @rtype: string
  @return: Formatted seconds (e.g. "2d 9h 19m 49s")

  """
  parts = []

  secs = round(secs, 0)

  if secs > 0:
    # Negative values would be a bit tricky
    for unit, one in [("d", 24 * 60 * 60), ("h", 60 * 60), ("m", 60)]:
      (complete, secs) = divmod(secs, one)
      if complete or parts:
        parts.append("%d%s" % (complete, unit))

  parts.append("%ds" % secs)

  return " ".join(parts)


class LineSplitter(object):
  """Splits data chunks into lines separated by newline.

  Instances provide a file-like interface.

  """
  def __init__(self, line_fn, *args):
    """Initializes this class.

    @type line_fn: callable
    @param line_fn: Function called for each line, first parameter is line
    @param args: Extra arguments for L{line_fn}

    """
    assert callable(line_fn)

    if args:
      # Python 2.4 doesn't have functools.partial yet
      self._line_fn = lambda line: line_fn(line, *args)
    else:
      self._line_fn = line_fn

    self._lines = collections.deque()
    self._buffer = ""

  def write(self, data):
    parts = (self._buffer + data).split("\n")
    self._buffer = parts.pop()
    self._lines.extend(parts)

  def flush(self):
    while self._lines:
      self._line_fn(self._lines.popleft().rstrip("\r\n"))

  def close(self):
    self.flush()
    if self._buffer:
      self._line_fn(self._buffer)


def IsValidShellParam(word):
  """Verifies is the given word is safe from the shell's p.o.v.

  This means that we can pass this to a command via the shell and be
  sure that it doesn't alter the command line and is passed as such to
  the actual command.

  Note that we are overly restrictive here, in order to be on the safe
  side.

  @type word: str
  @param word: the word to check
  @rtype: boolean
  @return: True if the word is 'safe'

  """
  return bool(_SHELLPARAM_REGEX.match(word))


def BuildShellCmd(template, *args):
  """Build a safe shell command line from the given arguments.

  This function will check all arguments in the args list so that they
  are valid shell parameters (i.e. they don't contain shell
  metacharacters). If everything is ok, it will return the result of
  template % args.

  @type template: str
  @param template: the string holding the template for the
      string formatting
  @rtype: str
  @return: the expanded command line

  """
  for word in args:
    if not IsValidShellParam(word):
      raise errors.ProgrammerError("Shell argument '%s' contains"
                                   " invalid characters" % word)
  return template % args


def FormatOrdinal(value):
  """Formats a number as an ordinal in the English language.

  E.g. the number 1 becomes "1st", 22 becomes "22nd".

  @type value: integer
  @param value: Number
  @rtype: string

  """
  tens = value % 10

  if value > 10 and value < 20:
    suffix = "th"
  elif tens == 1:
    suffix = "st"
  elif tens == 2:
    suffix = "nd"
  elif tens == 3:
    suffix = "rd"
  else:
    suffix = "th"

  return "%s%s" % (value, suffix)


def Truncate(text, length):
  """Truncate string and add ellipsis if needed.

  @type text: string
  @param text: Text
  @type length: integer
  @param length: Desired length
  @rtype: string
  @return: Truncated text

  """
  assert length > len(_ASCII_ELLIPSIS)

  # Serialize if necessary
  if not isinstance(text, str):
    text = str(text)

  if len(text) <= length:
    return text
  else:
    return text[:length - len(_ASCII_ELLIPSIS)] + _ASCII_ELLIPSIS


def FilterEmptyLinesAndComments(text):
  """Filters empty lines and comments from a line-based string.

  Whitespace is also removed from the beginning and end of all lines.

  @type text: string
  @param text: Input string
  @rtype: list

  """
  return [line for line in [s.strip() for s in text.splitlines()]
          # Ignore empty lines and comments
          if line and not line.startswith("#")]


def FormatKeyValue(data):
  """Formats a dictionary as "key=value" parameters.

  The keys are sorted to have a stable order.

  @type data: dict
  @rtype: list of string

  """
  return ["%s=%s" % (key, value) for (key, value) in sorted(data.items())]
