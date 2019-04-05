#
#

# Copyright (C) 2006, 2007, 2008, 2012 Google Inc.
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


"""Remote API base resources library.

"""

# pylint: disable=C0103

# C0103: Invalid name, since the R_* names are not conforming

import logging

from ganeti import luxi
import ganeti.rpc.errors as rpcerr
from ganeti import rapi
from ganeti import http
from ganeti import errors
from ganeti import compat
from ganeti import constants
from ganeti import utils


# Dummy value to detect unchanged parameters
_DEFAULT = object()

#: Supported HTTP methods
_SUPPORTED_METHODS = compat.UniqueFrozenset([
  http.HTTP_DELETE,
  http.HTTP_GET,
  http.HTTP_POST,
  http.HTTP_PUT,
  ])


class OpcodeAttributes(object):
  """Acts as a structure containing the per-method attribute names.

  """
  __slots__ = [
    "method",
    "opcode",
    "rename",
    "aliases",
    "forbidden",
    "get_input",
    ]

  def __init__(self, method_name):
    """Initializes the opcode attributes for the given method name.

    """
    self.method = method_name
    self.opcode = "%s_OPCODE" % method_name
    self.rename = "%s_RENAME" % method_name
    self.aliases = "%s_ALIASES" % method_name
    self.forbidden = "%s_FORBIDDEN" % method_name
    self.get_input = "Get%sOpInput" % method_name.capitalize()

  def GetModifiers(self):
    """Returns the names of all the attributes that replace or modify a method.

    """
    return [self.opcode, self.rename, self.aliases, self.forbidden,
            self.get_input]

  def GetAll(self):
    return [self.method] + self.GetModifiers()


def _BuildOpcodeAttributes():
  """Builds list of attributes used for per-handler opcodes.

  """
  return [OpcodeAttributes(method) for method in _SUPPORTED_METHODS]


OPCODE_ATTRS = _BuildOpcodeAttributes()


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
    op = opcls(**params)
    op.Validate(False)
  except (errors.OpPrereqError, TypeError) as err:
    raise http.HttpBadRequest("Invalid body parameters: %s" % err)

  return op


