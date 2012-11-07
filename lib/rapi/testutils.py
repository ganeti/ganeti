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


"""Remote API test utilities.

"""

import logging
import re
import base64
import pycurl
from cStringIO import StringIO

from ganeti import errors
from ganeti import opcodes
from ganeti import http
from ganeti import server
from ganeti import utils
from ganeti import compat
from ganeti import luxi
from ganeti import rapi

import ganeti.http.server # pylint: disable=W0611
import ganeti.server.rapi
import ganeti.rapi.client


_URI_RE = re.compile(r"https://(?P<host>.*):(?P<port>\d+)(?P<path>/.*)")


class VerificationError(Exception):
  """Dedicated error class for test utilities.

  This class is used to hide all of Ganeti's internal exception, so that
  external users of these utilities don't have to integrate Ganeti's exception
  hierarchy.

  """


def _GetOpById(op_id):
  """Tries to get an opcode class based on its C{OP_ID}.

  """
  try:
    return opcodes.OP_MAPPING[op_id]
  except KeyError:
    raise VerificationError("Unknown opcode ID '%s'" % op_id)


def _HideInternalErrors(fn):
  """Hides Ganeti-internal exceptions, see L{VerificationError}.

  """
  def wrapper(*args, **kwargs):
    try:
      return fn(*args, **kwargs)
    except (errors.GenericError, rapi.client.GanetiApiError), err:
      raise VerificationError("Unhandled Ganeti error: %s" % err)

  return wrapper


@_HideInternalErrors
def VerifyOpInput(op_id, data):
  """Verifies opcode parameters according to their definition.

  @type op_id: string
  @param op_id: Opcode ID (C{OP_ID} attribute), e.g. C{OP_CLUSTER_VERIFY}
  @type data: dict
  @param data: Opcode parameter values
  @raise VerificationError: Parameter verification failed

  """
  op_cls = _GetOpById(op_id)

  try:
    op = op_cls(**data) # pylint: disable=W0142
  except TypeError, err:
    raise VerificationError("Unable to create opcode instance: %s" % err)

  try:
    op.Validate(False)
  except errors.OpPrereqError, err:
    raise VerificationError("Parameter validation for opcode '%s' failed: %s" %
                            (op_id, err))


@_HideInternalErrors
def VerifyOpResult(op_id, result):
  """Verifies opcode results used in tests (e.g. in a mock).

  @type op_id: string
  @param op_id: Opcode ID (C{OP_ID} attribute), e.g. C{OP_CLUSTER_VERIFY}
  @param result: Mocked opcode result
  @raise VerificationError: Return value verification failed

  """
  resultcheck_fn = _GetOpById(op_id).OP_RESULT

  if not resultcheck_fn:
    logging.warning("Opcode '%s' has no result type definition", op_id)
  elif not resultcheck_fn(result):
    raise VerificationError("Given result does not match result description"
                            " for opcode '%s': %s" % (op_id, resultcheck_fn))


def _GetPathFromUri(uri):
  """Gets the path and query from a URI.

  """
  match = _URI_RE.match(uri)
  if match:
    return match.groupdict()["path"]
  else:
    return None


class FakeCurl:
  """Fake cURL object.

  """
  def __init__(self, handler):
    """Initialize this class

    @param handler: Request handler instance

    """
    self._handler = handler
    self._opts = {}
    self._info = {}

  def setopt(self, opt, value):
    self._opts[opt] = value

  def getopt(self, opt):
    return self._opts.get(opt)

  def unsetopt(self, opt):
    self._opts.pop(opt, None)

  def getinfo(self, info):
    return self._info[info]

  def perform(self):
    method = self._opts[pycurl.CUSTOMREQUEST]
    url = self._opts[pycurl.URL]
    request_body = self._opts[pycurl.POSTFIELDS]
    writefn = self._opts[pycurl.WRITEFUNCTION]

    if pycurl.HTTPHEADER in self._opts:
      baseheaders = "\n".join(self._opts[pycurl.HTTPHEADER])
    else:
      baseheaders = ""

    headers = http.ParseHeaders(StringIO(baseheaders))

    if request_body:
      headers[http.HTTP_CONTENT_LENGTH] = str(len(request_body))

    if self._opts.get(pycurl.HTTPAUTH, 0) & pycurl.HTTPAUTH_BASIC:
      try:
        userpwd = self._opts[pycurl.USERPWD]
      except KeyError:
        raise errors.ProgrammerError("Basic authentication requires username"
                                     " and password")

      headers[http.HTTP_AUTHORIZATION] = \
        "%s %s" % (http.auth.HTTP_BASIC_AUTH, base64.b64encode(userpwd))

    path = _GetPathFromUri(url)
    (code, resp_body) = \
      self._handler.FetchResponse(path, method, headers, request_body)

    self._info[pycurl.RESPONSE_CODE] = code
    if resp_body is not None:
      writefn(resp_body)


