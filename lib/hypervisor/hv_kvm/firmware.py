#
#

# Copyright (C) 2026 the Ganeti project
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

"""On-disk layout of the per-instance UEFI firmware disk.

The firmware disk holds several raw regions (currently the OVMF read-only
*code* and the writable *vars*/NVRAM) plus a small self-describing superblock
in sector 0. QEMU's pflash maps the *entire* backing node and requires it to
be exactly the flash size, and the C{-blockdev} C{file} driver has no
offset/size option, so each region is later exposed as a standalone whole
device via a device-mapper C{linear} target (see the KVM hypervisor driver).

This module is intentionally I/O-free: it only computes the layout and
packs/unpacks the superblock, so it can be used both on the master (to size
the disk) and on the node (to seed and to expose the regions).

"""

import collections
import struct

from ganeti import errors


#: Superblock magic, identifying a Ganeti firmware disk.
MAGIC = b"GNTOVMF\x00"

#: Superblock format version.
VERSION = 1

#: Logical sector size used for the superblock and for device-mapper tables.
SECTOR_SIZE = 512

#: Alignment of region start offsets. 1 MiB is comfortably above any flash
#: erase-block boundary and device-mapper's sector alignment, and leaves the
#: whole first MiB free for the superblock.
ALIGNMENT = 1 << 20

#: Region holding the read-only OVMF code (seeded from OVMF_CODE_TEMPLATE).
REGION_CODE = "code"

#: Region holding the writable OVMF vars / NVRAM (seeded from
#: OVMF_VARS_TEMPLATE). This is the precious, per-instance state.
REGION_VARS = "vars"

#: Maximum length of a region name in the on-disk superblock.
_NAME_LEN = 16

#: struct format for the superblock header: magic, version, region count.
_HEADER_FMT = "<8sII"
_HEADER_LEN = struct.calcsize(_HEADER_FMT)

#: struct format for one region table entry: name, offset, size (all bytes).
_ENTRY_FMT = "<%dsQQ" % _NAME_LEN
_ENTRY_LEN = struct.calcsize(_ENTRY_FMT)


def _AlignUp(value, alignment):
  """Round C{value} up to the next multiple of C{alignment}."""
  return ((value + alignment - 1) // alignment) * alignment


def ComputeLayout(code_size, vars_size):
  """Compute the region layout for the given seed template sizes.

  The code region starts at the first aligned offset (1 MiB, leaving the
  superblock its own sector) and the vars region follows at the next aligned
  offset after the code region. Sizes are the exact template sizes so the
  pflash backing matches the flash device size.

  @type code_size: int
  @param code_size: size in bytes of the OVMF code template
  @type vars_size: int
  @param vars_size: size in bytes of the OVMF vars template
  @rtype: collections.OrderedDict
  @return: ordered mapping region name -> (offset, size), both in bytes

  """
  code_off = ALIGNMENT
  vars_off = _AlignUp(code_off + code_size, ALIGNMENT)
  return collections.OrderedDict([
    (REGION_CODE, (code_off, code_size)),
    (REGION_VARS, (vars_off, vars_size)),
    ])


def RequiredDiskSize(layout):
  """Return the minimum disk size (bytes) able to hold the given layout.

  @type layout: dict
  @param layout: mapping region name -> (offset, size)
  @rtype: int

  """
  return max(offset + size for (offset, size) in layout.values())


def PackSuperblock(layout):
  """Serialize a region layout into the sector-0 superblock.

  @type layout: collections.OrderedDict
  @param layout: ordered mapping region name -> (offset, size)
  @rtype: bytes
  @return: exactly L{SECTOR_SIZE} bytes

  """
  buf = struct.pack(_HEADER_FMT, MAGIC, VERSION, len(layout))
  for name, (offset, size) in layout.items():
    encoded = name.encode("ascii")
    if len(encoded) > _NAME_LEN:
      raise errors.HypervisorError("Firmware region name too long: %s" % name)
    buf += struct.pack(_ENTRY_FMT, encoded, offset, size)
  if len(buf) > SECTOR_SIZE:
    raise errors.HypervisorError("Firmware superblock exceeds one sector")
  return buf + (b"\x00" * (SECTOR_SIZE - len(buf)))


def UnpackSuperblock(data):
  """Parse a sector-0 superblock back into a region layout.

  @type data: bytes
  @param data: at least L{SECTOR_SIZE} bytes read from the firmware disk
  @rtype: collections.OrderedDict
  @return: ordered mapping region name -> (offset, size)
  @raise errors.HypervisorError: if the magic or version is unexpected

  """
  if len(data) < _HEADER_LEN:
    raise errors.HypervisorError("Firmware superblock truncated")

  magic, version, count = struct.unpack(_HEADER_FMT, data[:_HEADER_LEN])
  if magic != MAGIC:
    raise errors.HypervisorError("Bad firmware superblock magic %r" % magic)
  if version != VERSION:
    raise errors.HypervisorError("Unsupported firmware superblock version %d"
                                 % version)

  layout = collections.OrderedDict()
  pos = _HEADER_LEN
  for _ in range(count):
    name, offset, size = struct.unpack(_ENTRY_FMT, data[pos:pos + _ENTRY_LEN])
    layout[name.rstrip(b"\x00").decode("ascii")] = (offset, size)
    pos += _ENTRY_LEN
  return layout
