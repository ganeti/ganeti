#
#

# Copyright (C) 2007, 2008, 2014 Google Inc.
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
import json
from copy import deepcopy
from dataclasses import is_dataclass, asdict

from ganeti import errors
from ganeti import utils
from ganeti import constants

_RE_EOLSP = re.compile("[ \t]+$", re.MULTILINE)


def DumpJson(data, private_encoder=None):
  """Serialize a given object.

  @param data: the data to serialize
  @return: the bytes representation of data
  @param private_encoder: specify L{serializer.EncodeWithPrivateFields} if you
                          require the produced JSON to also contain private
                          parameters. Otherwise, they will encode to null.

  """

  if private_encoder is None:
    # Do not leak private fields by default.
    private_encoder = EncodeWithoutPrivateFields
  encoded = json.dumps(data, cls=private_encoder)

  txt = _RE_EOLSP.sub("", encoded)
  if not txt.endswith("\n"):
    txt += "\n"

  return txt.encode("utf-8")


def LoadJson(data):
  """Unserialize data from bytes.

  @param data: the json-encoded form
  @type data: str or bytes
  @return: the original data
  @raise JSONDecodeError: if L{txt} is not a valid JSON document

  """

  # convert data to string if data is a byte array
  if isinstance(data, bytes):
    data = data.decode('utf-8')

  values = json.loads(data)

  # Hunt and seek for Private fields and wrap them.
  WrapPrivateValues(values)

  return values


def WrapPrivateValues(json_data):
  """Crawl a JSON decoded structure for private values and wrap them.

  @param json_data: the json-decoded value to protect.

  """
  # This function used to be recursive. I use this list to avoid actual
  # recursion, however, since this is a very high-traffic area.
  todo = [json_data]

  while todo:
    data = todo.pop()

    if isinstance(data, list): # Array
      for item in data:
        todo.append(item)
    elif isinstance(data, dict): # Object

      # This is kind of a kludge, but the only place where we know what should
      # be protected is in ganeti.opcodes, and not in a way that is helpful to
      # us, especially in such a high traffic method; on the other hand, the
      # Haskell `py_compat_fields` test should complain whenever this check
      # does not protect fields properly.
      for field in data:
        value = data[field]
        if field in constants.PRIVATE_PARAMETERS_BLACKLIST:
          if not field.endswith("_cluster"):
            data[field] = PrivateDict(value)
          elif data[field] is not None:
            for os in data[field]:
              value[os] = PrivateDict(value[os])
        else:
          todo.append(value)
    else: # Values
      pass


def DumpSignedJson(data, key, salt=None, key_selector=None,
                   private_encoder=None):
  """Serialize a given object and authenticate it.

  @param data: the data to serialize
  @param key: shared hmac key
  @param key_selector: name/id that identifies the key (in case there are
    multiple keys in use, e.g. in a multi-cluster environment)
  @param private_encoder: see L{DumpJson}
  @return: the string representation of data signed by the hmac key

  """
  txt = DumpJson(data, private_encoder=private_encoder)
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

  WrapPrivateValues(signed_dict)

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
  except Exception as err:
    raise errors.ParseError("Can't parse input data: %s" % err)

  if not verify_fn(data):
    raise errors.ParseError("Data does not match expected format: %s" %
                            verify_fn)

  return data


Dump = DumpJson
Load = LoadJson
DumpSigned = DumpSignedJson
LoadSigned = LoadSignedJson


