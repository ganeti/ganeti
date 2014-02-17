{-| Ganeti lock-related types and type classes

-}

{-

Copyright (C) 2014 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.Locking.Types
  ( Lock
  , lockImplications
  ) where

{-| The type class of being a lock

As usual, locks need to come with an order, the lock order, and
be an instance of Show, so that malformed requests can meaningfully
be reported.

Additionally, in Ganeti we also have group locks, like a lock for all
nodes. While those group locks contain infinitely many locks, the set
of locks a single lock is included in is always finite, and usually
very small. So we take this association from a lock to the locks it
is (strictly) included in as additional data of the type class.

It is a prerequisite that whenever 'a' is implied in 'b', then all locks
that are in the lock order between 'a' and 'b' are also implied in 'b'.

-}

class (Ord a, Show a) => Lock a where
  lockImplications :: a -> [a]
