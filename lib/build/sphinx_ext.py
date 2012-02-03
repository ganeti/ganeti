#
#

# Copyright (C) 2011, 2012 Google Inc.
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

from cStringIO import StringIO

import docutils.statemachine
import docutils.nodes
import docutils.utils

import sphinx.errors
import sphinx.util.compat

s_compat = sphinx.util.compat

from ganeti import constants
from ganeti import compat
from ganeti import errors
from ganeti import utils
from ganeti import opcodes
from ganeti import ht
from ganeti import rapi

import ganeti.rapi.rlib2 # pylint: disable=W0611


def _GetCommonParamNames():
  """Builds a list of parameters common to all opcodes.

  """
  names = set(map(compat.fst, opcodes.OpCode.OP_PARAMS))

  # The "depends" attribute should be listed
  names.remove(opcodes.DEPEND_ATTR)

  return names


COMMON_PARAM_NAMES = _GetCommonParamNames()

#: Namespace for evaluating expressions
EVAL_NS = dict(compat=compat, constants=constants, utils=utils, errors=errors,
               rlib2=rapi.rlib2)

# Constants documentation for man pages
CV_ECODES_DOC = "ecodes"
# We don't care about the leak of variables _, name and doc here.
# pylint: disable=W0621
CV_ECODES_DOC_LIST = [(name, doc) for (_, name, doc) in constants.CV_ALL_ECODES]
DOCUMENTED_CONSTANTS = {
  CV_ECODES_DOC: CV_ECODES_DOC_LIST,
  }


class OpcodeError(sphinx.errors.SphinxError):
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
                   key=compat.fst)

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


def _BuildOpcodeResult(op_id):
  """Build opcode result documentation.

  @type op_id: string
  @param op_id: Opcode ID

  """
  op_cls = opcodes.OP_MAPPING[op_id]

  result_fn = getattr(op_cls, "OP_RESULT", None)

  if not result_fn:
    raise OpcodeError("Opcode '%s' has no result description" % op_id)

  return "``%s``" % result_fn


class OpcodeParams(s_compat.Directive):
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
    include_lines = docutils.statemachine.string2lines(include_text, tab_width,
                                                       convert_whitespace=1)
    self.state_machine.insert_input(include_lines, path)

    return []


class OpcodeResult(s_compat.Directive):
  """Custom directive for opcode result.

  See also <http://docutils.sourceforge.net/docs/howto/rst-directives.html>.

  """
  has_content = False
  required_arguments = 1
  optional_arguments = 0
  final_argument_whitespace = False

  def run(self):
    op_id = self.arguments[0]

    tab_width = 2
    path = op_id
    include_text = _BuildOpcodeResult(op_id)

    # Inject into state machine
    include_lines = docutils.statemachine.string2lines(include_text, tab_width,
                                                       convert_whitespace=1)
    self.state_machine.insert_input(include_lines, path)

    return []


def PythonEvalRole(role, rawtext, text, lineno, inliner,
                   options={}, content=[]):
  """Custom role to evaluate Python expressions.

  The expression's result is included as a literal.

  """
  # pylint: disable=W0102,W0613,W0142
  # W0102: Dangerous default value as argument
  # W0142: Used * or ** magic
  # W0613: Unused argument

  code = docutils.utils.unescape(text, restore_backslashes=True)

  try:
    result = eval(code, EVAL_NS)
  except Exception, err: # pylint: disable=W0703
    msg = inliner.reporter.error("Failed to evaluate %r: %s" % (code, err),
                                 line=lineno)
    return ([inliner.problematic(rawtext, rawtext, msg)], [msg])

  node = docutils.nodes.literal("", unicode(result), **options)

  return ([node], [])


class PythonAssert(s_compat.Directive):
  """Custom directive for writing assertions.

  The content must be a valid Python expression. If its result does not
  evaluate to C{True}, the assertion fails.

  """
  has_content = True
  required_arguments = 0
  optional_arguments = 0
  final_argument_whitespace = False

  def run(self):
    # Handle combinations of Sphinx and docutils not providing the wanted method
    if hasattr(self, "assert_has_content"):
      self.assert_has_content()
    else:
      assert self.content

    code = "\n".join(self.content)

    try:
      result = eval(code, EVAL_NS)
    except Exception, err:
      raise self.error("Failed to evaluate %r: %s" % (code, err))

    if not result:
      raise self.error("Assertion failed: %s" % (code, ))

    return []


def BuildQueryFields(fields):
  """Build query fields documentation.

  @type fields: dict (field name as key, field details as value)

  """
  defs = [(fdef.name, fdef.doc)
           for (_, (fdef, _, _, _)) in utils.NiceSort(fields.items(),
                                                      key=compat.fst)]
  return BuildValuesDoc(defs)


def BuildValuesDoc(values):
  """Builds documentation for a list of values

  @type values: list of tuples in the form (value, documentation)

  """
  for name, doc in values:
    assert len(doc.splitlines()) == 1
    yield "``%s``" % name
    yield "  %s" % doc


# TODO: Implement Sphinx directive for query fields


def setup(app):
  """Sphinx extension callback.

  """
  app.add_directive("opcode_params", OpcodeParams)
  app.add_directive("opcode_result", OpcodeResult)
  app.add_directive("pyassert", PythonAssert)
  app.add_role("pyeval", PythonEvalRole)
