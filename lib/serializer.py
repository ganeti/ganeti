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

import simplejson
import re
import hmac

from ganeti import errors

try:
  from hashlib import sha1
except ImportError:
  import sha as sha1

# Check whether the simplejson module supports indentation
_JSON_INDENT = 2
try:
  simplejson.dumps(1, indent=_JSON_INDENT)
except TypeError:
  _JSON_INDENT = None

_RE_EOLSP = re.compile('[ \t]+$', re.MULTILINE)


def DumpJson(data, indent=True):
  """Serialize a given object.

  @param data: the data to serialize
  @param indent: whether to indent output (depends on simplejson version)

  @return: the string representation of data

  """
  if not indent or _JSON_INDENT is None:
    txt = simplejson.dumps(data)
  else:
    txt = simplejson.dumps(data, indent=_JSON_INDENT)

  txt = _RE_EOLSP.sub("", txt)
  if not txt.endswith('\n'):
    txt += '\n'
  return txt


def LoadJson(txt):
  """Unserialize data from a string.

  @param txt: the json-encoded form

  @return: the original data

  """
  return simplejson.loads(txt)


def DumpSignedJson(data, key, salt=None):
  """Serialize a given object and authenticate it.

  @param data: the data to serialize
  @param key: shared hmac key
  @return: the string representation of data signed by the hmac key

  """
  txt = DumpJson(data, indent=False)
  if salt is None:
    salt = ''
  signed_dict = {
    'msg': txt,
    'salt': salt,
    'hmac': hmac.new(key, salt + txt, sha1).hexdigest(),
  }
  return DumpJson(signed_dict)


def LoadSignedJson(txt, key, salt_verifier=None):
  """Verify that a given message was signed with the given key, and load it.

  @param txt: json-encoded hmac-signed message
  @param key: shared hmac key
  @param salt_verifier: function taking a salt as input and returning boolean
  @rtype: tuple of original data, string
  @return: (original data, salt)
  @raises errors.SignatureError: if the message signature doesn't verify

  """
  signed_dict = LoadJson(txt)
  if not isinstance(signed_dict, dict):
    raise errors.SignatureError('Invalid external message')
  try:
    msg = signed_dict['msg']
    salt = signed_dict['salt']
    hmac_sign = signed_dict['hmac']
  except KeyError:
    raise errors.SignatureError('Invalid external message')

  if salt and not salt_verifier:
    raise errors.SignatureError('Salted message is not verified')
  elif salt_verifier is not None:
    if not salt_verifier(salt):
      raise errors.SignatureError('Invalid salt')

  if hmac.new(key, salt + msg, sha1).hexdigest() != hmac_sign:
    raise errors.SignatureError('Invalid Signature')
  return LoadJson(msg)


def SaltEqualTo(expected):
  """Helper salt verifier function that checks for equality.

  @type expected: string
  @param expected: expected salt
  @rtype: function
  @return: salt verifier that returns True if the target salt is "x"

  """
  return lambda salt: salt == expected


def SaltIn(expected):
  """Helper salt verifier function that checks for equality.

  @type expected: collection
  @param expected: collection of possible valid salts
  @rtype: function
  @return: salt verifier that returns True if the salt is in the collection

  """
  return lambda salt: salt in expected


def SaltInRange(min, max):
  """Helper salt verifier function that checks for equality.

  @type min: integer
  @param min: minimum salt value
  @type max: integer
  @param max: maximum salt value
  @rtype: function
  @return: salt verifier that returns True if the salt is in the min,max range

  """
  def _CheckSaltInRange(salt):
    try:
      i_salt = int(salt)
    except (TypeError, ValueError), err:
      return False

    return i_salt > min and i_salt < max

  return _CheckSaltInRange


Dump = DumpJson
Load = LoadJson
DumpSigned = DumpSignedJson
LoadSigned = LoadSignedJson
