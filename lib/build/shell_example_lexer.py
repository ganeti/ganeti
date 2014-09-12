#
#

# Copyright (C) 2012 Google Inc.
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
