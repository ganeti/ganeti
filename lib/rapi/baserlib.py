#
#

# Copyright (C) 2006, 2007, 2008, 2012 Google Inc.
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


"""Remote API base resources library.

"""

# pylint: disable=C0103

# C0103: Invalid name, since the R_* names are not conforming

import logging

from ganeti import luxi
from ganeti import rapi
from ganeti import http
from ganeti import errors
from ganeti import compat
from ganeti import constants
from ganeti import pathutils


# Dummy value to detect unchanged parameters
_DEFAULT = object()

#: Supported HTTP methods
_SUPPORTED_METHODS = frozenset([
  http.HTTP_DELETE,
  http.HTTP_GET,
  http.HTTP_POST,
  http.HTTP_PUT,
  ])


def _BuildOpcodeAttributes():
  """Builds list of attributes used for per-handler opcodes.

  """
  return [(method, "%s_OPCODE" % method, "%s_RENAME" % method,
           "Get%sOpInput" % method.capitalize())
          for method in _SUPPORTED_METHODS]


_OPCODE_ATTRS = _BuildOpcodeAttributes()


def BuildUriList(ids, uri_format, uri_fields=("name", "uri")):
  """Builds a URI list as used by index resources.

  @param ids: list of ids as strings
  @param uri_format: format to be applied for URI
  @param uri_fields: optional parameter for field IDs

  """
  (field_id, field_uri) = uri_fields

  def _MapId(m_id):
    return {
      field_id: m_id,
      field_uri: uri_format % m_id,
      }

  # Make sure the result is sorted, makes it nicer to look at and simplifies
  # unittests.
  ids.sort()

  return map(_MapId, ids)


def ExtractField(sequence, index):
  """Creates a list containing one column out of a list of lists.

  @param sequence: sequence of lists
  @param index: index of field

  """
  return map(lambda item: item[index], sequence)


def MapFields(names, data):
  """Maps two lists into one dictionary.

  Example::
      >>> MapFields(["a", "b"], ["foo", 123])
      {'a': 'foo', 'b': 123}

  @param names: field names (list of strings)
  @param data: field data (list)

  """
  if len(names) != len(data):
    raise AttributeError("Names and data must have the same length")
  return dict(zip(names, data))


def MapBulkFields(itemslist, fields):
  """Map value to field name in to one dictionary.

  @param itemslist: a list of items values
  @param fields: a list of items names

  @return: a list of mapped dictionaries

  """
  items_details = []
  for item in itemslist:
    mapped = MapFields(fields, item)
    items_details.append(mapped)
  return items_details


def MakeParamsDict(opts, params):
  """Makes params dictionary out of a option set.

  This function returns a dictionary needed for hv or be parameters. But only
  those fields which provided in the option set. Takes parameters frozensets
  from constants.

  @type opts: dict
  @param opts: selected options
  @type params: frozenset
  @param params: subset of options
  @rtype: dict
  @return: dictionary of options, filtered by given subset.

  """
  result = {}

  for p in params:
    try:
      value = opts[p]
    except KeyError:
      continue
    result[p] = value

  return result


def FillOpcode(opcls, body, static, rename=None):
  """Fills an opcode with body parameters.

  Parameter types are checked.

  @type opcls: L{opcodes.OpCode}
  @param opcls: Opcode class
  @type body: dict
  @param body: Body parameters as received from client
  @type static: dict
  @param static: Static parameters which can't be modified by client
  @type rename: dict
  @param rename: Renamed parameters, key as old name, value as new name
  @return: Opcode object

  """
  if body is None:
    params = {}
  else:
    CheckType(body, dict, "Body contents")

    # Make copy to be modified
    params = body.copy()

  if rename:
    for old, new in rename.items():
      if new in params and old in params:
        raise http.HttpBadRequest("Parameter '%s' was renamed to '%s', but"
                                  " both are specified" %
                                  (old, new))
      if old in params:
        assert new not in params
        params[new] = params.pop(old)

  if static:
    overwritten = set(params.keys()) & set(static.keys())
    if overwritten:
      raise http.HttpBadRequest("Can't overwrite static parameters %r" %
                                overwritten)

    params.update(static)

  # Convert keys to strings (simplejson decodes them as unicode)
  params = dict((str(key), value) for (key, value) in params.items())

  try:
    op = opcls(**params) # pylint: disable=W0142
    op.Validate(False)
  except (errors.OpPrereqError, TypeError), err:
    raise http.HttpBadRequest("Invalid body parameters: %s" % err)

  return op


def HandleItemQueryErrors(fn, *args, **kwargs):
  """Converts errors when querying a single item.

  """
  try:
    return fn(*args, **kwargs)
  except errors.OpPrereqError, err:
    if len(err.args) == 2 and err.args[1] == errors.ECODE_NOENT:
      raise http.HttpNotFound()

    raise


