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


import ConfigParser
import errno
import logging
import os
import os.path
import re
import shutil
import tarfile
import tempfile
import xml.dom.minidom
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
VSSD_SCHEMA = ("http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/"
               "CIM_VirtualSystemSettingData")
XML_SCHEMA = "http://www.w3.org/2001/XMLSchema-instance"

# File extensions in OVF package
OVA_EXT = ".ova"
OVF_EXT = ".ovf"
MF_EXT = ".mf"
CERT_EXT = ".cert"
COMPRESSION_EXT = ".gz"
FILE_EXTENSIONS = [
  OVF_EXT,
  MF_EXT,
  CERT_EXT,
]

COMPRESSION_TYPE = "gzip"
COMPRESS = "compression"
DECOMPRESS = "decompression"
ALLOWED_ACTIONS = [COMPRESS, DECOMPRESS]

# ResourceType values
RASD_TYPE = {
  "vcpus": "3",
  "memory": "4",
}

# AllocationUnits values and conversion
ALLOCATION_UNITS = {
  'b': ["bytes", "b"],
  'kb': ["kilobytes", "kb", "byte * 2^10", "kibibytes", "kib"],
  'mb': ["megabytes", "mb", "byte * 2^20", "mebibytes", "mib"],
  'gb': ["gigabytes", "gb", "byte * 2^30", "gibibytes", "gib"],
}
CONVERT_UNITS_TO_MB = {
  'b': lambda x: x / (1024 * 1024),
  'kb': lambda x: x / 1024,
  'mb': lambda x: x,
  'gb': lambda x: x * 1024,
}

# Names of the config fields
NAME = "name"
OS = "os"
HYPERV = "hypervisor"
VCPUS = "vcpus"
MEMORY = "memory"
AUTO_BALANCE = "auto_balance"
DISK_TEMPLATE = "disk_template"
TAGS = "tags"
VERSION = "version"


