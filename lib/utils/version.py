#
#

# Copyright (C) 2013 Google Inc.
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


"""Version utilities."""

import re

from ganeti import constants

_FULL_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_SHORT_VERSION_RE = re.compile(r"(\d+)\.(\d+)")

# The first Ganeti version that supports automatic upgrades
FIRST_UPGRADE_VERSION = (2, 10, 0)

CURRENT_VERSION = (constants.VERSION_MAJOR, constants.VERSION_MINOR,
                   constants.VERSION_REVISION)

# Format for CONFIG_VERSION:
#   01 03 0123 = 01030123
#   ^^ ^^ ^^^^
#   |  |  + Configuration version/revision
#   |  + Minor version
#   + Major version
#
# It is stored as an integer. Make sure not to write an octal number.

# BuildVersion and SplitVersion must be in here because we can't import other
# modules. The cfgupgrade tool must be able to read and write version numbers
# and thus requires these functions. To avoid code duplication, they're kept in
# here.


def BuildVersion(major, minor, revision):
  """Calculates int version number from major, minor and revision numbers.

  Returns: int representing version number

  """
  assert isinstance(major, int)
  assert isinstance(minor, int)
  assert isinstance(revision, int)
  return (1000000 * major +
            10000 * minor +
                1 * revision)


def SplitVersion(version):
  """Splits version number stored in an int.

  Returns: tuple; (major, minor, revision)

  """
  assert isinstance(version, int)

  (major, remainder) = divmod(version, 1000000)
  (minor, revision) = divmod(remainder, 10000)

  return (major, minor, revision)


def ParseVersion(versionstring):
  """Parses a version string.

  @param versionstring: the version string to parse
  @type versionstring: string
  @rtype: tuple or None
  @return: (major, minor, revision) if parsable, None otherwise.

  """
  m = _FULL_VERSION_RE.match(versionstring)
  if m is not None:
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

  m = _SHORT_VERSION_RE.match(versionstring)
  if m is not None:
    return (int(m.group(1)), int(m.group(2)), 0)

  return None


def UpgradeRange(target, current=CURRENT_VERSION):
  """Verify whether a version is within the range of automatic upgrades.

  @param target: The version to upgrade to as (major, minor, revision)
  @type target: tuple
  @param current: The version to upgrade from as (major, minor, revision)
  @type current: tuple
  @rtype: string or None
  @return: None, if within the range, and a human-readable error message
      otherwise

  """
  if target < FIRST_UPGRADE_VERSION or current < FIRST_UPGRADE_VERSION:
    return "automatic upgrades only supported from 2.10 onwards"

  if target[0] != current[0]:
    return "different major versions"

  if target[1] < current[1] - 1:
    return "can only downgrade one minor version at a time"

  return None


def ShouldCfgdowngrade(version, current=CURRENT_VERSION):
  """Decide whether cfgupgrade --downgrade should be called.

  Given the current version and the version to change to, decide
  if in the transition process cfgupgrade --downgrade should
  be called

  @param version: The version to upgrade to as (major, minor, revision)
  @type version: tuple
  @param current: The version to upgrade from as (major, minor, revision)
  @type current: tuple
  @rtype: bool
  @return: True, if cfgupgrade --downgrade should be called.

  """
  return version[0] == current[0] and version[1] == current[1] - 1


def IsCorrectConfigVersion(targetversion, configversion):
  """Decide whether configuration version is compatible with the target.

  @param targetversion: The version to upgrade to as (major, minor, revision)
  @type targetversion: tuple
  @param configversion: The version of the current configuration
  @type configversion: tuple
  @rtype: bool
  @return: True, if the configversion fits with the target version.

  """
  return (configversion[0] == targetversion[0] and
          configversion[1] == targetversion[1])