def FeedbackFn(msg):
  """Feedback logging function for jobs.

  We don't have a stdout for printing log messages, so log them to the
  http log at least.

  @param msg: the message

  """
  (_, log_type, log_msg) = msg
  logging.info("%s: %s", log_type, log_msg)


def CheckType(value, exptype, descr):
  """Abort request if value type doesn't match expected type.

  @param value: Value
  @type exptype: type
  @param exptype: Expected type
  @type descr: string
  @param descr: Description of value
  @return: Value (allows inline usage)

  """
  if not isinstance(value, exptype):
    raise http.HttpBadRequest("%s: Type is '%s', but '%s' is expected" %
                              (descr, type(value).__name__, exptype.__name__))

  return value


def CheckParameter(data, name, default=_DEFAULT, exptype=_DEFAULT):
  """Check and return the value for a given parameter.

  If no default value was given and the parameter doesn't exist in the input
  data, an error is raise.

  @type data: dict
  @param data: Dictionary containing input data
  @type name: string
  @param name: Parameter name
  @param default: Default value (can be None)
  @param exptype: Expected type (can be None)

  """
  try:
    value = data[name]
  except KeyError:
    if default is not _DEFAULT:
      return default

    raise http.HttpBadRequest("Required parameter '%s' is missing" %
                              name)

  if exptype is _DEFAULT:
    return value

  return CheckType(value, exptype, "'%s' parameter" % name)


class ResourceBase(object):
  """Generic class for resources.

  """
  # Default permission requirements
  GET_ACCESS = []
  PUT_ACCESS = [rapi.RAPI_ACCESS_WRITE]
  POST_ACCESS = [rapi.RAPI_ACCESS_WRITE]
  DELETE_ACCESS = [rapi.RAPI_ACCESS_WRITE]

  def __init__(self, items, queryargs, req, _client_cls=None):
    """Generic resource constructor.

    @param items: a list with variables encoded in the URL
    @param queryargs: a dictionary with additional options from URL
    @param req: Request context
    @param _client_cls: L{luxi} client class (unittests only)

    """
    self.items = items
    self.queryargs = queryargs
    self._req = req

    if _client_cls is None:
      _client_cls = luxi.Client

    self._client_cls = _client_cls

  def _GetRequestBody(self):
    """Returns the body data.

    """
    return self._req.private.body_data

  request_body = property(fget=_GetRequestBody)

  def _checkIntVariable(self, name, default=0):
    """Return the parsed value of an int argument.

    """
    val = self.queryargs.get(name, default)
    if isinstance(val, list):
      if val:
        val = val[0]
      else:
        val = default
    try:
      val = int(val)
    except (ValueError, TypeError):
      raise http.HttpBadRequest("Invalid value for the"
                                " '%s' parameter" % (name,))
    return val

  def _checkStringVariable(self, name, default=None):
    """Return the parsed value of an int argument.

    """
    val = self.queryargs.get(name, default)
    if isinstance(val, list):
      if val:
        val = val[0]
      else:
        val = default
    return val

  def getBodyParameter(self, name, *args):
    """Check and return the value for a given parameter.

    If a second parameter is not given, an error will be returned,
    otherwise this parameter specifies the default value.

    @param name: the required parameter

    """
    if args:
      return CheckParameter(self.request_body, name, default=args[0])

    return CheckParameter(self.request_body, name)

  def useLocking(self):
    """Check if the request specifies locking.

    """
    return bool(self._checkIntVariable("lock"))

  def useBulk(self):
    """Check if the request specifies bulk querying.

    """
    return bool(self._checkIntVariable("bulk"))

  def useForce(self):
    """Check if the request specifies a forced operation.

    """
    return bool(self._checkIntVariable("force"))

  def dryRun(self):
    """Check if the request specifies dry-run mode.

    """
    return bool(self._checkIntVariable("dry-run"))

  def GetClient(self, query=False):
    """Wrapper for L{luxi.Client} with HTTP-specific error handling.

    @param query: this signifies that the client will only be used for
        queries; if the build-time parameter enable-split-queries is
        enabled, then the client will be connected to the query socket
        instead of the masterd socket

    """
    if query and constants.ENABLE_SPLIT_QUERY:
      address = pathutils.QUERY_SOCKET
    else:
      address = None
    # Could be a function, pylint: disable=R0201
    try:
      return self._client_cls(address=address)
    except luxi.NoMasterError, err:
      raise http.HttpBadGateway("Can't connect to master daemon: %s" % err)
    except luxi.PermissionError:
      raise http.HttpInternalServerError("Internal error: no permission to"
                                         " connect to the master daemon")

  def SubmitJob(self, op, cl=None):
    """Generic wrapper for submit job, for better http compatibility.

    @type op: list
    @param op: the list of opcodes for the job
    @type cl: None or luxi.Client
    @param cl: optional luxi client to use
    @rtype: string
    @return: the job ID

    """
    if cl is None:
      cl = self.GetClient()
    try:
      return cl.SubmitJob(op)
    except errors.JobQueueFull:
      raise http.HttpServiceUnavailable("Job queue is full, needs archiving")
    except errors.JobQueueDrainError:
      raise http.HttpServiceUnavailable("Job queue is drained, cannot submit")
    except luxi.NoMasterError, err:
      raise http.HttpBadGateway("Master seems to be unreachable: %s" % err)
    except luxi.PermissionError:
      raise http.HttpInternalServerError("Internal error: no permission to"
                                         " connect to the master daemon")
    except luxi.TimeoutError, err:
      raise http.HttpGatewayTimeout("Timeout while talking to the master"
                                    " daemon: %s" % err)


