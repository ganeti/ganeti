#
#

# Copyright (C) 2012 Google Inc.
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

"""Module for object related utils."""


#: Supported container types for serialization/de-serialization (must be a
#: tuple as it's used as a parameter for C{isinstance})
_SEQUENCE_TYPES = (list, tuple, set, frozenset)


class AutoSlots(type):
  """Meta base class for __slots__ definitions.

  """
  def __new__(mcs, name, bases, attrs):
    """Called when a class should be created.

    @param mcs: The meta class
    @param name: Name of created class
    @param bases: Base classes
    @type attrs: dict
    @param attrs: Class attributes

    """
    assert "__slots__" not in attrs, \
      "Class '%s' defines __slots__ when it should not" % name

    attrs["__slots__"] = mcs._GetSlots(attrs)

    return type.__new__(mcs, name, bases, attrs)

  @classmethod
  def _GetSlots(mcs, attrs):
    """Used to get the list of defined slots.

    @param attrs: The attributes of the class

    """
    raise NotImplementedError


class ValidatedSlots(object):
  """Sets and validates slots.

  """
  __slots__ = []

  def __init__(self, **kwargs):
    """Constructor for BaseOpCode.

    The constructor takes only keyword arguments and will set
    attributes on this object based on the passed arguments. As such,
    it means that you should not pass arguments which are not in the
    __slots__ attribute for this class.

    """
    slots = self.GetAllSlots()
    for (key, value) in kwargs.items():
      if key not in slots:
        raise TypeError("Object %s doesn't support the parameter '%s'" %
                        (self.__class__.__name__, key))
      setattr(self, key, value)

  @classmethod
  def GetAllSlots(cls):
    """Compute the list of all declared slots for a class.

    """
    slots = []
    for parent in cls.__mro__:
      slots.extend(getattr(parent, "__slots__", []))
    return slots

  def Validate(self):
    """Validates the slots.

    This method must be implemented by the child classes.

    """
    raise NotImplementedError


def ContainerToDicts(container):
  """Convert the elements of a container to standard Python types.

  This method converts a container with elements to standard Python types. If
  the input container is of the type C{dict}, only its values are touched.
  Those values, as well as all elements of input sequences, must support a
  C{ToDict} method returning a serialized version.

  @type container: dict or sequence (see L{_SEQUENCE_TYPES})

  """
  if isinstance(container, dict):
    ret = dict([(k, v.ToDict()) for k, v in container.items()])
  elif isinstance(container, _SEQUENCE_TYPES):
    ret = [elem.ToDict() for elem in container]
  else:
    raise TypeError("Unknown container type '%s'" % type(container))

  return ret


def ContainerFromDicts(source, c_type, e_type):
  """Convert a container from standard python types.

  This method converts a container with standard Python types to objects. If
  the container is a dict, we don't touch the keys, only the values.

  @type source: None, dict or sequence (see L{_SEQUENCE_TYPES})
  @param source: Input data
  @type c_type: type class
  @param c_type: Desired type for returned container
  @type e_type: element type class
  @param e_type: Item type for elements in returned container (must have a
    C{FromDict} class method)

  """
  if not isinstance(c_type, type):
    raise TypeError("Container type '%s' is not a type" % type(c_type))

  if source is None:
    source = c_type()

  if c_type is dict:
    ret = dict([(k, e_type.FromDict(v)) for k, v in source.items()])
  elif c_type in _SEQUENCE_TYPES:
    ret = c_type(map(e_type.FromDict, source))
  else:
    raise TypeError("Unknown container type '%s'" % c_type)

  return ret
