#
#

# Copyright (C) 2011, 2012, 2013 Google Inc.
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


"""Sphinx extension for building opcode documentation.

"""

# pylint: disable=C0413
# C0413: Wrong import position

import re
from cStringIO import StringIO

import docutils.statemachine
import docutils.nodes
import docutils.utils
import docutils.parsers.rst

import sphinx.errors
import sphinx.util.compat
import sphinx.roles
import sphinx.addnodes

s_compat = sphinx.util.compat

try:
  # Access to a protected member of a client class
  # pylint: disable=W0212
  orig_manpage_role = docutils.parsers.rst.roles._roles["manpage"]
except (AttributeError, ValueError, KeyError), err:
  # Normally the "manpage" role is registered by sphinx/roles.py
  raise Exception("Can't find reST role named 'manpage': %s" % err)

from ganeti import _constants
from ganeti import constants
from ganeti import compat
from ganeti import errors
from ganeti import utils
from ganeti import opcodes
from ganeti import opcodes_base
from ganeti import ht
from ganeti import rapi
from ganeti import luxi
from ganeti import objects
from ganeti import http
from ganeti import pathutils

import ganeti.rapi.rlib2 # pylint: disable=W0611
import ganeti.rapi.connector # pylint: disable=W0611


#: Regular expression for man page names
_MAN_RE = re.compile(r"^(?P<name>[-\w_]+)\((?P<section>\d+)\)$")

_TAB_WIDTH = 2

RAPI_URI_ENCODE_RE = re.compile("[^_a-z0-9]+", re.I)


class ReSTError(Exception):
  """Custom class for generating errors in Sphinx.

  """


def _GetCommonParamNames():
  """Builds a list of parameters common to all opcodes.

  """
  names = set(map(compat.fst, opcodes.OpCode.OP_PARAMS))

  # The "depends" attribute should be listed
  names.remove(opcodes_base.DEPEND_ATTR)

  return names


COMMON_PARAM_NAMES = _GetCommonParamNames()

