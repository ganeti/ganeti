#!/usr/bin/python
#

# Copyright (C) 2011, 2012 Google Inc.
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


"""Converter tools between ovf and ganeti config file

"""

# pylint: disable=F0401, E1101, C0413

# F0401 because ElementTree is not default for python 2.4
# E1101 makes no sense - pylint assumes that ElementTree object is a tuple
# C0413 Wrong import position


import configparser
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

try:
  ParseError = ET.ParseError # pylint: disable=E1103
except AttributeError:
  ParseError = None

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import pathutils


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
NO_COMPRESSION = [None, "identity"]
COMPRESS = "compression"
DECOMPRESS = "decompression"
ALLOWED_ACTIONS = [COMPRESS, DECOMPRESS]

VMDK = "vmdk"
RAW = "raw"
COW = "cow"
ALLOWED_FORMATS = [RAW, COW, VMDK]

# ResourceType values
RASD_TYPE = {
  "vcpus": "3",
  "memory": "4",
  "scsi-controller": "6",
  "ethernet-adapter": "10",
  "disk": "17",
}

SCSI_SUBTYPE = "lsilogic"
VS_TYPE = {
  "ganeti": "ganeti-ovf",
  "external": "vmx-04",
}

# AllocationUnits values and conversion
ALLOCATION_UNITS = {
  "b": ["bytes", "b"],
  "kb": ["kilobytes", "kb", "byte * 2^10", "kibibytes", "kib"],
  "mb": ["megabytes", "mb", "byte * 2^20", "mebibytes", "mib"],
  "gb": ["gigabytes", "gb", "byte * 2^30", "gibibytes", "gib"],
}
CONVERT_UNITS_TO_MB = {
  "b": lambda x: x // (1024 * 1024),
  "kb": lambda x: x // 1024,
  "mb": lambda x: x,
  "gb": lambda x: x * 1024,
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

# Instance IDs of System and SCSI controller
INSTANCE_ID = {
  "system": 0,
  "vcpus": 1,
  "memory": 2,
  "scsi": 3,
}

# Disk format descriptions
DISK_FORMAT = {
  RAW: "http://en.wikipedia.org/wiki/Byte",
  VMDK: "http://www.vmware.com/interfaces/specifications/vmdk.html"
          "#monolithicSparse",
  COW: "http://www.gnome.org/~markmc/qcow-image-format.html",
}


def CheckQemuImg():
  """ Make sure that qemu-img is present before performing operations.

  @raise errors.OpPrereqError: when qemu-img was not found in the system

  """
  if not constants.QEMUIMG_PATH:
    raise errors.OpPrereqError("qemu-img not found at build time, unable"
                               " to continue", errors.ECODE_STATE)


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
    except OSError as err:
      if err.errno == errno.EEXIST:
        new_path = utils.PathJoin(directory,
                                  "%s_%s%s" % (prefix, counter, suffix))
        counter += 1
      else:
        raise errors.OpPrereqError("Error moving the file %s to %s location:"
                                   " %s" % (old_path, new_path, err),
                                   errors.ECODE_ENVIRON)
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
    except (ParseError, xml.parsers.expat.ExpatError) as err:
      raise errors.OpPrereqError("Error while reading %s file: %s" %
                                 (OVF_EXT, err), errors.ECODE_ENVIRON)

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
        raise errors.OpPrereqError("File does not exist: %s" % file_path,
                                   errors.ECODE_ENVIRON)
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
    return [r for r in results if r]

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
    if root is None:
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
      for file_name, value in manifest_files.items():
        if sha1_sums.get(utils.PathJoin(self.input_dir, file_name)) != value:
          raise errors.OpPrereqError("SHA1 checksum of %s does not match the"
                                     " value in manifest file" % file_name,
                                     errors.ECODE_ENVIRON)
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
    if hypervisor_data is None:
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
    if os_data is not None:
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
    if vcpus is not None:
      vcpus_count = vcpus.findtext("{%s}VirtualQuantity" % RASD_SCHEMA,
                                   default=constants.VALUE_AUTO)
    else:
      vcpus_count = constants.VALUE_AUTO
    results["vcpus"] = str(vcpus_count)

    find_memory = find_vcpus
    match_memory = ("{%s}ResourceType" % RASD_SCHEMA, RASD_TYPE["memory"])
    memory = self._GetElementMatchingText(find_memory, match_memory)
    memory_raw = None
    if memory is not None:
      alloc_units = memory.findtext("{%s}AllocationUnits" % RASD_SCHEMA)
      matching_units = [units for units, variants in ALLOCATION_UNITS.items()
                        if alloc_units.lower() in variants]
      if matching_units == []:
        raise errors.OpPrereqError("Unit %s for RAM memory unknown" %
                                   alloc_units, errors.ECODE_INVAL)
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
    required = ["ip", "mac", "link", "mode", "network"]
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
      if network_ganeti_data is not None:
        ganeti_data["mode"] = network_ganeti_data.findtext("{%s}Mode" %
                                                           GANETI_SCHEMA)
        ganeti_data["mac"] = network_ganeti_data.findtext("{%s}MACAddress" %
                                                          GANETI_SCHEMA)
        ganeti_data["ip"] = network_ganeti_data.findtext("{%s}IPAddress" %
                                                         GANETI_SCHEMA)
        ganeti_data["link"] = network_ganeti_data.findtext("{%s}Link" %
                                                           GANETI_SCHEMA)
        ganeti_data["network"] = network_ganeti_data.findtext("{%s}Net" %
                                                              GANETI_SCHEMA)
      mac_data = None
      if network_data is not None:
        mac_data = network_data.findtext("{%s}Address" % RASD_SCHEMA)

      network_name = network_name.lower()

      # First, some not Ganeti-specific information is collected
      if constants.NIC_MODE_BRIDGED in network_name:
        results["nic%s_mode" % counter] = "bridged"
      elif constants.NIC_MODE_ROUTED in network_name:
        results["nic%s_mode" % counter] = "routed"
      results["nic%s_mac" % counter] = mac_data

      # GanetiSection data overrides 'manually' collected data
      for name, value in ganeti_data.items():
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
                                   " references" % (OVF_EXT, disk),
                                   errors.ECODE_ENVIRON)
      disk_name = disk_elem.get("{%s}href" % OVF_SCHEMA)
      disk_compression = disk_elem.get("{%s}compression" % OVF_SCHEMA)
      results.append((disk_name, disk_compression))
    return results


