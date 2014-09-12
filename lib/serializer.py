#
#

# Copyright (C) 2007, 2008 Google Inc.
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

"""Serializer abstraction module

This module introduces a simple abstraction over the serialization
backend (currently json).

"""
# pylint: disable=C0103

# C0103: Invalid name, since pylint doesn't see that Dump points to a
# function and not a constant

import re

# Python 2.6 and above contain a JSON module based on simplejson. Unfortunately
# the standard library version is significantly slower than the external
# module. While it should be better from at least Python 3.2 on (see Python
# issue 7451), for now Ganeti needs to work well with older Python versions
# too.
import simplejson

from ganeti import errors
from ganeti import utils


_RE_EOLSP = re.compile("[ \t]+$", re.MULTILINE)


def DumpJson(data):
  """Serialize a given object.

  @param data: the data to serialize
  @return: the string representation of data

  """
  encoded = simplejson.dumps(data)

  txt = _RE_EOLSP.sub("", encoded)
  if not txt.endswith("\n"):
    txt += "\n"

  return txt


def LoadJson(txt):
  """Unserialize data from a string.

  @param txt: the json-encoded form

  @return: the original data

  """
  return simplejson.loads(txt)


def DumpSignedJson(data, key, salt=None, key_selector=None):
  """Serialize a given object and authenticate it.

  @param data: the data to serialize
  @param key: shared hmac key
  @param key_selector: name/id that identifies the key (in case there are
    multiple keys in use, e.g. in a multi-cluster environment)
  @return: the string representation of data signed by the hmac key

  """
  txt = DumpJson(data)
  if salt is None:
    salt = ""
  signed_dict = {
    "msg": txt,
    "salt": salt,
    }

  if key_selector:
    signed_dict["key_selector"] = key_selector
  else:
    key_selector = ""

  signed_dict["hmac"] = utils.Sha1Hmac(key, txt, salt=salt + key_selector)

  return DumpJson(signed_dict)


def LoadSignedJson(txt, key):
  """Verify that a given message was signed with the given key, and load it.

  @param txt: json-encoded hmac-signed message
  @param key: the shared hmac key or a callable taking one argument (the key
    selector), which returns the hmac key belonging to the key selector.
    Typical usage is to pass a reference to the get method of a dict.
  @rtype: tuple of original data, string
  @return: original data, salt
  @raises errors.SignatureError: if the message signature doesn't verify

  """
  signed_dict = LoadJson(txt)
  if not isinstance(signed_dict, dict):
    raise errors.SignatureError("Invalid external message")
  try:
    msg = signed_dict["msg"]
    salt = signed_dict["salt"]
    hmac_sign = signed_dict["hmac"]
  except KeyError:
    raise errors.SignatureError("Invalid external message")

  if callable(key):
    # pylint: disable=E1103
    key_selector = signed_dict.get("key_selector", None)
    hmac_key = key(key_selector)
    if not hmac_key:
      raise errors.SignatureError("No key with key selector '%s' found" %
                                  key_selector)
  else:
    key_selector = ""
    hmac_key = key

  if not utils.VerifySha1Hmac(hmac_key, msg, hmac_sign,
                              salt=salt + key_selector):
    raise errors.SignatureError("Invalid Signature")

  return LoadJson(msg), salt


def LoadAndVerifyJson(raw, verify_fn):
  """Parses and verifies JSON data.

  @type raw: string
  @param raw: Input data in JSON format
  @type verify_fn: callable
  @param verify_fn: Verification function, usually from L{ht}
  @return: De-serialized data

  """
  try:
    data = LoadJson(raw)
  except Exception, err:
    raise errors.ParseError("Can't parse input data: %s" % err)

  if not verify_fn(data):
    raise errors.ParseError("Data does not match expected format: %s" %
                            verify_fn)

  return data


Dump = DumpJson
Load = LoadJson
DumpSigned = DumpSignedJson
LoadSigned = LoadSignedJson
