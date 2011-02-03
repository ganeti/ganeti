#
#

# Copyright (C) 2011 Google Inc.
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


"""Sphinx extension for building opcode documentation.

"""

import operator
from cStringIO import StringIO

from docutils import statemachine

from sphinx.errors import SphinxError
from sphinx.util.compat import Directive

from ganeti import utils
from ganeti import opcodes
from ganeti import ht


COMMON_PARAM_NAMES = map(operator.itemgetter(0), opcodes.OpCode.OP_PARAMS)


class OpcodeError(SphinxError):
  category = "Opcode error"


def _SplitOption(text):
  """Split simple option list.

  @type text: string
  @param text: Options, e.g. "foo, bar, baz"

  """
  return [i.strip(",").strip() for i in text.split()]


def _ParseAlias(text):
  """Parse simple assignment option.

  @type text: string
  @param text: Assignments, e.g. "foo=bar, hello=world"
  @rtype: dict

  """
  result = {}

  for part in _SplitOption(text):
    if "=" not in part:
      raise OpcodeError("Invalid option format, missing equal sign")

    (name, value) = part.split("=", 1)

    result[name.strip()] = value.strip()

  return result


def _BuildOpcodeParams(op_id, include, exclude, alias):
  """Build opcode parameter documentation.

  @type op_id: string
  @param op_id: Opcode ID

  """
  op_cls = opcodes.OP_MAPPING[op_id]

  params_with_alias = \
    utils.NiceSort([(alias.get(name, name), name, default, test, doc)
                    for (name, default, test, doc) in op_cls.GetAllParams()],
                   key=operator.itemgetter(0))

  for (rapi_name, name, default, test, doc) in params_with_alias:
    # Hide common parameters if not explicitely included
    if (name in COMMON_PARAM_NAMES and
        (not include or name not in include)):
      continue
    if exclude is not None and name in exclude:
      continue
    if include is not None and name not in include:
      continue

    has_default = default is not ht.NoDefault
    has_test = not (test is None or test is ht.NoType)

    buf = StringIO()
    buf.write("``%s``" % rapi_name)
    if has_default or has_test:
      buf.write(" (")
      if has_default:
        buf.write("defaults to ``%s``" % default)
        if has_test:
          buf.write(", ")
      if has_test:
        buf.write("must be ``%s``" % test)
      buf.write(")")
    yield buf.getvalue()

    # Add text
    for line in doc.splitlines():
      yield "  %s" % line


class OpcodeParams(Directive):
  """Custom directive for opcode parameters.

  See also <http://docutils.sourceforge.net/docs/howto/rst-directives.html>.

  """
  has_content = False
  required_arguments = 1
  optional_arguments = 0
  final_argument_whitespace = False
  option_spec = dict(include=_SplitOption, exclude=_SplitOption,
                     alias=_ParseAlias)

  def run(self):
    op_id = self.arguments[0]
    include = self.options.get("include", None)
    exclude = self.options.get("exclude", None)
    alias = self.options.get("alias", {})

    tab_width = 2
    path = op_id
    include_text = "\n".join(_BuildOpcodeParams(op_id, include, exclude, alias))

    # Inject into state machine
    include_lines = statemachine.string2lines(include_text, tab_width,
                                              convert_whitespace=1)
    self.state_machine.insert_input(include_lines, path)

    return []


def setup(app):
  """Sphinx extension callback.

  """
  app.add_directive("opcode_params", OpcodeParams)
