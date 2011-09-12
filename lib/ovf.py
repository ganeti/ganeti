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

# pylint: disable=F0401, E1101

# F0401 because ElementTree is not default for python 2.4
# E1101 makes no sense - pylint assumes that ElementTree object is a tuple


import logging
import os.path
import re
import shutil
import tarfile
import tempfile
import xml.parsers.expat
try:
  import xml.etree.ElementTree as ET
except ImportError:
  import elementtree.ElementTree as ET

from ganeti import constants
from ganeti import errors
from ganeti import utils


# Schemas used in OVF format
GANETI_SCHEMA = "http://ganeti"
OVF_SCHEMA = "http://schemas.dmtf.org/ovf/envelope/1"
RASD_SCHEMA = ("http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/"
               "CIM_ResourceAllocationSettingData")

# File extensions in OVF package
OVA_EXT = ".ova"
OVF_EXT = ".ovf"
MF_EXT = ".mf"
CERT_EXT = ".cert"
FILE_EXTENSIONS = [
  OVF_EXT,
  MF_EXT,
  CERT_EXT,
]


class OVFReader(object):
  """Reader class for OVF files.

  @type files_list: list
  @ivar files_list: list of files in the OVF package
  @type tree: ET.ElementTree
  @ivar tree: XML tree of the .ovf file
  @type schema_name: string
  @ivar schema_name: name of the .ovf file
  @type input_dir: string
  @ivar input_dir: directory in which the .ovf file resides

  """
  def __init__(self, input_path):
    """Initialiaze the reader - load the .ovf file to XML parser.

    It is assumed that names of manifesto (.mf), certificate (.cert) and ovf
    files are the same. In order to account any other files as part of the ovf
    package, they have to be explicitly mentioned in the Resources section
    of the .ovf file.

    @type input_path: string
    @param input_path: absolute path to the .ovf file

    @raise errors.OpPrereqError: when .ovf file is not a proper XML file or some
      of the files mentioned in Resources section do not exist

    """
    self.tree = ET.ElementTree()
    try:
      self.tree.parse(input_path)
    except xml.parsers.expat.ExpatError, err:
      raise errors.OpPrereqError("Error while reading %s file: %s" %
                                 (OVF_EXT, err))

    # Create a list of all files in the OVF package
    (input_dir, input_file) = os.path.split(input_path)
    (input_name, _) = os.path.splitext(input_file)
    files_directory = utils.ListVisibleFiles(input_dir)
    files_list = []
    for file_name in files_directory:
      (name, extension) = os.path.splitext(file_name)
      if extension in FILE_EXTENSIONS and name == input_name:
        files_list.append(file_name)
    files_list += self._GetAttributes("{%s}References/{%s}File" %
                                      (OVF_SCHEMA, OVF_SCHEMA),
                                      "{%s}href" % OVF_SCHEMA)
    for file_name in files_list:
      file_path = utils.PathJoin(input_dir, file_name)
      if not os.path.exists(file_path):
        raise errors.OpPrereqError("File does not exist: %s" % file_path)
    logging.info("Files in the OVF package: %s", " ".join(files_list))
    self.files_list = files_list
    self.input_dir = input_dir
    self.schema_name = input_name

  def _GetAttributes(self, path, attribute):
    """Get specified attribute from all nodes accessible using given path.

    Function follows the path from root node to the desired tags using path,
    then reads the apropriate attribute values.

    @type path: string
    @param path: path of nodes to visit
    @type attribute: string
    @param attribute: attribute for which we gather the information
    @rtype: list
    @return: for each accessible tag with the attribute value set, value of the
      attribute

    """
    current_list = self.tree.findall(path)
    results = [x.get(attribute) for x in current_list]
    return filter(None, results)

  def VerifyManifest(self):
    """Verifies manifest for the OVF package, if one is given.

    @raise errors.OpPrereqError: if SHA1 checksums do not match

    """
    if "%s%s" % (self.schema_name, MF_EXT) in self.files_list:
      logging.warning("Verifying SHA1 checksums, this may take a while")
      manifest_filename = "%s%s" % (self.schema_name, MF_EXT)
      manifest_path = utils.PathJoin(self.input_dir, manifest_filename)
      manifest_content = utils.ReadFile(manifest_path).splitlines()
      manifest_files = {}
      regexp = r"SHA1\((\S+)\)= (\S+)"
      for line in manifest_content:
        match = re.match(regexp, line)
        if match:
          file_name = match.group(1)
          sha1_sum = match.group(2)
          manifest_files[file_name] = sha1_sum
      files_with_paths = [utils.PathJoin(self.input_dir, file_name)
        for file_name in self.files_list]
      sha1_sums = utils.FingerprintFiles(files_with_paths)
      for file_name, value in manifest_files.iteritems():
        if sha1_sums.get(utils.PathJoin(self.input_dir, file_name)) != value:
          raise errors.OpPrereqError("SHA1 checksum of %s does not match the"
                                     " value in manifest file" % file_name)
      logging.info("SHA1 checksums verified")


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
  """Converter from OVF to Ganeti config file.

  @type input_dir: string
  @ivar input_dir: directory in which the .ovf file resides
  @type output_dir: string
  @ivar output_dir: directory to which the results of conversion shall be
    written
  @type input_path: string
  @ivar input_path: complete path to the .ovf file
  @type ovf_reader: L{OVFReader}
  @ivar ovf_reader: OVF reader instance collects data from .ovf file

  """
  def _ReadInputData(self, input_path):
    """Reads the data on which the conversion will take place.

    @type input_path: string
    @param input_path: absolute path to the .ovf or .ova input file

    @raise errors.OpPrereqError: if input file is neither .ovf nor .ova

    """
    (input_dir, input_file) = os.path.split(input_path)
    (_, input_extension) = os.path.splitext(input_file)

    if input_extension == OVF_EXT:
      logging.info("%s file extension found, no unpacking necessary", OVF_EXT)
      self.input_dir = input_dir
      self.input_path = input_path
      self.temp_dir = None
    elif input_extension == OVA_EXT:
      logging.info("%s file extension found, proceeding to unpacking", OVA_EXT)
      self._UnpackOVA(input_path)
    else:
      raise errors.OpPrereqError("Unknown file extension; expected %s or %s"
                                 " file" % (OVA_EXT, OVF_EXT))
    assert ((input_extension == OVA_EXT and self.temp_dir) or
            (input_extension == OVF_EXT and not self.temp_dir))
    assert self.input_dir in self.input_path

    if self.options.output_dir:
      self.output_dir = os.path.abspath(self.options.output_dir)
      if (os.path.commonprefix([constants.EXPORT_DIR, self.output_dir]) !=
          constants.EXPORT_DIR):
        logging.warning("Export path is not under %s directory, import to"
                        " Ganeti using gnt-backup may fail",
                        constants.EXPORT_DIR)
    else:
      self.output_dir = constants.EXPORT_DIR

    self.ovf_reader = OVFReader(self.input_path)
    self.ovf_reader.VerifyManifest()

  def _UnpackOVA(self, input_path):
    """Unpacks the .ova package into temporary directory.

    @type input_path: string
    @param input_path: path to the .ova package file

    @raise errors.OpPrereqError: if file is not a proper tarball, one of the
        files in the archive seem malicious (e.g. path starts with '../') or
        .ova package does not contain .ovf file

    """
    input_name = None
    if not tarfile.is_tarfile(input_path):
      raise errors.OpPrereqError("The provided %s file is not a proper tar"
                                 " archive", OVA_EXT)
    ova_content = tarfile.open(input_path)
    temp_dir = tempfile.mkdtemp()
    self.temp_dir = temp_dir
    for file_name in ova_content.getnames():
      file_normname = os.path.normpath(file_name)
      try:
        utils.PathJoin(temp_dir, file_normname)
      except ValueError, err:
        raise errors.OpPrereqError("File %s inside %s package is not safe" %
                                   (file_name, OVA_EXT))
      if file_name.endswith(OVF_EXT):
        input_name = file_name
    if not input_name:
      raise errors.OpPrereqError("No %s file in %s package found" %
                                 (OVF_EXT, OVA_EXT))
    logging.warning("Unpacking the %s archive, this may take a while",
      input_path)
    self.input_dir = temp_dir
    self.input_path = utils.PathJoin(self.temp_dir, input_name)
    try:
      try:
        extract = ova_content.extractall
      except AttributeError:
        # This is a prehistorical case of using python < 2.5
        for member in ova_content.getmembers():
          ova_content.extract(member, path=self.temp_dir)
      else:
        extract(self.temp_dir)
    except tarfile.TarError, err:
      raise errors.OpPrereqError("Error while extracting %s archive: %s" %
                                 (OVA_EXT, err))
    logging.info("OVA package extracted to %s directory", self.temp_dir)

  def Parse(self):
    pass

  def Save(self):
    """Saves all the gathered information in a constant.EXPORT_CONF_FILE file.

    @raise errors.OpPrereqError: when saving to config file failed

    """
    logging.info("Conversion was succesfull, saving %s in %s directory",
                 constants.EXPORT_CONF_FILE, self.output_dir)
    results = {
      constants.INISECT_INS: {},
      constants.INISECT_BEP: {},
      constants.INISECT_EXP: {},
      constants.INISECT_OSP: {},
      constants.INISECT_HYP: {},
    }

    results[constants.INISECT_INS].update(self.results_disk)
    results[constants.INISECT_INS]["name"] = self.results_name
    if self.results_template:
      results[constants.INISECT_INS]["disk_template"] = self.results_template

    output_file_name = utils.PathJoin(self.output_dir,
      constants.EXPORT_CONF_FILE)

    output = []
    for section, options in results.iteritems():
      output.append("[%s]" % section)
      for name, value in options.iteritems():
        output.append("%s = %s" % (name, value))
      output.append("")
    output_contents = "\n".join(output)

    try:
      utils.WriteFile(output_file_name, data=output_contents)
    except errors.ProgrammerError, err:
      raise errors.OpPrereqError("Saving the config file failed: %s" % err)

    self.Cleanup()


class OVFExporter(Converter):
  def _ReadInputData(self, input_path):
    pass

  def Parse(self):
    pass

  def Save(self):
    pass