def LinkFile(old_path, prefix=None, suffix=None, directory=None):
  """Create link with a given prefix and suffix.

  This is a wrapper over os.link. It tries to create a hard link for given file,
  but instead of rising error when file exists, the function changes the name
  a little bit.

  @type old_path:string
  @param old_path: path to the file that is to be linked
  @type prefix: string
  @param prefix: prefix of filename for the link
  @type suffix: string
  @param suffix: suffix of the filename for the link
  @type directory: string
  @param directory: directory of the link

  @raise errors.OpPrereqError: when error on linking is different than
    "File exists"

  """
  assert(prefix is not None or suffix is not None)
  if directory is None:
    directory = os.getcwd()
  new_path = utils.PathJoin(directory, "%s%s" % (prefix, suffix))
  counter = 1
  while True:
    try:
      os.link(old_path, new_path)
      break
    except OSError, err:
      if err.errno == errno.EEXIST:
        new_path = utils.PathJoin(directory,
          "%s_%s%s" % (prefix, counter, suffix))
        counter += 1
      else:
        raise errors.OpPrereqError("Error moving the file %s to %s location:"
                                   " %s" % (old_path, new_path, err))
  return new_path


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

  def _GetElementMatchingAttr(self, path, match_attr):
    """Searches for element on a path that matches certain attribute value.

    Function follows the path from root node to the desired tags using path,
    then searches for the first one matching the attribute value.

    @type path: string
    @param path: path of nodes to visit
    @type match_attr: tuple
    @param match_attr: pair (attribute, value) for which we search
    @rtype: ET.ElementTree or None
    @return: first element matching match_attr or None if nothing matches

    """
    potential_elements = self.tree.findall(path)
    (attr, val) = match_attr
    for elem in potential_elements:
      if elem.get(attr) == val:
        return elem
    return None

  def _GetElementMatchingText(self, path, match_text):
    """Searches for element on a path that matches certain text value.

    Function follows the path from root node to the desired tags using path,
    then searches for the first one matching the text value.

    @type path: string
    @param path: path of nodes to visit
    @type match_text: tuple
    @param match_text: pair (node, text) for which we search
    @rtype: ET.ElementTree or None
    @return: first element matching match_text or None if nothing matches

    """
    potential_elements = self.tree.findall(path)
    (node, text) = match_text
    for elem in potential_elements:
      if elem.findtext(node) == text:
        return elem
    return None

  @staticmethod
  def _GetDictParameters(root, schema):
    """Reads text in all children and creates the dictionary from the contents.

    @type root: ET.ElementTree or None
    @param root: father of the nodes we want to collect data about
    @type schema: string
    @param schema: schema name to be removed from the tag
    @rtype: dict
    @return: dictionary containing tags and their text contents, tags have their
      schema fragment removed or empty dictionary, when root is None

    """
    if not root:
      return {}
    results = {}
    for element in list(root):
      pref_len = len("{%s}" % schema)
      assert(schema in element.tag)
      tag = element.tag[pref_len:]
      results[tag] = element.text
    return results

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

  def GetInstanceName(self):
    """Provides information about instance name.

    @rtype: string
    @return: instance name string

    """
    find_name = "{%s}VirtualSystem/{%s}Name" % (OVF_SCHEMA, OVF_SCHEMA)
    return self.tree.findtext(find_name)

  def GetDiskTemplate(self):
    """Returns disk template from .ovf file

    @rtype: string or None
    @return: name of the template
    """
    find_template = ("{%s}GanetiSection/{%s}DiskTemplate" %
                     (GANETI_SCHEMA, GANETI_SCHEMA))
    return self.tree.findtext(find_template)

  def GetHypervisorData(self):
    """Provides hypervisor information - hypervisor name and options.

    @rtype: dict
    @return: dictionary containing name of the used hypervisor and all the
      specified options

    """
    hypervisor_search = ("{%s}GanetiSection/{%s}Hypervisor" %
                         (GANETI_SCHEMA, GANETI_SCHEMA))
    hypervisor_data = self.tree.find(hypervisor_search)
    if not hypervisor_data:
      return {"hypervisor_name": constants.VALUE_AUTO}
    results = {
      "hypervisor_name": hypervisor_data.findtext("{%s}Name" % GANETI_SCHEMA,
                           default=constants.VALUE_AUTO),
    }
    parameters = hypervisor_data.find("{%s}Parameters" % GANETI_SCHEMA)
    results.update(self._GetDictParameters(parameters, GANETI_SCHEMA))
    return results

  def GetOSData(self):
    """ Provides operating system information - os name and options.

    @rtype: dict
    @return: dictionary containing name and options for the chosen OS

    """
    results = {}
    os_search = ("{%s}GanetiSection/{%s}OperatingSystem" %
                 (GANETI_SCHEMA, GANETI_SCHEMA))
    os_data = self.tree.find(os_search)
    if os_data:
      results["os_name"] = os_data.findtext("{%s}Name" % GANETI_SCHEMA)
      parameters = os_data.find("{%s}Parameters" % GANETI_SCHEMA)
      results.update(self._GetDictParameters(parameters, GANETI_SCHEMA))
    return results

  def GetBackendData(self):
    """ Provides backend information - vcpus, memory, auto balancing options.

    @rtype: dict
    @return: dictionary containing options for vcpus, memory and auto balance
      settings

    """
    results = {}

    find_vcpus = ("{%s}VirtualSystem/{%s}VirtualHardwareSection/{%s}Item" %
                   (OVF_SCHEMA, OVF_SCHEMA, OVF_SCHEMA))
    match_vcpus = ("{%s}ResourceType" % RASD_SCHEMA, RASD_TYPE["vcpus"])
    vcpus = self._GetElementMatchingText(find_vcpus, match_vcpus)
    if vcpus:
      vcpus_count = vcpus.findtext("{%s}VirtualQuantity" % RASD_SCHEMA,
        default=constants.VALUE_AUTO)
    else:
      vcpus_count = constants.VALUE_AUTO
    results["vcpus"] = str(vcpus_count)

    find_memory = find_vcpus
    match_memory = ("{%s}ResourceType" % RASD_SCHEMA, RASD_TYPE["memory"])
    memory = self._GetElementMatchingText(find_memory, match_memory)
    memory_raw = None
    if memory:
      alloc_units = memory.findtext("{%s}AllocationUnits" % RASD_SCHEMA)
      matching_units = [units for units, variants in
        ALLOCATION_UNITS.iteritems() if alloc_units.lower() in variants]
      if matching_units == []:
        raise errors.OpPrereqError("Unit %s for RAM memory unknown",
          alloc_units)
      units = matching_units[0]
      memory_raw = int(memory.findtext("{%s}VirtualQuantity" % RASD_SCHEMA,
            default=constants.VALUE_AUTO))
      memory_count = CONVERT_UNITS_TO_MB[units](memory_raw)
    else:
      memory_count = constants.VALUE_AUTO
    results["memory"] = str(memory_count)

    find_balance = ("{%s}GanetiSection/{%s}AutoBalance" %
                   (GANETI_SCHEMA, GANETI_SCHEMA))
    balance = self.tree.findtext(find_balance, default=constants.VALUE_AUTO)
    results["auto_balance"] = balance

    return results

  def GetTagsData(self):
    """Provides tags information for instance.

    @rtype: string or None
    @return: string of comma-separated tags for the instance

    """
    find_tags = "{%s}GanetiSection/{%s}Tags" % (GANETI_SCHEMA, GANETI_SCHEMA)
    results = self.tree.findtext(find_tags)
    if results:
      return results
    else:
      return None

  def GetVersionData(self):
    """Provides version number read from .ovf file

    @rtype: string
    @return: string containing the version number

    """
    find_version = ("{%s}GanetiSection/{%s}Version" %
                    (GANETI_SCHEMA, GANETI_SCHEMA))
    return self.tree.findtext(find_version)

  def GetNetworkData(self):
    """Provides data about the network in the OVF instance.

    The method gathers the data about networks used by OVF instance. It assumes
    that 'name' tag means something - in essence, if it contains one of the
    words 'bridged' or 'routed' then that will be the mode of this network in
    Ganeti. The information about the network can be either in GanetiSection or
    VirtualHardwareSection.

    @rtype: dict
    @return: dictionary containing all the network information

    """
    results = {}
    networks_search = ("{%s}NetworkSection/{%s}Network" %
                       (OVF_SCHEMA, OVF_SCHEMA))
    network_names = self._GetAttributes(networks_search,
      "{%s}name" % OVF_SCHEMA)
    required = ["ip", "mac", "link", "mode"]
    for (counter, network_name) in enumerate(network_names):
      network_search = ("{%s}VirtualSystem/{%s}VirtualHardwareSection/{%s}Item"
                        % (OVF_SCHEMA, OVF_SCHEMA, OVF_SCHEMA))
      ganeti_search = ("{%s}GanetiSection/{%s}Network/{%s}Nic" %
                       (GANETI_SCHEMA, GANETI_SCHEMA, GANETI_SCHEMA))
      network_match = ("{%s}Connection" % RASD_SCHEMA, network_name)
      ganeti_match = ("{%s}name" % OVF_SCHEMA, network_name)
      network_data = self._GetElementMatchingText(network_search, network_match)
      network_ganeti_data = self._GetElementMatchingAttr(ganeti_search,
        ganeti_match)

      ganeti_data = {}
      if network_ganeti_data:
        ganeti_data["mode"] = network_ganeti_data.findtext("{%s}Mode" %
                                                           GANETI_SCHEMA)
        ganeti_data["mac"] = network_ganeti_data.findtext("{%s}MACAddress" %
                                                          GANETI_SCHEMA)
        ganeti_data["ip"] = network_ganeti_data.findtext("{%s}IPAddress" %
                                                         GANETI_SCHEMA)
        ganeti_data["link"] = network_ganeti_data.findtext("{%s}Link" %
                                                           GANETI_SCHEMA)
      mac_data = None
      if network_data:
        mac_data = network_data.findtext("{%s}Address" % RASD_SCHEMA)

      network_name = network_name.lower()

      # First, some not Ganeti-specific information is collected
      if constants.NIC_MODE_BRIDGED in network_name:
        results["nic%s_mode" % counter] = "bridged"
      elif constants.NIC_MODE_ROUTED in network_name:
        results["nic%s_mode" % counter] = "routed"
      results["nic%s_mac" % counter] = mac_data

      # GanetiSection data overrides 'manually' collected data
      for name, value in ganeti_data.iteritems():
        results["nic%s_%s" % (counter, name)] = value

      # Bridged network has no IP - unless specifically stated otherwise
      if (results.get("nic%s_mode" % counter) == "bridged" and
          not results.get("nic%s_ip" % counter)):
        results["nic%s_ip" % counter] = constants.VALUE_NONE

      for option in required:
        if not results.get("nic%s_%s" % (counter, option)):
          results["nic%s_%s" % (counter, option)] = constants.VALUE_AUTO

    if network_names:
      results["nic_count"] = str(len(network_names))
    return results

  def GetDisksNames(self):
    """Provides list of file names for the disks used by the instance.

    @rtype: list
    @return: list of file names, as referenced in .ovf file

    """
    results = []
    disks_search = "{%s}DiskSection/{%s}Disk" % (OVF_SCHEMA, OVF_SCHEMA)
    disk_ids = self._GetAttributes(disks_search, "{%s}fileRef" % OVF_SCHEMA)
    for disk in disk_ids:
      disk_search = "{%s}References/{%s}File" % (OVF_SCHEMA, OVF_SCHEMA)
      disk_match = ("{%s}id" % OVF_SCHEMA, disk)
      disk_elem = self._GetElementMatchingAttr(disk_search, disk_match)
      if disk_elem is None:
        raise errors.OpPrereqError("%s file corrupted - disk %s not found in"
                                   " references" % (OVF_EXT, disk))
      disk_name = disk_elem.get("{%s}href" % OVF_SCHEMA)
      disk_compression = disk_elem.get("{%s}compression" % OVF_SCHEMA)
      results.append((disk_name, disk_compression))
    return results