class _RapiMock:
  """Mocking out the RAPI server parts.

  """
  def __init__(self, user_fn, luxi_client):
    """Initialize this class.

    @type user_fn: callable
    @param user_fn: Function to authentication username
    @param luxi_client: A LUXI client implementation

    """
    self.handler = \
      server.rapi.RemoteApiHandler(user_fn, _client_cls=luxi_client)

  def FetchResponse(self, path, method, headers, request_body):
    """This is a callback method used to fetch a response.

    This method is called by the FakeCurl.perform method

    @type path: string
    @param path: Requested path
    @type method: string
    @param method: HTTP method
    @type request_body: string
    @param request_body: Request body
    @type headers: mimetools.Message
    @param headers: Request headers
    @return: Tuple containing status code and response body

    """
    req_msg = http.HttpMessage()
    req_msg.start_line = \
      http.HttpClientToServerStartLine(method, path, http.HTTP_1_0)
    req_msg.headers = headers
    req_msg.body = request_body

    (_, _, _, resp_msg) = \
      http.server.HttpResponder(self.handler)(lambda: (req_msg, None))

    return (resp_msg.start_line.code, resp_msg.body)


class _TestLuxiTransport:
  """Mocked LUXI transport.

  Raises L{errors.RapiTestResult} for all method calls, no matter the
  arguments.

  """
  def __init__(self, record_fn, address, timeouts=None): # pylint: disable=W0613
    """Initializes this class.

    """
    self._record_fn = record_fn

  def Close(self):
    pass

  def Call(self, data):
    """Calls LUXI method.

    In this test class the method is not actually called, but added to a list
    of called methods and then an exception (L{errors.RapiTestResult}) is
    raised. There is no return value.

    """
    (method, _, _) = luxi.ParseRequest(data)

    # Take a note of called method
    self._record_fn(method)

    # Everything went fine until here, so let's abort the test
    raise errors.RapiTestResult


class _LuxiCallRecorder:
  """Records all called LUXI client methods.

  """
  def __init__(self):
    """Initializes this class.

    """
    self._called = set()

  def Record(self, name):
    """Records a called function name.

    """
    self._called.add(name)

  def CalledNames(self):
    """Returns a list of called LUXI methods.

    """
    return self._called

  def __call__(self):
    """Creates an instrumented LUXI client.

    The LUXI client will record all method calls (use L{CalledNames} to
    retrieve them).

    """
    return luxi.Client(transport=compat.partial(_TestLuxiTransport,
                                                self.Record))


def _TestWrapper(fn, *args, **kwargs):
  """Wrapper for ignoring L{errors.RapiTestResult}.

  """
  try:
    return fn(*args, **kwargs)
  except errors.RapiTestResult:
    # Everything was fine up to the point of sending a LUXI request
    return NotImplemented


class InputTestClient:
  """Test version of RAPI client.

  Instances of this class can be used to test input arguments for RAPI client
  calls. See L{rapi.client.GanetiRapiClient} for available methods and their
  arguments. Functions can return C{NotImplemented} if all arguments are
  acceptable, but a LUXI request would be necessary to provide an actual return
  value. In case of an error, L{VerificationError} is raised.

  @see: An example on how to use this class can be found in
    C{doc/examples/rapi_testutils.py}

  """
  def __init__(self):
    """Initializes this class.

    """
    username = utils.GenerateSecret()
    password = utils.GenerateSecret()

    def user_fn(wanted):
      """Called to verify user credentials given in HTTP request.

      """
      assert username == wanted
      return http.auth.PasswordFileUser(username, password,
                                        [rapi.RAPI_ACCESS_WRITE])

    self._lcr = _LuxiCallRecorder()

    # Create a mock RAPI server
    handler = _RapiMock(user_fn, self._lcr)

    self._client = \
      rapi.client.GanetiRapiClient("master.example.com",
                                   username=username, password=password,
                                   curl_factory=lambda: FakeCurl(handler))

  def _GetLuxiCalls(self):
    """Returns the names of all called LUXI client functions.

    """
    return self._lcr.CalledNames()

  def __getattr__(self, name):
    """Finds method by name.

    The method is wrapped using L{_TestWrapper} to produce the actual test
    result.

    """
    return _HideInternalErrors(compat.partial(_TestWrapper,
                                              getattr(self._client, name)))
