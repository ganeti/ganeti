#
#

# Copyright (C) 2022 the Ganeti project
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

import re
import logging

from ganeti import constants
from ganeti import errors

_BLOCKDEV_URI_REGEX_GLUSTER = (
  r"^gluster:\/\/(?P<host>[a-z0-9-.]+):"
  r"(?P<port>\d+)/(?P<volume>[^/]+)/(?P<path>.+)$"
)
_BLOCKDEV_URI_REGEX_RBD = r"^rbd:(?P<pool>\w+)/(?P<image>[a-z0-9-\.]+)$"

def TranslateBoolToOnOff(value):
  """Converts a given boolean to 'on'|'off' for use in QEMUs cmdline

  @param value: bool
  @return: 'on' or 'off'
  @rtype: string
  """
  if value:
    return 'on'
  else:
    return 'off'


def ParseStorageUriToBlockdevParam(uri):
  """Parse a storage uri into qemu blockdev params

  @type uri: string
  @param uri: storage-describing URI
  @return: dict
  """
  match = re.match(_BLOCKDEV_URI_REGEX_GLUSTER, uri)
  if match is not None:
    return {
        "driver": "gluster",
        "server": [
          {
            'type': 'inet',
            'host': match.group("host"),
            'port': match.group("port"),
          }
        ],
        "volume": match.group("volume"),
        "path": match.group("path")
      }
  match = re.match(_BLOCKDEV_URI_REGEX_RBD, uri)
  if match is not None:
    return {
        "driver": "rbd",
        "pool": match.group("pool"),
        "image": match.group("image")
      }
  raise errors.HypervisorError("Unsupported storage URI scheme: %s" % (uri))


def FlattenDict(d, parent_key='', sep='.'):
  """Helper method to convert nested dicts to flat string representation
  """
  items = []
  for k, v in d.items():
    if isinstance(v, bool):
      v = TranslateBoolToOnOff(v)
    new_key = f"{parent_key}{sep}{k}" if parent_key else k
    if isinstance(v, dict):
      items.extend(FlattenDict(v, new_key, sep=sep).items())
    else:
      items.append((new_key, v))
  return dict(items)


def DictToQemuStringNotation(data):
  """Convert dictionary to flat string representation

  This function is used to transform a blockdev QEMU parameter set for use as
  command line parameters (to QEMUs -blockdev parameter)

  @type data: dict
  @param data: data to convert
  @return: string
  """
  logging.debug("Converting the following data structure "
                "to flat string: %s" % (data))
  flat_str = ','.join(["%s=%s" % (key, value) for key, value in
                       FlattenDict(data).items()])
  logging.debug("Result: %s" % flat_str)
  return flat_str


def GetCacheSettings(cache_type, dev_type):
  """Return cache settings suitable for use with -blockdev

  @param cache_type: string (one of L{constants.HT_VALID_CACHE_TYPES})
  @param dev_type: string (one of L{constants.DISK_TEMPLATES}
  @return: (writeback, direct, no_flush)
  @rtype: tuple
  """
  if dev_type in constants.DTS_EXT_MIRROR and dev_type != constants.DT_RBD:
    logging.warning("KVM: overriding disk_cache setting '%s' with 'none'"
                    " to prevent shared storage corruption on migration",
                    cache_type)
    cache_type = constants.HT_CACHE_NONE

  if cache_type == constants.HT_CACHE_NONE:
    return True, True, False
  elif cache_type in [constants.HT_CACHE_WBACK, constants.HT_CACHE_DEFAULT]:
    return True, False, False
  elif cache_type == constants.HT_CACHE_WTHROUGH:
    return False, False, False
  else:
    raise errors.HypervisorError("Invalid KVM cache setting '%s'" % cache_type)