class OVFWriter(object):
  """Writer class for OVF files.

  @type tree: ET.ElementTree
  @ivar tree: XML tree that we are constructing

  """
  def __init__(self, has_gnt_section):
    """Initialize the writer - set the top element.

    @type has_gnt_section: bool
    @param has_gnt_section: if the Ganeti schema should be added - i.e. this
      means that Ganeti section will be present

    """
    env_attribs = {
      "xmlns:xsi": XML_SCHEMA,
      "xmlns:vssd": VSSD_SCHEMA,
      "xmlns:rasd": RASD_SCHEMA,
      "xmlns:ovf": OVF_SCHEMA,
      "xmlns": OVF_SCHEMA,
      "xml:lang": "en-US",
    }
    if has_gnt_section:
      env_attribs["xmlns:gnt"] = GANETI_SCHEMA
    self.tree = ET.Element("Envelope", attrib=env_attribs)

  def PrettyXmlDump(self):
    """Formatter of the XML file.

    @rtype: string
    @return: XML tree in the form of nicely-formatted string

    """
    raw_string = ET.tostring(self.tree)
    parsed_xml = xml.dom.minidom.parseString(raw_string)
    xml_string = parsed_xml.toprettyxml(indent="  ")
    text_re = re.compile(">\n\s+([^<>\s].*?)\n\s+</", re.DOTALL)
    return text_re.sub(">\g<1></", xml_string)


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

  def _CompressDisk(self, disk_path, compression, action):
    """Performs (de)compression on the disk and returns the new path

    @type disk_path: string
    @param disk_path: path to the disk
    @type compression: string
    @param compression: compression type
    @type action: string
    @param action: whether the action is compression or decompression
    @rtype: string
    @return: new disk path after (de)compression

    @raise errors.OpPrereqError: disk (de)compression failed or "compression"
      is not supported

    """
    assert(action in ALLOWED_ACTIONS)
    # For now we only support gzip, as it is used in ovftool
    if compression != COMPRESSION_TYPE:
      raise errors.OpPrereqError("Unsupported compression type: %s"
                                 % compression)
    disk_file = os.path.basename(disk_path)
    if action == DECOMPRESS:
      (disk_name, _) = os.path.splitext(disk_file)
      prefix = disk_name
    elif action == COMPRESS:
      prefix = disk_file
    new_path = utils.GetClosedTempfile(suffix=COMPRESSION_EXT, prefix=prefix,
      dir=self.output_dir)
    self.temp_file_manager.Add(new_path)
    args = ["gzip", "-c", disk_path]
    run_result = utils.RunCmd(args, output=new_path)
    if run_result.failed:
      raise errors.OpPrereqError("Disk %s failed with output: %s"
                                 % (action, run_result.stderr))
    logging.info("The %s of the disk is completed", action)
    return (COMPRESSION_EXT, new_path)

  def _ConvertDisk(self, disk_format, disk_path):
    """Performes conversion to specified format.

    @type disk_format: string
    @param disk_format: format to which the disk should be converted
    @type disk_path: string
    @param disk_path: path to the disk that should be converted
    @rtype: string
    @return path to the output disk

    @raise errors.OpPrereqError: convertion of the disk failed

    """
    disk_file = os.path.basename(disk_path)
    (disk_name, disk_extension) = os.path.splitext(disk_file)
    if disk_extension != disk_format:
      logging.warning("Conversion of disk image to %s format, this may take"
                      " a while", disk_format)

    new_disk_path = utils.GetClosedTempfile(suffix=".%s" % disk_format,
      prefix=disk_name, dir=self.output_dir)
    self.temp_file_manager.Add(new_disk_path)
    args = [
      "qemu-img",
      "convert",
      "-O",
      disk_format,
      disk_path,
      new_disk_path,
    ]
    run_result = utils.RunCmd(args, cwd=os.getcwd())
    if run_result.failed:
      raise errors.OpPrereqError("Convertion to %s failed, qemu-img output was"
                                 ": %s" % (disk_format, run_result.stderr))
    return (".%s" % disk_format, new_disk_path)

  @staticmethod
  def _GetDiskQemuInfo(disk_path, regexp):
    """Figures out some information of the disk using qemu-img.

    @type disk_path: string
    @param disk_path: path to the disk we want to know the format of
    @type regexp: string
    @param regexp: string that has to be matched, it has to contain one group
    @rtype: string
    @return: disk format

    @raise errors.OpPrereqError: format information cannot be retrieved

    """
    args = ["qemu-img", "info", disk_path]
    run_result = utils.RunCmd(args, cwd=os.getcwd())
    if run_result.failed:
      raise errors.OpPrereqError("Gathering info about the disk using qemu-img"
                                 " failed, output was: %s" % run_result.stderr)
    result = run_result.output
    regexp = r"%s" % regexp
    match = re.search(regexp, result)
    if match:
      disk_format = match.group(1)
    else:
      raise errors.OpPrereqError("No file information matching %s found in:"
                                 " %s" % (regexp, result))
    return disk_format

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
  @type results_name: string
  @ivar results_name: name of imported instance
  @type results_template: string
  @ivar results_template: disk template read from .ovf file or command line
    arguments
  @type results_hypervisor: dict
  @ivar results_hypervisor: hypervisor information gathered from .ovf file or
    command line arguments
  @type results_os: dict
  @ivar results_os: operating system information gathered from .ovf file or
    command line arguments
  @type results_backend: dict
  @ivar results_backend: backend information gathered from .ovf file or
    command line arguments
  @type results_tags: string
  @ivar results_tags: string containing instance-specific tags
  @type results_version: string
  @ivar results_version: version as required by Ganeti import
  @type results_network: dict
  @ivar results_network: network information gathered from .ovf file or command
    line arguments
  @type results_disk: dict
  @ivar results_disk: disk information gathered from .ovf file or command line
    arguments

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
    """Parses the data and creates a structure containing all required info.

    The method reads the information given either as a command line option or as
    a part of the OVF description.

    @raise errors.OpPrereqError: if some required part of the description of
      virtual instance is missing or unable to create output directory

    """
    self.results_name = self._GetInfo("instance name", self.options.name,
      self._ParseNameOptions, self.ovf_reader.GetInstanceName)
    if not self.results_name:
      raise errors.OpPrereqError("Name of instance not provided")

    self.output_dir = utils.PathJoin(self.output_dir, self.results_name)
    try:
      utils.Makedirs(self.output_dir)
    except OSError, err:
      raise errors.OpPrereqError("Failed to create directory %s: %s" %
                                 (self.output_dir, err))

    self.results_template = self._GetInfo("disk template",
      self.options.disk_template, self._ParseTemplateOptions,
      self.ovf_reader.GetDiskTemplate)
    if not self.results_template:
      logging.info("Disk template not given")

    self.results_hypervisor = self._GetInfo("hypervisor",
      self.options.hypervisor, self._ParseHypervisorOptions,
      self.ovf_reader.GetHypervisorData)
    assert self.results_hypervisor["hypervisor_name"]
    if self.results_hypervisor["hypervisor_name"] == constants.VALUE_AUTO:
      logging.debug("Default hypervisor settings from the cluster will be used")

    self.results_os = self._GetInfo("OS", self.options.os,
      self._ParseOSOptions, self.ovf_reader.GetOSData)
    if not self.results_os.get("os_name"):
      raise errors.OpPrereqError("OS name must be provided")

    self.results_backend = self._GetInfo("backend", self.options.beparams,
      self._ParseBackendOptions, self.ovf_reader.GetBackendData)
    assert self.results_backend.get("vcpus")
    assert self.results_backend.get("memory")
    assert self.results_backend.get("auto_balance") is not None

    self.results_tags = self._GetInfo("tags", self.options.tags,
      self._ParseTags, self.ovf_reader.GetTagsData)

    ovf_version = self.ovf_reader.GetVersionData()
    if ovf_version:
      self.results_version = ovf_version
    else:
      self.results_version = constants.EXPORT_VERSION

    self.results_network = self._GetInfo("network", self.options.nics,
      self._ParseNicOptions, self.ovf_reader.GetNetworkData,
      ignore_test=self.options.no_nics)

    self.results_disk = self._GetInfo("disk", self.options.disks,
      self._ParseDiskOptions, self._GetDiskInfo,
      ignore_test=self.results_template == constants.DT_DISKLESS)

    if not self.results_disk and not self.results_network:
      raise errors.OpPrereqError("Either disk specification or network"
                                 " description must be present")

  @staticmethod
  def _GetInfo(name, cmd_arg, cmd_function, nocmd_function,
    ignore_test=False):
    """Get information about some section - e.g. disk, network, hypervisor.

    @type name: string
    @param name: name of the section
    @type cmd_arg: dict
    @param cmd_arg: command line argument specific for section 'name'
    @type cmd_function: callable
    @param cmd_function: function to call if 'cmd_args' exists
    @type nocmd_function: callable
    @param nocmd_function: function to call if 'cmd_args' is not there

    """
    if ignore_test:
      logging.info("Information for %s will be ignored", name)
      return {}
    if cmd_arg:
      logging.info("Information for %s will be parsed from command line", name)
      results = cmd_function()
    else:
      logging.info("Information for %s will be parsed from %s file",
        name, OVF_EXT)
      results = nocmd_function()
    logging.info("Options for %s were succesfully read", name)
    return results

  def _ParseNameOptions(self):
    """Returns name if one was given in command line.

    @rtype: string
    @return: name of an instance

    """
    return self.options.name

  def _ParseTemplateOptions(self):
    """Returns disk template if one was given in command line.

    @rtype: string
    @return: disk template name

    """
    return self.options.disk_template

  def _ParseHypervisorOptions(self):
    """Parses hypervisor options given in a command line.

    @rtype: dict
    @return: dictionary containing name of the chosen hypervisor and all the
      options

    """
    assert type(self.options.hypervisor) is tuple
    assert len(self.options.hypervisor) == 2
    results = {}
    if self.options.hypervisor[0]:
      results["hypervisor_name"] = self.options.hypervisor[0]
    else:
      results["hypervisor_name"] = constants.VALUE_AUTO
    results.update(self.options.hypervisor[1])
    return results

  def _ParseOSOptions(self):
    """Parses OS options given in command line.

    @rtype: dict
    @return: dictionary containing name of chosen OS and all its options

    """
    assert self.options.os
    results = {}
    results["os_name"] = self.options.os
    results.update(self.options.osparams)
    return results

  def _ParseBackendOptions(self):
    """Parses backend options given in command line.

    @rtype: dict
    @return: dictionary containing vcpus, memory and auto-balance options

    """
    assert self.options.beparams
    backend = {}
    backend.update(self.options.beparams)
    must_contain = ["vcpus", "memory", "auto_balance"]
    for element in must_contain:
      if backend.get(element) is None:
        backend[element] = constants.VALUE_AUTO
    return backend

  def _ParseTags(self):
    """Returns tags list given in command line.

    @rtype: string
    @return: string containing comma-separated tags

    """
    return self.options.tags

  def _ParseNicOptions(self):
    """Parses network options given in a command line or as a dictionary.

    @rtype: dict
    @return: dictionary of network-related options

    """
    assert self.options.nics
    results = {}
    for (nic_id, nic_desc) in self.options.nics:
      results["nic%s_mode" % nic_id] = \
        nic_desc.get("mode", constants.VALUE_AUTO)
      results["nic%s_mac" % nic_id] = nic_desc.get("mac", constants.VALUE_AUTO)
      results["nic%s_link" % nic_id] = \
        nic_desc.get("link", constants.VALUE_AUTO)
      if nic_desc.get("mode") == "bridged":
        results["nic%s_ip" % nic_id] = constants.VALUE_NONE
      else:
        results["nic%s_ip" % nic_id] = constants.VALUE_AUTO
    results["nic_count"] = str(len(self.options.nics))
    return results

  def _ParseDiskOptions(self):
    """Parses disk options given in a command line.

    @rtype: dict
    @return: dictionary of disk-related options

    @raise errors.OpPrereqError: disk description does not contain size
      information or size information is invalid or creation failed

    """
    assert self.options.disks
    results = {}
    for (disk_id, disk_desc) in self.options.disks:
      results["disk%s_ivname" % disk_id] = "disk/%s" % disk_id
      if disk_desc.get("size"):
        try:
          disk_size = utils.ParseUnit(disk_desc["size"])
        except ValueError:
          raise errors.OpPrereqError("Invalid disk size for disk %s: %s" %
                                     (disk_id, disk_desc["size"]))
        new_path = utils.PathJoin(self.output_dir, str(disk_id))
        args = [
          "qemu-img",
          "create",
          "-f",
          "raw",
          new_path,
          disk_size,
        ]
        run_result = utils.RunCmd(args)
        if run_result.failed:
          raise errors.OpPrereqError("Creation of disk %s failed, output was:"
                                     " %s" % (new_path, run_result.stderr))
        results["disk%s_size" % disk_id] = str(disk_size)
        results["disk%s_dump" % disk_id] = "disk%s.raw" % disk_id
      else:
        raise errors.OpPrereqError("Disks created for import must have their"
                                   " size specified")
    results["disk_count"] = str(len(self.options.disks))
    return results

  def _GetDiskInfo(self):
    """Gathers information about disks used by instance, perfomes conversion.

    @rtype: dict
    @return: dictionary of disk-related options

    @raise errors.OpPrereqError: disk is not in the same directory as .ovf file

    """
    results = {}
    disks_list = self.ovf_reader.GetDisksNames()
    for (counter, (disk_name, disk_compression)) in enumerate(disks_list):
      if os.path.dirname(disk_name):
        raise errors.OpPrereqError("Disks are not allowed to have absolute"
                                   " paths or paths outside main OVF directory")
      disk, _ = os.path.splitext(disk_name)
      disk_path = utils.PathJoin(self.input_dir, disk_name)
      if disk_compression:
        _, disk_path = self._CompressDisk(disk_path, disk_compression,
          DECOMPRESS)
        disk, _ = os.path.splitext(disk)
      if self._GetDiskQemuInfo(disk_path, "file format: (\S+)") != "raw":
        logging.info("Conversion to raw format is required")
      ext, new_disk_path = self._ConvertDisk("raw", disk_path)

      final_disk_path = LinkFile(new_disk_path, prefix=disk, suffix=ext,
        directory=self.output_dir)
      final_name = os.path.basename(final_disk_path)
      disk_size = os.path.getsize(final_disk_path) / (1024 * 1024)
      results["disk%s_dump" % counter] = final_name
      results["disk%s_size" % counter] = str(disk_size)
      results["disk%s_ivname" % counter] = "disk/%s" % str(counter)
    if disks_list:
      results["disk_count"] = str(len(disks_list))
    return results

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
    results[constants.INISECT_INS].update(self.results_network)
    results[constants.INISECT_INS]["hypervisor"] = \
      self.results_hypervisor["hypervisor_name"]
    results[constants.INISECT_INS]["name"] = self.results_name
    if self.results_template:
      results[constants.INISECT_INS]["disk_template"] = self.results_template
    if self.results_tags:
      results[constants.INISECT_INS]["tags"] = self.results_tags

    results[constants.INISECT_BEP].update(self.results_backend)

    results[constants.INISECT_EXP]["os"] = self.results_os["os_name"]
    results[constants.INISECT_EXP]["version"] = self.results_version

    del self.results_os["os_name"]
    results[constants.INISECT_OSP].update(self.results_os)

    del self.results_hypervisor["hypervisor_name"]
    results[constants.INISECT_HYP].update(self.results_hypervisor)

    output_file_name = utils.PathJoin(self.output_dir,
      constants.EXPORT_CONF_FILE)

    output = []
    for section, options in results.iteritems():
      output.append("[%s]" % section)
      for name, value in options.iteritems():
        if value is None:
          value = ""
        output.append("%s = %s" % (name, value))
      output.append("")
    output_contents = "\n".join(output)

    try:
      utils.WriteFile(output_file_name, data=output_contents)
    except errors.ProgrammerError, err:
      raise errors.OpPrereqError("Saving the config file failed: %s" % err)

    self.Cleanup()


