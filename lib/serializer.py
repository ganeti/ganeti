#
#

# Copyright (C) 2007, 2008 Google Inc.
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

"""Serializer abstraction module

This module introduces a simple abstraction over the serialization
backend (currently json).

"""
# pylint: disable=C0103

# C0103: Invalid name, since pylint doesn't see that Dump points to a
# function and not a constant

_OLD_SIMPLEJSON = False

try:
  import json
except ImportError:
  # The "json" module was only added in Python 2.6. Earlier versions must use
  # the separate "simplejson" module.
  import simplejson as json
  _OLD_SIMPLEJSON = True

import re
import logging

from ganeti import errors
from ganeti import utils


_JSON_INDENT = 2

_RE_EOLSP = re.compile("[ \t]+$", re.MULTILINE)


class _CustomJsonEncoder(json.JSONEncoder):
  if __debug__ and not _OLD_SIMPLEJSON:
    try:
      _orig_fn = json.JSONEncoder._iterencode_dict
    except AttributeError:
      raise Exception("Can't override JSONEncoder's '_iterencode_dict'")
    else:
      def _iterencode_dict(self, data, *args, **kwargs):
        for key in data.keys():
          if not (key is None or isinstance(key, (basestring, bool))):
            raise ValueError("Key '%s' is of disallowed type '%s'" %
                             (key, type(key)))

        return self._orig_fn(data, *args, **kwargs)


def _GetJsonDumpers(_encoder_class=_CustomJsonEncoder):
  """Returns two JSON functions to serialize data.

  @rtype: (callable, callable)
  @return: The function to generate a compact form of JSON and another one to
           generate a more readable, indented form of JSON (if supported)

  """
  plain_encoder = _encoder_class(sort_keys=True)

  # Check whether the simplejson module supports indentation
  try:
    indent_encoder = _encoder_class(indent=_JSON_INDENT, sort_keys=True)
  except TypeError:
    # Indentation not supported
    indent_encoder = plain_encoder

  return (plain_encoder.encode, indent_encoder.encode)


(_DumpJson, _DumpJsonIndent) = _GetJsonDumpers()


def DumpJson(data, indent=True):
  """Serialize a given object.

  @param data: the data to serialize
  @param indent: whether to indent output (depends on simplejson version)

  @return: the string representation of data

  """
  if indent:
    fn = _DumpJsonIndent
  else:
    fn = _DumpJson

  txt = _RE_EOLSP.sub("", fn(data))
  if not txt.endswith("\n"):
    txt += "\n"

  return txt


def LoadJson(txt):
  """Unserialize data from a string.

  @param txt: the json-encoded form

  @return: the original data

  """
  return json.loads(txt)


def DumpSignedJson(data, key, salt=None, key_selector=None):
  """Serialize a given object and authenticate it.

  @param data: the data to serialize
  @param key: shared hmac key
  @param key_selector: name/id that identifies the key (in case there are
    multiple keys in use, e.g. in a multi-cluster environment)
  @return: the string representation of data signed by the hmac key

  """
  txt = DumpJson(data, indent=False)
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

  return DumpJson(signed_dict, indent=False)


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


Dump = DumpJson
Load = LoadJson
DumpSigned = DumpSignedJson
LoadSigned = LoadSignedJson
