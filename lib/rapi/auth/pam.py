#
#

# Copyright (C) 2015 Google Inc.
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


"""Module interacting with PAM performing authorization and authentication

This module authenticates and authorizes RAPI users based on their credintials.
Both actions are performed by interaction with PAM as a 'ganeti-rapi' service.

"""

import logging
try:
  import ctypes as c # pylint: disable=F0401
  import ctypes.util as util
except ImportError:
  c = None

from ganeti import constants
from ganeti.errors import PamRapiAuthError
import ganeti.http as http
from ganeti.http.auth import HttpServerRequestAuthentication
from ganeti.rapi import auth


__all__ = ['PamAuthenticator']

DEFAULT_SERVICE_NAME = 'ganeti-rapi'
MAX_STR_LENGTH = 100000
MAX_MSG_COUNT = 100
PAM_ENV_URI = 'GANETI_RAPI_URI'
PAM_ENV_BODY = 'GANETI_REQUEST_BODY'
PAM_ENV_METHOD = 'GANETI_REQUEST_METHOD'
PAM_ENV_ACCESS = 'GANETI_RESOURCE_ACCESS'

PAM_ABORT = 26
PAM_BUF_ERR = 5
PAM_CONV_ERR = 19
PAM_SILENT = 32768
PAM_SUCCESS = 0

PAM_PROMPT_ECHO_OFF = 1

PAM_AUTHTOK = 6

if c:
  class PamHandleT(c.Structure):
    """Wrapper for PamHandleT

    """
    _fields_ = [("hidden", c.c_void_p)]

    def __init__(self):
      c.Structure.__init__(self)
      self.handle = 0

  class PamMessage(c.Structure):
    """Wrapper for PamMessage

    """
    _fields_ = [
      ("msg_style", c.c_int),
      ("msg", c.c_char_p),
      ]

  class PamResponse(c.Structure):
    """Wrapper for PamResponse

    """
    _fields_ = [
      ("resp", c.c_char_p),
      ("resp_retcode", c.c_int),
      ]

  CONV_FUNC = c.CFUNCTYPE(c.c_int, c.c_int, c.POINTER(c.POINTER(PamMessage)),
                          c.POINTER(c.POINTER(PamResponse)), c.c_void_p)

  class PamConv(c.Structure):
    """Wrapper for PamConv

    """
    _fields_ = [
      ("conv", CONV_FUNC),
      ("appdata_ptr", c.c_void_p),
      ]


class CFunctions(object):
  def __init__(self):
    if not c:
      raise PamRapiAuthError("ctypes Python package is not found;"
                             " remote API PAM authentication is not available")
    self.libpam = c.CDLL(util.find_library("pam"))
    if not self.libpam:
      raise PamRapiAuthError("libpam C library is not found;"
                             " remote API PAM authentication is not available")
    self.libc = c.CDLL(util.find_library("c"))
    if not self.libc:
      raise PamRapiAuthError("libc C library is not found;"
                             " remote API PAM authentication is not available")

    self.pam_acct_mgmt = self.libpam.pam_acct_mgmt
    self.pam_acct_mgmt.argtypes = [PamHandleT, c.c_int]
    self.pam_acct_mgmt.restype = c.c_int

    self.pam_authenticate = self.libpam.pam_authenticate
    self.pam_authenticate.argtypes = [PamHandleT, c.c_int]
    self.pam_authenticate.restype = c.c_int

    self.pam_end = self.libpam.pam_end
    self.pam_end.argtypes = [PamHandleT, c.c_int]
    self.pam_end.restype = c.c_int

    self.pam_get_item = self.libpam.pam_get_item
    self.pam_get_item.argtypes = [PamHandleT, c.c_int, c.POINTER(c.c_void_p)]
    self.pam_get_item.restype = c.c_int

    self.pam_putenv = self.libpam.pam_putenv
    self.pam_putenv.argtypes = [PamHandleT, c.c_char_p]
    self.pam_putenv.restype = c.c_int

    self.pam_set_item = self.libpam.pam_set_item
    self.pam_set_item.argtypes = [PamHandleT, c.c_int, c.c_void_p]
    self.pam_set_item.restype = c.c_int

    self.pam_start = self.libpam.pam_start
    self.pam_start.argtypes = [
      c.c_char_p,
      c.c_char_p,
      c.POINTER(PamConv),
      c.POINTER(PamHandleT),
      ]
    self.pam_start.restype = c.c_int

    self.calloc = self.libc.calloc
    self.calloc.argtypes = [c.c_uint, c.c_uint]
    self.calloc.restype = c.c_void_p

    self.free = self.libc.free
    self.free.argstypes = [c.c_void_p]
    self.free.restype = None

    self.strndup = self.libc.strndup
    self.strndup.argstypes = [c.c_char_p, c.c_uint]
    self.strndup.restype = c.c_char_p