class ConfigParserWithDefaults(ConfigParser.SafeConfigParser):
  """This is just a wrapper on SafeConfigParser, that uses default values

  """
  def get(self, section, options, raw=None, vars=None): # pylint: disable=W0622
    try:
      result = ConfigParser.SafeConfigParser.get(self, section, options, \
        raw=raw, vars=vars)
    except ConfigParser.NoOptionError:
      result = None
    return result

  def getint(self, section, options):
    try:
      result = ConfigParser.SafeConfigParser.get(self, section, options)
    except ConfigParser.NoOptionError:
      result = 0
    return int(result)


class OVFExporter(Converter):
  """Converter from Ganeti config file to OVF

  @type input_dir: string
  @ivar input_dir: directory in which the config.ini file resides
  @type output_dir: string
  @ivar output_dir: directory to which the results of conversion shall be
    written
  @type packed_dir: string
  @ivar packed_dir: if we want OVA package, this points to the real (i.e. not
    temp) output directory
  @type input_path: string
  @ivar input_path: complete path to the config.ini file
  @type output_path: string
  @ivar output_path: complete path to .ovf file
  @type config_parser: L{ConfigParserWithDefaults}
  @ivar config_parser: parser for the config.ini file
  @type results_disk: list
  @ivar results_disk: list of dictionaries of disk options from config.ini
  @type results_network: list
  @ivar results_network: list of dictionaries of network options form config.ini
  @type results_name: string
  @ivar results_name: name of the instance
  @type results_vcpus: string
  @ivar results_vcpus: number of VCPUs
  @type results_memory: string
  @ivar results_memory: RAM memory in MB
  @type results_ganeti: dict
  @ivar results_ganeti: dictionary of Ganeti-specific options from config.ini

  """
  def _ReadInputData(self, input_path):
    """Reads the data on which the conversion will take place.

    @type input_path: string
    @param input_path: absolute path to the config.ini input file

    @raise errors.OpPrereqError: error when reading the config file

    """
    input_dir = os.path.dirname(input_path)
    self.input_path = input_path
    self.input_dir = input_dir
    if self.options.output_dir:
      self.output_dir = os.path.abspath(self.options.output_dir)
    else:
      self.output_dir = input_dir
    self.config_parser = ConfigParserWithDefaults()
    logging.info("Reading configuration from %s file", input_path)
    try:
      self.config_parser.read(input_path)
    except ConfigParser.MissingSectionHeaderError, err:
      raise errors.OpPrereqError("Error when trying to read %s: %s" %
                                 (input_path, err))
    if self.options.ova_package:
      self.temp_dir = tempfile.mkdtemp()
      self.packed_dir = self.output_dir
      self.output_dir = self.temp_dir

    self.ovf_writer = OVFWriter(not self.options.ext_usage)

  def _ParseName(self):
    """Parses name from command line options or config file.

    @rtype: string
    @return: name of Ganeti instance

    @raise errors.OpPrereqError: if name of the instance is not provided

    """
    if self.options.name:
      name = self.options.name
    else:
      name = self.config_parser.get(constants.INISECT_INS, NAME)
    if name is None:
      raise errors.OpPrereqError("No instance name found")
    return name

  def _ParseVCPUs(self):
    """Parses vcpus number from config file.

    @rtype: int
    @return: number of virtual CPUs

    @raise errors.OpPrereqError: if number of VCPUs equals 0

    """
    vcpus = self.config_parser.getint(constants.INISECT_BEP, VCPUS)
    if vcpus == 0:
      raise errors.OpPrereqError("No CPU information found")
    return vcpus

  def _ParseMemory(self):
    """Parses vcpus number from config file.

    @rtype: int
    @return: amount of memory in MB

    @raise errors.OpPrereqError: if amount of memory equals 0

    """
    memory = self.config_parser.getint(constants.INISECT_BEP, MEMORY)
    if memory == 0:
      raise errors.OpPrereqError("No memory information found")
    return memory

  def _ParseGaneti(self):
    """Parses Ganeti data from config file.

    @rtype: dictionary
    @return: dictionary of Ganeti-specific options

    """
    results = {}
    # hypervisor
    results["hypervisor"] = {}
    hyp_name = self.config_parser.get(constants.INISECT_INS, HYPERV)
    if hyp_name is None:
      raise errors.OpPrereqError("No hypervisor information found")
    results["hypervisor"]["name"] = hyp_name
    pairs = self.config_parser.items(constants.INISECT_HYP)
    for (name, value) in pairs:
      results["hypervisor"][name] = value
    # os
    results["os"] = {}
    os_name = self.config_parser.get(constants.INISECT_EXP, OS)
    if os_name is None:
      raise errors.OpPrereqError("No operating system information found")
    results["os"]["name"] = os_name
    pairs = self.config_parser.items(constants.INISECT_OSP)
    for (name, value) in pairs:
      results["os"][name] = value
    # other
    others = [
      (constants.INISECT_INS, DISK_TEMPLATE, "disk_template"),
      (constants.INISECT_BEP, AUTO_BALANCE, "auto_balance"),
      (constants.INISECT_INS, TAGS, "tags"),
      (constants.INISECT_EXP, VERSION, "version"),
    ]
    for (section, element, name) in others:
      results[name] = self.config_parser.get(section, element)
    return results

  def _ParseNetworks(self):
    """Parses network data from config file.

    @rtype: list
    @return: list of dictionaries of network options

    @raise errors.OpPrereqError: then network mode is not recognized

    """
    results = []
    counter = 0
    while True:
      data_link = \
        self.config_parser.get(constants.INISECT_INS, "nic%s_link" % counter)
      if data_link is None:
        break
      results.append({
        "mode": self.config_parser.get(constants.INISECT_INS,
           "nic%s_mode" % counter),
        "mac": self.config_parser.get(constants.INISECT_INS,
           "nic%s_mac" % counter),
        "ip": self.config_parser.get(constants.INISECT_INS,
           "nic%s_ip" % counter),
        "link": data_link,
      })
      if results[counter]["mode"] not in constants.NIC_VALID_MODES:
        raise errors.OpPrereqError("Network mode %s not recognized"
                                   % results[counter]["mode"])
      counter += 1
    return results

  def _GetDiskOptions(self, disk_file, compression):
    """Convert the disk and gather disk info for .ovf file.

    @type disk_file: string
    @param disk_file: name of the disk (without the full path)
    @type compression: bool
    @param compression: whether the disk should be compressed or not

    @raise errors.OpPrereqError: when disk image does not exist

    """
    disk_path = utils.PathJoin(self.input_dir, disk_file)
    results = {}
    if not os.path.isfile(disk_path):
      raise errors.OpPrereqError("Disk image does not exist: %s" % disk_path)
    if os.path.dirname(disk_file):
      raise errors.OpPrereqError("Path for the disk: %s contains a directory"
                                 " name" % disk_path)
    disk_name, _ = os.path.splitext(disk_file)
    ext, new_disk_path = self._ConvertDisk(self.options.disk_format, disk_path)
    results["format"] = self.options.disk_format
    results["virt-size"] = self._GetDiskQemuInfo(new_disk_path,
      "virtual size: \S+ \((\d+) bytes\)")
    if compression:
      ext2, new_disk_path = self._CompressDisk(new_disk_path, "gzip",
        COMPRESS)
      disk_name, _ = os.path.splitext(disk_name)
      results["compression"] = "gzip"
      ext += ext2
    final_disk_path = LinkFile(new_disk_path, prefix=disk_name, suffix=ext,
      directory=self.output_dir)
    final_disk_name = os.path.basename(final_disk_path)
    results["real-size"] = os.path.getsize(final_disk_path)
    results["path"] = final_disk_name
    self.references_files.append(final_disk_path)
    return results

  def _ParseDisks(self):
    """Parses disk data from config file.

    @rtype: list
    @return: list of dictionaries of disk options

    """
    results = []
    counter = 0
    while True:
      disk_file = \
        self.config_parser.get(constants.INISECT_INS, "disk%s_dump" % counter)
      if disk_file is None:
        break
      results.append(self._GetDiskOptions(disk_file, self.options.compression))
      counter += 1
    return results

  def Parse(self):
    """Parses the data and creates a structure containing all required info.

    """
    try:
      utils.Makedirs(self.output_dir)
    except OSError, err:
      raise errors.OpPrereqError("Failed to create directory %s: %s" %
                                 (self.output_dir, err))

    self.references_files = []
    self.results_name = self._ParseName()
    self.results_vcpus = self._ParseVCPUs()
    self.results_memory = self._ParseMemory()
    if not self.options.ext_usage:
      self.results_ganeti = self._ParseGaneti()
    self.results_network = self._ParseNetworks()
    self.results_disk = self._ParseDisks()

  def _PrepareManifest(self, path):
    """Creates manifest for all the files in OVF package.

    @type path: string
    @param path: path to manifesto file

    @raise errors.OpPrereqError: if error occurs when writing file

    """
    logging.info("Preparing manifest for the OVF package")
    lines = []
    files_list = [self.output_path]
    files_list.extend(self.references_files)
    logging.warning("Calculating SHA1 checksums, this may take a while")
    sha1_sums = utils.FingerprintFiles(files_list)
    for file_path, value in sha1_sums.iteritems():
      file_name = os.path.basename(file_path)
      lines.append("SHA1(%s)= %s" % (file_name, value))
    lines.append("")
    data = "\n".join(lines)
    try:
      utils.WriteFile(path, data=data)
    except errors.ProgrammerError, err:
      raise errors.OpPrereqError("Saving the manifest file failed: %s" % err)

  @staticmethod
  def _PrepareTarFile(tar_path, files_list):
    """Creates tarfile from the files in OVF package.

    @type tar_path: string
    @param tar_path: path to the resulting file
    @type files_list: list
    @param files_list: list of files in the OVF package

    """
    logging.info("Preparing tarball for the OVF package")
    open(tar_path, mode="w").close()
    ova_package = tarfile.open(name=tar_path, mode="w")
    for file_name in files_list:
      ova_package.add(file_name)
    ova_package.close()

  def Save(self):
    """Saves the gathered configuration in an apropriate format.

    @raise errors.OpPrereqError: if unable to create output directory

    """
    output_file = "%s%s" % (self.results_name, OVF_EXT)
    output_path = utils.PathJoin(self.output_dir, output_file)
    self.ovf_writer = OVFWriter(not self.options.ext_usage)
    logging.info("Saving read data to %s", output_path)

    self.output_path = utils.PathJoin(self.output_dir, output_file)
    files_list = [self.output_path]

    data = self.ovf_writer.PrettyXmlDump()
    utils.WriteFile(self.output_path, data=data)

    manifest_file = "%s%s" % (self.results_name, MF_EXT)
    manifest_path = utils.PathJoin(self.output_dir, manifest_file)
    self._PrepareManifest(manifest_path)
    files_list.append(manifest_path)

    files_list.extend(self.references_files)

    if self.options.ova_package:
      ova_file = "%s%s" % (self.results_name, OVA_EXT)
      packed_path = utils.PathJoin(self.packed_dir, ova_file)
      try:
        utils.Makedirs(self.packed_dir)
      except OSError, err:
        raise errors.OpPrereqError("Failed to create directory %s: %s" %
                                   (self.packed_dir, err))
      self._PrepareTarFile(packed_path, files_list)
    logging.info("Creation of the OVF package was successfull")
    self.Cleanup()
