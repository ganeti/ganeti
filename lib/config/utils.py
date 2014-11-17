#
#

# Copyright (C) 2014 Google Inc.
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


"""Utilities used by the config module."""


import logging


def ConfigSync(shared=0):
  """Configuration synchronization decorator.

  """
  def wrap(fn):
    def sync_function(*args, **kwargs):
      with args[0].GetConfigManager(shared):
        return fn(*args, **kwargs)
    return sync_function
  return wrap


class ConfigManager(object):
  """Locks the configuration and exposes it to be read or modified.

  """
  def __init__(self, config_writer, shared=False, forcelock=False):
    assert hasattr(config_writer, '_ConfigData'), \
           "invalid argument: Not a ConfigWriter"
    self._config_writer = config_writer
    self._shared = shared
    self._forcelock = forcelock

  def __enter__(self):
    try:
      self._config_writer._OpenConfig(# pylint: disable=W0212
                                      self._shared,
                                      force=self._forcelock)
    except Exception:
      logging.debug("Opening configuration failed")
      try:
        self._config_writer._CloseConfig(False) # pylint: disable=W0212
      except Exception: # pylint: disable=W0703
        logging.debug("Closing configuration failed as well")
      raise

  def __exit__(self, exc_type, exc_value, traceback):
    # save the configuration, if this was a write opreration that succeeded
    if exc_type is not None:
      logging.debug("Configuration operation failed,"
                    " the changes will not be saved")
    # pylint: disable=W0212
    self._config_writer._CloseConfig(not self._shared and exc_type is None)
    return False
