#!/usr/bin/python -u
#

# Copyright (C) 2013 Google Inc.
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


"""Script for adding colorized output to Ganeti.

Colors are enabled only if the standard output is a proper terminal.
(Or call check_for_colors() to make a thorough test using "tput".)

See http://en.wikipedia.org/wiki/ANSI_escape_code for more possible additions.
"""

import os
import subprocess
import sys

DEFAULT = "0"
BOLD = "1"
UNDERLINE = "4"
REVERSE = "7"

BLACK = "30"
RED = "31"
GREEN = "32"
YELLOW = "33"
BLUE = "34"
MAGENTA = "35"
CYAN = "36"
WHITE = "37"

BG_BLACK = "40"
BG_RED = "41"
BG_GREEN = "42"
BG_YELLOW = "43"
BG_BLUE = "44"
BG_MAGENTA = "45"
BG_CYAN = "46"
BG_WHITE = "47"

_enabled = sys.stdout.isatty()


def _escape_one(code):
  return "\033[" + code + "m" if code else ""


def _escape(codes):
  if hasattr(codes, "__iter__"):
    return _escape_one(";".join(codes))
  else:
    return _escape_one(codes)


def _reset():
  return _escape([DEFAULT])


def colorize(line, color=None):
  """Wraps a given string into ANSI color codes corresponding to given
  color(s).

  @param line: a string
  @param color: a color or a list of colors selected from this module's
    constants
  """
  if _enabled and color:
    return _escape(color) + line + _reset()
  else:
    return line


def check_for_colors():
  """Tries to call 'tput' to properly determine, if the terminal has colors.

  This functions is meant to be run once at the program's start. If not
  invoked, colors are enabled iff standard output is a terminal.
  """
  colors = 0
  if sys.stdout.isatty():
    try:
      p = subprocess.Popen(["tput", "colors"], stdout=subprocess.PIPE)
      output = p.communicate()[0]
      if p.returncode == 0:
        colors = int(output)
    except (OSError, ValueError):
      pass
  global _enabled
  _enabled = (colors >= 2)