def Authenticate(cf, pam_handle, authtok=None):
  """Performs authentication via PAM.

  Perfroms two steps:
    - if authtok is provided then set it with pam_set_item
    - call pam_authenticate

  """
  try:
    authtok_copy = None
    if authtok:
      authtok_copy = cf.strndup(authtok, len(authtok))
      if not authtok_copy:
        raise http.HttpInternalServerError("Not enough memory for PAM")
      ret = cf.pam_set_item(c.pointer(pam_handle), PAM_AUTHTOK, authtok_copy)
      if ret != PAM_SUCCESS:
        raise http.HttpInternalServerError("pam_set_item failed [%d]" % ret)

    ret = cf.pam_authenticate(pam_handle, 0)
    if ret == PAM_ABORT:
      raise http.HttpInternalServerError("pam_authenticate requested abort")
    if ret != PAM_SUCCESS:
      raise http.HttpUnauthorized("Authentication failed")
  except:
    cf.pam_end(pam_handle, ret)
    raise
  finally:
    if authtok_copy:
      cf.free(authtok_copy)


def PutPamEnvVariable(cf, pam_handle, name, value):
  """Wrapper over pam_setenv.

  """
  setenv = "%s=" % name
  if value:
    setenv += value
  ret = cf.pam_putenv(pam_handle, setenv)
  if ret != PAM_SUCCESS:
    raise http.HttpInternalServerError("pam_putenv call failed [%d]" % ret)


def Authorize(cf, pam_handle, uri_access_rights, uri=None, method=None,
              body=None):
  """Performs authorization via PAM.

  Performs two steps:
    - initialize environmental variables
    - call pam_acct_mgmt

  """
  try:
    PutPamEnvVariable(cf, pam_handle, PAM_ENV_ACCESS, uri_access_rights)
    PutPamEnvVariable(cf, pam_handle, PAM_ENV_URI, uri)
    PutPamEnvVariable(cf, pam_handle, PAM_ENV_METHOD, method)
    PutPamEnvVariable(cf, pam_handle, PAM_ENV_BODY, body)

    ret = cf.pam_acct_mgmt(pam_handle, PAM_SILENT)
    if ret != PAM_SUCCESS:
      raise http.HttpUnauthorized("Authorization failed")
  except:
    cf.pam_end(pam_handle, ret)
    raise


def ValidateParams(username, _uri_access_rights, password, service, authtok,
                   _uri, _method, _body):
  """Checks whether ValidateRequest has been called with a correct params.

  These checks includes:
    - username is an obligatory parameter
    - either password or authtok is an obligatory parameter

  """
  if not username:
    raise http.HttpUnauthorized("Username should be provided")
  if not service:
    raise http.HttpBadRequest("Service should be proivded")
  if not password and not authtok:
    raise http.HttpUnauthorized("Password or authtok should be provided")


