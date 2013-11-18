#!/usr/bin/python -u
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