def GetResourceOpcodes(cls):
  """Returns all opcodes used by a resource.

  """
  return frozenset(filter(None, (getattr(cls, op_attr, None)
                                 for (_, op_attr, _, _) in _OPCODE_ATTRS)))


class _MetaOpcodeResource(type):
  """Meta class for RAPI resources.

  """
  def __call__(mcs, *args, **kwargs):
    """Instantiates class and patches it for use by the RAPI daemon.

    """
    # Access to private attributes of a client class, pylint: disable=W0212
    obj = type.__call__(mcs, *args, **kwargs)

    for (method, op_attr, rename_attr, fn_attr) in _OPCODE_ATTRS:
      if hasattr(obj, method):
        # If the method handler is already defined, "*_RENAME" or "Get*OpInput"
        # shouldn't be (they're only used by the automatically generated
        # handler)
        assert not hasattr(obj, rename_attr)
        assert not hasattr(obj, fn_attr)
      else:
        # Try to generate handler method on handler instance
        try:
          opcode = getattr(obj, op_attr)
        except AttributeError:
          pass
        else:
          setattr(obj, method,
                  compat.partial(obj._GenericHandler, opcode,
                                 getattr(obj, rename_attr, None),
                                 getattr(obj, fn_attr, obj._GetDefaultData)))

    return obj


class OpcodeResource(ResourceBase):
  """Base class for opcode-based RAPI resources.

  Instances of this class automatically gain handler functions through
  L{_MetaOpcodeResource} for any method for which a C{$METHOD$_OPCODE} variable
  is defined at class level. Subclasses can define a C{Get$Method$OpInput}
  method to do their own opcode input processing (e.g. for static values). The
  C{$METHOD$_RENAME} variable defines which values are renamed (see
  L{baserlib.FillOpcode}).

  @cvar GET_OPCODE: Set this to a class derived from L{opcodes.OpCode} to
    automatically generate a GET handler submitting the opcode
  @cvar GET_RENAME: Set this to rename parameters in the GET handler (see
    L{baserlib.FillOpcode})
  @ivar GetGetOpInput: Define this to override the default method for
    getting opcode parameters (see L{baserlib.OpcodeResource._GetDefaultData})

  @cvar PUT_OPCODE: Set this to a class derived from L{opcodes.OpCode} to
    automatically generate a PUT handler submitting the opcode
  @cvar PUT_RENAME: Set this to rename parameters in the PUT handler (see
    L{baserlib.FillOpcode})
  @ivar GetPutOpInput: Define this to override the default method for
    getting opcode parameters (see L{baserlib.OpcodeResource._GetDefaultData})

  @cvar POST_OPCODE: Set this to a class derived from L{opcodes.OpCode} to
    automatically generate a POST handler submitting the opcode
  @cvar POST_RENAME: Set this to rename parameters in the DELETE handler (see
    L{baserlib.FillOpcode})
  @ivar GetPostOpInput: Define this to override the default method for
    getting opcode parameters (see L{baserlib.OpcodeResource._GetDefaultData})

  @cvar DELETE_OPCODE: Set this to a class derived from L{opcodes.OpCode} to
    automatically generate a GET handler submitting the opcode
  @cvar DELETE_RENAME: Set this to rename parameters in the DELETE handler (see
    L{baserlib.FillOpcode})
  @ivar GetDeleteOpInput: Define this to override the default method for
    getting opcode parameters (see L{baserlib.OpcodeResource._GetDefaultData})

  """
  __metaclass__ = _MetaOpcodeResource

  def _GetDefaultData(self):
    return (self.request_body, None)

  def _GenericHandler(self, opcode, rename, fn):
    (body, static) = fn()
    op = FillOpcode(opcode, body, static, rename=rename)
    return self.SubmitJob([op])