def SubElementText(parent, tag, text, attrib={}, **extra):
# pylint: disable=W0102
  """This is just a wrapper on ET.SubElement that always has text content.

  """
  if text is None:
    return None
  elem = ET.SubElement(parent, tag, attrib=attrib, **extra)
  elem.text = str(text)
  return elem


class OVFWriter(object):
  """Writer class for OVF files.

  @type tree: ET.ElementTree
  @ivar tree: XML tree that we are constructing
  @type virtual_system_type: string
  @ivar virtual_system_type: value of vssd:VirtualSystemType, for external usage
    in VMWare this requires to be vmx
  @type hardware_list: list
  @ivar hardware_list: list of items prepared for VirtualHardwareSection
  @type next_instance_id: int
  @ivar next_instance_id: next instance id to be used when creating elements on
    hardware_list

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
      self.virtual_system_type = VS_TYPE["ganeti"]
    else:
      self.virtual_system_type = VS_TYPE["external"]
    self.tree = ET.Element("Envelope", attrib=env_attribs)
    self.hardware_list = []
    # INSTANCE_ID contains statically assigned IDs, starting from 0
    self.next_instance_id = len(INSTANCE_ID) # FIXME: hackish

  def SaveDisksData(self, disks):
    """Convert disk information to certain OVF sections.

    @type disks: list
    @param disks: list of dictionaries of disk options from config.ini

    """
    references = ET.SubElement(self.tree, "References")
    disk_section = ET.SubElement(self.tree, "DiskSection")
    SubElementText(disk_section, "Info", "Virtual disk information")
    for counter, disk in enumerate(disks):
      file_id = "file%s" % counter
      disk_id = "disk%s" % counter
      file_attribs = {
        "ovf:href": disk["path"],
        "ovf:size": str(disk["real-size"]),
        "ovf:id": file_id,
      }
      disk_attribs = {
        "ovf:capacity": str(disk["virt-size"]),
        "ovf:diskId": disk_id,
        "ovf:fileRef": file_id,
        "ovf:format": DISK_FORMAT.get(disk["format"], disk["format"]),
      }
      if "compression" in disk:
        file_attribs["ovf:compression"] = disk["compression"]
      ET.SubElement(references, "File", attrib=file_attribs)
      ET.SubElement(disk_section, "Disk", attrib=disk_attribs)

      # Item in VirtualHardwareSection creation
      disk_item = ET.Element("Item")
      SubElementText(disk_item, "rasd:ElementName", disk_id)
      SubElementText(disk_item, "rasd:HostResource", "ovf:/disk/%s" % disk_id)
      SubElementText(disk_item, "rasd:InstanceID", self.next_instance_id)
      SubElementText(disk_item, "rasd:Parent", INSTANCE_ID["scsi"])
      SubElementText(disk_item, "rasd:ResourceType", RASD_TYPE["disk"])
      self.hardware_list.append(disk_item)
      self.next_instance_id += 1

  def SaveNetworksData(self, networks):
    """Convert network information to NetworkSection.

    @type networks: list
    @param networks: list of dictionaries of network options form config.ini

    """
    network_section = ET.SubElement(self.tree, "NetworkSection")
    SubElementText(network_section, "Info", "List of logical networks")
    for counter, network in enumerate(networks):
      network_name = "%s%s" % (network["mode"], counter)
      network_attrib = {"ovf:name": network_name}
      ET.SubElement(network_section, "Network", attrib=network_attrib)

      # Item in VirtualHardwareSection creation
      network_item = ET.Element("Item")
      SubElementText(network_item, "rasd:Address", network["mac"])
      SubElementText(network_item, "rasd:Connection", network_name)
      SubElementText(network_item, "rasd:ElementName", network_name)
      SubElementText(network_item, "rasd:InstanceID", self.next_instance_id)
      SubElementText(network_item, "rasd:ResourceType",
                     RASD_TYPE["ethernet-adapter"])
      self.hardware_list.append(network_item)
      self.next_instance_id += 1

  @staticmethod
  def _SaveNameAndParams(root, data):
    """Save name and parameters information under root using data.

    @type root: ET.Element
    @param root: root element for the Name and Parameters
    @type data: dict
    @param data: data from which we gather the values

    """
    assert(data.get("name"))
    name = SubElementText(root, "gnt:Name", data["name"])
    params = ET.SubElement(root, "gnt:Parameters")
    for name, value in data.items():
      if name != "name":
        SubElementText(params, "gnt:%s" % name, value)

  def SaveGanetiData(self, ganeti, networks):
    """Convert Ganeti-specific information to GanetiSection.

    @type ganeti: dict
    @param ganeti: dictionary of Ganeti-specific options from config.ini
    @type networks: list
    @param networks: list of dictionaries of network options form config.ini

    """
    ganeti_section = ET.SubElement(self.tree, "gnt:GanetiSection")

    SubElementText(ganeti_section, "gnt:Version", ganeti.get("version"))
    SubElementText(ganeti_section, "gnt:DiskTemplate",
                   ganeti.get("disk_template"))
    SubElementText(ganeti_section, "gnt:AutoBalance",
                   ganeti.get("auto_balance"))
    SubElementText(ganeti_section, "gnt:Tags", ganeti.get("tags"))

    osys = ET.SubElement(ganeti_section, "gnt:OperatingSystem")
    self._SaveNameAndParams(osys, ganeti["os"])

    hypervisor = ET.SubElement(ganeti_section, "gnt:Hypervisor")
    self._SaveNameAndParams(hypervisor, ganeti["hypervisor"])

    network_section = ET.SubElement(ganeti_section, "gnt:Network")
    for counter, network in enumerate(networks):
      network_name = "%s%s" % (network["mode"], counter)
      nic_attrib = {"ovf:name": network_name}
      nic = ET.SubElement(network_section, "gnt:Nic", attrib=nic_attrib)
      SubElementText(nic, "gnt:Mode", network["mode"])
      SubElementText(nic, "gnt:MACAddress", network["mac"])
      SubElementText(nic, "gnt:IPAddress", network["ip"])
      SubElementText(nic, "gnt:Link", network["link"])
      SubElementText(nic, "gnt:Net", network["network"])

  def SaveVirtualSystemData(self, name, vcpus, memory):
    """Convert virtual system information to OVF sections.

    @type name: string
    @param name: name of the instance
    @type vcpus: int
    @param vcpus: number of VCPUs
    @type memory: int
    @param memory: RAM memory in MB

    """
    assert(vcpus > 0)
    assert(memory > 0)
    vs_attrib = {"ovf:id": name}
    virtual_system = ET.SubElement(self.tree, "VirtualSystem", attrib=vs_attrib)
    SubElementText(virtual_system, "Info", "A virtual machine")

    name_section = ET.SubElement(virtual_system, "Name")
    name_section.text = name
    os_attrib = {"ovf:id": "0"}
    os_section = ET.SubElement(virtual_system, "OperatingSystemSection",
                               attrib=os_attrib)
    SubElementText(os_section, "Info", "Installed guest operating system")
    hardware_section = ET.SubElement(virtual_system, "VirtualHardwareSection")
    SubElementText(hardware_section, "Info", "Virtual hardware requirements")

    # System description
    system = ET.SubElement(hardware_section, "System")
    SubElementText(system, "vssd:ElementName", "Virtual Hardware Family")
    SubElementText(system, "vssd:InstanceID", INSTANCE_ID["system"])
    SubElementText(system, "vssd:VirtualSystemIdentifier", name)
    SubElementText(system, "vssd:VirtualSystemType", self.virtual_system_type)

    # Item for vcpus
    vcpus_item = ET.SubElement(hardware_section, "Item")
    SubElementText(vcpus_item, "rasd:ElementName",
                   "%s virtual CPU(s)" % vcpus)
    SubElementText(vcpus_item, "rasd:InstanceID", INSTANCE_ID["vcpus"])
    SubElementText(vcpus_item, "rasd:ResourceType", RASD_TYPE["vcpus"])
    SubElementText(vcpus_item, "rasd:VirtualQuantity", vcpus)

    # Item for memory
    memory_item = ET.SubElement(hardware_section, "Item")
    SubElementText(memory_item, "rasd:AllocationUnits", "byte * 2^20")
    SubElementText(memory_item, "rasd:ElementName", "%sMB of memory" % memory)
    SubElementText(memory_item, "rasd:InstanceID", INSTANCE_ID["memory"])
    SubElementText(memory_item, "rasd:ResourceType", RASD_TYPE["memory"])
    SubElementText(memory_item, "rasd:VirtualQuantity", memory)

    # Item for scsi controller
    scsi_item = ET.SubElement(hardware_section, "Item")
    SubElementText(scsi_item, "rasd:Address", INSTANCE_ID["system"])
    SubElementText(scsi_item, "rasd:ElementName", "scsi_controller0")
    SubElementText(scsi_item, "rasd:InstanceID", INSTANCE_ID["scsi"])
    SubElementText(scsi_item, "rasd:ResourceSubType", SCSI_SUBTYPE)
    SubElementText(scsi_item, "rasd:ResourceType", RASD_TYPE["scsi-controller"])

    # Other items - from self.hardware_list
    for item in self.hardware_list:
      hardware_section.append(item)

  def PrettyXmlDump(self):
    """Formatter of the XML file.

    @rtype: string
    @return: XML tree in the form of nicely-formatted string

    """
    raw_string = ET.tostring(self.tree)
    parsed_xml = xml.dom.minidom.parseString(raw_string)
    xml_string = parsed_xml.toprettyxml(indent="  ")
    text_re = re.compile(r">\n\s+([^<>\s].*?)\n\s+</", re.DOTALL)
    return text_re.sub(r">\g<1></", xml_string)


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
      raise errors.OpPrereqError("File does not exist: %s" % input_path,
                                 errors.ECODE_ENVIRON)
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
                                 % compression, errors.ECODE_INVAL)
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
                                 % (action, run_result.stderr),
                                 errors.ECODE_ENVIRON)
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
    CheckQemuImg()
    disk_file = os.path.basename(disk_path)
    (disk_name, disk_extension) = os.path.splitext(disk_file)
    if disk_extension != disk_format:
      logging.warning("Conversion of disk image to %s format, this may take"
                      " a while", disk_format)

    new_disk_path = utils.GetClosedTempfile(
      suffix=".%s" % disk_format, prefix=disk_name, dir=self.output_dir)
    self.temp_file_manager.Add(new_disk_path)
    args = [
      constants.QEMUIMG_PATH,
      "convert",
      "-O",
      disk_format,
      disk_path,
      new_disk_path,
    ]
    run_result = utils.RunCmd(args, cwd=os.getcwd())
    if run_result.failed:
      raise errors.OpPrereqError("Convertion to %s failed, qemu-img output was"
                                 ": %s" % (disk_format, run_result.stderr),
                                 errors.ECODE_ENVIRON)
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
    CheckQemuImg()
    args = [constants.QEMUIMG_PATH, "info", disk_path]
    run_result = utils.RunCmd(args, cwd=os.getcwd())
    if run_result.failed:
      raise errors.OpPrereqError("Gathering info about the disk using qemu-img"
                                 " failed, output was: %s" % run_result.stderr,
                                 errors.ECODE_ENVIRON)
    result = run_result.output
    regexp = r"%s" % regexp
    match = re.search(regexp, result)
    if match:
      disk_format = match.group(1)
    else:
      raise errors.OpPrereqError("No file information matching %s found in:"
                                 " %s" % (regexp, result),
                                 errors.ECODE_ENVIRON)
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
                                 " file" % (OVA_EXT, OVF_EXT),
                                 errors.ECODE_INVAL)
    assert ((input_extension == OVA_EXT and self.temp_dir) or
            (input_extension == OVF_EXT and not self.temp_dir))
    assert self.input_dir in self.input_path

    if self.options.output_dir:
      self.output_dir = os.path.abspath(self.options.output_dir)
      if (os.path.commonprefix([pathutils.EXPORT_DIR, self.output_dir]) !=
          pathutils.EXPORT_DIR):
        logging.warning("Export path is not under %s directory, import to"
                        " Ganeti using gnt-backup may fail",
                        pathutils.EXPORT_DIR)
    else:
      self.output_dir = pathutils.EXPORT_DIR

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
                                 " archive" % OVA_EXT, errors.ECODE_ENVIRON)
    ova_content = tarfile.open(input_path)
    temp_dir = tempfile.mkdtemp()
    self.temp_dir = temp_dir
    for file_name in ova_content.getnames():
      file_normname = os.path.normpath(file_name)
      try:
        utils.PathJoin(temp_dir, file_normname)
      except ValueError as err:
        raise errors.OpPrereqError("File %s inside %s package is not safe" %
                                   (file_name, OVA_EXT), errors.ECODE_ENVIRON)
      if file_name.endswith(OVF_EXT):
        input_name = file_name
    if not input_name:
      raise errors.OpPrereqError("No %s file in %s package found" %
                                 (OVF_EXT, OVA_EXT), errors.ECODE_ENVIRON)
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
    except tarfile.TarError as err:
      raise errors.OpPrereqError("Error while extracting %s archive: %s" %
                                 (OVA_EXT, err), errors.ECODE_ENVIRON)
    logging.info("OVA package extracted to %s directory", self.temp_dir)

  def Parse(self):
    """Parses the data and creates a structure containing all required info.

    The method reads the information given either as a command line option or as
    a part of the OVF description.

    @raise errors.OpPrereqError: if some required part of the description of
      virtual instance is missing or unable to create output directory

    """
    self.results_name = self._GetInfo("instance name", self.options.name,
                                      self._ParseNameOptions,
                                      self.ovf_reader.GetInstanceName)
    if not self.results_name:
      raise errors.OpPrereqError("Name of instance not provided",
                                 errors.ECODE_INVAL)

    self.output_dir = utils.PathJoin(self.output_dir, self.results_name)
    try:
      utils.Makedirs(self.output_dir)
    except OSError as err:
      raise errors.OpPrereqError("Failed to create directory %s: %s" %
                                 (self.output_dir, err), errors.ECODE_ENVIRON)

    self.results_template = self._GetInfo(
      "disk template", self.options.disk_template, self._ParseTemplateOptions,
      self.ovf_reader.GetDiskTemplate)
    if not self.results_template:
      logging.info("Disk template not given")

    self.results_hypervisor = self._GetInfo(
      "hypervisor", self.options.hypervisor, self._ParseHypervisorOptions,
      self.ovf_reader.GetHypervisorData)
    assert self.results_hypervisor["hypervisor_name"]
    if self.results_hypervisor["hypervisor_name"] == constants.VALUE_AUTO:
      logging.debug("Default hypervisor settings from the cluster will be used")

    self.results_os = self._GetInfo(
      "OS", self.options.os, self._ParseOSOptions, self.ovf_reader.GetOSData)
    if not self.results_os.get("os_name"):
      raise errors.OpPrereqError("OS name must be provided",
                                 errors.ECODE_INVAL)

    self.results_backend = self._GetInfo(
      "backend", self.options.beparams,
      self._ParseBackendOptions, self.ovf_reader.GetBackendData)
    assert self.results_backend.get("vcpus")
    assert self.results_backend.get("memory")
    assert self.results_backend.get("auto_balance") is not None

    self.results_tags = self._GetInfo(
      "tags", self.options.tags, self._ParseTags, self.ovf_reader.GetTagsData)

    ovf_version = self.ovf_reader.GetVersionData()
    if ovf_version:
      self.results_version = ovf_version
    else:
      self.results_version = constants.EXPORT_VERSION

    self.results_network = self._GetInfo(
      "network", self.options.nics, self._ParseNicOptions,
      self.ovf_reader.GetNetworkData, ignore_test=self.options.no_nics)

    self.results_disk = self._GetInfo(
      "disk", self.options.disks, self._ParseDiskOptions, self._GetDiskInfo,
      ignore_test=self.results_template == constants.DT_DISKLESS)

    if not self.results_disk and not self.results_network:
      raise errors.OpPrereqError("Either disk specification or network"
                                 " description must be present",
                                 errors.ECODE_STATE)

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
    assert isinstance(self.options.hypervisor, tuple)
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
      results["nic%s_network" % nic_id] = \
        nic_desc.get("network", constants.VALUE_AUTO)
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
    CheckQemuImg()
    assert self.options.disks
    results = {}
    for (disk_id, disk_desc) in self.options.disks:
      results["disk%s_ivname" % disk_id] = "disk/%s" % disk_id
      if disk_desc.get("size"):
        try:
          disk_size = utils.ParseUnit(disk_desc["size"])
        except ValueError:
          raise errors.OpPrereqError("Invalid disk size for disk %s: %s" %
                                     (disk_id, disk_desc["size"]),
                                     errors.ECODE_INVAL)
        new_path = utils.PathJoin(self.output_dir, str(disk_id))
        args = [
          constants.QEMUIMG_PATH,
          "create",
          "-f",
          "raw",
          new_path,
          disk_size,
        ]
        run_result = utils.RunCmd(args)
        if run_result.failed:
          raise errors.OpPrereqError("Creation of disk %s failed, output was:"
                                     " %s" % (new_path, run_result.stderr),
                                     errors.ECODE_ENVIRON)
        results["disk%s_size" % disk_id] = str(disk_size)
        results["disk%s_dump" % disk_id] = "disk%s.raw" % disk_id
      else:
        raise errors.OpPrereqError("Disks created for import must have their"
                                   " size specified",
                                   errors.ECODE_INVAL)
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
                                   " paths or paths outside main OVF"
                                   " directory", errors.ECODE_ENVIRON)
      disk, _ = os.path.splitext(disk_name)
      disk_path = utils.PathJoin(self.input_dir, disk_name)
      if disk_compression not in NO_COMPRESSION:
        _, disk_path = self._CompressDisk(disk_path, disk_compression,
                                          DECOMPRESS)
        disk, _ = os.path.splitext(disk)
      if self._GetDiskQemuInfo(disk_path, r"file format: (\S+)") != "raw":
        logging.info("Conversion to raw format is required")
      ext, new_disk_path = self._ConvertDisk("raw", disk_path)

      final_disk_path = LinkFile(new_disk_path, prefix=disk, suffix=ext,
                                 directory=self.output_dir)
      final_name = os.path.basename(final_disk_path)
      disk_size = os.path.getsize(final_disk_path) // (1024 * 1024)
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
    for section, options in results.items():
      output.append("[%s]" % section)
      for name, value in options.items():
        if value is None:
          value = ""
        output.append("%s = %s" % (name, value))
      output.append("")
    output_contents = "\n".join(output)

    try:
      utils.WriteFile(output_file_name, data=output_contents)
    except errors.ProgrammerError as err:
      raise errors.OpPrereqError("Saving the config file failed: %s" % err,
                                 errors.ECODE_ENVIRON)

    self.Cleanup()


class ConfigParserWithDefaults(configparser.ConfigParser):
  """This is just a wrapper on ConfigParser, that uses default values

  """
  def get(self, section, options, raw=None, vars=None): # pylint: disable=W0622
    try:
      result = configparser.ConfigParser.get(self, section, options,
                                                 raw=raw, vars=vars)
    except configparser.NoOptionError:
      result = None
    return result

  def getint(self, section, options):
    try:
      result = configparser.ConfigParser.get(self, section, options)
    except configparser.NoOptionError:
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
  @type reference_files: list
  @ivar reference_files: files referenced in the ovf file
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
    except configparser.MissingSectionHeaderError as err:
      raise errors.OpPrereqError("Error when trying to read %s: %s" %
                                 (input_path, err), errors.ECODE_ENVIRON)
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
      raise errors.OpPrereqError("No instance name found",
                                 errors.ECODE_ENVIRON)
    return name

  def _ParseVCPUs(self):
    """Parses vcpus number from config file.

    @rtype: int
    @return: number of virtual CPUs

    @raise errors.OpPrereqError: if number of VCPUs equals 0

    """
    vcpus = self.config_parser.getint(constants.INISECT_BEP, VCPUS)
    if vcpus == 0:
      raise errors.OpPrereqError("No CPU information found",
                                 errors.ECODE_ENVIRON)
    return vcpus

  def _ParseMemory(self):
    """Parses vcpus number from config file.

    @rtype: int
    @return: amount of memory in MB

    @raise errors.OpPrereqError: if amount of memory equals 0

    """
    memory = self.config_parser.getint(constants.INISECT_BEP, MEMORY)
    if memory == 0:
      raise errors.OpPrereqError("No memory information found",
                                 errors.ECODE_ENVIRON)
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
      raise errors.OpPrereqError("No hypervisor information found",
                                 errors.ECODE_ENVIRON)
    results["hypervisor"]["name"] = hyp_name
    pairs = self.config_parser.items(constants.INISECT_HYP)
    for (name, value) in pairs:
      results["hypervisor"][name] = value
    # os
    results["os"] = {}
    os_name = self.config_parser.get(constants.INISECT_EXP, OS)
    if os_name is None:
      raise errors.OpPrereqError("No operating system information found",
                                 errors.ECODE_ENVIRON)
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
        self.config_parser.get(constants.INISECT_INS,
                               "nic%s_link" % counter)
      if data_link is None:
        break
      results.append({
        "mode": self.config_parser.get(constants.INISECT_INS,
                                       "nic%s_mode" % counter),
        "mac": self.config_parser.get(constants.INISECT_INS,
                                      "nic%s_mac" % counter),
        "ip": self.config_parser.get(constants.INISECT_INS,
                                     "nic%s_ip" % counter),
        "network": self.config_parser.get(constants.INISECT_INS,
                                          "nic%s_network" % counter),
        "link": data_link,
      })
      if results[counter]["mode"] not in constants.NIC_VALID_MODES:
        raise errors.OpPrereqError("Network mode %s not recognized"
                                   % results[counter]["mode"],
                                   errors.ECODE_INVAL)
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
      raise errors.OpPrereqError("Disk image does not exist: %s" % disk_path,
                                 errors.ECODE_ENVIRON)
    if os.path.dirname(disk_file):
      raise errors.OpPrereqError("Path for the disk: %s contains a directory"
                                 " name" % disk_path, errors.ECODE_ENVIRON)
    disk_name, _ = os.path.splitext(disk_file)
    ext, new_disk_path = self._ConvertDisk(self.options.disk_format, disk_path)
    results["format"] = self.options.disk_format
    results["virt-size"] = self._GetDiskQemuInfo(
      new_disk_path, r"virtual size: \S+ \((\d+) bytes\)")
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
    except OSError as err:
      raise errors.OpPrereqError("Failed to create directory %s: %s" %
                                 (self.output_dir, err), errors.ECODE_ENVIRON)

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
    for file_path, value in sha1_sums.items():
      file_name = os.path.basename(file_path)
      lines.append("SHA1(%s)= %s" % (file_name, value))
    lines.append("")
    data = "\n".join(lines)
    try:
      utils.WriteFile(path, data=data)
    except errors.ProgrammerError as err:
      raise errors.OpPrereqError("Saving the manifest file failed: %s" % err,
                                 errors.ECODE_ENVIRON)

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
    for file_path in files_list:
      file_name = os.path.basename(file_path)
      ova_package.add(file_path, arcname=file_name)
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

    self.ovf_writer.SaveDisksData(self.results_disk)
    self.ovf_writer.SaveNetworksData(self.results_network)
    if not self.options.ext_usage:
      self.ovf_writer.SaveGanetiData(self.results_ganeti, self.results_network)

    self.ovf_writer.SaveVirtualSystemData(self.results_name, self.results_vcpus,
                                          self.results_memory)

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
      except OSError as err:
        raise errors.OpPrereqError("Failed to create directory %s: %s" %
                                   (self.packed_dir, err),
                                   errors.ECODE_ENVIRON)
      self._PrepareTarFile(packed_path, files_list)
    logging.info("Creation of the OVF package was successfull")
    self.Cleanup()
