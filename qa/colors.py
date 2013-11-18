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

"""

import os
import subprocess
import sys

DEFAULT = '\033[0m'
RED = '\033[91m'
GREEN = '\033[92m'
BLUE = '\033[94m'
CYAN = '\033[96m'
WHITE = '\033[97m'
YELLOW = '\033[93m'
MAGENTA = '\033[95m'
GREY = '\033[90m'
BLACK = '\033[90m'

_enabled = sys.stdout.isatty()


def colorize(line, color=None):
  if _enabled and color is not None:
    return color + line + DEFAULT
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
