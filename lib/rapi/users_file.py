#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2012, 2013, 2015 Google Inc.
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

"""RAPI users config file parser.

"""

import errno
import logging

from ganeti import utils


class PasswordFileUser(object):
  """Data structure for users from password file.

  """
  def __init__(self, name, password, options):
    self.name = name
    self.password = password
    self.options = options


def ParsePasswordFile(contents):
  """Parses the contents of a password file.

  Lines in the password file are of the following format::

      <username> <password> [options]

  Fields are separated by whitespace. Username and password are mandatory,
  options are optional and separated by comma (','). Empty lines and comments
  ('#') are ignored.

  @type contents: str
  @param contents: Contents of password file
  @rtype: dict
  @return: Dictionary containing L{PasswordFileUser} instances

  """
  users = {}

  for line in utils.FilterEmptyLinesAndComments(contents):
    parts = line.split(None, 2)
    if len(parts) < 2:
      # Invalid line
      # TODO: Return line number from FilterEmptyLinesAndComments
      logging.warning("Ignoring non-comment line with less than two fields")
      continue

    name = parts[0]
    password = parts[1]

    # Extract options
    options = []
    if len(parts) >= 3:
      for part in parts[2].split(","):
        options.append(part.strip())
    else:
      logging.warning("Ignoring values for user '%s': %s", name, parts[3:])

    users[name] = PasswordFileUser(name, password, options)

  return users


class RapiUsers(object):
  def __init__(self):
    """Initializes this class.

    """
    self._users = None

  def Get(self, username):
    """Checks whether a user exists.

    """
    if self._users:
      return self._users.get(username, None)
    else:
      return None

  def Load(self, filename):
    """Loads a file containing users and passwords.

    @type filename: string
    @param filename: Path to file

    """
    logging.info("Reading users file at %s", filename)
    try:
      try:
        contents = utils.ReadFile(filename)
      except EnvironmentError, err:
        self._users = None
        if err.errno == errno.ENOENT:
          logging.warning("No users file at %s", filename)
        else:
          logging.warning("Error while reading %s: %s", filename, err)
        return False

      users = ParsePasswordFile(contents)

    except Exception, err: # pylint: disable=W0703
      # We don't care about the type of exception
      logging.error("Error while parsing %s: %s", filename, err)
      return False

    self._users = users

    return True