#: Namespace for evaluating expressions
EVAL_NS = dict(compat=compat, constants=constants, utils=utils, errors=errors,
               rlib2=rapi.rlib2, luxi=luxi, rapi=rapi, objects=objects,
               http=http, pathutils=pathutils)

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
    # Hide common parameters if not explicitly included
    if (name in COMMON_PARAM_NAMES and
        (not include or name not in include)):
      continue
    if exclude is not None and name in exclude:
      continue
    if include is not None and name not in include:
      continue

    has_default = default is not None or default is not ht.NoDefault
    has_test = test is not None

    buf = StringIO()
    buf.write("``%s``" % (rapi_name,))
    if has_default or has_test:
      buf.write(" (")
      if has_default:
        if default == "":
          buf.write("defaults to the empty string")
        else:
          buf.write("defaults to ``%s``" % (default,))
        if has_test:
          buf.write(", ")
      if has_test:
        buf.write("must be ``%s``" % (test,))
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

    path = op_id
    include_text = "\n\n".join(_BuildOpcodeParams(op_id,
                                                  include,
                                                  exclude,
                                                  alias))

    # Inject into state machine
    include_lines = docutils.statemachine.string2lines(include_text, _TAB_WIDTH,
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

    path = op_id
    include_text = _BuildOpcodeResult(op_id)

    # Inject into state machine
    include_lines = docutils.statemachine.string2lines(include_text, _TAB_WIDTH,
                                                       convert_whitespace=1)
    self.state_machine.insert_input(include_lines, path)

    return []


def PythonEvalRole(role, rawtext, text, lineno, inliner,
                   options={}, content=[]):
  """Custom role to evaluate Python expressions.

  The expression's result is included as a literal.

  """
  # pylint: disable=W0102,W0613
  # W0102: Dangerous default value as argument
  # W0613: Unused argument

  code = docutils.utils.unescape(text, restore_backslashes=True)

  try:
    result = eval(code, EVAL_NS) # pylint: disable=W0123
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
      result = eval(code, EVAL_NS) # pylint: disable=W0123
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
    yield "``%s``" % (name,)
    yield "  %s" % (doc,)


def _ManPageNodeClass(*args, **kwargs):
  """Generates a pending XRef like a ":doc:`...`" reference.

  """
  # Type for sphinx/environment.py:BuildEnvironment.resolve_references
  kwargs["reftype"] = "doc"

  # Force custom title
  kwargs["refexplicit"] = True

  return sphinx.addnodes.pending_xref(*args, **kwargs)


class _ManPageXRefRole(sphinx.roles.XRefRole):
  def __init__(self):
    """Initializes this class.

    """
    sphinx.roles.XRefRole.__init__(self, nodeclass=_ManPageNodeClass,
                                   warn_dangling=True)

    assert not hasattr(self, "converted"), \
      "Sphinx base class gained an attribute named 'converted'"

    self.converted = None

  def process_link(self, env, refnode, has_explicit_title, title, target):
    """Specialization for man page links.

    """
    if has_explicit_title:
      raise ReSTError("Setting explicit title is not allowed for man pages")

    # Check format and extract name and section
    m = _MAN_RE.match(title)
    if not m:
      raise ReSTError("Man page reference '%s' does not match regular"
                      " expression '%s'" % (title, _MAN_RE.pattern))

    name = m.group("name")
    section = int(m.group("section"))

    wanted_section = _constants.MAN_PAGES.get(name, None)

    if not (wanted_section is None or wanted_section == section):
      raise ReSTError("Referenced man page '%s' has section number %s, but the"
                      " reference uses section %s" %
                      (name, wanted_section, section))

    self.converted = bool(wanted_section is not None and
                          env.app.config.enable_manpages)

    if self.converted:
      # Create link to known man page
      return (title, "man-%s" % name)
    else:
      # No changes
      return (title, target)


def _ManPageRole(typ, rawtext, text, lineno, inliner, # pylint: disable=W0102
                 options={}, content=[]):
  """Custom role for man page references.

  Converts man pages to links if enabled during the build.

  """
  xref = _ManPageXRefRole()

  assert ht.TNone(xref.converted)

  # Check if it's a known man page
  try:
    result = xref(typ, rawtext, text, lineno, inliner,
                  options=options, content=content)
  except ReSTError, err:
    msg = inliner.reporter.error(str(err), line=lineno)
    return ([inliner.problematic(rawtext, rawtext, msg)], [msg])

  assert ht.TBool(xref.converted)

  # Return if the conversion was successful (i.e. the man page was known and
  # conversion was enabled)
  if xref.converted:
    return result

  # Fallback if man page links are disabled or an unknown page is referenced
  return orig_manpage_role(typ, rawtext, text, lineno, inliner,
                           options=options, content=content)


def _EncodeRapiResourceLink(method, uri):
  """Encodes a RAPI resource URI for use as a link target.

  """
  parts = [RAPI_URI_ENCODE_RE.sub("-", uri.lower()).strip("-")]

  if method is not None:
    parts.append(method.lower())

  return "rapi-res-%s" % "+".join(filter(None, parts))


def _MakeRapiResourceLink(method, uri):
  """Generates link target name for RAPI resource.

  """
  if uri in ["/", "/2"]:
    # Don't link these
    return None

  elif uri == "/version":
    return _EncodeRapiResourceLink(method, uri)

  elif uri.startswith("/2/"):
    return _EncodeRapiResourceLink(method, uri[len("/2/"):])

  else:
    raise ReSTError("Unhandled URI '%s'" % uri)


def _GetHandlerMethods(handler):
  """Returns list of HTTP methods supported by handler class.

  @type handler: L{rapi.baserlib.ResourceBase}
  @param handler: Handler class
  @rtype: list of strings

  """
  return sorted(m_attrs.method for m_attrs in rapi.baserlib.OPCODE_ATTRS
                # Only if handler supports method
                if hasattr(handler, m_attrs.method) or
                   hasattr(handler, m_attrs.opcode))


def _DescribeHandlerAccess(handler, method):
  """Returns textual description of required RAPI permissions.

  @type handler: L{rapi.baserlib.ResourceBase}
  @param handler: Handler class
  @type method: string
  @param method: HTTP method (e.g. L{http.HTTP_GET})
  @rtype: string

  """
  access = rapi.baserlib.GetHandlerAccess(handler, method)

  if access:
    return utils.CommaJoin(sorted(access))
  else:
    return "*(none)*"


class _RapiHandlersForDocsHelper(object):
  @classmethod
  def Build(cls):
    """Returns dictionary of resource handlers.

    """
    resources = \
      rapi.connector.GetHandlers("[node_name]", "[instance_name]",
                                 "[group_name]", "[network_name]", "[job_id]",
                                 "[disk_index]", "[filter_uuid]",
                                 "[resource]",
                                 translate=cls._TranslateResourceUri)

    return resources

  @classmethod
  def _TranslateResourceUri(cls, *args):
    """Translates a resource URI for use in documentation.

    @see: L{rapi.connector.GetHandlers}

    """
    return "".join(map(cls._UriPatternToString, args))

  @staticmethod
  def _UriPatternToString(value):
    """Converts L{rapi.connector.UriPattern} to strings.

    """
    if isinstance(value, rapi.connector.UriPattern):
      return value.content
    else:
      return value


_RAPI_RESOURCES_FOR_DOCS = _RapiHandlersForDocsHelper.Build()


def _BuildRapiAccessTable(res):
  """Build a table with access permissions needed for all RAPI resources.

  """
  for (uri, handler) in utils.NiceSort(res.items(), key=compat.fst):
    reslink = _MakeRapiResourceLink(None, uri)
    if not reslink:
      # No link was generated
      continue

    yield ":ref:`%s <%s>`" % (uri, reslink)

    for method in _GetHandlerMethods(handler):
      yield ("  | :ref:`%s <%s>`: %s" %
             (method, _MakeRapiResourceLink(method, uri),
              _DescribeHandlerAccess(handler, method)))


class RapiAccessTable(s_compat.Directive):
  """Custom directive to generate table of all RAPI resources.

  See also <http://docutils.sourceforge.net/docs/howto/rst-directives.html>.

  """
  has_content = False
  required_arguments = 0
  optional_arguments = 0
  final_argument_whitespace = False
  option_spec = {}

  def run(self):
    include_text = "\n".join(_BuildRapiAccessTable(_RAPI_RESOURCES_FOR_DOCS))

    # Inject into state machine
    include_lines = docutils.statemachine.string2lines(include_text, _TAB_WIDTH,
                                                       convert_whitespace=1)
    self.state_machine.insert_input(include_lines, self.__class__.__name__)

    return []


class RapiResourceDetails(s_compat.Directive):
  """Custom directive for RAPI resource details.

  See also <http://docutils.sourceforge.net/docs/howto/rst-directives.html>.

  """
  has_content = False
  required_arguments = 1
  optional_arguments = 0
  final_argument_whitespace = False

  def run(self):
    uri = self.arguments[0]

    try:
      handler = _RAPI_RESOURCES_FOR_DOCS[uri]
    except KeyError:
      raise self.error("Unknown resource URI '%s'" % uri)

    lines = [
      ".. list-table::",
      "   :widths: 1 4",
      "   :header-rows: 1",
      "",
      "   * - Method",
      "     - :ref:`Required permissions <rapi-users>`",
      ]

    for method in _GetHandlerMethods(handler):
      lines.extend([
        "   * - :ref:`%s <%s>`" % (method, _MakeRapiResourceLink(method, uri)),
        "     - %s" % _DescribeHandlerAccess(handler, method),
        ])

    # Inject into state machine
    include_lines = \
      docutils.statemachine.string2lines("\n".join(lines), _TAB_WIDTH,
                                         convert_whitespace=1)
    self.state_machine.insert_input(include_lines, self.__class__.__name__)

    return []


def setup(app):
  """Sphinx extension callback.

  """
  # TODO: Implement Sphinx directive for query fields
  app.add_directive("opcode_params", OpcodeParams)
  app.add_directive("opcode_result", OpcodeResult)
  app.add_directive("pyassert", PythonAssert)
  app.add_role("pyeval", PythonEvalRole)
  app.add_directive("rapi_access_table", RapiAccessTable)
  app.add_directive("rapi_resource_details", RapiResourceDetails)

  app.add_config_value("enable_manpages", False, True)
  app.add_role("manpage", _ManPageRole)