class Private(object):
  """Wrap a value so it is hard to leak it accidentally.

  >>> x = Private("foo")
  >>> print("Value: %s" % x)
  Value: <redacted>
  >>> print("Value: {0}".format(x))
  Value: <redacted>
  >>> x.upper() == "FOO"
  True

  """
  def __init__(self, item, descr="redacted"):
    if isinstance(item, Private):
      raise ValueError("Attempted to nest Private values.")
    self._item = item
    self._descr = descr

  def Get(self):
    "Return the wrapped value."
    return self._item

  def __str__(self):
    return "<%s>" % (self._descr, )

  def __repr__(self):
    return "Private(?, descr=%r)" % (self._descr, )

  # pylint: disable=W0212
  # If it doesn't access _item directly, the call will go through __getattr__
  # because this class defines __slots__ and "item" is not in it.
  # OTOH, if we do add it there, we'd risk shadowing an "item" attribute.
  def __eq__(self, other):
    if isinstance(other, Private):
      return self._item == other._item
    else:
      return self._item == other

  def __hash__(self):
    return hash(self._item)

  def __format__(self, *_1, **_2):
    return self.__str__()

  def __copy__(self):
    return Private(self._item, self._descr)

  def __deepcopy__(self, memo):
    new_item = deepcopy(self._item, memo)
    return Private(new_item, self._descr)

  def __getattr__(self, attr):
    return Private(getattr(self._item, attr),
                   descr="%s.%s" % (self._descr, attr))

  def __call__(self, *args, **kwargs):
    return Private(self._item(*args, **kwargs),
                   descr="%s()" % (self._descr, ))

  # pylint: disable=R0201
  # While this could get away with being a function, it needs to be a method.
  # Required by the copy.deepcopy function used by FillDict.
  def __getnewargs__(self):
    return tuple()

  def __bool__(self):
    return bool(self._item)

  # Get in the way of Pickle by implementing __slots__ but not __getstate__
  # ...and get a performance boost, too.
  __slots__ = ["_item", "_descr"]


class PrivateDict(dict):
  """A dictionary that turns its values to private fields.

  >>> PrivateDict()
  {}
  >>> supersekkrit = PrivateDict({"password": "foobar"})
  >>> print(supersekkrit["password"])
  <password>
  >>> supersekkrit["password"].Get()
  'foobar'
  >>> supersekkrit.GetPrivate("password")
  'foobar'
  >>> supersekkrit["user"] = "eggspam"
  >>> supersekkrit.Unprivate()
  {'password': 'foobar', 'user': 'eggspam'}

  """
  def __init__(self, data=None):
    dict.__init__(self)
    self.update(data)

  def __setitem__(self, item, value):
    if not isinstance(value, Private):
      if not isinstance(item, dict):
        value = Private(value, descr=item)
      else:
        value = PrivateDict(value)
    dict.__setitem__(self, item, value)

  # The actual conversion to Private containers is done by __setitem__

  # copied straight from cpython/Lib/UserDict.py
  # Copyright (c) 2001-2014 Python Software Foundation; All Rights Reserved
  def update(self, other=None, **kwargs):
    # Make progressively weaker assumptions about "other"
    if other is None:
      pass
    elif hasattr(other, 'iteritems'):  # iteritems saves memory and lookups
      for k, v in other.items():
        self[k] = v
    elif hasattr(other, 'keys'):
      for k in other.keys():
        self[k] = other[k]
    else:
      for k, v in other:
        self[k] = v
    if kwargs:
      self.update(kwargs)

  def GetPrivate(self, *args):
    """Like dict.get, but extracting the value in the process.

    Arguments are semantically equivalent to ``dict.get``

    >>> PrivateDict({"foo": "bar"}).GetPrivate("foo")
    'bar'
    >>> PrivateDict({"foo": "bar"}).GetPrivate("baz", "spam")
    'spam'

    """
    if len(args) == 1:
      key, = args
      return self[key].Get()
    elif len(args) == 2:
      key, default = args
      if key not in self:
        return default
      else:
        return self[key].Get()
    else:
      raise TypeError("GetPrivate() takes 2 arguments (%d given)" % len(args))

  def Unprivate(self):
    """Turn this dict of Private() values to a dict of values.

    >>> PrivateDict({"foo": "bar"}).Unprivate()
    {'foo': 'bar'}

    @rtype: dict

    """
    returndict = {}
    for key in self:
      returndict[key] = self[key].Get()
    return returndict


# to support dataclass json encoding
class DataClassEncoder(json.JSONEncoder):
  def default(self, o):
    if is_dataclass(o):
      return asdict(o)
    return super().default(o)

# This class extends the default JsonEncoder to serialize byte arrays.
# Unlike simplejson, python build-in json cannot encode byte arrays.
class ByteEncoder(DataClassEncoder):
  def default(self, o):
    if isinstance(o, bytes):
      return str(o, encoding="ascii")
    return super().default(o)


class EncodeWithoutPrivateFields(ByteEncoder):
  def default(self, o):
    if isinstance(o, Private):
      return None
    return super().default(o)


class EncodeWithPrivateFields(ByteEncoder):
  def default(self, o):
    if isinstance(o, Private):
      return o.Get()
    return super().default(o)
