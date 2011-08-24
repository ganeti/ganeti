#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Converter tools between ovf and ganeti config file

"""

import os.path
import shutil

from ganeti import errors
from ganeti import utils


class Converter(object):
  """Converter class for OVF packages.

  Converter is a class above both ImporterOVF and ExporterOVF. It's purpose is
  to provide a common interface for the two.

  @type options: optparse.Values
  @ivar options: options parsed from the command line
  @type output_dir: string
  @ivar output_dir: directory to which the results of conversion shall be
    written
  @type temp_file_manager: L{utils.TemporaryFileManager}
  @ivar temp_file_manager: container for temporary files created during
    conversion
  @type temp_dir: string
  @ivar temp_dir: temporary directory created then we deal with OVA

  """
  def __init__(self, input_path, options):
    """Initialize the converter.

    @type input_path: string
    @param input_path: path to the Converter input file
    @type options: optparse.Values
    @param options: command line options

    @raise errors.OpPrereqError: if file does not exist

    """
    input_path = os.path.abspath(input_path)
    if not os.path.isfile(input_path):
      raise errors.OpPrereqError("File does not exist: %s" % input_path)
    self.options = options
    self.temp_file_manager = utils.TemporaryFileManager()
    self.temp_dir = None
    self.output_dir = None
    self._ReadInputData(input_path)

  def _ReadInputData(self, input_path):
    """Reads the data on which the conversion will take place.

    @type input_path: string
    @param input_path: absolute path to the Converter input file

    """
    raise NotImplementedError()

  def Parse(self):
    """Parses the data and creates a structure containing all required info.

    """
    raise NotImplementedError()

  def Save(self):
    """Saves the gathered configuration in an apropriate format.

    """
    raise NotImplementedError()

  def Cleanup(self):
    """Cleans the temporary directory, if one was created.

    """
    self.temp_file_manager.Cleanup()
    if self.temp_dir:
      shutil.rmtree(self.temp_dir)
      self.temp_dir = None


class OVFImporter(Converter):
  def _ReadInputData(self, input_path):
    pass

  def Parse(self):
    pass

  def Save(self):
    pass


class OVFExporter(Converter):
  def _ReadInputData(self, input_path):
    pass

  def Parse(self):
    pass

  def Save(self):
    pass