def HandleItemQueryErrors(fn, *args, **kwargs):
  """Converts errors when querying a single item.

  """
  try:
    result = fn(*args, **kwargs)
  except errors.OpPrereqError as err:
    if len(err.args) == 2 and err.args[1] == errors.ECODE_NOENT:
      raise http.HttpNotFound()

    raise

  # In case split query mechanism is used
  if not result:
    raise http.HttpNotFound()

  return result


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
    assert isinstance(queryargs, dict)

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
    """Return the parsed value of a string argument.

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

  def GetClient(self):
    """Wrapper for L{luxi.Client} with HTTP-specific error handling.

    """
    # Could be a function, pylint: disable=R0201
    try:
      return self._client_cls()
    except rpcerr.NoMasterError as err:
      raise http.HttpBadGateway("Can't connect to master daemon: %s" % err)
    except rpcerr.PermissionError:
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
    except rpcerr.NoMasterError as err:
      raise http.HttpBadGateway("Master seems to be unreachable: %s" % err)
    except rpcerr.PermissionError:
      raise http.HttpInternalServerError("Internal error: no permission to"
                                         " connect to the master daemon")
    except rpcerr.TimeoutError as err:
      raise http.HttpGatewayTimeout("Timeout while talking to the master"
                                    " daemon: %s" % err)


def GetResourceOpcodes(cls):
  """Returns all opcodes used by a resource.

  """
  return frozenset(filter(None, (getattr(cls, method_attrs.opcode, None)
                                 for method_attrs in OPCODE_ATTRS)))


def GetHandlerAccess(handler, method):
  """Returns the access rights for a method on a handler.

  @type handler: L{ResourceBase}
  @type method: string
  @rtype: string or None

  """
  return getattr(handler, "%s_ACCESS" % method, None)


def GetHandler(get_fn, aliases):
  result = get_fn()
  if not isinstance(result, dict) or aliases is None:
    return result

  for (param, alias) in aliases.items():
    if param in result:
      if alias in result:
        raise http.HttpBadRequest("Parameter '%s' has an alias of '%s', but"
                                  " both values are present in response" %
                                  (param, alias))
      result[alias] = result[param]

  return result


# Constant used to denote that a parameter cannot be set
ALL_VALUES_FORBIDDEN = "all_values_forbidden"


def ProduceForbiddenParamDict(class_name, method_name, param_list):
  """Turns a list of parameter names and possibly values into a dictionary.

  @type class_name: string
  @param class_name: The name of the handler class
  @type method_name: string
  @param method_name: The name of the HTTP method
  @type param_list: list of string or tuple of (string, list of any)
  @param param_list: A list of forbidden parameters, specified in the RAPI
                     handler class

  @return: The dictionary of forbidden param names to values or
           ALL_VALUES_FORBIDDEN

  """
  # A simple error-raising function
  def _RaiseError(message):
    raise errors.ProgrammerError(
      "While examining the %s_FORBIDDEN field of class %s: %s" %
      (method_name, class_name, message)
    )

  param_dict = {}
  for value in param_list:
    if isinstance(value, str):
      param_dict[value] = ALL_VALUES_FORBIDDEN
    elif isinstance(value, tuple):
      if len(value) != 2:
        _RaiseError("Tuples of only length 2 allowed")
      param_name, forbidden_values = value
      param_dict[param_name] = forbidden_values
    else:
      _RaiseError("Only strings or tuples allowed, found %s" % value)

  return param_dict


def InspectParams(params_dict, forbidden_params, rename_dict):
  """Inspects a dictionary of params, looking for forbidden values.

  @type params_dict: dict of string to anything
  @param params_dict: A dictionary of supplied parameters
  @type forbidden_params: dict of string to string or list of any
  @param forbidden_params: The forbidden parameters, with a list of forbidden
                           values or the constant ALL_VALUES_FORBIDDEN
                           signifying that all values are forbidden
  @type rename_dict: None or dict of string to string
  @param rename_dict: The list of parameter renamings used by the method

  @raise http.HttpForbidden: If a forbidden param has been set

  """
  for param in params_dict:
    # Check for possible renames to ensure nothing slips through
    if rename_dict is not None and param in rename_dict:
      param = rename_dict[param]

    # Now see if there are restrictions on this parameter
    if param in forbidden_params:
      forbidden_values = forbidden_params[param]
      if forbidden_values == ALL_VALUES_FORBIDDEN:
        raise http.HttpForbidden("The parameter %s cannot be set via RAPI" %
                                 param)

      param_value = params_dict[param]
      if param_value in forbidden_values:
        raise http.HttpForbidden("The parameter %s cannot be set to the value"
                                 " %s via RAPI" % (param, param_value))


class _MetaOpcodeResource(type):
  """Meta class for RAPI resources.

  """
  def __call__(mcs, *args, **kwargs):
    """Instantiates class and patches it for use by the RAPI daemon.

    """
    # Access to private attributes of a client class, pylint: disable=W0212
    obj = type.__call__(mcs, *args, **kwargs)

    for m_attrs in OPCODE_ATTRS:
      method, op_attr, rename_attr, aliases_attr, _, fn_attr = m_attrs.GetAll()
      if hasattr(obj, method):
        # If the method handler is already defined, "*_RENAME" or
        # "Get*OpInput" shouldn't be (they're only used by the automatically
        # generated handler)
        assert not hasattr(obj, rename_attr)
        assert not hasattr(obj, fn_attr)

        # The aliases are allowed only on GET calls
        assert not hasattr(obj, aliases_attr) or method == http.HTTP_GET

        # GET methods can add aliases of values they return under a different
        # name
        if method == http.HTTP_GET and hasattr(obj, aliases_attr):
          setattr(obj, method,
                  compat.partial(GetHandler, getattr(obj, method),
                                 getattr(obj, aliases_attr)))
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

      # Finally, the method (generated or not) should be wrapped to handle
      # forbidden values
      if hasattr(obj, m_attrs.forbidden):
        forbidden_dict = ProduceForbiddenParamDict(
          obj.__class__.__name__, method, getattr(obj, m_attrs.forbidden)
        )
        setattr(
          obj, method, compat.partial(obj._ForbiddenHandler,
                                      getattr(obj, method),
                                      forbidden_dict,
                                      getattr(obj, m_attrs.rename, None))
        )

    return obj


class OpcodeResource(ResourceBase):
  """Base class for opcode-based RAPI resources.

  Instances of this class automatically gain handler functions through
  L{_MetaOpcodeResource} for any method for which a C{$METHOD$_OPCODE} variable
  is defined at class level. Subclasses can define a C{Get$Method$OpInput}
  method to do their own opcode input processing (e.g. for static values). The
  C{$METHOD$_RENAME} variable defines which values are renamed (see
  L{baserlib.FillOpcode}).
  Still default behavior cannot be totally overriden. There are opcode params
  that are available to all opcodes, e.g. "depends". In case those params
  (currently only "depends") are found in the original request's body, they are
  added to the dictionary of parsed parameters and eventually passed to the
  opcode. If the parsed body is not represented as a dictionary object, the
  values are not added.

  @cvar GET_OPCODE: Set this to a class derived from L{opcodes.OpCode} to
    automatically generate a GET handler submitting the opcode
  @cvar GET_RENAME: Set this to rename parameters in the GET handler (see
    L{baserlib.FillOpcode})
  @cvar GET_FORBIDDEN: Set this to disable listed parameters and optionally
    specific values from being set through the GET handler (see
    L{baserlib.InspectParams})
  @cvar GET_ALIASES: Set this to duplicate return values in GET results (see
    L{baserlib.GetHandler})
  @ivar GetGetOpInput: Define this to override the default method for
    getting opcode parameters (see L{baserlib.OpcodeResource._GetDefaultData})

  @cvar PUT_OPCODE: Set this to a class derived from L{opcodes.OpCode} to
    automatically generate a PUT handler submitting the opcode
  @cvar PUT_RENAME: Set this to rename parameters in the PUT handler (see
    L{baserlib.FillOpcode})
  @cvar PUT_FORBIDDEN: Set this to disable listed parameters and optionally
    specific values from being set through the PUT handler (see
    L{baserlib.InspectParams})
  @ivar GetPutOpInput: Define this to override the default method for
    getting opcode parameters (see L{baserlib.OpcodeResource._GetDefaultData})

  @cvar POST_OPCODE: Set this to a class derived from L{opcodes.OpCode} to
    automatically generate a POST handler submitting the opcode
  @cvar POST_RENAME: Set this to rename parameters in the POST handler (see
    L{baserlib.FillOpcode})
  @cvar POST_FORBIDDEN: Set this to disable listed parameters and optionally
    specific values from being set through the POST handler (see
    L{baserlib.InspectParams})
  @ivar GetPostOpInput: Define this to override the default method for
    getting opcode parameters (see L{baserlib.OpcodeResource._GetDefaultData})

  @cvar DELETE_OPCODE: Set this to a class derived from L{opcodes.OpCode} to
    automatically generate a DELETE handler submitting the opcode
  @cvar DELETE_RENAME: Set this to rename parameters in the DELETE handler (see
    L{baserlib.FillOpcode})
  @cvar DELETE_FORBIDDEN: Set this to disable listed parameters and optionally
    specific values from being set through the DELETE handler (see
    L{baserlib.InspectParams})
  @ivar GetDeleteOpInput: Define this to override the default method for
    getting opcode parameters (see L{baserlib.OpcodeResource._GetDefaultData})

  """
  __metaclass__ = _MetaOpcodeResource

  def _ForbiddenHandler(self, method_fn, forbidden_params, rename_dict):
    """Examines provided parameters for forbidden values.

    """
    InspectParams(self.queryargs, forbidden_params, rename_dict)
    InspectParams(self.request_body, forbidden_params, rename_dict)
    return method_fn()

  def _GetDefaultData(self):
    return (self.request_body, None)

  def _GetRapiOpName(self):
    """Extracts the name of the RAPI operation from the class name

    """
    if self.__class__.__name__.startswith("R_2_"):
      return self.__class__.__name__[4:]
    return self.__class__.__name__

  def _GetCommonStatic(self):
    """Return the static parameters common to all the RAPI calls

    The reason is a parameter present in all the RAPI calls, and the reason
    trail has to be build for all of them, so the parameter is read here and
    used to build the reason trail, that is the actual parameter passed
    forward.

    """
    trail = []
    usr_reason = self._checkStringVariable("reason", default=None)
    if usr_reason:
      trail.append((constants.OPCODE_REASON_SRC_USER,
                    usr_reason,
                    utils.EpochNano()))
    reason_src = "%s:%s" % (constants.OPCODE_REASON_SRC_RLIB2,
                            self._GetRapiOpName())
    trail.append((reason_src, "", utils.EpochNano()))
    common_static = {
      "reason": trail,
      }
    return common_static

  def _GetDepends(self):
    ret = {}
    if isinstance(self.request_body, dict):
      depends = self.getBodyParameter("depends", None)
      if depends:
        ret.update({"depends": depends})
    return ret

  def _GenericHandler(self, opcode, rename, fn):
    (body, specific_static) = fn()
    if isinstance(body, dict):
      body.update(self._GetDepends())
    static = self._GetCommonStatic()
    if specific_static:
      static.update(specific_static)
    op = FillOpcode(opcode, body, static, rename=rename)
    return self.SubmitJob([op])
