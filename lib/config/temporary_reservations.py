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


"""Reserve resources, so that jobs can't take them.

"""

from ganeti import errors


class TemporaryReservationManager(object):
  """A temporary resource reservation manager.

  This is used to reserve resources in a job, before using them, making sure
  other jobs cannot get them in the meantime.

  """
  def __init__(self):
    self._ec_reserved = {}

  def Reserved(self, resource):
    for holder_reserved in self._ec_reserved.values():
      if resource in holder_reserved:
        return True
    return False

  def Reserve(self, ec_id, resource):
    if self.Reserved(resource):
      raise errors.ReservationError("Duplicate reservation for resource '%s'"
                                    % str(resource))
    if ec_id not in self._ec_reserved:
      self._ec_reserved[ec_id] = set([resource])
    else:
      self._ec_reserved[ec_id].add(resource)

  def DropECReservations(self, ec_id):
    if ec_id in self._ec_reserved:
      del self._ec_reserved[ec_id]

  def GetReserved(self):
    all_reserved = set()
    for holder_reserved in self._ec_reserved.values():
      all_reserved.update(holder_reserved)
    return all_reserved

  def GetECReserved(self, ec_id):
    """ Used when you want to retrieve all reservations for a specific
        execution context. E.g when commiting reserved IPs for a specific
        network.

    """
    ec_reserved = set()
    if ec_id in self._ec_reserved:
      ec_reserved.update(self._ec_reserved[ec_id])
    return ec_reserved

  def Generate(self, existing, generate_one_fn, ec_id):
    """Generate a new resource of this type

    """
    assert callable(generate_one_fn)

    all_elems = self.GetReserved()
    all_elems.update(existing)
    retries = 64
    while retries > 0:
      new_resource = generate_one_fn()
      if new_resource is not None and new_resource not in all_elems:
        break
    else:
      raise errors.ConfigurationError("Not able generate new resource"
                                      " (last tried: %s)" % new_resource)
    self.Reserve(ec_id, new_resource)
    return new_resource
