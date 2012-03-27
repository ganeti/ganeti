#
#

# Copyright (C) 2012 Google Inc.
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


"""Pygments lexer for our custom shell example sessions.

The lexer support the following custom markup:

  - comments: # this is a comment
  - command lines: '$ ' at the beginning of a line denotes a command
  - variable input: %input% (works in both commands and screen output)
  - otherwise, regular text output from commands will be plain

"""

from pygments.lexer import RegexLexer, bygroups, include
from pygments.token import Name, Text, Generic, Comment


class ShellExampleLexer(RegexLexer):
  name = "ShellExampleLexer"
  aliases = "shell-example"
  filenames = []

  tokens = {
    "root": [
      include("comments"),
      include("userinput"),
      # switch to state input on '$ ' at the start of the line
      (r"^\$ ", Text, "input"),
      (r"\s+", Text),
      (r"[^#%\s\\]+", Text),
      (r"\\", Text),
      ],
    "input": [
      include("comments"),
      include("userinput"),
      (r"[^#%\s\\]+", Generic.Strong),
      (r"\\\n", Generic.Strong),
      (r"\\", Generic.Strong),
      # switch to prev state at non-escaped new-line
      (r"\n", Text, "#pop"),
      (r"\s+", Text),
      ],
    "comments": [
      (r"#.*\n", Comment.Single),
      ],
    "userinput": [
      (r"(\\)(%)", bygroups(None, Text)),
      (r"(%)([^%]*)(%)", bygroups(None, Name.Variable, None)),
      ],
    }


def setup(app):
  app.add_lexer("shell-example", ShellExampleLexer())