def ValidateRequest(cf, username, uri_access_rights, password=None,
                    service=DEFAULT_SERVICE_NAME, authtok=None, uri=None,
                    method=None, body=None):
  """Checks whether it's permitted to execute an rapi request.

  Calls pam_authenticate and then pam_acct_mgmt in order to check whether a
  request should be executed.

  @param cf: An instance of CFunctions class containing necessary imports
  @param username: username
  @param uri_access_rights: handler access rights
  @param password: password
  @param service: a service name that will be used for the interaction with PAM
  @param authtok: user's authentication token (e.g. some kind of signature)
  @param uri: an uri of a target resource obtained from an http header
  @param method: http method trying to access the uri
  @param body: a body of an RAPI request

  """
  ValidateParams(username, uri_access_rights, password, service, authtok, uri,
                 method, body)

  def ConversationFunction(num_msg, msg, resp, _app_data_ptr):
    """Conversation function that will be provided to PAM modules.

    The function replies with a password for each message with
    PAM_PROMPT_ECHO_OFF style and just ignores the others.

    """
    if num_msg > MAX_MSG_COUNT:
      logging.info("Too many messages passed to conv function: [%d]", num_msg)
      return PAM_BUF_ERR
    response = cf.calloc(num_msg, c.sizeof(PamResponse))
    if not response:
      logging.info("calloc failed in conv function")
      return PAM_BUF_ERR
    resp[0] = c.cast(response, c.POINTER(PamResponse))
    for i in range(num_msg):
      if msg[i].contents.msg_style != PAM_PROMPT_ECHO_OFF:
        continue
      resp.contents[i].resp = cf.strndup(password, len(password))
      if not resp.contents[i].resp:
        logging.info("strndup failed in conv function")
        for j in range(i):
          cf.free(c.cast(resp.contents[j].resp, c.c_void_p))
        cf.free(response)
        return PAM_BUF_ERR
      resp.contents[i].resp_retcode = 0
    return PAM_SUCCESS

  pam_handle = PamHandleT()
  conv = PamConv(CONV_FUNC(ConversationFunction), 0)
  ret = cf.pam_start(service, username, c.pointer(conv), c.pointer(pam_handle))
  if ret != PAM_SUCCESS:
    cf.pam_end(pam_handle, ret)
    raise http.HttpInternalServerError("pam_start call failed [%d]" % ret)

  Authenticate(cf, pam_handle, authtok)
  Authorize(cf, pam_handle, uri_access_rights, uri, method, body)

  cf.pam_end(pam_handle, PAM_SUCCESS)


def MakeStringC(string):
  """Converts a string to a valid C string.

  As a C side treats non-unicode strings, encode unicode string with 'ascii'.
  Also ensure that C string will not be longer than MAX_STR_LENGTH in order to
  prevent attacs based on too long buffers.

  """
  if string is None:
    return None
  if isinstance(string, unicode):
    string = string.encode("ascii")
  if not isinstance(string, str):
    return None
  if len(string) <= MAX_STR_LENGTH:
    return string
  return string[:MAX_STR_LENGTH]


class PamAuthenticator(auth.RapiAuthenticator):
  """Class providing an Authenticate method based on interaction with PAM.

  """

  def __init__(self):
    """Checks whether ctypes has been imported.

    """
    self.cf = CFunctions()

  def ValidateRequest(self, req, handler_access):
    """Checks whether a user can access a resource.

    """
    username, password = HttpServerRequestAuthentication \
                           .ExtractUserPassword(req)
    authtok = req.request_headers.get(constants.HTTP_RAPI_PAM_CREDENTIAL, None)
    if handler_access is not None:
      handler_access_ = ','.join(handler_access)
    ValidateRequest(self.cf, MakeStringC(username),
                    MakeStringC(handler_access_),
                    MakeStringC(password),
                    MakeStringC(DEFAULT_SERVICE_NAME),
                    MakeStringC(authtok), MakeStringC(req.request_path),
                    MakeStringC(req.request_method),
                    MakeStringC(req.request_body))
    return True
